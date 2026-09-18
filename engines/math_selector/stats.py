# -*- coding: utf-8 -*-
"""统计推断 + 偏离波动：χ²均匀性检验 + z-score 偏离量化（数学模型选号模块）

诚实定位：统计推断只用于"描述分布/验证随机性"，不预测下期。
热号冷号预测下期=赌徒谬误（每期独立）。
"""
from math import sqrt, erf, exp, factorial, comb
from collections import Counter


def _norm_cdf(x):
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def chi2_uniform(observed):
    """单样本χ²均匀性检验。observed: list[int] 各号出现频次。
    返回 {chi2, df, p_value(近似), uniform, note}。"""
    k = len(observed)
    n = sum(observed)
    if k < 2 or n == 0:
        return {"chi2": 0.0, "df": 0, "p_value": 1.0, "uniform": True,
                "note": "样本不足"}
    exp = n / k
    chi2 = sum((o - exp) ** 2 / exp for o in observed)
    df = k - 1
    if df >= 2:
        z = (chi2 - df) / sqrt(2.0 * df)
        p = 1.0 - _norm_cdf(z)
    else:
        p = 1.0
    return {"chi2": round(chi2, 3), "df": df, "p_value": round(p, 4),
            "uniform": chi2 < df + 2.0 * sqrt(2.0 * df),
            "note": "p_value>0.05 表示不能拒绝'各号均匀'假设，符合随机抽取。"}


def zscore_deviation(values):
    """values: 各号某统计量（遗漏/频次）。返回 z-score 与极端项。"""
    n = len(values)
    if n < 2:
        return {"mean": 0.0, "std": 0.0, "zscores": [], "extreme": [],
                "note": "样本不足"}
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    std = sqrt(var) if var > 0 else 0.0
    zs = [(v - mean) / std if std > 0 else 0.0 for v in values]
    extreme = [i for i, z in enumerate(zs) if abs(z) > 2.0]
    return {"mean": round(mean, 3), "std": round(std, 3),
            "zscores": [round(z, 2) for z in zs], "extreme": extreme,
            "note": "z>2 仅表示偏离长期均值>2σ；随机序列本身约5%概率出现，非预测信号。"}


# ---------------------------------------------------------------------------
# 描述性统计基础（用户清单首项）：任何数字分析的第一步
# 诚实定位：只描述"已发生数据的样子"，不推断"下期会怎样"。
# ---------------------------------------------------------------------------

def mean(values):
    """算术均值。空/非数值返回 0.0。"""
    vals = [v for v in values if isinstance(v, (int, float))]
    return sum(vals) / len(vals) if vals else 0.0


def median(values):
    """中位数（偶数取中间两值均值）。空返回 0.0。"""
    vals = sorted(v for v in values if isinstance(v, (int, float)))
    n = len(vals)
    if n == 0:
        return 0.0
    if n % 2:
        return vals[n // 2]
    return (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def mode(values):
    """众数（可能多个，返回升序列表）。空返回 []。"""
    vals = [v for v in values if isinstance(v, (int, float))]
    if not vals:
        return []
    c = Counter(vals)
    top = max(c.values())
    return sorted(k for k, v in c.items() if v == top)


def variance(values, ddof=0):
    """方差（ddof=0 总体，ddof=1 样本）。空/单值返回 0.0。"""
    vals = [v for v in values if isinstance(v, (int, float))]
    n = len(vals)
    if n <= ddof:
        return 0.0
    m = sum(vals) / n
    return sum((v - m) ** 2 for v in vals) / (n - ddof)


def std(values, ddof=0):
    """标准差。"""
    return sqrt(variance(values, ddof=ddof))


def stat_range(values):
    """极差 = 最大值 - 最小值。空/单值返回 0.0。"""
    vals = [v for v in values if isinstance(v, (int, float))]
    return max(vals) - min(vals) if len(vals) >= 2 else 0.0


def describe(values):
    """一次性给出均值/中位数/众数/方差/标准差/极差，便于前端直接消费。"""
    return {
        "count": len([v for v in values if isinstance(v, (int, float))]),
        "mean": round(mean(values), 3),
        "median": round(median(values), 3),
        "mode": mode(values),
        "variance": round(variance(values, ddof=1), 3),
        "std": round(std(values, ddof=1), 3),
        "range": round(stat_range(values), 3),
    }


# ---------------------------------------------------------------------------
# 概率分布（用户清单）：理论对照 / 随机性验证，不作选号依据
# ---------------------------------------------------------------------------

def poisson_pmf(lam, k):
    """泊松分布 P(X=k)，用于"某号码出现次数"的理论对照（λ=期望频次）。"""
    if k < 0 or lam < 0:
        return 0.0
    if lam == 0.0:
        return 1.0 if k == 0 else 0.0
    return exp(-lam) * (lam ** k) / factorial(k)


def binomial_pmf(n, k, p):
    """二项分布 P(X=k)，用于"中 k 码"的理论命中概率（n 选号数, p 单码概率）。"""
    if k < 0 or k > n or p < 0 or p > 1:
        return 0.0
    return comb(n, k) * (p ** k) * ((1 - p) ** (n - k))


def bernoulli_pmf(p, k):
    """伯努利分布 P(X=k)（k∈{0,1}），单码是否出现的单次试验。"""
    if k not in (0, 1):
        return 0.0
    return p if k == 1 else 1.0 - p


# ---------------------------------------------------------------------------
# 风险比率（用户清单）：最大回撤，衡量收益曲线最坏跌幅
# ---------------------------------------------------------------------------

def max_drawdown(series):
    """series: 单调递增的资产/收益序列。返回最大回撤比例(0~1)与对应区间。"""
    vals = [v for v in series if isinstance(v, (int, float))]
    if len(vals) < 2:
        return {"max_drawdown": 0.0, "peak_idx": 0, "trough_idx": 0}
    peak = vals[0]
    peak_i = 0
    worst = 0.0
    worst_peak, worst_trough = 0, 0
    for i, v in enumerate(vals):
        if v > peak:
            peak = v
            peak_i = i
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > worst:
            worst = dd
            worst_peak, worst_trough = peak_i, i
    return {"max_drawdown": round(worst, 4),
            "peak_idx": worst_peak, "trough_idx": worst_trough}
