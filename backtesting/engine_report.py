# -*- coding: utf-8 -*-
"""回测报告生成 —— 从 BacktestEngine 抽出的报告构建逻辑"""
import logging

logger = logging.getLogger(__name__)


def calc_max_drawdown(daily_values):
    """计算最大回撤（基于每日资产总值序列）"""
    if not daily_values:
        return 0.0
    peak = daily_values[0]["value"]
    max_dd = 0.0
    for dv in daily_values:
        val = dv["value"]
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def calc_daily_returns(daily_values):
    """从每日资产总值计算日收益率序列"""
    returns = []
    for i in range(1, len(daily_values)):
        prev = daily_values[i - 1]["value"]
        curr = daily_values[i]["value"]
        if prev > 0:
            returns.append((curr - prev) / prev)
    return returns


def calc_sharpe(returns):
    """简化夏普比率（无风险利率=0，年化）"""
    if not returns:
        return 0.0
    avg_ret = sum(returns) / len(returns)
    var = sum((r - avg_ret) ** 2 for r in returns) / len(returns)
    std = var ** 0.5
    if std <= 0:
        return 0.0
    return (avg_ret / std) * (252 ** 0.5)


def calc_win_rate(trades):
    """计算卖出交易的胜率"""
    win_trades = sum(1 for t in trades if t.get("action") == "sell" and t.get("revenue", 0) > t.get("cost", 0))
    total_trades = sum(1 for t in trades if t.get("action") == "sell")
    return win_trades, total_trades


def build_report(engine):
    """生成回测报告

    Args:
        engine: BacktestEngine 实例（读取 daily_values/trades/name/initial_capital）

    Returns:
        dict: 回测报告
    """
    if not engine.daily_values:
        return {"error": "无回测数据"}

    final_value = engine.daily_values[-1]["value"]
    total_return = (final_value - engine.initial_capital) / engine.initial_capital
    max_dd = calc_max_drawdown(engine.daily_values)
    returns = calc_daily_returns(engine.daily_values)
    sharpe = calc_sharpe(returns)
    win_trades, total_trades = calc_win_rate(engine.trades)

    return {
        "name": engine.name,
        "type": "stock",
        "initial_capital": engine.initial_capital,
        "final_value": round(final_value, 2),
        "total_return": round(total_return, 4),
        "total_return_pct": f"{total_return*100:.2f}%",
        "max_drawdown": round(max_dd, 4),
        "max_drawdown_pct": f"{max_dd*100:.2f}%",
        "sharpe_ratio": round(sharpe, 3),
        "total_trades": total_trades,
        "win_trades": win_trades,
        "win_rate": round(win_trades / total_trades, 4) if total_trades > 0 else 0,
        "trade_count": len(engine.trades),
        "daily_values": engine.daily_values,
        "trades": engine.trades,
        "summary": (f"回测完成: 初始{engine.initial_capital:.0f} → 最终{final_value:.2f} "
                   f"(收益率{total_return*100:.2f}%, 最大回撤{max_dd*100:.2f}%, 夏普{sharpe:.2f})"),
    }
