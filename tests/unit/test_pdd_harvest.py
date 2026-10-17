# -*- coding: utf-8 -*-
"""JS-20261017-04 · 批量商品视频提取流水线测试（先证它红：本文件先于实现落地）

覆盖权利闸（本模块的第一性原则）：
  - 白名单外的 goods_id 必须 out_of_scope，且 source.detect 一次都不被调用
  - research 模式允许探测元数据但禁止下载
  - 撤销验证：把白名单临时放开后，越权测试必须变红
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from domains.pdd_video.harvest import (  # noqa: E402
    ERROR_CODES,
    ITEM_STATUSES,
    SCOPE_MODES,
    STATUS_FETCH_FAILED,
    STATUS_HAS_VIDEO,
    STATUS_NO_VIDEO,
    STATUS_OUT_OF_SCOPE,
    STATUS_READY,
    ApiGoodsVideoSource,
    FetchError,
    FFmpegMissingError,
    HarvestItem,
    Harvester,
    HarvestReport,
    HarvestScope,
    ManifestGoodsVideoSource,
    ProcessError,
    VideoFetcher,
    VideoNormalizer,
)
from domains.pdd_video.harvest import (  # noqa: E402
    VideoMeta,
    NormalizedAsset,
)


# ---------- 测试替身 ----------

class SpySource:
    """记录 detect 调用轨迹的探测源。"""

    name = "spy"

    def __init__(self, mapping):
        self._mapping = mapping
        self.calls = []

    def detect(self, goods_id):
        self.calls.append(goods_id)
        return self._mapping.get(goods_id)


class FakeResponse:
    """最小 urlopen 响应替身（含 headers.get_content_type）。"""

    def __init__(self, data, content_type="video/mp4"):
        self._data = data
        self.headers = _FakeHeaders(content_type)
        self.closed = False

    def read(self, n=-1):
        if n is None or n < 0:
            chunk, self._data = self._data, b""
        else:
            chunk, self._data = self._data[:n], self._data[n:]
        return chunk

    def close(self):
        self.closed = True


class _FakeHeaders:
    def __init__(self, content_type):
        self._ct = content_type

    def get_content_type(self):
        return self._ct


class FakeRunner:
    """ffmpeg/ffprobe 替身：按 argv 内容分派预置响应（子串匹配）。"""

    def __init__(self, responses):
        # responses: list of (match_substring, returncode, stdout, stderr)
        self._responses = responses
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        for key, rc, out, err in self._responses:
            if any(key in a for a in argv):
                return rc, out, err
        raise AssertionError("FakeRunner 未预置该命令: %s" % argv)


def _load_fresh(path):
    """从文件路径沙箱加载模块——绕开 pyc 缓存与 sys.modules 污染。

    撤销验证专用：改文件 → exec 新源码 → 断言 → 恢复 → 再 exec 一次
    原始源码断言闸门恢复。exec 期间把模块临时注册进 sys.modules——
    因为 `from __future__ import annotations` 下 dataclass 装饰器要按
    __module__ 去 sys.modules 取命名空间解析字符串注解；exec 完立刻摘除。
    不写 pyc、不留 sys.modules 残痕，也不受时间戳 staleness 影响
    （写-恢复若在同一秒，pyc 会把旧字节码当新的，曾致失败数 8↔10 波动）。
    """
    import types

    src = open(path, encoding="utf-8").read()
    mod = types.ModuleType("module_under_test")
    mod.__file__ = path
    sys.modules["module_under_test"] = mod
    try:
        exec(compile(src, path, "exec"), mod.__dict__)
    finally:
        sys.modules.pop("module_under_test", None)
    return mod


def _probe_json(duration=30.0, width=1080, height=1920, fps="30/1", audio=True):
    import json
    streams = [
        {
            "codec_type": "video",
            "width": width,
            "height": height,
            "avg_frame_rate": fps,
            "duration": str(duration),
        }
    ]
    if audio:
        streams.append({"codec_type": "audio", "duration": str(duration)})
    return json.dumps({"format": {"duration": str(duration)}, "streams": streams})


# ---------- 权利闸：本模块第一性原则 ----------

class TestRightsGate:
    def test_scope_rejects_unknown_mode(self):
        with pytest.raises(ValueError):
            HarvestScope(mode="whatever", allowed_goods_ids=frozenset())

    def test_authorized_mode_requires_evidence_dir(self):
        with pytest.raises(ValueError):
            HarvestScope(mode="merchant_authorized", allowed_goods_ids=frozenset({"G1"}))

    def test_out_of_scope_goods_never_touched_by_source(self):
        """越权商品：状态为 out_of_scope，且 source.detect 一次都没被调用。"""
        scope = HarvestScope(mode="own_store", allowed_goods_ids=frozenset({"G1"}))
        spy = SpySource({"G1": None, "EVIL": "http://x/v.mp4"})
        h = Harvester(scope, spy)
        report = h.run(["G1", "EVIL"])
        assert spy.calls == ["G1"], "越权商品竟然触发了探测: %s" % spy.calls
        item = report.by_id("EVIL")
        assert item.status == STATUS_OUT_OF_SCOPE

    def test_authorized_scope_allows_whitelisted(self):
        scope = HarvestScope(mode="own_store", allowed_goods_ids=frozenset({"G1"}))
        spy = SpySource({"G1": None})
        report = Harvester(scope, spy).run(["G1"])
        assert report.by_id("G1").status == STATUS_NO_VIDEO

    def test_research_mode_detects_but_never_downloads(self):
        """research 模式：元数据可探测，下载被禁（fetch 一次都不调）。"""
        from domains.pdd_video.harvest import GoodsVideoRef

        scope = HarvestScope(mode="research_metadata_only", allowed_goods_ids=frozenset())
        spy = SpySource({"ANY": GoodsVideoRef("ANY", "http://x/v.mp4")})
        fetcher = VideoFetcher(opener=lambda url, timeout=None: FakeResponse(b"data"))
        h = Harvester(scope, spy, fetcher=fetcher, work_dir=".")
        report = h.run(["ANY"])
        item = report.by_id("ANY")
        assert item.status == STATUS_HAS_VIDEO
        assert item.downloaded is False, "research 模式竟然下载了"

    def test_research_mode_forbids_empty_whitelist_downloads(self):
        scope = HarvestScope(mode="research_metadata_only", allowed_goods_ids=frozenset())
        assert scope.permits_download() is False


# ---------- 探测源 ----------

class TestSources:
    def test_manifest_source_none_when_absent(self):
        src = ManifestGoodsVideoSource({"G1": "http://x/v.mp4"})
        assert src.detect("G1") is not None
        assert src.detect("G2") is None

    def test_manifest_source_carries_metadata(self):
        src = ManifestGoodsVideoSource({"G1": "http://x/v.mp4"}, titles={"G1": "工具箱"})
        ref = src.detect("G1")
        assert ref.video_url == "http://x/v.mp4"
        assert ref.title == "工具箱"

    def test_api_source_error_becomes_fetch_failed(self):
        def bad_client(goods_id):
            raise ConnectionError("boom")

        src = ApiGoodsVideoSource(bad_client)
        with pytest.raises(FetchError) as ei:
            src.detect("G1")
        assert ei.value.code == "source_error"

    def test_api_source_none_for_no_video(self):
        src = ApiGoodsVideoSource(lambda gid: None)
        assert src.detect("G1") is None

    def test_api_source_reads_url_from_client(self):
        src = ApiGoodsVideoSource(lambda gid: {"video_url": "http://x/v.mp4", "title": "t"})
        ref = src.detect("G1")
        assert ref.video_url == "http://x/v.mp4" and ref.title == "t"


# ---------- 下载器 ----------

class TestFetcher:
    def test_fetch_ok(self, tmp_path):
        data = b"fake-mp4-bytes"
        fetcher = VideoFetcher(opener=lambda url, timeout=None: FakeResponse(data))
        dest = tmp_path / "v.mp4"
        f = fetcher.fetch("http://x/v.mp4", str(dest))
        assert f.size_bytes == len(data)
        assert f.md5 and len(f.md5) == 32
        assert dest.read_bytes() == data

    def test_fetch_timeout_classified(self, tmp_path):
        def opener(url, timeout=None):
            raise TimeoutError("timed out")

        fetcher = VideoFetcher(opener=opener)
        with pytest.raises(FetchError) as ei:
            fetcher.fetch("http://x/v.mp4", str(tmp_path / "v.mp4"))
        assert ei.value.code == "timeout"

    def test_fetch_http_error_classified(self, tmp_path):
        import urllib.error

        def opener(url, timeout=None):
            raise urllib.error.HTTPError("http://x", 404, "Not Found", None, None)

        fetcher = VideoFetcher(opener=opener)
        with pytest.raises(FetchError) as ei:
            fetcher.fetch("http://x/v.mp4", str(tmp_path / "v.mp4"))
        assert ei.value.code == "http_error"

    def test_fetch_size_exceeded(self, tmp_path):
        fetcher = VideoFetcher(opener=lambda url, timeout=None: FakeResponse(b"x" * 5000),
                               max_bytes=1000)
        with pytest.raises(FetchError) as ei:
            fetcher.fetch("http://x/v.mp4", str(tmp_path / "v.mp4"))
        assert ei.value.code == "size_exceeded"

    def test_fetch_content_type_mismatch(self, tmp_path):
        fetcher = VideoFetcher(opener=lambda url, timeout=None: FakeResponse(b"data", "text/html"))
        with pytest.raises(FetchError) as ei:
            fetcher.fetch("http://x/v.mp4", str(tmp_path / "v.mp4"))
        assert ei.value.code == "content_type_mismatch"

    def test_fetch_network_error_classified(self, tmp_path):
        import urllib.error

        def opener(url, timeout=None):
            raise urllib.error.URLError("connection refused")

        fetcher = VideoFetcher(opener=opener)
        with pytest.raises(FetchError) as ei:
            fetcher.fetch("http://x/v.mp4", str(tmp_path / "v.mp4"))
        assert ei.value.code == "network_error"


# ---------- 归一化与质检 ----------

class TestNormalizer:
    def _normalizer(self):
        runner = FakeRunner([("ffprobe", 0, _probe_json(), ""), ("ffmpeg", 0, "", "")])
        return VideoNormalizer(runner=runner, ffmpeg_path="/fake/ffmpeg")

    def test_probe_parses_metadata(self):
        meta = self._normalizer().probe("x.mp4")
        assert meta.duration_sec == 30.0
        assert (meta.width, meta.height) == (1080, 1920)
        assert meta.has_audio is True

    def test_probe_fraction_fps(self):
        runner = FakeRunner([("ffprobe", 0, _probe_json(fps="24000/1001"), "")])
        meta = VideoNormalizer(runner=runner, ffmpeg_path="/fake/ffmpeg").probe("x.mp4")
        assert abs(meta.fps - 23.976) < 0.01

    def test_probe_no_video_stream_raises(self):
        import json

        payload = json.dumps({"format": {"duration": "10"}, "streams": [{"codec_type": "audio"}]})
        runner = FakeRunner([("ffprobe", 0, payload, "")])
        with pytest.raises(ProcessError):
            VideoNormalizer(runner=runner, ffmpeg_path="/fake/ffmpeg").probe("x.mp4")

    def test_quality_flags_low_resolution(self):
        runner = FakeRunner([("ffprobe", 0, _probe_json(width=540, height=960), "")])
        meta = VideoNormalizer(runner=runner, ffmpeg_path="/fake/ffmpeg").probe("x.mp4")
        issues = VideoNormalizer(runner=runner, ffmpeg_path="/fake/ffmpeg").quality_check(meta)
        assert "resolution_below_720p" in issues

    def test_quality_flags_no_audio(self):
        runner = FakeRunner([("ffprobe", 0, _probe_json(audio=False), "")])
        n = VideoNormalizer(runner=runner, ffmpeg_path="/fake/ffmpeg")
        assert "no_audio_track" in n.quality_check(n.probe("x.mp4"))

    def test_quality_flags_too_short(self):
        runner = FakeRunner([("ffprobe", 0, _probe_json(duration=8.0), "")])
        n = VideoNormalizer(runner=runner, ffmpeg_path="/fake/ffmpeg")
        assert "duration_below_15s" in n.quality_check(n.probe("x.mp4"))

    def test_quality_clean_video_no_issues(self):
        n = self._normalizer()
        assert n.quality_check(n.probe("x.mp4")) == []

    def test_missing_ffmpeg_raises_not_silent_skip(self):
        """显式三态：没给 runner 也没给路径 → 明确报错，绝不静默跳过。"""
        n = VideoNormalizer()
        with pytest.raises(FFmpegMissingError):
            n.probe("x.mp4")

    def test_normalize_issues_scaling_command(self, tmp_path):
        n = self._normalizer()
        out = str(tmp_path / "out.mp4")
        n.normalize("in.mp4", out)
        last = n._last_argv
        assert last[0].endswith("ffmpeg")
        assert any("720" in a for a in last)
        assert last[-1] == out


# ---------- 报告与断点续跑 ----------

class TestReport:
    def _report(self):
        return HarvestReport(items=[
            HarvestItem("G1", STATUS_READY),
            HarvestItem("G2", STATUS_NO_VIDEO),
            HarvestItem("G3", STATUS_OUT_OF_SCOPE),
        ])

    def test_counts(self):
        r = self._report()
        assert r.counts[STATUS_READY] == 1
        assert r.counts[STATUS_NO_VIDEO] == 1

    def test_roundtrip(self):
        r = self._report()
        r2 = HarvestReport.from_dict(r.to_dict())
        assert r2.counts == r.counts
        assert r2.ok_ids == {"G1"}

    def test_ok_ids_only_ready(self):
        assert self._report().ok_ids == {"G1"}


# ---------- 常量表非空闸（坑变检查） ----------

class TestRuleTables:
    def test_rule_tables_not_empty(self):
        assert len(SCOPE_MODES) >= 3
        assert len(ERROR_CODES) >= 5
        assert len(ITEM_STATUSES) >= 5

    def test_scan_finds_all_tables(self):
        """自检扫描口径本身必须找到 >=3 张表，否则这条检查会空转。"""
        import domains.pdd_video.harvest as mod

        found = [n for n in dir(mod) if n.isupper() and isinstance(getattr(mod, n), tuple)]
        assert len(found) >= 3, "扫描口径只找到 %d 张表: %s" % (len(found), found)


# ---------- 撤销验证（证明闸门真的在拦） ----------

class TestGateReverseVerification:
    def test_reverse_verification_rights_gate(self):
        """撤销验证：把白名单判定临时改成恒真 → 越权商品必须不再被拦
        （证明拦住靠的确实是白名单）→ 恢复后重新加载，闸门必须重新拦得住。

        对应铁律：只跑绿不算验证，必须见它红。用 exec 沙箱加载，
        不碰 sys.modules / pyc（见 _load_fresh 注释）。
        """
        import hashlib

        import domains.pdd_video.harvest as mod
        from domains.pdd_video.harvest import GoodsVideoRef

        path = mod.__file__
        original = open(path, "rb").read()
        md5_before = hashlib.md5(original).hexdigest()
        patched = original.replace(
            b"if goods_id not in self.allowed_goods_ids:",
            b"if False:",
        )
        assert patched != original, "撤销验证的注入点没匹配上，检查实现是否改名"
        try:
            open(path, "wb").write(patched)
            ns = _load_fresh(path)
            scope = ns.HarvestScope(mode="own_store", allowed_goods_ids=frozenset())
            spy = SpySource({"EVIL": GoodsVideoRef("EVIL", "http://x/v.mp4")})
            report = ns.Harvester(scope, spy).run(["EVIL"])
            assert report.by_id("EVIL").status != ns.STATUS_OUT_OF_SCOPE, (
                "白名单已放开却仍判越权，说明拦住靠的不是白名单"
            )
        finally:
            open(path, "wb").write(original)
            assert hashlib.md5(open(path, "rb").read()).hexdigest() == md5_before, (
                "恢复后 md5 不一致"
            )
        ns2 = _load_fresh(path)
        scope2 = ns2.HarvestScope(mode="own_store", allowed_goods_ids=frozenset())
        report2 = ns2.Harvester(scope2, SpySource({})).run(["EVIL"])
        assert report2.by_id("EVIL").status == ns2.STATUS_OUT_OF_SCOPE, (
            "恢复后闸门没有重新拦住越权商品"
        )
