# -*- coding: utf-8 -*-
"""金水谣系统 - 预算分配器

诚实声明（JS-20260727 十七模型元分析缺口#2 闭环）：
本模块只做「固定小注预算封顶」的纪律化分配（风控手段），
任何注型/码池配置（含组六5码池复式）均**不提升命中率**——
诚实回测+随机基准实测已证明选号无超越随机的能力，
预算分配的唯一价值是控制损失上限，不是提高收益。
"""


class BudgetControllerV2:
    def __init__(self, app):
        self.app = app

    def allocate(self, lots):
        pm = {}
        for lot in lots:
            if lot == "快乐8":
                pm[lot] = [{"type": "复式", "count": 1, "cost": 22, "config": {"code_count": 11, "play": "选10"}}]
            elif lot in ["福彩3D", "排列三"]:
                pm[lot] = [
                    # 组六5码池复式=固定小注纪律（20元封顶），非提升命中率的手段；
                    # 5码池覆盖率与随机5码池无显著差异（诚实回测定论，勿误读为"缩水优选"）。
                    # 口径统一（JS-20261020）：4码/8元 → 5码/20元，与 gui/play_plans.py
                    # 及 engines/group6_utils.DEFAULT_DIGIT_COUNT 对齐（C(5,3)=10注×2元）。
                    {"type": "复式", "count": 1, "cost": 20, "config": {"digit_count": 5, "play": "组六",
                                                                       "honest_note": "固定小注风控，非提升命中率"}},
                    {"type": "单注", "count": 1, "cost": 2, "config": {"play": "组三"}},
                    {"type": "胆拖", "count": 1, "cost": 2, "config": {}},
                ]
            elif lot == "七乐彩":
                pm[lot] = [
                    {"type": "单注", "count": 3, "cost": 6, "config": {}},
                    {"type": "复式", "count": 1, "cost": 14, "config": {}},
                    {"type": "胆拖", "count": 1, "cost": 4, "config": {}},
                ]
            else:
                pm[lot] = [
                    {"type": "单注", "count": 3, "cost": 6, "config": {}},
                    {"type": "复式", "count": 1, "cost": 12, "config": {"red_extra": 1, "blue_extra": 0}},
                    {"type": "胆拖", "count": 1, "cost": 4, "config": {}},
                ]
        total_cost = sum(sum(p['cost'] for p in plans) for plans in pm.values())
        return pm, total_cost