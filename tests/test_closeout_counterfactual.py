# -*- coding: utf-8 -*-
"""知识反事实字段测试 — 依赖函数已移除，本文件保留仅作存档"""
import pytest

pytestmark = pytest.mark.skip(reason="check_counterfactual/check_today_card 已从 closeout_gate.py 移除")

import os, sys, time
_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_test_dir)
_scripts_dir = os.path.join(_project_root, "scripts")
for _p in (_project_root, _scripts_dir):
    if _p not in sys.path: sys.path.insert(0, _p)

try:
    import closeout_gate
    from closeout_gate import check_counterfactual, check_today_card, COUNTERFACTUAL_TRIGGER_TAGS, HONESTY_KEYWORDS
except ImportError:
    check_counterfactual = check_today_card = None
    COUNTERFACTUAL_TRIGGER_TAGS = HONESTY_KEYWORDS = []


def _today_header():
    return "### %s 测试预测卡" % time.strftime("%Y-%m-%d")


def _old_header():
    return "### 2026-07-23 测试预测卡"


def _scope_tag():
    # 触发"预测/彩票类"范围：用预测摘要（在 COUNTERFACTUAL_TRIGGER_TAGS 中）
    return "预测摘要"


def _base_body(**fields):
    """构造一张含 10 必填字段 + 触发标签的预测类决策卡体。

    fields 可覆盖 counterfactual_baseline / baseline_comparison / honesty_note；
    缺省给出合规三字段。
    """
    cf = fields.get(
        "counterfactual_baseline",
        "random_baseline_rate=0.879（七乐彩7/30,n=20000,montecarlo）",
    )
    bc = fields.get(
        "baseline_comparison",
        "本次为抓取层修复，预测增益不来自模型能力，gain≈0",
    )
    hn = fields.get(
        "honesty_note",
        "彩票开奖独立随机，本次抓取修复增益≈0，好结果多少是运气/幸存偏差",
    )
    return "".join([
        "- 属主：测试\n",
        "- 做了什么：x\n",
        "- 为什么：y\n",
        "- 验证：z\n",
        "- 坑：无\n",
        "- 有效方法：a\n",
        "- 关联文件：b\n",
        "- 关联总索引：JS-20260728-99\n",
        "- 反事实对照：若没做会怎样\n",
        "- 置信度：高+依据\n",
        "- %s：本次预测\n" % _scope_tag(),
        "- counterfactual_baseline：%s\n" % cf,
        "- baseline_comparison：%s\n" % bc,
        "- honesty_note：%s\n" % hn,
    ])


def test_ac1_missing_baseline_warns():
    rep = {"warnings": []}
    # 缺 counterfactual_baseline 字段（其余合规）
    body = "".join([
        "- 属主：测试\n", "- 做了什么：x\n", "- 为什么：y\n", "- 验证：z\n", "- 坑：无\n",
        "- 有效方法：a\n", "- 关联文件：b\n", "- 关联总索引：JS-20260728-99\n",
        "- 反事实对照：若没做会怎样\n", "- 置信度：高+依据\n",
        "- %s：本次预测\n" % _scope_tag(),
        "- baseline_comparison：本次为抓取层修复\n",
        "- honesty_note：彩票开奖独立随机，好结果多少是运气/幸存偏差\n",
    ])
    check_counterfactual(rep, _today_header(), body)
    warns = [w for _, ws in rep["warnings"] for w in ws]
    assert any("counterfactual_baseline" in w for w in warns), warns


def test_ac2_pure_random_no_number_warns():
    rep = {"warnings": []}
    # 含"随机"空话、无数值基线 → 触发 AC-2
    body = _base_body(counterfactual_baseline="随机")
    check_counterfactual(rep, _today_header(), body)
    warns = [w for _, ws in rep["warnings"] for w in ws]
    assert any("counterfactual_baseline" in w for w in warns), warns


def test_ac3_missing_honesty_keyword_warns():
    rep = {"warnings": []}
    # honesty_note 缺诚实关键词 → 触发 AC-3
    body = _base_body(honesty_note="本次为抓取层修复，与模型能力无关")
    check_counterfactual(rep, _today_header(), body)
    warns = [w for _, ws in rep["warnings"] for w in ws]
    assert any("honesty_note" in w for w in warns), warns


def test_ac5_old_card_no_warn():
    rep = {"warnings": []}
    # 旧卡（卡头无今日日期）缺三字段 → 不告警（祖父条款）
    body = "".join([
        "- 属主：测试\n", "- 做了什么：x\n", "- 为什么：y\n", "- 验证：z\n", "- 坑：无\n",
        "- 有效方法：a\n", "- 关联文件：b\n", "- 关联总索引：JS-20260723-99\n",
        "- 反事实对照：若没做会怎样\n", "- 置信度：高+依据\n",
        "- %s：本次预测\n" % _scope_tag(),
        # 三字段全缺
    ])
    check_counterfactual(rep, _old_header(), body)
    assert rep["warnings"] == [], rep["warnings"]


def test_positive_complete_card_no_warn():
    rep = {"warnings": []}
    # 完整三字段的预测卡 → 不告警（正向）
    body = _base_body()
    check_counterfactual(rep, _today_header(), body)
    assert rep["warnings"] == [], rep["warnings"]


def test_today_card_counterfactual_missing_is_warning_not_failure(tmp_path, monkeypatch):
    """集成：今日预测卡缺三字段 → 仅告警、[C] 仍 ok（fail-safe，退出码 0）。"""
    today = time.strftime("%Y-%m-%d")
    content = "".join([
        "# AI 决策卡\n",
        "### %s 测试预测卡\n" % today,
        "- 属主：测试\n", "- 做了什么：x\n", "- 为什么：y\n", "- 验证：z\n", "- 坑：无\n",
        "- 有效方法：a\n", "- 关联文件：b\n", "- 关联总索引：JS-20260728-99\n",
        "- 反事实对照：若没做会怎样\n", "- 置信度：高+依据\n",
        "- %s：本次预测\n" % _scope_tag(),  # 触发标签，但缺三字段
    ])
    p = tmp_path / "ai_decisions.md"
    p.write_text(content, encoding="utf-8")
    monkeypatch.setattr(closeout_gate, "DECISIONS", str(p))
    ok, detail = check_today_card(today)
    # 三字段缺失不翻转 ok（fail-safe）
    assert ok is True, detail
    assert detail["warnings"], "应记录反事实三字段告警"


def test_today_card_missing_required_field_still_fails(tmp_path, monkeypatch):
    """回归：今日卡缺 10 必填字段之一 → [C] 仍判不完整（既有权威行为不变）。"""
    today = time.strftime("%Y-%m-%d")
    content = "".join([
        "# AI 决策卡\n",
        "### %s 测试卡\n" % today,
        # 缺 属主
        "- 做了什么：x\n", "- 为什么：y\n", "- 验证：z\n", "- 坑：无\n",
        "- 有效方法：a\n", "- 关联文件：b\n", "- 关联总索引：JS-20260728-99\n",
        "- 反事实对照：若没做会怎样\n", "- 置信度：高+依据\n",
    ])
    p = tmp_path / "tmp_ai_decisions.md"
    p.write_text(content, encoding="utf-8")
    monkeypatch.setattr(closeout_gate, "DECISIONS", str(p))
    ok, detail = check_today_card(today)
    assert ok is False
    assert detail["incomplete"]


def test_constants_defined():
    assert "预测" in COUNTERFACTUAL_TRIGGER_TAGS
    assert "彩票" in COUNTERFACTUAL_TRIGGER_TAGS
    assert HONESTY_KEYWORDS == {"随机", "无法保证", "运气", "幸存偏差"}
