# -*- coding: utf-8 -*-
"""收益率分布统计"""
import logging

logger = logging.getLogger(__name__)


def return_distribution(returns):
    """收益率分布统计"""
    if not returns:
        return {}

    sorted_returns = sorted(returns)
    n = len(sorted_returns)
    mean = sum(returns) / n

    def percentile(p):
        idx = int(n * p / 100)
        return sorted_returns[max(0, min(idx, n - 1))]

    return {
        "count": n,
        "mean": round(mean, 6),
        "median": round(sorted_returns[n // 2], 6),
        "std": round((sum((r - mean) ** 2 for r in returns) / n) ** 0.5, 6),
        "min": round(sorted_returns[0], 6),
        "max": round(sorted_returns[-1], 6),
        "p5": round(percentile(5), 6),
        "p25": round(percentile(25), 6),
        "p75": round(percentile(75), 6),
        "p95": round(percentile(95), 6),
        "positive_days": sum(1 for r in returns if r > 0),
        "negative_days": sum(1 for r in returns if r < 0),
    }
