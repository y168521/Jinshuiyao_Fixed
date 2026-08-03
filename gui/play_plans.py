# -*- coding: utf-8 -*-
"""各彩种玩法计划与头奖概率配置

从 main_window.py 拆出的静态数据，零 GUI 依赖。
"""

# 各彩种默认玩法方案：3单注 + 1复式 + 1胆拖
PLAY_PLANS = {
    "双色球": [
        {"type": "单注", "count": 3, "cost": 6, "config": {}},
        {"type": "复式", "count": 1, "cost": 14, "config": {"red_extra": 1, "blue_extra": 0}},
        {"type": "胆拖", "count": 1, "cost": 4, "config": {}},
    ],
    "大乐透": [
        {"type": "单注", "count": 3, "cost": 6, "config": {}},
        {"type": "复式", "count": 1, "cost": 12, "config": {"red_extra": 2, "blue_extra": 1}},
        {"type": "胆拖", "count": 1, "cost": 4, "config": {}},
    ],
    "福彩3D": [
        {"type": "单注", "count": 3, "cost": 6, "config": {"zu3_min": 1}},
        {"type": "复式", "count": 1, "cost": 20, "config": {"digit_count": 5, "play": "组六"}},
        {"type": "胆拖", "count": 1, "cost": 2, "config": {}},
    ],
    "排列三": [
        {"type": "单注", "count": 3, "cost": 6, "config": {"zu3_min": 1}},
        {"type": "复式", "count": 1, "cost": 20, "config": {"digit_count": 5, "play": "组六"}},
        {"type": "胆拖", "count": 1, "cost": 2, "config": {}},
    ],
    "七乐彩": [
        {"type": "单注", "count": 3, "cost": 6, "config": {}},
        {"type": "复式", "count": 1, "cost": 8, "config": {}},
        {"type": "胆拖", "count": 1, "cost": 4, "config": {}},
    ],
    "七星彩": [
        {"type": "单注", "count": 3, "cost": 6, "config": {}},
        {"type": "复式", "count": 1, "cost": 14, "config": {"digit_count": 8}},
        {"type": "胆拖", "count": 1, "cost": 4, "config": {}},
    ],
    "快乐8": [
        {"type": "单注", "count": 3, "cost": 6, "config": {}},
        {"type": "复式", "count": 1, "cost": 22, "config": {"code_count": 11, "play": "选10"}},
        {"type": "胆拖", "count": 1, "cost": 4, "config": {}},
    ],
}

# 默认玩法方案（未在 PLAY_PLANS 中的彩种使用）
DEFAULT_PLAY_PLAN = [
    {"type": "单注", "count": 3, "cost": 6, "config": {}},
    {"type": "复式", "count": 1, "cost": 8, "config": {}},
    {"type": "胆拖", "count": 1, "cost": 4, "config": {}},
]

# 生成基础玩法计划（3单+1复+1胆拖）
def make_play_plan(lot=None):
    """生成玩法计划（3单+1复+1胆拖）

    Args:
        lot: 彩种名称（可选，不同彩种可配置不同参数）

    Returns:
        list: 玩法计划列表
    """
    return [
        {"type": "单注", "count": 3, "config": {}},
        {"type": "复式", "count": 1, "config": {}},
        {"type": "胆拖", "count": 1, "config": {}},
    ]

# 各彩种头奖概率
LOTTERY_PROBS = {
    "双色球": "1/17,721,088",
    "大乐透": "1/21,425,712",
    "福彩3D": "1/1,000",
    "排列三": "1/20,358,520",
    "七乐彩": "1/10,000,000",
    "快乐8": "选10中10: 1/8,911,711",
}
