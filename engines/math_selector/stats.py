# -*- coding: utf-8 -*-
"""统计推断 + 偏离波动：χ²均匀性检验 + z-score 偏离量化（数学模型选号模块）

诚实定位：统计推断只用于"描述分布/验证随机性"，不预测下期。
热号冷号预测下期=赌徒谬误（每期独立）。
"""
from math import sqrt, erf
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
