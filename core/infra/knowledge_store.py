# -*- coding: utf-8 -*-
"""知识资产版本化存储层（WAL + 快照 + 索引）—— 方案见 docs/数据与知识留存与更新_方案设计.md

设计要点（为什么不是直接读写 JSON）：
  1. **主存储是 JSONL append-only 事件日志**：崩溃最多丢最后一行，不会损坏已有数据；
     每次变更追加一个新版本（rev+1，supersedes 指旧），历史只增不减 → 追溯/回滚天然可用。
  2. **索引是物化视图**（index.json），可由日志重建 —— 日志才是权威，索引坏了重建即可。
  3. **软删除**：delete/deprecate 只追加墓碑事件，物理删除仅发生在 compact 且先落 archive。
     依据 MEMORY 副本治理铁律：保内容 + 保链接 + 断写入，不直接删。

复用的现役能力（不重复造轮子）：
  - `utils/safe_json.safe_write_json`  —— 索引落盘的 tmp+replace 原子写
  - `utils/safe_json.safe_load_json`   —— 索引损坏自动回退备份
  - `knowledge_gateway._cached_asset`  —— 检索缓存按 (mtime,size) 失效的思路（本模块自持一份）

关键常量登记见 `金水谣_标准唯一真源.md` §三；改常量须同步文档并过 check_consistency。

用法：
    from core.infra.knowledge_store import put, get, history, rollback, compact, verify
    put("经验", "JS-20260925-10", {...}, {"tags": ["协作"], "tier": "L0"})
    get("经验", "JS-20260925-10")            # -> 最新版本 dict
    history("经验", "JS-20260925-10")        # -> 全部版本（新→旧）
    rollback("经验", "JS-20260925-10", 1)    # -> 以 rev=1 的内容追加一个新版本
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta

from utils.safe_json import safe_load_json, safe_write_json

# ---------------------------------------------------------------------------
# 常量（模块级大写；改值须同步标准真源 §三 并过阈值 watch）
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORE_DIRNAME = "knowledge_store"
RECORDS_NAME = "records.jsonl"
INDEX_NAME = "index.json"
ARCHIVE_DIRNAME = "archive"
SNAPSHOT_DIRNAME = "snapshot"

SCHEMA_VERSION = 1
"""索引/事件结构版本。与现役 safe_json 的"旧格式兼容"同思路：版本不符即重建索引。"""

RETRY_MAX = 3
"""写入重试次数。失败必须抛错（MEMORY：静默失败会让闸门变哑巴），绝不 except: pass。"""

RETRY_BASE_SLEEP = 0.05
"""重试退避基数（秒），第 n 次等待 = RETRY_BASE_SLEEP * 2**n。"""

COMPACT_SHRINK_GUARD = 0.5
"""compact 骤降守卫：压实后**业务键(ns:key)数** < 原业务键数 × 本比例则拒绝写入。

事故原型（MEMORY JS-20260925-06）：data_maintenance 把 predictions.json 从 3258 条
硬截成 200 条（保留率 6%，远低于本阈值）。

⚠️ 判定维度必须是**业务键数**而不是事件行数：compact 的目的就是压掉同一 key 的
中间版本，3 个版本压成 1 条时行数降到 33%，若按行数守卫会把**正常压实**误判成
数据丢失而拒绝（初版正是踩了这个坑）。真正的事故是"记录（key）丢失"，不是"版本变少"。
"""

DEFAULT_TTL_DAYS = 180
"""默认过期天数兜底。与 utils/lottery_prize.py 的 PRIZE_RULES_STALE_DAYS=180 同量级。"""

MAX_LINE_BYTES = 2 * 1024 * 1024
"""单行上限（2MB）：超过应改用 patch 增量或外置存储，避免单行过大拖垮重建。"""

ACL_LEVELS = ("public", "internal", "secret")
"""权限分级。secret 级禁止进入倒排索引与网关召回（密钥一律走 ~/.jinshuiyao-secrets/）。"""

EVENTS = ("put", "patch", "deprecate", "delete")

_lock = threading.RLock()
"""重入锁。MEMORY 并发铁律要求 RLock；现役 utils/locks.py 是普通 Lock（非重入），
嵌套获取会死锁，故本模块自持 RLock。"""


class KnowledgeStoreError(Exception):
    """存储层异常：失败一律抛错，禁止静默。"""


class ConflictError(KnowledgeStoreError):
    """乐观锁冲突：expect_rev 与当前 rev 不匹配。

    绝不静默覆盖 —— MEMORY 闸门铁律：「守卫有两种失败模式：报错和静默，静默才是真敌人」。
    """

    def __init__(self, ns, key, expect_rev, actual_rev):
        super().__init__(
            "冲突：%s/%s 期望 rev=%s 但实际 rev=%s（请刷新后重试，或用 force 覆盖并留痕）"
            % (ns, key, expect_rev, actual_rev))
        self.ns = ns
        self.key = key
        self.expect_rev = expect_rev
        self.actual_rev = actual_rev


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
_STORE_ROOT = None
"""测试隔离钩子（编码规范 §7 测试隔离规范）。

单测用 monkeypatch 把它指向临时目录，避免污染真实数据；生产环境保持 None = 默认路径。
"""


def store_dir():
    return _STORE_ROOT or os.path.join(BASE_DIR, "金水谣数据", STORE_DIRNAME)


def records_path():
    return os.path.join(store_dir(), RECORDS_NAME)


def index_path():
    return os.path.join(store_dir(), INDEX_NAME)


def archive_dir():
    return os.path.join(store_dir(), ARCHIVE_DIRNAME)


def snapshot_dir():
    return os.path.join(store_dir(), SNAPSHOT_DIRNAME)


def _ensure_dir(d):
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def _now_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def checksum_of(payload):
    """payload 的 sha256（一致性校验用）；与 safe_json 的 checksum 互不影响。"""
    s = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _with_retry(fn, what=""):
    """带退避的重试；**重试耗尽必须抛错**，不返回 None、不静默。"""
    last = None
    for i in range(RETRY_MAX):
        try:
            return fn()
        except OSError as e:
            last = e
            time.sleep(RETRY_BASE_SLEEP * (2 ** i))
    raise KnowledgeStoreError("%s 失败（已重试 %d 次）: %s" % (what, RETRY_MAX, last))


def _new_id():
    return uuid.uuid4().hex[:12]


def _nskey(ns, key):
    return "%s:%s" % (ns, key)


# ---------------------------------------------------------------------------
# 事件日志读写
# ---------------------------------------------------------------------------
def _append_event(ev):
    """追加一行事件（append + fsync），返回 (offset, length)。

    崩溃安全：只 append，最多丢最后一行（未 fsync 部分），已有数据不受影响。
    """
    path = records_path()
    _ensure_dir(os.path.dirname(path))
    line = json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n"
    raw = line.encode("utf-8")
    if len(raw) > MAX_LINE_BYTES:
        raise KnowledgeStoreError("单行超过 %d 字节，请改用 patch 增量" % MAX_LINE_BYTES)

    def _do():
        # ⚠️ off 必须是**字节偏移**，不能用文本模式 f.tell()（那是字符 cookie）。
        # 含中文时字符数 ≠ 字节数，两者混用会让 verify() 抽样读错位 → 静默 mismatch。
        off = os.path.getsize(path) if os.path.isfile(path) else 0
        with io.open(path, "ab") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        return off, len(raw)

    return _with_retry(_do, "追加事件")


def _iter_lines():
    """逐行产出 (**字节** offset, 原始行文本)；跳过空行、跳过尾部半行。

    ⚠️ 全程用二进制读并自行按字节累加：文本模式的迭代/seek 走的是字符 cookie，
    与 `_append_event` 返回的字节偏移不是同一坐标系（中文下必然错位）。
    """
    path = records_path()
    if not os.path.isfile(path):
        return
    with io.open(path, "rb") as f:
        off = 0
        for raw in f:
            ln = len(raw)
            if raw.strip():
                yield off, raw.decode("utf-8", errors="replace")
            off += ln


def _parse_line(line):
    """解析一行；**尾部半行（崩溃残留）返回 None**，由调用方跳过而非整库失败。"""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _read_event_at(offset, length):
    """按 (**字节** offset, **字节** length) 精确读取一条事件。"""
    path = records_path()
    if not os.path.isfile(path):
        return None
    with io.open(path, "rb") as f:
        f.seek(offset)
        return _parse_line(f.read(length).decode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# 索引
# ---------------------------------------------------------------------------
def _empty_index():
    return {"schema": SCHEMA_VERSION, "updated_at": "", "by_key": {}, "by_id": {}}


def _load_index():
    """读索引；缺失或版本不符即重建（日志是权威，索引坏了重建即可）。"""
    idx = safe_load_json(index_path(), default=None)
    if isinstance(idx, dict) and idx.get("schema") == SCHEMA_VERSION \
            and isinstance(idx.get("by_key"), dict) and isinstance(idx.get("by_id"), dict):
        return idx
    return rebuild_index()


def _save_index(idx):
    idx["updated_at"] = _now_iso()
    _ensure_dir(os.path.dirname(index_path()))
    if not safe_write_json(index_path(), idx, embed_checksum=False, backup=True):
        raise KnowledgeStoreError("索引落盘失败: %s" % index_path())


def rebuild_index():
    """从事件日志全量重建索引（幂等，可安全重复调用）。"""
    idx = _empty_index()
    for off, line in _iter_lines():
        raw_len = len(line.encode("utf-8"))
        ev = _parse_line(line)
        if not ev or ev.get("ev") not in EVENTS:
            continue
        rid = ev.get("id")
        ns, key = ev.get("ns"), ev.get("key")
        if not rid or not ns or not key:
            continue
        node = {"offset": off, "length": raw_len, "ns": ns, "key": key, "id": rid,
                "rev": ev.get("rev", 0), "status": ev.get("meta", {}).get("status", "active"),
                "ts": ev.get("ts", ""), "ev": ev.get("ev")}
        idx["by_id"][rid] = node
        cur = idx["by_key"].get(_nskey(ns, key))
        # 只保留 rev 最大者作为 latest（日志是追加序，但以 rev 为准更稳）
        if cur is None or node["rev"] >= cur.get("rev", 0):
            idx["by_key"][_nskey(ns, key)] = node
    _save_index(idx)
    return idx


# ---------------------------------------------------------------------------
# 元数据规范化
# ---------------------------------------------------------------------------
def _build_meta(ns, key, meta, payload, prev_node, rev):
    """补全元数据：必填项兜底、checksum、版本链、base_rev。"""
    m = dict(meta or {})
    m.setdefault("schema", SCHEMA_VERSION)
    m.setdefault("author", "unknown")
    m.setdefault("source", "")
    m.setdefault("tags", [])
    m.setdefault("tier", "L0")
    m.setdefault("maturity", "draft")
    m.setdefault("status", "active")
    m.setdefault("acl", "internal")
    m.setdefault("expires_at", None)
    if m.get("acl") not in ACL_LEVELS:
        raise KnowledgeStoreError("acl 非法: %s（可选 %s）" % (m.get("acl"), ACL_LEVELS))
    m["checksum"] = checksum_of(payload)
    m["base_rev"] = (prev_node or {}).get("rev", 0)
    m["supersedes"] = (prev_node or {}).get("id") if prev_node else None
    m["rev"] = rev
    return m


def _make_event(ev_type, ns, key, payload, meta, rev):
    return {"ev": ev_type, "id": _new_id(), "ns": ns, "key": key,
            "rev": rev, "ts": _now_iso(), "payload": payload, "meta": meta}


def _commit(ev, ns, key):
    """落盘事件 + 增量更新索引（**不重建全量**，保证更新后即时生效）。"""
    off, ln = _append_event(ev)
    idx = _load_index()
    node = {"offset": off, "length": ln, "ns": ns, "key": key,
            "rev": ev.get("rev", 0), "status": ev.get("meta", {}).get("status", "active"),
            "ts": ev.get("ts", ""), "ev": ev.get("ev"), "id": ev.get("id")}
    idx["by_id"][ev["id"]] = node
    idx["by_key"][_nskey(ns, key)] = node
    _save_index(idx)
    return ev


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def put(ns, key, payload, meta=None, expect_rev=None):
    """新增/更新：追加一个新版本，旧版本保留。

    Args:
        ns: 命名空间（如 经验/决策/知识卡/规则）
        key: 业务键（如 JS 编号）
        payload: 内容主体（dict）
        meta: 元数据，见方案 §2.3；缺项自动兜底
        expect_rev: 乐观锁基线；与当前 rev 不符抛 ConflictError（**不静默覆盖**）

    Returns:
        写入的事件 dict
    """
    if not ns or not key:
        raise KnowledgeStoreError("ns 与 key 必填")
    with _lock:
        idx = _load_index()
        prev = idx["by_key"].get(_nskey(ns, key))
        if expect_rev is not None and (prev or {}).get("rev", 0) != expect_rev:
            raise ConflictError(ns, key, expect_rev, (prev or {}).get("rev", 0))
        rev = (prev or {}).get("rev", 0) + 1
        m = _build_meta(ns, key, meta, payload, prev, rev)
        if m.get("acl") == "secret":
            raise KnowledgeStoreError("secret 级禁止入库（密钥走 ~/.jinshuiyao-secrets/）")
        return _commit(_make_event("put", ns, key, payload, m, rev), ns, key)


def patch(ns, key, changes, expect_rev=None):
    """增量更新：只存变更字段，读取时沿链合并（避免大对象全量重写）。"""
    if not isinstance(changes, dict):
        raise KnowledgeStoreError("changes 必须是 dict")
    with _lock:
        idx = _load_index()
        prev = idx["by_key"].get(_nskey(ns, key))
        if prev is None:
            raise KnowledgeStoreError("不存在: %s/%s" % (ns, key))
        if expect_rev is not None and prev.get("rev", 0) != expect_rev:
            raise ConflictError(ns, key, expect_rev, prev.get("rev", 0))
        rev = prev.get("rev", 0) + 1
        m = _build_meta(ns, key, {"acl": "internal"}, changes, prev, rev)
        return _commit(_make_event("patch", ns, key, changes, m, rev), ns, key)


def deprecate(ns, key, reason="", superseded_by=None):
    """标记过期/失效：**只追加墓碑，内容保留**（MEMORY：不直接删）。"""
    with _lock:
        idx = _load_index()
        prev = idx["by_key"].get(_nskey(ns, key))
        if prev is None:
            raise KnowledgeStoreError("不存在: %s/%s" % (ns, key))
        rev = prev.get("rev", 0) + 1
        payload = {"reason": reason, "superseded_by": superseded_by}
        m = _build_meta(ns, key, {"status": "deprecated", "acl": "internal"}, payload, prev, rev)
        return _commit(_make_event("deprecate", ns, key, payload, m, rev), ns, key)


def delete(ns, key, reason=""):
    """软删除：追加 delete 墓碑，物理删除只在 compact（且先落 archive）时发生。"""
    with _lock:
        idx = _load_index()
        prev = idx["by_key"].get(_nskey(ns, key))
        if prev is None:
            raise KnowledgeStoreError("不存在: %s/%s" % (ns, key))
        rev = prev.get("rev", 0) + 1
        payload = {"reason": reason}
        m = _build_meta(ns, key, {"status": "deleted", "acl": "internal"}, payload, prev, rev)
        return _commit(_make_event("delete", ns, key, payload, m, rev), ns, key)


def get(ns, key, include_deleted=False):
    """取最新版本。

    Returns:
        dict（含 payload / meta / rev / id）；不存在返回 None。
        put/patch 会沿链**物化合并** patch，返回完整内容。
    """
    with _lock:
        idx = _load_index()
        node = idx["by_key"].get(_nskey(ns, key))
        if node is None:
            return None
        ev = _read_event_at(node.get("offset", 0), node.get("length", 0))
        if ev is None:
            return None
        if not include_deleted and ev.get("meta", {}).get("status") in ("deleted",):
            return None
        return _materialize(ns, key, ev)


def _materialize(ns, key, ev):
    """把 patch 链合并成完整内容：从最近的 put 开始，依次叠加后续 patch。"""
    chain = history(ns, key)
    if not chain:
        return ev
    base = None
    patches = []
    for e in reversed(chain):  # 旧 → 新
        if e.get("ev") == "put":
            base = dict(e.get("payload") or {})
            patches = []
        elif e.get("ev") == "patch":
            patches.append(e.get("payload") or {})
    if base is None:
        return ev
    merged = dict(base)
    for p in patches:
        merged.update(p)
    out = dict(ev)
    out["payload"] = merged
    out["materialized"] = bool(patches)
    return out


def get_by_id(rid):
    with _lock:
        idx = _load_index()
        node = idx["by_id"].get(rid)
        if node is None:
            return None
        return _read_event_at(node.get("offset", 0), node.get("length", 0))


def history(ns, key):
    """返回全部版本（新 → 旧），沿 supersedes 链回溯。

    方向说明：`meta.supersedes` 指向**前驱（旧版本）**，所以从最新版本出发
    要顺着 supersedes 往**旧**走。初版曾误建"后继映射"导致只返回 1 条 ——
    静默少了历史，正是 MEMORY 里"静默才是真敌人"的典型形态，故单测锁死长度。
    """
    with _lock:
        idx = _load_index()
        node = idx["by_key"].get(_nskey(ns, key))
        if node is None:
            return []
        by_id = {}
        for off, line in _iter_lines():
            ev = _parse_line(line)
            if ev and ev.get("id"):
                by_id[ev["id"]] = ev
        out, seen = [], set()
        cur = by_id.get(node.get("id")) or _read_event_at(node.get("offset", 0),
                                                           node.get("length", 0))
        while cur is not None and cur.get("id") not in seen:
            seen.add(cur.get("id"))
            out.append(cur)
            sup = (cur.get("meta") or {}).get("supersedes")
            cur = by_id.get(sup) if sup else None
        return out


def rollback(ns, key, rev):
    """回滚到指定 rev —— 以该版内容**追加一个新版本**，历史只增不减（回滚本身也可被回滚）。"""
    with _lock:
        target = None
        for e in history(ns, key):
            if e.get("rev") == rev:
                target = e
                break
        if target is None:
            raise KnowledgeStoreError("找不到 rev=%s: %s/%s" % (rev, ns, key))
        payload = target.get("payload") or {}
        meta = dict(target.get("meta") or {})
        meta.pop("checksum", None)
        meta["status"] = "active"
        meta["rollback_from"] = rev
        return put(ns, key, payload, meta)


def scan(ns=None, status="active", with_payload=False):
    """列出指定命名空间（或全部）的当前版本，支持按状态过滤。

    Args:
        with_payload: 附带物化后的 payload。默认 False（只给索引摘要，省一次读盘）。
            ⚠️ 需要按内容体检时必须显式打开：初版调用方以为 scan 自带 payload，
            结果 `node.get("payload")` 恒为 None → 缺失统计永远 0（**假绿**）。
            本函数已持 RLock，内部再调 get() 不会死锁（正是不用普通 Lock 的原因）。
    """
    with _lock:
        idx = _load_index()
        out = []
        for nk, node in idx["by_key"].items():
            if ns and node.get("ns") != ns:
                continue
            if status and node.get("status") != status:
                continue
            item = {"ns": node.get("ns"), "key": node.get("key"),
                    "rev": node.get("rev"), "id": node.get("id"),
                    "ts": node.get("ts"), "status": node.get("status")}
            if with_payload:
                rec = get(node.get("ns"), node.get("key"))
                item["payload"] = (rec or {}).get("payload")
            out.append(item)
        return out


# ---------------------------------------------------------------------------
# 过期 / 失效 / 冲突
# ---------------------------------------------------------------------------
def find_expired(now=None, ttl_days=DEFAULT_TTL_DAYS):
    """找出过期条目（expires_at 到期，或超过 ttl_days 未更新）—— **只报告不自动改**。

    诚实铁律：与 utils/lottery_prize.py 同思路，超期**只提醒、绝不自动改写内容**。
    """
    now_dt = now or datetime.now()
    out = []
    for off, line in _iter_lines():
        ev = _parse_line(line)
        if not ev or ev.get("ev") not in EVENTS:
            continue
        meta = ev.get("meta") or {}
        if meta.get("status") in ("deleted", "deprecated"):
            continue
        exp = meta.get("expires_at")
        if exp:
            try:
                if datetime.strptime(str(exp)[:10], "%Y-%m-%d") <= now_dt:
                    out.append({"ns": ev.get("ns"), "key": ev.get("key"),
                                "reason": "expires_at 到期", "exp": exp})
                    continue
            except ValueError:
                pass
        ts = ev.get("ts") or ""
        if ts:
            try:
                dt = datetime.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S")
                if now_dt - dt > timedelta(days=ttl_days):
                    out.append({"ns": ev.get("ns"), "key": ev.get("key"),
                                "reason": "超过 %d 天未更新" % ttl_days, "ts": ts})
            except ValueError:
                continue
    return out


# ---------------------------------------------------------------------------
# 一致性校验 / compact
# ---------------------------------------------------------------------------
def verify(sample=50):
    """一致性校验：逐行可解析 + checksum 匹配 + 索引 offset 抽样。

    Returns:
        dict: {"ok": bool, "total": int, "bad_lines": [...], "bad_checksum": [...],
               "index_mismatch": [...]}
    """
    res = {"ok": True, "total": 0, "bad_lines": [], "bad_checksum": [], "index_mismatch": []}
    total = 0
    for off, line in _iter_lines():
        total += 1
        ev = _parse_line(line)
        if ev is None:
            res["bad_lines"].append(off)
            continue
        meta = ev.get("meta") or {}
        ck = meta.get("checksum")
        if ck and ev.get("ev") in ("put", "patch") and ck != checksum_of(ev.get("payload")):
            res["bad_checksum"].append(ev.get("id"))
    res["total"] = total
    idx = _load_index()
    checked = 0
    for node in idx["by_id"].values():
        if checked >= sample:
            break
        ev = _read_event_at(node.get("offset", 0), node.get("length", 0))
        if ev is None or ev.get("id") != node.get("id"):
            res["index_mismatch"].append(node.get("id"))
        checked += 1
    res["ok"] = not (res["bad_lines"] or res["bad_checksum"] or res["index_mismatch"])
    return res


def compact():
    """压实：丢弃中间版本与被删除的旧版本，**先落 archive**，带骤降守卫。

    保留策略：每个 ns:key 保留最新版本；deprecated 事件保留（作为历史）。

    骤降守卫（⚠️ 按**业务键数**判定，不是事件行数）：
    压实的本意就是砍掉同一 key 的中间版本，行数必然下降（3 个版本压成 1 条只剩 33%），
    若按行数守卫会把**正常压实**误判成数据丢失而拒绝。真正的事故是「记录（ns:key）丢失」，
    所以这里比较压前后的**去重业务键数**：keys_after < keys_before × COMPACT_SHRINK_GUARD → 拒绝写入。
    """
    with _lock:
        path = records_path()
        if not os.path.isfile(path):
            return {"kept": 0, "removed": 0, "archived": None}
        lines = []
        for off, line in _iter_lines():
            lines.append(line)
        if not lines:
            return {"kept": 0, "removed": 0, "archived": None}

        parsed = []
        for line in lines:
            ev = _parse_line(line)
            parsed.append(ev)
            if not ev:
                continue
        keys_before = set()
        for ev in parsed:
            if ev:
                keys_before.add(_nskey(ev.get("ns"), ev.get("key")))

        latest = {}
        for ev in parsed:
            if not ev:
                continue
            nk = _nskey(ev.get("ns"), ev.get("key"))
            cur = latest.get(nk)
            if cur is None or ev.get("rev", 0) >= (cur.get("rev", 0) or 0):
                latest[nk] = ev

        kept = []
        keys_after = set()
        for line, ev in zip(lines, parsed):
            if ev is None:
                continue
            nk = _nskey(ev.get("ns"), ev.get("key"))
            top = latest.get(nk)
            if top is not None and ev.get("id") == top.get("id"):
                kept.append(line)
                keys_after.add(nk)
            elif ev.get("ev") == "deprecate":
                kept.append(line)  # 墓碑保留，历史可追溯
                keys_after.add(nk)

        if len(keys_after) < len(keys_before) * COMPACT_SHRINK_GUARD:
            raise KnowledgeStoreError(
                "骤降守卫拦截：业务键 %d → %d（低于 %.0f%%），疑似误删，已拒绝写入"
                % (len(keys_before), len(keys_after), COMPACT_SHRINK_GUARD * 100))

        _ensure_dir(archive_dir())
        arc = os.path.join(archive_dir(), "records_%s.jsonl" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        with io.open(arc, "w", encoding="utf-8") as f:
            f.writelines(lines)
        tmp = path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            f.writelines(kept)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        rebuild_index()
        return {"kept": len(kept), "removed": len(lines) - len(kept), "archived": arc}


def refresh():
    """强制重建索引（跨进程看不到最新时调用）。"""
    with _lock:
        return rebuild_index()


def stats():
    """规模统计，供门禁/看板消费。

    ⚠️ 踩坑记录：`keys` 初版直接数 `by_key` 的长度，但 by_key 里**含已软删除的键**
    （墓碑留在索引里是设计本意，为了可追溯）。结果冒烟数据删完后仍报 "2 条"，
    门禁/看板会被这个虚高数字误导。故按 status 分档统计，`keys` 只数 active。
    """
    with _lock:
        idx = _load_index()
        v = verify(sample=20)
        by_status = {}
        for node in idx.get("by_key", {}).values():
            s = node.get("status") or "active"
            by_status[s] = by_status.get(s, 0) + 1
        return {"keys": by_status.get("active", 0), "by_status": by_status,
                "events": len(idx.get("by_id", {})),
                "expired": len(find_expired()), "verify_ok": v["ok"],
                "records_bytes": os.path.getsize(records_path()) if os.path.isfile(records_path()) else 0}
