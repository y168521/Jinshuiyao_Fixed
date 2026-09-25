# -*- coding: utf-8 -*-
"""风险指标计算（最大回撤、波动率、夏普/索提诺/Calmar）"""
import logging

logger = logging.getLogger(__name__)


def max_drawdown_detail(daily_values):
    """计算最大回撤及区间"""
    peak = daily_values[0]["value"]
    peak_idx = 0
    max_dd = 0
    dd_start = daily_values[0]["date"]
    dd_end = daily_values[0]["date"]

    for i, dv in enumerate(daily_values):
        val = dv["value"]
        if val > peak:
            peak = val
            peak_idx = i
        dd = (peak - val) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            dd_start = daily_values[peak_idx]["date"]
            dd_end = dv["date"]

    return max_dd, dd_start, dd_end


def _volatility(returns):
    """年化波动率"""
    if len(returns) <= 1:
        return 0.0
    avg_ret = sum(returns) / len(returns)
    variance = sum((r - avg_ret) ** 2 for r in returns) / len(returns)
    return (variance ** 0.5) * (252 ** 0.5)


def _sharpe(returns, volatility, risk_free_rate):
    """夏普比率"""
    daily_rf = risk_free_rate / 252
    if volatility <= 0 or not returns:
        return 0.0
    excess_return = sum(returns) / len(returns) - daily_rf
    return (excess_return / (volatility / 252 ** 0.5)) * (252 ** 0.5)


def _sortino(returns, risk_free_rate):
    """索提诺比率（只考虑下行波动）"""
    downside = [r for r in returns if r < 0]
    if not downside:
        return 0.0
    downside_std = (sum(r ** 2 for r in downside) / len(downside)) ** 0.5
    downside_std *= (252 ** 0.5)
    if downside_std <= 0:
        return 0.0
    return (sum(returns) / len(returns) * 252 - risk_free_rate) / downside_std


def risk_metrics(daily_values, returns, risk_free_rate=0.03):
    """风险指标"""
    max_dd, max_dd_start, max_dd_end = max_drawdown_detail(daily_values)
    volatility = _volatility(returns)
    sharpe = _sharpe(returns, volatility, risk_free_rate)
    sortino = _sortino(returns, risk_free_rate)

    calmar = (sum(returns) / len(returns) * 252) / max_dd if max_dd > 0 and returns else 0

    return {
        "max_drawdown": round(max_dd, 4),
        "max_drawdown_pct": f"{max_dd*100:.2f}%",
        "max_dd_period": {"start": max_dd_start, "end": max_dd_end},
        "volatility": round(volatility, 4),
        "volatility_pct": f"{volatility*100:.2f}%",
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "calmar_ratio": round(calmar, 3),
    }
