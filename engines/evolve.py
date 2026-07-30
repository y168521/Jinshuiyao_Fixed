# -*- coding: utf-8 -*-
"""金水谣系统 - 热号进化训练（优化版）

优化要点：
- 加入 hot_window 参数，只用近N期数据计算热号（默认80期）
- 增大衰减系数 lambda 从 0.08 提高到 0.15，让远期数据更快衰减
- 近期加成从 1.1 提高到 1.3，更强调近期趋势
- 失败惩罚从 0.3 降到 0.5，减少过度惩罚
"""
import math
from collections import Counter, defaultdict
from models.lottery_data import Data
from utils.number_utils import parse_reds, clean_nums
from config import LOTTERY_RULES

# 默认只用最近80期数据计算热号
DEFAULT_HOT_WINDOW = 80


class Evolve:
    def __init__(self, lambda_decay=0.15):
        self.failure_counter = defaultdict(int)
        self.lambda_decay = lambda_decay

    def train(self, name, predictions=None, hurst=None, hot_window=DEFAULT_HOT_WINDOW):
        a = Data.load(name)
        if not a:
            return {}
        # 只使用最近N期数据
        if hot_window and len(a) > hot_window:
            a = a[-hot_window:]
        lam = self.lambda_decay
        if hurst:
            if hurst > 0.55:
                lam *= 0.7
            elif hurst < 0.45:
                lam *= 1.4
        rule = LOTTERY_RULES.get(name, {})
        red_rule = rule.get("red", (0, 99))
        if isinstance(red_rule[0], tuple):
            rmin, rmax = 0, max(r[1] for r in red_rule)
        else:
            rmin, rmax = red_rule[0], red_rule[1]
        weighted = Counter()
        latest = max(x["period"] for x in a) if a else 0
        for d in a:
            period_diff = latest - d["period"]
            w = math.exp(-lam * period_diff)
            # 近5期加成从1.1提高到1.3，更强调近期
            if period_diff <= 5:
                w *= 1.3
            reds = [n for n in parse_reds(d["nums"].split("+")[0]) if rmin <= n <= rmax]
            for n in reds:
                weighted[n] += w
        blue_rule = rule.get("blue")
        if blue_rule:
            bmin, bmax, _ = blue_rule
            for d in a:
                if "+" in d.get("nums", ""):
                    period_diff = latest - d["period"]
                    w = math.exp(-lam * period_diff)
                    if period_diff <= 5:
                        w *= 1.3
                    blues = [n for n in parse_reds(d["nums"].split("+")[1]) if bmin <= n <= bmax]
                    for n in blues:
                        weighted[n] += w * 0.3
        total = sum(weighted.values())
        hot = {k: v / total for k, v in weighted.items()} if total else {}
        if predictions:
            for p in predictions:
                if p.get("lot") != name or not p.get("reviewed"):
                    continue
                hits = p.get("hits", 0)
                nums = [n for n in parse_reds(clean_nums(p.get("nums", "")).split("+")[0]) if rmin <= n <= rmax]
                factor = max(0.1, hits / max(1, len(nums)))
                for n in nums:
                    if n in hot:
                        hot[n] *= (0.7 + 0.6 * factor)
                    else:
                        hot[n] = 0.01 * (0.7 + 0.6 * factor)
                if hits == 0:
                    for n in nums:
                        self.failure_counter[n] += 1
                    for n in nums:
                        # 惩罚从0.3提高到0.5（乘以0.5=减半）
                        if self.failure_counter[n] >= 2 and n in hot:
                            hot[n] *= 0.5
                else:
                    for n in nums:
                        self.failure_counter[n] = 0
        t2 = sum(hot.values()) or 1
        return {k: v / t2 for k, v in hot.items()}
