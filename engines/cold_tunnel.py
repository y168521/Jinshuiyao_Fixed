# -*- coding: utf-8 -*-
"""金水谣系统 - 冷号突破概率"""
import math
from utils.number_utils import parse_reds


class ColdTunnel:
    @staticmethod
    def breakthrough_prob(lot, num, history):
        if not history:
            return 0.0
        intervals = []
        last = None
        for i, d in enumerate(history):
            if num in parse_reds(d.get("nums", "").split("+")[0]):
                if last is not None:
                    intervals.append(i - last)
                last = i
        if not intervals:
            return 0.01
        avg = sum(intervals) / len(intervals)
        lam = 1.0 / max(1, avg)
        prob = 1 - math.exp(-lam)
        missing = 0
        for d in reversed(history):
            if num in parse_reds(d.get("nums", "").split("+")[0]):
                break
            missing += 1
        if missing > avg * 2:
            prob = min(0.5, prob * 1.5)
        return prob