# -*- coding: utf-8 -*-
"""批量商品视频资源提取与统一处理（权利受控版）。

第一性原则：权利闸编译进代码，不写进文档。
    本工具只对「用户有权使用的商品」提取视频——自己店铺的商品、
    或已获得商家授权（凭证留痕）的商品。对平台他人商品的批量扒取是
    搬运流水线的第一步，已被平台检测技术（内容指纹+多模态比对）、
    五部门新规（2026-09-01 生效）、著作权法三重封死（见 JS-20261017-04
    §2.2 与《旧搬运做法与平台检测机制对照》）。因此：
      - Harvester 构造必须传 HarvestScope，白名单外的 goods_id 连请求都不发；
      - research_metadata_only 模式允许探测元数据（市场调研），禁止下载；
      - 下载类素材必须经 MaterialRegistry 绑定授权登记后才能使用。

异常处理策略（用户明确要求，分层显式）：
    来源层   单个商品探测失败 → FetchError(source_error)，不影响整批
    下载层   超时/HTTP/超限/类型不符/网络 → FetchError 带错误码，逐项记录
    处理层   ffmpeg 缺失 → FFmpegMissingError 明确报错（禁静默降级）
    登记层   授权不全 → LicenseError 拒绝登记，不静默放行
    全链路   禁止 except: pass——本项目 P0-B 就是 301 处静默吞异常
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 常量表（配非空闸：tests/unit/test_pdd_harvest.py::test_rule_tables_not_empty）
# ---------------------------------------------------------------------------

SCOPE_MODES = ("own_store", "merchant_authorized", "research_metadata_only")

STATUS_HAS_VIDEO = "has_video"
STATUS_NO_VIDEO = "no_video"
STATUS_OUT_OF_SCOPE = "out_of_scope"
STATUS_FETCH_FAILED = "fetch_failed"
STATUS_DOWNLOAD_FAILED = "download_failed"
STATUS_PROCESS_FAILED = "process_failed"
STATUS_READY = "ready"

ITEM_STATUSES = (
    STATUS_HAS_VIDEO,
    STATUS_NO_VIDEO,
    STATUS_OUT_OF_SCOPE,
    STATUS_FETCH_FAILED,
    STATUS_DOWNLOAD_FAILED,
    STATUS_PROCESS_FAILED,
    STATUS_READY,
)

ERROR_CODES = (
    "timeout",
    "http_error",
    "size_exceeded",
    "content_type_mismatch",
    "network_error",
    "source_error",
)

_CHUNK = 65536


# ---------------------------------------------------------------------------
# 异常类型（全部显式，无裸 except）
# ---------------------------------------------------------------------------

class FetchError(Exception):
    """来源/下载层错误，携带机器可判的错误码。"""

    def __init__(self, code: str, detail: str):
        super().__init__("[%s] %s" % (code, detail))
        self.code = code
        self.detail = detail


class ProcessError(Exception):
    """ffmpeg 处理层错误（探测失败/无视频流/命令非零退出）。"""

    def __init__(self, code: str, detail: str):
        super().__init__("[%s] %s" % (code, detail))
        self.code = code
        self.detail = detail


class FFmpegMissingError(RuntimeError):
    """ffmpeg 不可用——显式报错，绝不静默跳过质检环节。"""


class RightsViolationError(RuntimeError):
    """权利闸被触发（内部不变量：白名单外商品不得进入下载）。"""


# ---------------------------------------------------------------------------
# 权利边界
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HarvestScope:
    """一次批量提取任务的权利边界。

    own_store           自己店铺商品：白名单必填，可下载
    merchant_authorized 商家授权商品：白名单必填 + evidence_dir 必填，可下载
    research_metadata_only 竞品调研：白名单可为空（允许任意 goods_id 探测），
                        但 permits_download() 恒为 False——元数据可看，文件不落盘
    """

    mode: str
    allowed_goods_ids: frozenset
    evidence_dir: Optional[str] = None

    def __post_init__(self):
        if self.mode not in SCOPE_MODES:
            raise ValueError("未知提取模式: %r（合法值 %s）" % (self.mode, SCOPE_MODES))
        if self.mode == "merchant_authorized" and not self.evidence_dir:
            raise ValueError("merchant_authorized 模式必须提供授权凭证目录 evidence_dir")
        if not isinstance(self.allowed_goods_ids, frozenset):
            object.__setattr__(self, "allowed_goods_ids", frozenset(self.allowed_goods_ids))

    def permits_download(self) -> bool:
        return self.mode != "research_metadata_only"

    def check_downloadable(self, goods_id: str) -> None:
        """下载前的权利判定。越权抛 RightsViolationError。"""
        if not self.permits_download():
            raise RightsViolationError(
                "research_metadata_only 模式禁止下载（goods_id=%s）" % goods_id)
        if goods_id not in self.allowed_goods_ids:
            raise RightsViolationError(
                "goods_id=%s 不在白名单，拒绝提取（mode=%s）" % (goods_id, self.mode))


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GoodsVideoRef:
    """某个商品的视频引用（探测阶段产出，尚未下载）。"""

    goods_id: str
    video_url: str
    title: str = ""
    source: str = ""


@dataclass
class HarvestItem:
    """单个商品的提取结果。状态显式六选一，禁止静默跳过。"""

    goods_id: str
    status: str
    ref: Optional[GoodsVideoRef] = None
    downloaded: bool = False
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    asset: Optional["NormalizedAsset"] = None

    def to_dict(self) -> dict:
        d = {
            "goods_id": self.goods_id,
            "status": self.status,
            "downloaded": self.downloaded,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
        }
        if self.ref is not None:
            d["ref"] = {
                "goods_id": self.ref.goods_id,
                "video_url": self.ref.video_url,
                "title": self.ref.title,
                "source": self.ref.source,
            }
        if self.asset is not None:
            d["asset"] = self.asset.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "HarvestItem":
        ref = None
        if d.get("ref"):
            r = d["ref"]
            ref = GoodsVideoRef(r["goods_id"], r["video_url"], r.get("title", ""),
                                r.get("source", ""))
        asset = None
        if d.get("asset"):
            asset = NormalizedAsset.from_dict(d["asset"])
        return cls(
            goods_id=d["goods_id"],
            status=d["status"],
            ref=ref,
            downloaded=d.get("downloaded", False),
            error_code=d.get("error_code"),
            error_detail=d.get("error_detail"),
            asset=asset,
        )


@dataclass(frozen=True)
class VideoMeta:
    duration_sec: float
    width: int
    height: int
    fps: float
    has_audio: bool


@dataclass(frozen=True)
class NormalizedAsset:
    """统一处理后的素材资产（下载 + 质检的产物）。"""

    path: str
    md5: str
    size_bytes: int
    duration_sec: float
    width: int
    height: int
    has_audio: bool
    quality_issues: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "md5": self.md5,
            "size_bytes": self.size_bytes,
            "duration_sec": self.duration_sec,
            "width": self.width,
            "height": self.height,
            "has_audio": self.has_audio,
            "quality_issues": list(self.quality_issues),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NormalizedAsset":
        return cls(
            path=d["path"],
            md5=d["md5"],
            size_bytes=d["size_bytes"],
            duration_sec=d["duration_sec"],
            width=d["width"],
            height=d["height"],
            has_audio=d["has_audio"],
            quality_issues=tuple(d.get("quality_issues", ())),
        )


@dataclass
class HarvestReport:
    """整批提取报告：可序列化，支持断点续跑。"""

    items: List[HarvestItem] = field(default_factory=list)

    def add(self, item: HarvestItem) -> None:
        self.items.append(item)

    def by_id(self, goods_id: str) -> Optional[HarvestItem]:
        for it in self.items:
            if it.goods_id == goods_id:
                return it
        return None

    @property
    def counts(self) -> Dict[str, int]:
        c = {s: 0 for s in ITEM_STATUSES}
        for it in self.items:
            c[it.status] = c.get(it.status, 0) + 1
        return c

    @property
    def ok_ids(self) -> set:
        """已就绪（可进入登记/拼接）的 goods_id 集合。"""
        return {it.goods_id for it in self.items if it.status == STATUS_READY}

    def to_dict(self) -> dict:
        return {"items": [it.to_dict() for it in self.items]}

    @classmethod
    def from_dict(cls, d: dict) -> "HarvestReport":
        return cls(items=[HarvestItem.from_dict(x) for x in d.get("items", [])])


# ---------------------------------------------------------------------------
# 探测源（可插拔）
# ---------------------------------------------------------------------------

class ManifestGoodsVideoSource:
    """本地清单源：goods_id → video_url。测试与本环境的主力源。"""

    def __init__(self, mapping: Dict[str, str], titles: Optional[Dict[str, str]] = None):
        self._mapping = dict(mapping)
        self._titles = dict(titles or {})
        self.name = "manifest"

    def detect(self, goods_id: str) -> Optional[GoodsVideoRef]:
        url = self._mapping.get(goods_id)
        if not url:
            return None
        return GoodsVideoRef(goods_id=goods_id, video_url=url,
                             title=self._titles.get(goods_id, ""), source=self.name)


class ApiGoodsVideoSource:
    """开放平台适配壳（如多多进宝）。

    不在本环境发真实请求（无凭据）。client 为注入式调用：
        client(goods_id) -> dict(video_url=..., title=...) | None
    生产环境由调用方注入带 OAuth 的 client；测试注入 fake。
    """

    def __init__(self, client: Callable[[str], Optional[dict]], name: str = "open_api"):
        self._client = client
        self.name = name

    def detect(self, goods_id: str) -> Optional[GoodsVideoRef]:
        try:
            data = self._client(goods_id)
        except Exception as exc:  # 客户端异常统一转显式错误码，不裸吞
            raise FetchError("source_error", "%s: %s" % (type(exc).__name__, exc))
        if not data:
            return None
        url = data.get("video_url") if isinstance(data, dict) else None
        if not url:
            return None
        return GoodsVideoRef(goods_id=goods_id, video_url=url,
                             title=data.get("title", ""), source=self.name)


# ---------------------------------------------------------------------------
# 下载器
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FetchedFile:
    path: str
    size_bytes: int
    md5: str
    content_type: str


class VideoFetcher:
    """流式下载 + 大小上限 + 类型校验 + 错误码分类。

    opener 可注入（测试替身 / 自定义重试策略）；默认 urllib.request.urlopen。
    """

    def __init__(self, opener: Optional[Callable] = None, timeout: float = 15.0,
                 max_bytes: int = 200 * 1024 * 1024,
                 allowed_content_types: Tuple[str, ...] = ("video/",)):
        self._opener = opener or urllib.request.urlopen
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._allowed = allowed_content_types

    def fetch(self, url: str, dest_path: str) -> FetchedFile:
        try:
            resp = self._opener(url, timeout=self._timeout)
        except urllib.error.HTTPError as exc:
            raise FetchError("http_error", "HTTP %s %s" % (exc.code, url))
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc))
            if "timed out" in reason.lower():
                raise FetchError("timeout", reason)
            raise FetchError("network_error", reason)
        except TimeoutError as exc:
            raise FetchError("timeout", str(exc))

        md5 = hashlib.md5()
        total = 0
        content_type = ""
        try:
            headers = getattr(resp, "headers", None)
            if headers is not None and hasattr(headers, "get_content_type"):
                content_type = headers.get_content_type() or ""
            if content_type and not any(content_type.startswith(p)
                                        for p in self._allowed):
                raise FetchError("content_type_mismatch",
                                 "got %r, allowed prefixes %s" % (content_type,
                                                                  self._allowed))
            Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, "wb") as fh:
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self._max_bytes:
                        raise FetchError("size_exceeded",
                                         "超过 %d 字节上限（已读 %d）" % (self._max_bytes,
                                                                       total))
                    md5.update(chunk)
                    fh.write(chunk)
        finally:
            close = getattr(resp, "close", None)
            if callable(close):
                close()
        return FetchedFile(path=dest_path, size_bytes=total,
                           md5=md5.hexdigest(), content_type=content_type)


# ---------------------------------------------------------------------------
# 归一化与质检
# ---------------------------------------------------------------------------

def _parse_fraction(text: str) -> float:
    """"30/1" 或 "23.976" → float。解析失败抛 ProcessError。"""
    s = (text or "").strip()
    if not s or s in ("0/0", "N/A"):
        raise ProcessError("probe_parse_error", "无法解析帧率: %r" % text)
    try:
        if "/" in s:
            num, den = s.split("/", 1)
            den_f = float(den)
            if den_f == 0:
                raise ProcessError("probe_parse_error", "帧率分母为 0: %r" % text)
            return float(num) / den_f
        return float(s)
    except ValueError:
        raise ProcessError("probe_parse_error", "无法解析帧率: %r" % text)


class VideoNormalizer:
    """ffmpeg 归一化 + 平台质检规则。

    显式三态（项目铁律，禁静默降级）：
        runner 注入（测试）或 ffmpeg_path 显式给定（生产）→ 正常
        两者都没有 → FFmpegMissingError，明确报错并提示安装
    质检规则与 JS-20261017-03 合规闸一致：>=720P、有声、15-60s。
    竖屏不做机检（多来源口径冲突未解，留人工）。
    """

    MIN_DIMENSION = 720
    MIN_DURATION_SEC = 15.0
    MAX_DURATION_SEC = 60.0

    def __init__(self, runner: Optional[Callable] = None,
                 ffmpeg_path: Optional[str] = None):
        self._runner = runner
        self._ffmpeg_path = ffmpeg_path
        self._last_argv: List[str] = []

    def _run(self, argv: List[str]) -> str:
        if self._runner is None:
            raise FFmpegMissingError(
                "未提供 ffmpeg 可执行路径也未注入 runner——拒绝静默跳过质检。"
                "解法：venv 内 pip install imageio-ffmpeg 后取其路径，"
                "或本机安装 ffmpeg 入 PATH 后传 ffmpeg_path=")
        self._last_argv = argv
        rc, out, err = self._runner(argv)
        if rc != 0:
            raise ProcessError("ffmpeg_error", "rc=%s err=%s" % (rc, err))
        return out

    def probe(self, path: str) -> VideoMeta:
        exe = self._ffmpeg_path or "ffprobe"
        if not self._ffmpeg_path:
            # 允许 runner 模式下用任意 argv 前缀，测试替身按 "ffprobe" 关键字分派
            exe = "ffprobe"
        out = self._run([exe, "-v", "quiet", "-print_format", "json",
                         "-show_format", "-show_streams", path])
        try:
            data = json.loads(out)
            streams = data.get("streams") or []
            video = next((s for s in streams if s.get("codec_type") == "video"), None)
            if video is None:
                raise ProcessError("no_video_stream", "%s 无视频流" % path)
            has_audio = any(s.get("codec_type") == "audio" for s in streams)
            duration = (data.get("format") or {}).get("duration") \
                or video.get("duration") or "0"
            return VideoMeta(
                duration_sec=float(duration),
                width=int(video.get("width") or 0),
                height=int(video.get("height") or 0),
                fps=_parse_fraction(video.get("avg_frame_rate", "")),
                has_audio=has_audio,
            )
        except ProcessError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ProcessError("probe_parse_error", "%s: %s" % (type(exc).__name__, exc))

    def quality_check(self, meta: VideoMeta) -> List[str]:
        issues: List[str] = []
        if meta.width < self.MIN_DIMENSION or meta.height < self.MIN_DIMENSION:
            issues.append("resolution_below_720p")
        if not meta.has_audio:
            issues.append("no_audio_track")
        if meta.duration_sec < self.MIN_DURATION_SEC:
            issues.append("duration_below_15s")
        elif meta.duration_sec > self.MAX_DURATION_SEC:
            issues.append("duration_above_60s")
        return issues

    def normalize(self, in_path: str, out_path: str,
                  size: Tuple[int, int] = (720, 1280)) -> None:
        """确定性归一：缩放到目标竖屏尺寸 + fps 归一 + 移除元数据。

        刻意不做创意操作（转场/调色/画中画）——那既是用户不需要的，
        也是平台识别「伪原创」的特征操作（JS-20261017-04 §6.1）。
        """
        w, h = size
        exe = self._ffmpeg_path or "ffmpeg"
        self._run([
            exe, "-y", "-i", in_path,
            "-vf", "scale=%d:%d" % (w, h),
            "-r", "30",
            "-map_metadata", "-1",
            "-c:v", "libx264", "-c:a", "aac",
            out_path,
        ])


# ---------------------------------------------------------------------------
# 主管线
# ---------------------------------------------------------------------------

class Harvester:
    """批量提取主管线：权利判定 → 探测 → 下载 → 归一质检 → 报告。

    任何单商品失败只记录该商品（显式错误码），不影响整批继续。
    """

    def __init__(self, scope: HarvestScope, source,
                 fetcher: Optional[VideoFetcher] = None,
                 normalizer: Optional[VideoNormalizer] = None,
                 work_dir: str = "."):
        self.scope = scope
        self.source = source
        self.fetcher = fetcher or VideoFetcher()
        self.normalizer = normalizer or VideoNormalizer()
        self.work_dir = work_dir

    def run(self, goods_ids: Iterable[str]) -> HarvestReport:
        report = HarvestReport()
        for gid in goods_ids:
            report.add(self._process_one(gid))
        return report

    def _process_one(self, gid: str) -> HarvestItem:
        # 1) 权利判定：非 research 模式先过白名单（越权则 source 都不会被碰）
        if self.scope.permits_download():
            try:
                self.scope.check_downloadable(gid)
            except RightsViolationError:
                return HarvestItem(gid, STATUS_OUT_OF_SCOPE)

        # 2) 探测
        try:
            ref = self.source.detect(gid)
        except FetchError as exc:
            return HarvestItem(gid, STATUS_FETCH_FAILED,
                               error_code=exc.code, error_detail=exc.detail)
        if ref is None:
            return HarvestItem(gid, STATUS_NO_VIDEO)

        # 3) research 模式：只记元数据，不落盘
        if not self.scope.permits_download():
            return HarvestItem(gid, STATUS_HAS_VIDEO, ref=ref, downloaded=False)

        # 4) 下载
        dest = str(Path(self.work_dir) / ("%s.mp4" % gid))
        try:
            fetched = self.fetcher.fetch(ref.video_url, dest)
        except FetchError as exc:
            return HarvestItem(gid, STATUS_DOWNLOAD_FAILED,
                               ref=ref, error_code=exc.code, error_detail=exc.detail)

        # 5) 归一 + 质检
        try:
            meta = self.normalizer.probe(fetched.path)
            issues = tuple(self.normalizer.quality_check(meta))
        except FFmpegMissingError as exc:
            return HarvestItem(gid, STATUS_PROCESS_FAILED, ref=ref, downloaded=True,
                               error_code="ffmpeg_missing", error_detail=str(exc))
        except ProcessError as exc:
            return HarvestItem(gid, STATUS_PROCESS_FAILED, ref=ref, downloaded=True,
                               error_code=exc.code, error_detail=exc.detail)

        asset = NormalizedAsset(
            path=fetched.path,
            md5=fetched.md5,
            size_bytes=fetched.size_bytes,
            duration_sec=meta.duration_sec,
            width=meta.width,
            height=meta.height,
            has_audio=meta.has_audio,
            quality_issues=issues,
        )
        return HarvestItem(gid, STATUS_READY, ref=ref, downloaded=True, asset=asset)
