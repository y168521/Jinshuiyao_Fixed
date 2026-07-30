# -*- coding: utf-8 -*-
"""时间序列：自相关(ACF) + 平稳性检验（数学模型选号模块）

诚实定位：若开奖真随机，序列无显著滞后相关、平稳。时间序列模型拟合的是
噪声，预测无意义；本模块反向用于"证明无时序规律"，增强诚实性。
"""
from math import sqrt


def acf(series, max_lag=10):
    n = len(series)
    if n < max_lag + 2:
        return []
    mu = sum(series) / n
    var = sum((x - mu) ** 2 for x in series) / n
    if var == 0:
        return [0.0] * max_lag
    out = []
    for lag in range(1, max_lag + 1):
        cov = sum((series[i] - mu) * (series[i - lag] - mu) for i in range(lag, n)) / (n - lag)
        out.append(round(cov / var, 3))
    return out


def stationarity_report(series, max_lag=10):
    a = acf(series, max_lag)
    if not a:
        return {"acf": [], "threshold": 0.0, "significant_lags": [], "stationary": True,
                "note": "数据不足"}
    th = round(1.96 / sqrt(len(series)), 3)
    sig = [i + 1 for i, v in enumerate(a) if abs(v) > th]
    stationary = len(sig) <= max(1, int(0.1 * max_lag))
    return {"acf": a, "threshold": th, "significant_lags": sig, "stationary": stationary,
            "note": "stationary=True 表示无显著自相关，符合随机抽取假设；任何选号策略无法利用时序规律。"}
