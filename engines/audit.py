# -*- coding: utf-8 -*-
"""彩票号码合规校验模块

注意：本模块名称虽为"audit"，但实际功能是「彩票投注号码的格式与范围校验」，
并非审计日志。名称保留为历史原因，避免破坏现有接口。

与其他"audit"模块的关系（非重复，职责不同）：
  - core/audit_log.py  — 全局操作审计日志（记录系统事件到文件）
  - jinshuiyao/audit.py   — 足彩崩溃捕获与自愈系统（运行时异常监控）
"""
from utils.number_utils import parse_reds, clean_nums
from config import LOTTERY_RULES


class Audit:
    def __init__(self, lot, tks):
        self.lot = lot
        self.tks = tks
        self.rule = LOTTERY_RULES[lot]

    def ok(self):
        try:
            return self._l1()
        except Exception:
            return False

    def _l1(self):
        for t in self.tks.get("单注", []):
            if not self._chk_range(t):
                return False
        if self.tks.get("复式", "") and not self._chk_range(self.tks["复式"], True):
            return False
        if self.tks.get("胆拖", "") and not self._chk_range(self.tks["胆拖"], False, True):
            return False
        return True

    def _chk_range(self, t, fushi=False, dantuo=False):
        if dantuo and '[' in t:
            try:
                dan_part = t[t.index('[') + 1:t.index(']')].replace('胆:', '').replace('拖:', '')
            except Exception:
                return False
        ct = t.split(" (组")[0].split("[胆:")[0].split("特别号:")[0].strip()
        ct = clean_nums(ct)
        parts = ct.split("+")
        reds = parse_reds(parts[0])
        if not reds:
            return False
        if self.lot == "快乐8":
            if len(reds) < 10 or len(reds) > 12:
                return False
            if any(n < 1 or n > 80 for n in reds):
                return False
            if len(set(reds)) != len(reds):
                return False
            return True
        if self.lot == "七星彩":
            if len(reds) != 7:
                return False
            for i, n in enumerate(reds):
                if i < 6 and (n < 0 or n > 9):
                    return False
                if i == 6 and (n < 0 or n > 14):
                    return False
            return True
        rmin, rmax, rcnt = self.rule["red"]
        if self.lot in ["福彩3D", "排列三"]:
            if fushi and len(reds) < 4:
                return False
            if dantuo and len(reds) < 3:
                return False
            if not fushi and not dantuo and len(reds) != 3:
                return False
        if any(n < rmin or n > rmax for n in reds):
            return False
        if len(set(reds)) != len(reds):
            return False
        if len(parts) > 1 and self.rule.get("blue"):
            blues = parse_reds(parts[1])
        return True