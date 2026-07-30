# -*- coding: utf-8 -*-
"""彩票专用 — 策略修正模块（穹武精华集成）

适用范围：彩票子系统（福彩3D、排列三等数字彩）

核心理念：不暂停预测，而是根据近期表现动态调整选号策略，让偏差自动拉回。

与 jinshuiyao/risk_controller.py 的关系（非重复，职责不同）：
  - engines/risk_controller.py      — 彩票策略修正（号码池换血/组三组六对冲/冷热自适应）
  - jinshuiyao/risk_controller.py      — 足彩资金风控（止损/连错暂停/相关性检查/凯利仓位）

三大修正机制：
1. 号码池换血：5码池连续2期中0码 → 全部替换为遗漏最大的5个号码（均值回归）
2. 组六对冲：连续2期开出组三 → 下期组三防守权重降低80%，组六权重上调
3. 热号/冷号自适应：连续命中时追热，连续未中时追冷

数据持久化到 risk_state.json，跨会话保持。
"""
import os
import json
import random
from collections import Counter
from utils.number_utils import parse_reds, clean_nums
from utils.safe_json import safe_load_json, safe_write_json


RISK_STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 "金水谣数据", "risk_state.json")

CONFIG = {
    "blood_change_zeros": 2,           # 连续N期码池中0码触发换血
    "group6_hedge_consecutive_g3": 2, # 连续N期组三触发组六对冲
    "group3_weight_on_hedge": 0.2,    # 对冲时组三权重（20%），即大幅减少组三防守注
}


class StrategyCorrector:
    """策略修正器：根据复盘结果动态修正选号策略"""

    def __init__(self, config=None):
        self.config = config or CONFIG
        self.state = self._load_state()

    def _load_state(self):
        if os.path.exists(RISK_STATE_FILE):
            try:
                return safe_load_json(RISK_STATE_FILE, default=None)
            except Exception:
                pass
        return self._empty_state()

    def _empty_state(self):
        return {
            "per_lot": {},
        }

    def _default_lot_state(self):
        return {
            "consecutive_zeros": 0,
            "pool_zeros": 0,
            "last_pool": [],
            "recent_forms": [],
        }

    def _get_lot(self, lot):
        if lot not in self.state["per_lot"]:
            self.state["per_lot"][lot] = self._default_lot_state()
        return self.state["per_lot"][lot]

    def save(self):
        os.makedirs(os.path.dirname(RISK_STATE_FILE), exist_ok=True)
        try:
            safe_write_json(RISK_STATE_FILE, self.state)
        except Exception:
            pass

    # ═══════════════════════════════════════════
    # 1. 号码池换血
    # ═══════════════════════════════════════════

    def need_blood_change(self, lot):
        """5码池连续N期中0码 → 需要换血"""
        ls = self._get_lot(lot)
        return ls["pool_zeros"] >= self.config["blood_change_zeros"]

    def execute_blood_change(self, current_pool, history):
        """换血：用遗漏最大的5个号码替换码池（均值回归）

        不暂停预测，而是替换号码池让策略自动修正。
        """
        if not history or len(history) < 5:
            return current_pool

        def get_missing(num):
            for d in reversed(history):
                if num in [x for x in parse_reds(clean_nums(d["nums"])) if 0 <= x <= 9]:
                    return history[-1]["period"] - d["period"]
            return 999

        # 选遗漏最大的5个号码
        candidates = sorted(range(10), key=lambda x: -get_missing(x))
        return sorted(candidates[:5])

    # ═══════════════════════════════════════════
    # 2. 组三/组六对冲
    # ═══════════════════════════════════════════

    def get_group3_weight_multiplier(self, lot):
        """获取组三防守注数乘数

        连续2期组三 → 返回0.2（大幅减少组三防守，增加组六）
        正常情况 → 返回1.0
        """
        ls = self._get_lot(lot)
        recent = ls.get("recent_forms", [])
        if len(recent) >= 2 and recent[-1] == "组三" and recent[-2] == "组三":
            return self.config["group3_weight_on_hedge"]
        return 1.0

    def should_force_group6(self, lot):
        """是否强制增加组六注（连续2期组三 → 强制加组六）"""
        ls = self._get_lot(lot)
        recent = ls.get("recent_forms", [])
        return len(recent) >= 2 and recent[-1] == "组三" and recent[-2] == "组三"

    # ═══════════════════════════════════════════
    # 3. 复盘后状态更新（核心入口）
    # ═══════════════════════════════════════════

    def update_after_review(self, lot, pool_nums, actual_nums, hits):
        """复盘后更新修正状态

        Args:
            lot: 彩种名
            pool_nums: 上期码池（如 [0,3,5,6,8]）
            actual_nums: 实际开奖号码（如 [6,7,7]）
            hits: 命中数
        """
        # 所有彩种都记录连续0命中
        ls = self._get_lot(lot)
        if hits == 0:
            ls["consecutive_zeros"] = ls.get("consecutive_zeros", 0) + 1
        else:
            ls["consecutive_zeros"] = 0

        # 记录开奖形态（仅3D/排列三有3位号码可判断组三组六）
        if actual_nums and len(actual_nums) == 3:
            form = "组三" if len(set(actual_nums)) == 2 else "组六"
            ls["recent_forms"].append(form)
            if len(ls["recent_forms"]) > 10:
                ls["recent_forms"] = ls["recent_forms"][-10:]

        # 记录上期码池
        if pool_nums:
            ls["last_pool"] = pool_nums

        # 更新码池命中计数（换血判定，仅3D/排列三）
        if pool_nums and actual_nums and len(actual_nums) == 3:
            pool_set = set(pool_nums)
            act_set = set(actual_nums)
            in_pool = len(pool_set & act_set)
            if in_pool == 0:
                ls["pool_zeros"] += 1
            else:
                ls["pool_zeros"] = 0

        self.save()

    # ═══════════════════════════════════════════
    # 状态查询
    # ═══════════════════════════════════════════

    def get_status(self, lot):
        ls = self._get_lot(lot)
        return {
            "consecutive_zeros": ls.get("consecutive_zeros", 0),
            "pool_zeros": ls.get("pool_zeros", 0),
            "need_blood_change": self.need_blood_change(lot),
            "group3_weight": self.get_group3_weight_multiplier(lot),
            "force_group6": self.should_force_group6(lot),
            "recent_forms": ls.get("recent_forms", [])[-5:],
            "last_pool": ls.get("last_pool", []),
        }


# 全局单例
_corrector = None

def get_corrector():
    """获取全局策略修正器单例"""
    global _corrector
    if _corrector is None:
        _corrector = StrategyCorrector()
    return _corrector
