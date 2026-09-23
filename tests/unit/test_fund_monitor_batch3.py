# -*- coding: utf-8 -*-
"""批3 切片A（JS-20260924-03）单元测试：组合概览聚合 + 渲染。"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import scripts.daily_fund_monitor as m


def _fund(code, name, inv_1y, ret_90, max_dd, sharpe):
    return {code: {
        "config": {"name": name, "code": code},
        "interval_returns": {"近1年": inv_1y},
        "risks": {"total_return": ret_90, "max_drawdown": max_dd, "sharpe": sharpe},
    }}


def test_aggregate_best_worst():
    data = {}
    data.update(_fund("A", "基金甲", 20.0, 5.0, -10.0, 1.5))
    data.update(_fund("B", "基金乙", -5.0, -2.0, -25.0, 0.3))
    data.update(_fund("C", "基金丙", 8.0, 3.0, -15.0, 1.1))
    ov = m._aggregate_portfolio(data)
    assert ov["best_1y"]["code"] == "A" and ov["best_1y"]["inv_1y"] == 20.0
    assert ov["worst_1y"]["code"] == "B"
    assert ov["best_90"]["code"] == "A" and ov["best_90"]["ret_90"] == 5.0
    assert ov["worst_90"]["code"] == "B"
    assert ov["worst_dd"]["code"] == "B" and ov["worst_dd"]["max_dd"] == -25.0
    assert ov["best_sharpe"]["code"] == "A"


def test_aggregate_handles_missing():
    data = {"X": {"config": {"name": "基金X"}, "interval_returns": {}, "risks": {}}}
    ov = m._aggregate_portfolio(data)
    # 全缺失时极值返回 None，不抛错
    assert ov["best_1y"] is None
    assert ov["worst_dd"] is None


def test_aggregate_dca(monkeypatch):
    fake = [
        {"dca_freq": "daily", "dca_amount": 10},
        {"dca_freq": "daily", "dca_amount": 10},
        {"dca_freq": "weekly", "dca_amount": 170},
    ]
    monkeypatch.setattr(m, "FUND_CONFIG", fake)
    ov = m._aggregate_portfolio({"Y": {"config": {"name": "Y"}, "interval_returns": {}, "risks": {}}})
    assert ov["dca_daily"] == 20
    assert ov["dca_weekly"] == 170


def test_render_contains_names_and_pct():
    data = {}
    data.update(_fund("A", "基金甲", 20.0, 5.0, -10.0, 1.5))
    data.update(_fund("B", "基金乙", -5.0, -2.0, -25.0, 0.3))
    ov = m._aggregate_portfolio(data)
    html = m._render_portfolio_overview(ov)
    assert "基金甲" in html and "基金乙" in html
    assert "+20.00%" in html
    assert "夏普最高" in html
    assert "定投计划" in html
    assert "summary-bar" in html


# ---------------------------------------------------------------
# JS-20260924-04 批3·切片B：加仓规则引擎
# ---------------------------------------------------------------

IDX = {"code": "270042", "name": "纳指基金", "related_index": "纳斯达克100"}
OTH = {"code": "011369", "name": "普通混合", "related_index": "沪深300"}


def test_add_index_tier1():
    """纳指/标普/恒生科技 跌 1%~3%（含 3%）→ 10 元。"""
    assert m._suggest_add_position(-1.5, IDX)["amount"] == m.ADD_AMOUNT_TIER1
    assert m._suggest_add_position(-3.0, IDX)["amount"] == m.ADD_AMOUNT_TIER1


def test_add_index_tier2():
    """跌 >3% → 20 元（边界：3.01 已进第二档）。"""
    assert m._suggest_add_position(-3.01, IDX)["amount"] == m.ADD_AMOUNT_TIER2
    assert m._suggest_add_position(-8.81, IDX)["amount"] == m.ADD_AMOUNT_TIER2


def test_add_other_fund_only_big_drop():
    """非指数基金：1%~3% 不给建议；>3% 才给 20 元。"""
    assert m._suggest_add_position(-1.5, OTH) is None
    assert m._suggest_add_position(-3.0, OTH) is None
    assert m._suggest_add_position(-5.0, OTH)["amount"] == m.ADD_AMOUNT_TIER2


def test_add_no_suggestion_when_rise_or_tiny():
    """上涨或跌幅不足 1% 不给建议。"""
    assert m._suggest_add_position(+2.0, IDX) is None
    assert m._suggest_add_position(-0.5, IDX) is None
    assert m._suggest_add_position(0.0, IDX) is None


def test_add_none_when_data_missing():
    """日涨跌缺失（None）时返回 None，绝不编造。"""
    assert m._suggest_add_position(None, IDX) is None


def test_add_reason_is_honest():
    """建议文案必须写明是规则建议，且不带执行语义。"""
    r = m._suggest_add_position(-4.0, IDX)
    assert "单日跌 4.00%" in r["reason"]


# ---------------------------------------------------------------
# JS-20260924-04 批3·切片C：今日操作待办
# ---------------------------------------------------------------

def _mk(code, name, tp=None, limited=False, drop=False, daily=None, related_index="沪深300"):
    return {code: {
        "config": {"code": code, "name": name, "related_index": related_index},
        "snapshot": {"daily_return": daily},
        "signals": {
            "take_profit": tp or {"signal": False, "warn": False, "message": ""},
            "purchase_limit": {"is_limited": limited, "status": "限大额" if limited else "开放申购"},
            "significant_drop": {"signal": drop, "message": "近5日下跌 -6.00% ⚠️ 显著下跌！"} if drop
                                else {"signal": False, "message": ""},
        },
    }}


def test_todo_alert_from_take_profit():
    items = m._build_todo_items(_mk("A", "甲", tp={"signal": True, "warn": False, "message": "已达止盈"}))
    assert len(items) == 1 and items[0]["level"] == m.TODO_LEVEL_ALERT


def test_todo_warning_from_warn_and_limit():
    data = _mk("A", "甲", tp={"signal": False, "warn": True, "message": "已过预警线"}, limited=True)
    items = m._build_todo_items(data)
    assert [i["level"] for i in items] == [m.TODO_LEVEL_WARNING, m.TODO_LEVEL_WARNING]


def test_todo_info_from_add_rule():
    items = m._build_todo_items(_mk("A", "甲", daily=-4.0, related_index="纳斯达克100"))
    assert len(items) == 1 and items[0]["level"] == m.TODO_LEVEL_INFO
    assert "20 元" in items[0]["action"]


def test_todo_sorted_by_level():
    data = {}
    data.update(_mk("B", "乙", daily=-4.0, related_index="标普500"))          # 蓝
    data.update(_mk("A", "甲", tp={"signal": True, "warn": False, "message": "止盈"}))  # 红
    data.update(_mk("C", "丙", limited=True))                                  # 橙
    items = m._build_todo_items(data)
    assert [i["level"] for i in items] == [
        m.TODO_LEVEL_ALERT, m.TODO_LEVEL_WARNING, m.TODO_LEVEL_INFO]


def test_todo_empty_renders_no_action():
    html = m._render_todo([])
    assert "今日无需操作" in html


def test_todo_render_has_table_and_levels():
    data = _mk("A", "甲", tp={"signal": True, "warn": False, "message": "已达止盈 16.4%"})
    html = m._render_todo(m._build_todo_items(data))
    assert "todo-table" in html
    assert m._LEVEL_TEXT[m.TODO_LEVEL_ALERT] in html
    assert "不代客下单" in html or "不会自动下单" in html
