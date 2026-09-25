# -*- coding: utf-8 -*-
"""收益指标计算"""
import logging

logger = logging.getLogger(__name__)


def calc_returns(daily_values):
    """计算日收益率序列"""
    returns = []
    for i in range(1, len(daily_values)):
        prev = daily_values[i - 1]["value"]
        curr = daily_values[i]["value"]
        if prev > 0:
            returns.append((curr - prev) / prev)
    return returns


def return_metrics(daily_values, initial_capital):
    """收益指标"""
    final_value = daily_values[-1]["value"]
    total_return = (final_value - initial_capital) / initial_capital

    days = len(daily_values)
    annual_return = (1 + total_return) ** (252 / days) - 1 if days > 0 else 0

    return {
        "total_return": round(total_return, 4),
        "total_return_pct": f"{total_return*100:.2f}%",
        "annual_return": round(annual_return, 4),
        "annual_return_pct": f"{annual_return*100:.2f}%",
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
    }
