# -*- coding: utf-8 -*-
"""策略对比（A/B 测试）"""
import logging

logger = logging.getLogger(__name__)


def _extract(report):
    return {
        "return": report.get("total_return", 0),
        "max_dd": report.get("max_drawdown", 0),
        "sharpe": report.get("sharpe_ratio", 0),
        "win_rate": report.get("win_rate", 0),
        "trades": report.get("trade_count", 0),
    }


def compare_strategies(results_a, results_b):
    """A/B 测试：对比两个策略的回测结果"""
    a = _extract(results_a)
    b = _extract(results_b)

    comparisons = {
        "return": {"a": a["return"], "b": b["return"], "winner": "A" if a["return"] > b["return"] else "B"},
        "max_dd": {"a": a["max_dd"], "b": b["max_dd"], "winner": "A" if a["max_dd"] < b["max_dd"] else "B"},
        "sharpe": {"a": a["sharpe"], "b": b["sharpe"], "winner": "A" if a["sharpe"] > b["sharpe"] else "B"},
        "win_rate": {"a": a["win_rate"], "b": b["win_rate"], "winner": "A" if a["win_rate"] > b["win_rate"] else "B"},
    }

    score_a = a["return"] + a["sharpe"] * 0.5 + a["win_rate"] - a["max_dd"] * 2
    score_b = b["return"] + b["sharpe"] * 0.5 + b["win_rate"] - b["max_dd"] * 2

    return {
        "comparisons": comparisons,
        "overall_winner": "A" if score_a > score_b else "B",
        "score_a": round(score_a, 4),
        "score_b": round(score_b, 4),
        "recommendation": "策略A更优" if score_a > score_b else "策略B更优",
    }
