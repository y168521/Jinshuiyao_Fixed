# -*- coding: utf-8 -*-
"""金水谣系统 - 校验器集合"""
from collections import Counter
from utils.number_utils import parse_reds, clean_nums, calc_ac


class AdvancedValidator:
    @staticmethod
    def check(lot, reds, blues=None):
        if lot not in ["双色球", "大乐透"]:
            return True, ""
        # 【修复】改为评分制，硬拦截改为扣分，降低误杀率
        score = 0
        s = sum(reds)
        span = max(reds) - min(reds)
        ac = calc_ac(reds)
        
        # 和值评分（70-150覆盖率约60%，放宽限制）
        if s < 50 or s > 180:
            score += 30
        elif s < 60 or s > 170:
            score += 20
        elif s < 70 or s > 160:
            score += 10
        
        # 跨度评分（15-32覆盖率约85%，放宽限制）
        if span < 10 or span > 35:
            score += 30
        elif span < 15 or span > 32:
            score += 15
        
        # AC值评分
        if ac < 3 or ac > 13:
            score += 20
        elif ac < 4 or ac > 12:
            score += 10
        
        # 红蓝重号硬拦截
        if blues and set(reds) & set(blues):
            return False, "红蓝重号"
        
        # 总分阈值 40，超过则拒绝
        return score <= 40, "" if score <= 40 else f"评分{score}超过阈值"


class KillChecker:
    @staticmethod
    def is_killed(lot, nums, history):
        if lot not in ["福彩3D", "排列三"] or not history:
            return False
        last_nums = parse_reds(clean_nums(history[-1]["nums"]))
        if len(last_nums) != 3:
            return False
        kd = max(last_nums) - min(last_nums)
        if sum(nums) % 10 == kd % 10:
            return True
        if nums[1] == (sum(last_nums) % 10 + kd) % 10:
            return True
        return False


class SmartKillScorer:
    def __init__(self, history):
        self.history = history

    def score(self, lot, reds):
        score = 0
        if not self.history:
            return score
        last = self.history[-1]
        last_reds = parse_reds(last["nums"].split("+")[0])
        overlap = len(set(reds) & set(last_reds))
        if overlap >= 3:
            score += 30
        elif overlap == 2:
            score += 10
        if "+" in last["nums"]:
            last_blue = parse_reds(last["nums"].split("+")[1])
            if set(reds) & set(last_blue):
                score += 10
        freq = Counter()
        for d in self.history[-5:]:
            freq.update(parse_reds(d["nums"].split("+")[0]))
        for r in reds:
            if freq.get(r, 0) >= 3:
                score += 20
        all_nums = [n for d in self.history for n in parse_reds(d["nums"].split("+")[0])]
        num_counter = Counter(all_nums)
        for r in reds:
            if num_counter.get(r, 0) < len(self.history) * 0.1:
                score += 15
        if abs(sum(reds) - sum(last_reds)) > 25:
            score += 20
        return score