# -*- coding: utf-8 -*-
"""金水谣系统 - 赫斯特指数计算器"""
import math


class HurstCalculator:
    @staticmethod
    def compute(sequence):
        if len(sequence) < 50:
            return 0.5
        lags = range(2, min(20, len(sequence) // 2))
        rs = []
        for lag in lags:
            chunks = [sequence[i:i + lag] for i in range(0, len(sequence) - lag + 1, lag)]
            if len(chunks) < 2:
                continue
            rs_chunk = []
            for chunk in chunks:
                mean = sum(chunk) / len(chunk)
                devs = [x - mean for x in chunk]
                cum = [sum(devs[:i + 1]) for i in range(len(devs))]
                R = max(cum) - min(cum)
                S = math.sqrt(sum(d ** 2 for d in devs) / len(devs))
                if S < 1e-10:
                    continue
                rs_chunk.append(R / S)
            if rs_chunk:
                rs.append((lag, sum(rs_chunk) / len(rs_chunk)))
        if not rs:
            return 0.5
        log_lags = [math.log(l) for l, _ in rs]
        log_rs = [math.log(r) for _, r in rs]
        n = len(log_lags)
        sx = sum(log_lags)
        sy = sum(log_rs)
        sxx = sum(x * x for x in log_lags)
        sxy = sum(x * y for x, y in zip(log_lags, log_rs))
        denom = n * sxx - sx * sx
        if abs(denom) < 1e-10:
            return 0.5
        return max(0.1, min(1.0, (n * sxy - sx * sy) / denom))