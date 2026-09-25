# -*- coding: utf-8 -*-
"""交易指标计算"""
import logging

logger = logging.getLogger(__name__)


def trade_metrics(trades):
    """交易指标"""
    buy_trades = [t for t in trades if t.get("action") == "buy"]
    sell_trades = [t for t in trades if t.get("action") == "sell"]

    profits = []
    for sell in sell_trades:
        cost = sell.get("cost", 0) or sell.get("shares", 0) * sell.get("price", 0)
        revenue = sell.get("revenue", 0)
        if cost > 0:
            profits.append((revenue - cost) / cost)

    if not profits:
        return {"total_trades": len(trades), "profit_trades": 0, "win_rate": 0}

    win_count = sum(1 for p in profits if p > 0)
    avg_profit = sum(profits) / len(profits)
    avg_win = sum(p for p in profits if p > 0) / win_count if win_count > 0 else 0
    loss_count = len(profits) - win_count
    avg_loss = sum(p for p in profits if p <= 0) / loss_count if loss_count > 0 else 1
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    return {
        "total_trades": len(trades),
        "buy_count": len(buy_trades),
        "sell_count": len(sell_trades),
        "profit_trades": len(profits),
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": round(win_count / len(profits), 4),
        "avg_return": round(avg_profit, 4),
        "avg_return_pct": f"{avg_profit*100:.2f}%",
        "max_profit": round(max(profits), 4),
        "max_loss": round(min(profits), 4),
        "profit_factor": round(profit_factor, 2),
    }
