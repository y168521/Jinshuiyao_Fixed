# -*- coding: utf-8 -*-
"""误差分析：SQI 置信度校准报告（数学模型选号模块-误差分析维）

SQI 非中奖概率，本模块仅统计历史上 SQI 各档对应的实际中奖率，
展示"模型宣称的清晰度"与"实际命中"的偏差，防止误读。
"""
from collections import defaultdict


def calibrate(sqi_levels, actual_hits):
    """sqi_levels: list['strong'|'medium'|'weak'] 各期SQI档；actual_hits: list[bool] 实际是否中奖。
    返回各档 {count, hit_rate}。"""
    buckets = defaultdict(lambda: [0, 0])
    for lvl, hit in zip(sqi_levels, actual_hits):
        buckets[lvl][0] += 1
        buckets[lvl][1] += 1 if hit else 0
    out = {}
    for lvl in ("strong", "medium", "weak"):
        if lvl in buckets:
            n, h = buckets[lvl]
            out[lvl] = {"count": n, "hit_rate": round(h / n, 4) if n else 0.0}
    return {"calibration": out,
            "note": "SQI 仅反映信号清晰度，非中奖概率；下表展示各档历史实际命中率，用于校准认知偏差。"}
