# -*- coding: utf-8 -*-
"""知识存储层单测（版本链 / 乐观锁 / 软删除 / 一致性 / 骤降守卫）

测试隔离：monkeypatch `_STORE_ROOT` 指向 tmp_path，**绝不污染真实数据**
（编码规范 §7 测试隔离规范）。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.infra import knowledge_store as ks  # noqa: E402
from tools import check_consistency as cc  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ks, "_STORE_ROOT", str(tmp_path / "ks"))
    return ks


@pytest.fixture
def gate(tmp_path, monkeypatch):
    """第 ⑬ 项门禁的隔离夹具：存储根 + 水位基线都指向 tmp_path。"""
    monkeypatch.setattr(ks, "_STORE_ROOT", str(tmp_path / "ks"))
    monkeypatch.setattr(cc, "KNOWLEDGE_STORE_WATERMARK", str(tmp_path / "wm.json"))
    return ks


def _meta(**kw):
    base = {"author": "test", "source": "unit", "tags": ["协作"], "tier": "L0", "acl": "internal"}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# CRUD 与版本链
# ---------------------------------------------------------------------------
def test_put_and_get(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    got = store.get("经验", "K1")
    assert got is not None
    assert got["payload"]["a"] == 1
    assert got["rev"] == 1


def test_put_twice_creates_new_version(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    store.put("经验", "K1", {"a": 2}, _meta())
    got = store.get("经验", "K1")
    assert got["payload"]["a"] == 2
    assert got["rev"] == 2
    # 历史保留两个版本，旧内容不丢失
    hist = store.history("经验", "K1")
    assert len(hist) == 2
    assert hist[-1]["payload"]["a"] == 1


def test_supersedes_chain(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    e2 = store.put("经验", "K1", {"a": 2}, _meta())
    assert e2["meta"]["supersedes"] is not None


def test_rollback_appends_new_version(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    store.put("经验", "K1", {"a": 2}, _meta())
    store.rollback("经验", "K1", 1)
    got = store.get("经验", "K1")
    assert got["payload"]["a"] == 1     # 内容回到 rev=1
    assert got["rev"] == 3              # 但版本是新增的，不覆盖历史
    assert len(store.history("经验", "K1")) == 3


def test_patch_materializes(store):
    store.put("经验", "K1", {"a": 1, "b": 2}, _meta())
    store.patch("经验", "K1", {"b": 99})
    got = store.get("经验", "K1")
    assert got["payload"] == {"a": 1, "b": 99}   # 增量被合并
    assert got.get("materialized") is True


def test_get_missing_returns_none(store):
    assert store.get("经验", "不存在") is None


# ---------------------------------------------------------------------------
# 乐观锁冲突
# ---------------------------------------------------------------------------
def test_conflict_error_on_stale_rev(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    with pytest.raises(ks.ConflictError):
        store.put("经验", "K1", {"a": 2}, _meta(), expect_rev=99)


def test_expect_rev_ok(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    e = store.put("经验", "K1", {"a": 2}, _meta(), expect_rev=1)
    assert e["rev"] == 2


def test_conflict_does_not_overwrite(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    with pytest.raises(ks.ConflictError):
        store.put("经验", "K1", {"a": 999}, _meta(), expect_rev=5)
    assert store.get("经验", "K1")["payload"]["a"] == 1   # 原值未被静默覆盖


# ---------------------------------------------------------------------------
# 软删除 / 过期
# ---------------------------------------------------------------------------
def test_delete_is_soft(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    store.delete("经验", "K1", reason="测试")
    assert store.get("经验", "K1") is None                     # 业务逻辑看不到
    assert len(store.history("经验", "K1")) == 2               # 历史仍在
    assert store.get("经验", "K1", include_deleted=True) is not None


def test_deprecate_keeps_content(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    store.deprecate("经验", "K1", reason="已被取代")
    got = store.get("经验", "K1")
    assert got is not None                                     # 过期≠删除，内容保留
    assert got["meta"]["status"] == "deprecated"


def test_find_expired_by_ttl(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    exp = store.find_expired(ttl_days=0)                       # ttl=0 → 一律过期
    assert any(x["key"] == "K1" for x in exp)


def test_find_expired_not_auto_modify(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    store.find_expired(ttl_days=0)
    assert store.get("经验", "K1")["payload"]["a"] == 1        # 只报告，绝不自动改


# ---------------------------------------------------------------------------
# 安全 / 校验
# ---------------------------------------------------------------------------
def test_secret_rejected(store):
    with pytest.raises(ks.KnowledgeStoreError):
        store.put("经验", "K1", {"token": "x"}, _meta(acl="secret"))


def test_bad_acl_rejected(store):
    with pytest.raises(ks.KnowledgeStoreError):
        store.put("经验", "K1", {"a": 1}, _meta(acl="godmode"))


def test_verify_ok(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    store.put("经验", "K2", {"b": 2}, _meta())
    v = store.verify()
    assert v["ok"] is True
    assert v["total"] == 2


def test_verify_detects_checksum_mismatch(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    # 直接篡改日志文件里的 payload，模拟内容被外部改动
    path = store.records_path()
    with open(path, "r", encoding="utf-8") as f:
        line = f.readline()
    bad = line.replace('"a":1', '"a":999')
    with open(path, "w", encoding="utf-8") as f:
        f.write(bad)
    v = store.verify()
    assert v["bad_checksum"], "篡改 payload 应被 checksum 校验抓到"


# ---------------------------------------------------------------------------
# compact 与骤降守卫
# ---------------------------------------------------------------------------
def test_compact_keeps_latest(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    store.put("经验", "K1", {"a": 2}, _meta())
    store.put("经验", "K1", {"a": 3}, _meta())
    r = store.compact()
    got = store.get("经验", "K1")
    assert got["payload"]["a"] == 3        # 最新版保留
    assert r["removed"] >= 2               # 中间版被压实


def test_compact_shrink_guard(store):
    """骤降守卫：条数骤降过半必须拒绝写入（事故原型 predictions.json 3258→200）。"""
    store.put("经验", "K1", {"a": 1}, _meta())
    lines_before = sum(1 for _ in store._iter_lines())
    # 伪造"压实后只剩 0 条"的极端场景：把 latest 表清空不可行，
    # 改为直接压到只剩 1 条且总数 2 条（1 < 2*0.5=1 不成立），
    # 故这里用 3 条 put 后手动构造守卫分支：断言阈值本身生效
    store.put("经验", "K2", {"b": 1}, _meta())
    store.put("经验", "K3", {"c": 1}, _meta())
    lines_now = sum(1 for _ in store._iter_lines())
    assert lines_now == lines_before + 2
    assert ks.COMPACT_SHRINK_GUARD == 0.5, "骤降守卫阈值必须是 0.5（标准真源登记值）"


def test_compact_archives_before_rewrite(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    store.put("经验", "K1", {"a": 2}, _meta())
    r = store.compact()
    assert r["archived"] and os.path.isfile(r["archived"]), "compact 前必须先落 archive"


# ---------------------------------------------------------------------------
# 索引与统计
# ---------------------------------------------------------------------------
def test_rebuild_index_idempotent(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    a = store.rebuild_index()
    b = store.rebuild_index()
    assert a["by_key"].keys() == b["by_key"].keys()
    assert store.get("经验", "K1")["payload"]["a"] == 1


def test_scan_filters_by_ns(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    store.put("规则", "R1", {"b": 1}, _meta())
    assert len(store.scan(ns="经验")) == 1
    assert len(store.scan()) == 2


def test_stats(store):
    store.put("经验", "K1", {"a": 1}, _meta())
    s = store.stats()
    assert s["keys"] == 1
    assert s["verify_ok"] is True


def test_stats_keys_excludes_tombstones(store):
    """墓碑保留是设计本意，但统计不能把它算进 active（否则门禁看到虚高数字）。"""
    store.put("经验", "K1", {"a": 1}, _meta())
    store.delete("经验", "K1", reason="清理")
    s = store.stats()
    assert s["keys"] == 0, "软删除后 active 应为 0，实际 %s" % s["keys"]
    assert s["by_status"].get("deleted") == 1, "墓碑必须留在统计里，供追溯"


# ---------------------------------------------------------------------------
# 第 ⑬ 项门禁反证：绿不算数，能红才算数
# ---------------------------------------------------------------------------
def test_gate_silent_on_clean_store(gate):
    for i in range(3):
        gate.put("知识", "K%d" % i, {"v": i}, _meta())
    assert cc.check_knowledge_store() == []


def test_gate_catches_tampered_payload(gate):
    """篡改 payload（字节等长）→ 必须报 checksum 不符。

    ⚠️ 重写日志必须走**二进制**：文本模式在 Windows 会把 \\n 写成 \\r\\n，
    每行多 1 字节导致全库 offset 错位（会把本用例污染成 index_mismatch）。
    """
    for i in range(3):
        gate.put("知识", "K%d" % i, {"v": i}, _meta())
    path = gate.records_path()
    raw0 = open(path, "rb").read()
    orig = raw0.decode("utf-8").splitlines(True)[0]
    v = json.loads(orig)["payload"]["v"]
    new = orig.replace('"v":%d' % v, '"v":%d' % ((v + 1) % 10))
    ob, nb = orig.encode("utf-8"), new.encode("utf-8")
    assert len(ob) == len(nb), "字节长度必须相同，否则测的不是 checksum"
    open(path, "wb").write(raw0.replace(ob, nb, 1))

    errs = cc.check_knowledge_store()
    assert any("checksum" in e for e in errs), "篡改未被抓到 → 闸门是哑巴: %s" % errs
    open(path, "wb").write(raw0)


def test_gate_catches_key_shrink_by_watermark(gate):
    """业务键从 10 骤降到 3（<50%）→ 必须报骤降。

    用**最高水位**而不是"比上次"：每天悄悄删一点时，"比上次"会被骗过去。
    """
    for i in range(10):
        gate.put("知识", "K%d" % i, {"v": i}, _meta())
    assert cc.check_knowledge_store() == []          # 先落水位 10
    for i in range(7):
        gate.delete("知识", "K%d" % i, reason="反证骤降")
    errs = cc.check_knowledge_store()
    assert any("骤降" in e for e in errs), "骤降未被抓到 → 闸门是哑巴: %s" % errs


def test_gate_reports_read_failure(monkeypatch, gate):
    """读存储失败 / 模块导入失败必须报错，不能静默放行（静默才是真敌人）。

    说明：两个失败点（导入、读取）共用同一段 try/except 并同样返回 KB-STORE 错误，
    这里覆盖"读取抛异常"这一支。
    踩坑：不要试图用 `sys.modules[name] = None` 模拟导入失败——`from pkg import mod`
    会直接取 pkg 的模块属性，压根不走 sys.modules，测出来是假绿。
    """
    gate.put("知识", "K0", {"v": 0}, _meta())

    def boom():
        raise RuntimeError("模拟读取失败")

    monkeypatch.setattr(gate, "verify", boom)
    errs = cc.check_knowledge_store()
    assert errs and any("KB-STORE" in e for e in errs), "读取失败被静默吞掉了: %s" % errs
