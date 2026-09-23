# -*- coding: utf-8 -*-
"""JS-20260924-02 日报三处修复单元测试：90天口径统一 / 日涨跌兜底 / Calmar 边界。"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pandas as pd
import scripts.daily_fund_monitor as m


def test_take_profit_endpoint_matches_total_return():
    """修复1：止盈端点与 calc_total_return 同源时，两个「90天」数值必须完全相等。"""
    nav = pd.Series([3.0, 2.9, 2.85, 2.87, 2.8505])
    tr = m.RiskCalculator.calc_total_return(nav)
    tp = m.SignalDetector.check_take_profit(float(nav.iloc[-1]), 3000, 0.164, nav)
    assert tp["current_return"] == tr


def test_wrong_endpoint_produces_different_value():
    """反证：若仍传快照源净值（与历史末值不同），两个「90天」就会不一致（即原 bug）。"""
    nav = pd.Series([3.0, 2.9, 2.85, 2.87, 2.8505])
    tr = m.RiskCalculator.calc_total_return(nav)
    tp_bug = m.SignalDetector.check_take_profit(2.9, 3000, 0.164, nav)  # 模拟两源不一致
    assert tp_bug["current_return"] != tr


def test_daily_return_fallback_fills_from_history():
    """修复2：快照日涨跌缺失时，用历史末两个净值补算。"""
    snap = {"daily_return": None}
    hist = pd.Series([1.0, 1.02])  # 末两点：1.0 -> 1.02 = +2.00%
    m._fill_daily_return_from_history(snap, hist)
    assert snap["daily_return"] == 2.0


def test_daily_return_fallback_no_overwrite():
    """已有日涨跌时不得覆盖（源数据优先）。"""
    snap = {"daily_return": 1.23}
    m._fill_daily_return_from_history(snap, pd.Series([1.0, 9.0]))
    assert snap["daily_return"] == 1.23


def test_daily_return_fallback_insufficient_history():
    """历史不足 2 点时保持 None，不编造。"""
    snap = {"daily_return": None}
    m._fill_daily_return_from_history(snap, pd.Series([1.0]))
    assert snap["daily_return"] is None


def test_daily_return_fallback_zero_prev_nav():
    """前值为 0 时避免除零，保持 None。"""
    snap = {"daily_return": None}
    m._fill_daily_return_from_history(snap, pd.Series([0.0, 1.0]))
    assert snap["daily_return"] is None


def test_calmar_none_when_drawdown_tiny():
    """修复3：回撤极小时返回 None（渲染「—」），不再给出 145.62 这类发散值。"""
    hist = pd.Series([1.0000, 1.0001, 1.0000, 1.0002, 1.0003,
                      1.0002, 1.0004, 1.0005, 1.0006, 1.0007])
    assert m.RiskCalculator.calc_calmar(hist) is None


def test_calmar_computed_when_drawdown_enough():
    """回撤足够时正常算出 Calmar。"""
    hist = pd.Series([1.0, 1.2, 1.1, 1.3, 1.25, 1.4, 1.35, 1.5, 1.45, 1.6])
    val = m.RiskCalculator.calc_calmar(hist)
    assert val is not None


def test_calmar_none_when_insufficient():
    """样本不足返回 None，不再是伪精确的 0.0。"""
    assert m.RiskCalculator.calc_calmar(pd.Series([1.0, 1.1])) is None


def test_total_return_none_when_insufficient():
    """样本不足返回 None，避免被渲染成「0.00%」误导为「没涨没跌」。"""
    assert m.RiskCalculator.calc_total_return(pd.Series([1.0])) is None


def test_total_return_normal():
    hist = pd.Series([1.0, 1.1, 1.2])
    assert m.RiskCalculator.calc_total_return(hist) == 20.0
