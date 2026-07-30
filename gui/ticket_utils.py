# -*- coding: utf-8 -*-
"""彩票号码类型检测与验证工具

从 main_window.py 拆出的纯函数，零 GUI 依赖。
"""

from utils.number_utils import is_valid_period
from utils.ticket_validator import validate_ticket


def detect_3d_type(nums, base_type):
    """检测3D/排列三号码的具体玩法类型

    Args:
        nums: 号码字符串，如 "03,05,07" 或 "01,03,05,06,07,09"
        base_type: 原始类型标签（单注/复式/胆拖/直选推荐）

    Returns:
        str: 细化后的类型（组六/组三/豹子/组六复式/直选等）
    """
    if base_type == "直选推荐":
        return "直选"
    if base_type == "胆拖":
        return "胆拖"
    # 提取数字
    try:
        digits = [int(x) for x in str(nums).replace("+", ",").split(",") if x.strip().isdigit()]
    except (ValueError, AttributeError):
        return base_type
    if base_type == "复式":
        if len(digits) >= 4:
            return f"组六复式({len(digits)}码)"
        return "复式"
    # 单注：判断组六/组三/豹子
    if len(digits) == 3:
        unique = len(set(digits))
        if unique == 3:
            return "组六"
        elif unique == 2:
            return "组三"
        else:
            return "豹子"
    return base_type


def is_valid_period(lot, period):
    """检查期号是否有效

    Args:
        lot: 彩种名称
        period: 期号

    Returns:
        bool: 期号是否有效
    """
    try:
        p = int(period)
    except (ValueError, TypeError):
        return False
    return is_valid_period(lot, p)


def validate_ticket(lot, nums_str):
    """验证号码格式

    支持: 双色球(红1-33蓝1-16), 大乐透(红1-35蓝1-12), 3D/排列3(0-9), 快乐8(1-80)

    Args:
        lot: 彩种名称
        nums_str: 号码字符串

    Returns:
        tuple: (is_valid: bool, error_msg: str)
    """
    if not nums_str:
        return False, "空号码"
    return validate_ticket(lot, nums_str)
