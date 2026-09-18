# -*- coding: utf-8 -*-
"""engines/math_selector/stats.py 描述性统计 + 概率分布 纯函数单测（JS-20260917-03）"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from engines.math_selector import stats


def test_descriptive_basic():
    v = [1, 2, 2, 3, 9]
    assert stats.mean(v) == 3.4
    assert stats.median(v) == 2.0
    assert stats.mode(v) == [2]
    assert stats.stat_range(v) == 8
    # 样本方差 41.2/4=10.3 → std≈3.209
    assert abs(stats.std(v, ddof=1) - 3.209) < 0.01


def test_descriptive_empty():
    assert stats.mean([]) == 0.0
    assert stats.median([]) == 0.0
    assert stats.mode([]) == []
    assert stats.variance([]) == 0.0
    assert stats.stat_range([5]) == 0.0


def test_describe_shape():
    d = stats.describe([1, 2, 2, 3, 9])
    for k in ("count", "mean", "median", "mode", "variance", "std", "range"):
        assert k in d
    assert d["count"] == 5


def test_poisson_pmf():
    # λ=1: P(0)=e^-1≈0.368, P(1)=0.368
    assert abs(stats.poisson_pmf(1.0, 0) - 0.3679) < 0.001
    assert abs(stats.poisson_pmf(1.0, 1) - 0.3679) < 0.001
    assert stats.poisson_pmf(0, 0) == 1.0
    assert stats.poisson_pmf(-1, 2) == 0.0


def test_binomial_pmf():
    # 七星彩每位独立对上概率 0.1，7 位 → 二项分布 Binomial(7,0.1)
    # 任中至少 1 位：1 - 0.9^7 ≈ 0.5217（这就是"任中1码"随机基线）
    p_at_least_1 = 1.0 - stats.binomial_pmf(7, 0, 0.1)
    assert abs(p_at_least_1 - 0.5217) < 0.001
    # 恰中 2 位：C(7,2)*0.1^2*0.9^5 ≈ 0.1240
    assert abs(stats.binomial_pmf(7, 2, 0.1) - 0.1240) < 0.001
    # 总和归一
    tot = sum(stats.binomial_pmf(10, k, 0.5) for k in range(11))
    assert abs(tot - 1.0) < 1e-9


def test_bernoulli_pmf():
    assert stats.bernoulli_pmf(0.1, 1) == 0.1
    assert stats.bernoulli_pmf(0.1, 0) == 0.9
    assert stats.bernoulli_pmf(0.1, 2) == 0.0


def test_max_drawdown():
    # 单调上升 → 0 回撤
    assert stats.max_drawdown([100, 110, 120, 130])["max_drawdown"] == 0.0
    # 100→80→90: 回撤 20%
    dd = stats.max_drawdown([100, 80, 90, 70, 95])
    assert abs(dd["max_drawdown"] - 0.3) < 0.001
    assert dd["peak_idx"] == 0 and dd["trough_idx"] == 3
