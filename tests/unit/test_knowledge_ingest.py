# -*- coding: utf-8 -*-
"""知识入库（决策卡 → knowledge_store）单测

重点锁三处**假绿**（都踩过）：
  1. 字段名加粗 `- **反事实对照**：` 曾识别不了 → 5 张明明写了反事实的卡被判缺失
  2. 单字字段「坑」曾被 `{2,10}` 长度下限挡掉 → 73 张卡 100% 假缺失
  3. `scan()` 默认不返回 payload → 完整性报告永远"缺失 0"

再加一条**调用链接入**验证：写入源若不被真正调用，存储层就是空库，门禁恒绿等于没监控。

参考知识库：
  - 编码规范 §7：单测 monkeypatch 指向 tmp_path，绝不污染真实数据。
  - MEMORY「写完检查脚本必须当场接进调用链」。
  - MEMORY「同一业务含义的指标必须锁同一个数据端点」→ 切分正则与
    `ai_decisions_extractor._load_new_decision_entries` 同口径。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.infra import knowledge_ingest as ki          # noqa: E402
from core.infra import knowledge_store as ks           # noqa: E402


@pytest.fixture
def ingest(tmp_path, monkeypatch):
    monkeypatch.setattr(ks, "_STORE_ROOT", str(tmp_path / "ks"))
    return ki


CARD_BOLD = """### 2026-10-02 测试卡（加粗字段名）

- 属主：WorkBuddy
- 做了什么：建了知识存储层
- **反事实对照**：若没建，历史无从追溯
- 坑：字段名加粗会识别不了
"""

CARD_PLAIN = """### 2026-10-01 测试卡（普通字段名）

- 属主：WorkBuddy
- 做了什么：修了正则
- 反事实对照：若不修，会一直假缺失
- 坑：单字字段被长度下限挡掉
"""


def test_parse_fields_handles_bold_name(ingest):
    """`- **反事实对照**：` 必须能识别（否则假缺失）。"""
    f = ingest.parse_fields(CARD_BOLD)["fields"]
    assert "反事实对照" in f, "加粗字段名未识别 → 假缺失: %s" % list(f)
    assert f["属主"] == "WorkBuddy"


def test_parse_fields_handles_single_char_field(ingest):
    """「坑」是单字必填字段，长度下限写成 2 会让它永远识别不到。"""
    f = ingest.parse_fields(CARD_PLAIN)["fields"]
    assert "坑" in f, "单字字段「坑」未识别（字段名长度下限太严）: %s" % list(f)


def test_parse_fields_reports_missing(ingest):
    p = ingest.parse_fields(CARD_BOLD)
    assert "置信度" in p["missing"], "缺字段必须报出来，不能假装齐全"
    assert p["date"] == "2026-10-02"


def test_ingest_is_idempotent(ingest):
    """调度器高频轮询下，内容没变就绝不能产生新版本（否则 WAL 无限膨胀）。"""
    r1 = ingest.ingest_decision_entries([CARD_BOLD, CARD_PLAIN])
    assert r1["created"] == 2 and r1["errors"] == []
    r2 = ingest.ingest_decision_entries([CARD_BOLD, CARD_PLAIN])
    assert r2["created"] == 0 and r2["updated"] == 0
    assert r2["skipped"] == 2, "重复导入应全部跳过: %s" % r2
    # 版本链没有被撑长
    assert ks.stats()["events"] == 2, "幂等失效 → 事件数增长: %s" % ks.stats()


def test_ingest_change_creates_new_version(ingest):
    """内容变化要**追加新版本**而不是覆盖（历史留得住、可回滚）。"""
    ingest.ingest_decision_entries([CARD_BOLD])
    changed = CARD_BOLD.replace("建了知识存储层", "建了知识存储层并接入门禁")
    r = ingest.ingest_decision_entries([changed])
    assert r["updated"] == 1
    # 不猜 key 格式，直接从索引取（猜格式本身就是一种会漂移的耦合）
    key = ks.scan(ns=ki.NS_DECISION)[0]["key"]
    rec = ks.get(ki.NS_DECISION, key)
    assert rec is not None
    assert rec["rev"] == 2, "应追加为 rev=2，实际 %s" % rec["rev"]
    assert len(ks.history(ki.NS_DECISION, key)) == 2, "历史应保留 2 个版本"


def test_completeness_report_counts_missing(ingest):
    """完整性体检必须真读到 payload —— scan 默认不含 payload，漏了就是假绿。"""
    ingest.ingest_decision_entries([CARD_BOLD, CARD_PLAIN])
    rep = ingest.completeness_report()
    assert rep["total"] == 2
    assert rep["incomplete"] == 2, "两张卡都缺字段，不能报 0 缺失（假绿）: %s" % rep
    assert rep["missing_by_field"].get("置信度") == 2


def test_scan_payload_flag(ingest):
    ingest.ingest_decision_entries([CARD_BOLD])
    assert "payload" not in ks.scan(ns=ki.NS_DECISION)[0], "默认不应带 payload（省读盘）"
    node = ks.scan(ns=ki.NS_DECISION, with_payload=True)[0]
    assert node.get("payload"), "with_payload=True 必须返回 payload"


def test_extract_inner_wires_store(ingest, monkeypatch):
    """调用链接入验证：`extract_from_ai_decisions` 必须真的把决策卡写进存储层。

    这才是 A3 的落点——写入源不被调用，存储层就是空库，第 ⑬ 项门禁恒绿。
    """
    import core.ai.ai_decisions_extractor as ade
    import core.infra.auto_knowledge as ak

    class _FakeExtractor:
        def save_cards(self, cards):
            return len(cards)

    monkeypatch.setattr(ade, "_load_new_decision_entries",
                        lambda *a, **kw: ([CARD_BOLD, CARD_PLAIN], "fakehash"))
    monkeypatch.setattr(ade, "_write_ai_decisions_marker", lambda h: None)
    monkeypatch.setattr(ak, "AutoKnowledgeExtractor", _FakeExtractor)

    out = ade._extract_from_ai_decisions_inner()
    assert "store" in out, "未返回 store 字段 → 写入源没接进调用链"
    assert out["store"].get("created") == 2, "决策卡没写进存储层: %s" % out["store"]
    assert ks.stats()["keys"] == 2
