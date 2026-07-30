# -*- coding: utf-8 -*-
"""金水谣系统 - 批量预测参考解析器"""
import re
from config import LOTTERY_RULES


class SuperParser:
    def __init__(self, text):
        self.raw = text

    def parse(self):
        results = []
        text = re.sub(r'[┌┐└┘├┤┬┴┼─│①②③④⑤⑥⑦⑧⑨⑩✅❌✔✖★☆●○⚠️]', '', self.raw)
        text = text.replace("，", ",").replace("：", ":").replace("＋", "+")
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            current_lot = None
            for l, p in {"双色球": "双色球|UNION LOTTO", "大乐透": "大乐透", "福彩3D": "福彩3D|3D|3d", "排列三": "排列三", "七星彩": "七星彩", "快乐8": "快乐8|kl8", "七乐彩": "七乐彩"}.items():
                if re.search(p, line, re.I):
                    current_lot = l
                    break
            if not current_lot:
                continue
            rule = LOTTERY_RULES[current_lot]
            red_rule = rule["red"]
            if isinstance(red_rule, tuple) and len(red_rule) == 2 and isinstance(red_rule[0], tuple):
                rmin, rmax = 0, 9
            else:
                rmin, rmax = red_rule[0], red_rule[1]
            nums = [int(n) for n in re.findall(r'\d{1,2}', line) if rmin <= int(n) <= rmax]
            if len(nums) >= 3:
                results.append((current_lot, self._get_next_period(current_lot), ",".join(map(str, nums)), "预测号码"))
        return results

    def _get_next_period(self, lot):
        from models.lottery_data import Data
        latest = Data.latest(lot)
        return latest + 1 if latest > 0 else 0