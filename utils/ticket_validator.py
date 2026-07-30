# -*- coding: utf-8 -*-
"""彩票号码验证工具

从 jinshuiyao.py App._validate_ticket 迁出的纯逻辑模块。
无GUI依赖，可被 LotteryDomain、PredictionService、测试等独立调用。
"""



def validate_ticket(lot, nums_str):
    """验证彩票号码格式

    Args:
        lot: 彩种名称
        nums_str: 号码字符串

    Returns:
        tuple: (is_valid: bool, error_msg: str)
    """
    if not nums_str:
        return False, "空号码"
    if '[' in nums_str and ']' in nums_str:
        return True, ""
    parts = nums_str.split('+') if '+' in nums_str else [nums_str]
    reds_str = parts[0]
    blues_str = parts[1] if len(parts) > 1 else ""
    reds = [int(x) for x in reds_str.split(',') if x.strip().isdigit()]
    blues = [int(x) for x in blues_str.split(',') if x.strip().isdigit()] if blues_str else []
    if lot == "双色球":
        if any(r < 1 or r > 33 for r in reds):
            return False, "红球超范围"
        if any(b < 1 or b > 16 for b in blues):
            return False, "蓝球超范围"
    elif lot == "大乐透":
        if any(r < 1 or r > 35 for r in reds):
            return False, "前区超范围"
        if any(b < 1 or b > 12 for b in blues):
            return False, "后区超范围"
    elif lot in ["福彩3D", "排列三"]:
        if any(d < 0 or d > 9 for d in reds):
            return False, "数字超范围"
    elif lot == "快乐8":
        if any(n < 1 or n > 80 for n in reds):
            return False, "号码超范围"
    elif lot == "七星彩":
        if len(reds) != 6:
            return False, f"前区号码{len(reds)}个，应为6个"
        if not blues or len(blues) != 1:
            return False, "特别号应为1个"
        for i, n in enumerate(reds):
            if n < 0 or n > 9:
                return False, f"第{i+1}位超范围(0-9)"
        if blues[0] < 0 or blues[0] > 14:
            return False, "特别号超范围(0-14)"
    return True, ""


def is_valid_period(lot, period, latest=None):
    """验证期号有效性

    Args:
        lot: 彩种名称
        period: 期号
        latest: 最新期号（可选，不传则从Data加载）

    Returns:
        bool: 期号是否有效
    """
    if period <= 0:
        return False
    if latest is None:
        from models.lottery_data import Data
        latest = Data.latest(lot)
    if latest > 0 and period > latest + 5:
        return False
    return True
