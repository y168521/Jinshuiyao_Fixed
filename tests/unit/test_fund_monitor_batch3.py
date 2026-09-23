# -*- coding: utf-8 -*-
"""批3 切片A（JS-20260924-01）单元测试：组合概览聚合 + 渲染。"""
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
