# -*- coding: utf-8 -*-
"""金水谣系统 - 号码处理工具函数"""
import re
import random
import datetime
from config import LOTTERY_RULES, EXCLUDED_LOTS


def get_red_count(rule):
    red = rule.get("red")
    if not red:
        return 0
    if isinstance(red, tuple) and len(red) == 3 and isinstance(red[0], int):
        return red[2]
    if isinstance(red, tuple) and len(red) == 2 and isinstance(red[0], tuple):
        return red[0][2]
    return 0


def get_blue_count(rule):
    blue = rule.get("blue")
    if blue and isinstance(blue, tuple) and len(blue) == 3:
        return blue[2]
    if rule.get("special") or rule.get("digit"):
        return 1
    return 0


def clean_nums(s):
    return re.sub(r'\s+', '', str(s))


def parse_reds(s):
    s = clean_nums(s)
    if ',' in s:
        return [int(x) for x in s.split(",") if x.strip().isdigit()]
    nums = []
    i = 0
    while i < len(s):
        if s[i].isdigit():
            if i + 1 < len(s) and s[i + 1].isdigit():
                nums.append(int(s[i:i + 2]))
                i += 2
            else:
                nums.append(int(s[i]))
                i += 1
        else:
            i += 1
    return nums


def fmt_period(lot, period):
    try:
        p = int(period)
    except (ValueError, TypeError):
        return str(period)
    return str(p).zfill(LOTTERY_RULES.get(lot, {}).get("period_len", 7))


def fix_period_5to7(period_int):
    """5位期号转7位：YY>=50补19(19XX)，YY<50补20(20XX)"""
    ps = str(period_int)
    if len(ps) == 5:
        yy = int(ps[:2])
        prefix = "19" if yy >= 50 else "20"
        return int(prefix + ps)
    return period_int


def fix_period_short_to7(period_int):
    """3-4位短期号补全为7位"""
    ps = str(period_int)
    cur_year = datetime.datetime.now().strftime("%Y")
    if len(ps) == 3:
        return int(cur_year + ps)
    elif len(ps) == 4:
        yy = int(ps[:2])
        prefix = "19" if yy >= 50 else "20"
        return int(prefix + ps)
    return period_int


def is_valid_period(lot, period):
    """验证期号是否在合理范围内"""
    try:
        p = int(period)
    except (ValueError, TypeError):
        return False
    ps = str(p)
    if len(ps) != 7:
        return False
    year = int(ps[:4])
    seq = int(ps[4:])
    cur_year = datetime.datetime.now().year
    if year < 2015 or year > cur_year:
        return False
    if lot in ["福彩3D", "排列三"]:
        max_seq = 400
    elif lot == "快乐8":
        max_seq = 400
    elif lot in ["双色球", "大乐透", "七乐彩", "七星彩"]:
        max_seq = 200
    else:
        max_seq = 400
    if seq < 1 or seq > max_seq:
        return False
    return True


def rpick(arr, n, p=None):
    if not arr:
        return []
    if n > len(arr):
        n = len(arr)
    if p:
        p = [max(0, x) for x in p]
        if sum(p) == 0:
            p = None
    return random.sample(list(arr), n) if not p else random.choices(list(arr), weights=p, k=n)


def calc_ac(nums):
    n = len(nums)
    if n < 2:
        return 0
    diffs = set()
    for i in range(n):
        for j in range(i + 1, n):
            diffs.add(abs(nums[i] - nums[j]))
    return len(diffs) - (n - 1)


def get_today_lots():
    wd = datetime.datetime.today().weekday()
    today = []
    for lot, rule in LOTTERY_RULES.items():
        if lot in EXCLUDED_LOTS:
            continue
        draw = rule.get("draw_days")
        if draw == "daily" or (isinstance(draw, list) and wd in draw):
            today.append(lot)
    return today


def format_display(lot, nums_str):
    if not nums_str:
        return ""
    # 拒绝 None 值（CWL API 返回 null 时 Python 会变成 None 或 "None" 字符串）
    sn = str(nums_str).strip().lower()
    if not sn or sn == "+":
        return ""
    if "none" in sn or "null" in sn:
        return ""
    parts = re.findall(r'\d+', str(nums_str))
    if not parts:
        return ""
    if lot == "双色球":
        reds = [f"{int(x):02d}" for x in parts[:6]]
        blues = [f"{int(x):02d}" for x in parts[6:7]]
        return ",".join(reds) + ("+" + ",".join(blues) if blues else "")
    elif lot == "大乐透":
        reds = [f"{int(x):02d}" for x in parts[:5]]
        blues = [f"{int(x):02d}" for x in parts[5:7]]
        return ",".join(reds) + ("+" + ",".join(blues) if blues else "")
    elif lot in ["福彩3D", "排列三"]:
        return ",".join(f"{int(x):02d}" for x in parts[:3])
    elif lot == "七乐彩":
        return ",".join(f"{int(x):02d}" for x in parts[:7])
    elif lot == "七星彩":
        return ",".join(f"{int(x):02d}" for x in parts[:7])
    elif lot == "快乐8":
        return ",".join(f"{int(x):02d}" for x in parts[:20])  # 【修复】快乐8开奖20个号码
    return nums_str


def normalize_ticket(lot, nums_str, keep_structure=False):
    if not nums_str or str(nums_str).strip() in ("00,00,00", "", "0", "00"):
        return None
    if '[' in nums_str and ']' in nums_str:
        return nums_str
    raw = str(nums_str)
    if '+' in raw:
        parts = raw.split('+', 1)
        red_str = parts[0]
        blue_str = parts[1] if len(parts) > 1 else ""
        red_numbers = [int(x) for x in re.findall(r'\d+', red_str)]
        blue_numbers = [int(x) for x in re.findall(r'\d+', blue_str)] if blue_str else []
    else:
        all_numbers = [int(x) for x in re.findall(r'\d+', raw)]
        if lot == "双色球":
            blue_numbers = [x for x in all_numbers if 1 <= x <= 16]
            red_numbers = [x for x in all_numbers if 1 <= x <= 33]
        elif lot == "大乐透":
            blue_numbers = [x for x in all_numbers if 1 <= x <= 12]
            red_numbers = [x for x in all_numbers if 1 <= x <= 35]
        else:
            red_numbers = all_numbers
            blue_numbers = []

    if lot == "双色球":
        if not keep_structure:
            reds = list(dict.fromkeys([x for x in red_numbers if 1 <= x <= 33]))[:6]
            while len(reds) < 6:
                reds.append(random.randint(1, 33))
            blues = list(dict.fromkeys([x for x in blue_numbers if 1 <= x <= 16]))[:1]
            if not blues:
                blues = [random.randint(1, 16)]
        else:
            reds = list(dict.fromkeys([x for x in red_numbers if 1 <= x <= 33]))[:20]
            blues = list(dict.fromkeys([x for x in blue_numbers if 1 <= x <= 16]))[:2]
        return ",".join(f"{x:02d}" for x in sorted(reds)) + (
            "+" + ",".join(f"{x:02d}" for x in sorted(blues)) if blues else "")
    elif lot == "大乐透":
        if not keep_structure:
            reds = list(dict.fromkeys([x for x in red_numbers if 1 <= x <= 35]))[:5]
            while len(reds) < 5:
                reds.append(random.randint(1, 35))
            blues = list(dict.fromkeys([x for x in blue_numbers if 1 <= x <= 12]))[:2]
            while len(blues) < 2:
                blues.append(random.randint(1, 12))
        else:
            reds = list(dict.fromkeys([x for x in red_numbers if 1 <= x <= 35]))[:20]
            blues = list(dict.fromkeys([x for x in blue_numbers if 1 <= x <= 12]))[:3]
        return ",".join(f"{x:02d}" for x in sorted(reds)) + (
            "+" + ",".join(f"{x:02d}" for x in sorted(blues)) if blues else "")
    elif lot in ["福彩3D", "排列三"]:
        digits = [int(x) for x in red_numbers if 0 <= x <= 9]
        if not keep_structure:
            # 3D/排列三允许组三，不能去重；同时避免退化成000/111等全同号。
            digits = digits[:3]
            while len(digits) < 3:
                digits.append(random.randint(0, 9))
            if len(set(digits)) == 1:
                digits[-1] = random.choice([x for x in range(10) if x != digits[0]])
        else:
            digits = digits[:6]
        return ",".join(f"{x:02d}" for x in digits)
    elif lot == "七乐彩":
        nums = [int(x) for x in red_numbers if 1 <= x <= 30]
        if not keep_structure:
            nums = list(dict.fromkeys(nums))[:7]
            while len(nums) < 7:
                nums.append(random.randint(1, 30))
        else:
            nums = list(dict.fromkeys(nums))
        return ",".join(f"{x:02d}" for x in sorted(nums))
    elif lot == "七星彩":
        front = [int(x) for x in red_numbers if 0 <= x <= 9][:6]
        back = [int(x) for x in blue_numbers if 0 <= x <= 14][:1] if blue_numbers else []
        while len(front) < 6:
            front.append(random.randint(0, 9))
        if not back:
            back = [random.randint(0, 14)]
        return ",".join(f"{x:02d}" for x in front) + "+" + f"{back[0]:02d}"
    elif lot == "快乐8":
        nums = [int(x) for x in red_numbers if 1 <= x <= 80]
        if not keep_structure:
            nums = list(dict.fromkeys(nums))
            if len(nums) < 10:
                while len(nums) < 10:
                    nums.append(random.randint(1, 80))
            elif len(nums) > 20:
                nums = nums[:20]
        else:
            nums = list(dict.fromkeys(nums))[:20]
        return ",".join(f"{x:02d}" for x in sorted(nums))
    return None


def validate_prediction(lot, nums_str):
    """输出前最后一道校验。不合格的号码返回False，不能打印/保存/复盘"""
    if not nums_str or str(nums_str).strip() in ("", "0", "00", "00,00,00"):
        return False
    raw = str(nums_str).strip()
    # 胆拖格式跳过校验
    if '[' in raw and ']' in raw:
        return _validate_dantuo(lot, raw)
    # 复式格式
    if raw.count('+') > 1:
        return False
    parts = raw.split('+') if '+' in raw else [raw]
    all_nums = [int(x) for x in re.findall(r'\d+', raw)]
    if not all_nums:
        return False
    if lot == "双色球":
        if len(parts) != 2:
            return False
        reds = [int(x) for x in re.findall(r'\d+', parts[0])]
        blues = [int(x) for x in re.findall(r'\d+', parts[1])]
        if not (1 <= len(reds) <= 20 and 1 <= len(blues) <= 2):
            return False
        if not all(1 <= n <= 33 for n in reds):
            return False
        if not all(1 <= n <= 16 for n in blues):
            return False
        if len(set(reds)) < len(reds):
            return False
    elif lot == "大乐透":
        if len(parts) != 2:
            return False
        reds = [int(x) for x in re.findall(r'\d+', parts[0])]
        blues = [int(x) for x in re.findall(r'\d+', parts[1])]
        if not (1 <= len(reds) <= 20 and 1 <= len(blues) <= 3):
            return False
        if not all(1 <= n <= 35 for n in reds):
            return False
        if not all(1 <= n <= 12 for n in blues):
            return False
        if len(set(reds)) < len(reds):
            return False
    elif lot in ["福彩3D", "排列三"]:
        if len(parts) != 1:
            return False
        nums = [int(x) for x in re.findall(r'\d+', parts[0])]
        if not (1 <= len(nums) <= 6):
            return False
        if not all(0 <= n <= 9 for n in nums):
            return False
        if len(nums) >= 3 and len(set(nums[:3])) == 1:
            return False
    elif lot == "七乐彩":
        nums = all_nums
        if len(nums) < 7:
            return False
    elif lot == "七星彩":
        if len(parts) == 2:
            front = [int(x) for x in re.findall(r'\d+', parts[0])]
            back = [int(x) for x in re.findall(r'\d+', parts[1])]
            if not (len(front) >= 6 and len(back) >= 1):
                return False
            if not all(0 <= n <= 9 for n in front):
                return False
            if not all(0 <= n <= 14 for n in back):
                return False
        else:
            if len(all_nums) < 7:
                return False
            if not all(0 <= n <= 9 for n in all_nums[:7]):
                return False
    elif lot == "快乐8":
        if len(all_nums) < 10:
            return False
        if not all(1 <= n <= 80 for n in all_nums):
            return False
        if len(set(all_nums)) < len(all_nums):
            return False
    return True


def _validate_dantuo(lot, raw):
    """校验胆拖格式"""
    try:
        if lot == "双色球":
            red_min, red_max = 1, 33
            blue_min, blue_max = 1, 16
        elif lot == "大乐透":
            red_min, red_max = 1, 35
            blue_min, blue_max = 1, 12
        elif lot in ["快乐8"]:
            # 快乐8: 1-80, 无蓝球
            red_min, red_max = 1, 80
            return _validate_dantuo_simple(lot, raw, red_min, red_max)
        elif lot in ["福彩3D", "排列三", "七乐彩"]:
            return True  # 其他彩种暂不严格校验胆拖
        else:
            return True
        # 大乐透特殊格式: [前区胆:... 拖:...] [后区胆:... 拖:...]
        if lot == "大乐透" and '前区胆' in raw:
            return _validate_dantuo_dlt(raw, red_min, red_max, blue_min, blue_max)
        # 双色球/通用格式: [胆:...]拖:...+蓝球
        return _validate_dantuo_simple(lot, raw, red_min, red_max, blue_min, blue_max)
    except (ValueError, TypeError, ZeroDivisionError):
        return False


def _validate_dantuo_simple(lot, raw, red_min, red_max, blue_min=None, blue_max=None):
    """通用胆拖校验：处理 [胆:...]拖:... 格式"""
    # 提取方括号内的胆码
    bracket_match = re.search(r'\[([^\]]+)\]', raw)
    if not bracket_match:
        return False
    bracket_content = bracket_match.group(1)
    # 提取胆码
    dan_match = re.search(r'胆:([^\]]*)', bracket_content)
    if not dan_match:
        return False
    dan_nums = [int(x) for x in re.findall(r'\d+', dan_match.group(1))]
    if not dan_nums:
        return False
    # 提取拖码（方括号外的）
    after_bracket = raw[bracket_match.end():]
    tuo_match = re.search(r'拖:([^+\]]+)', after_bracket)
    tuo_nums = []
    if tuo_match:
        tuo_nums = [int(x) for x in re.findall(r'\d+', tuo_match.group(1))]
    # 范围校验
    all_nums = dan_nums + tuo_nums
    if not all(red_min <= n <= red_max for n in all_nums):
        return False
    # 胆拖不重复
    if set(dan_nums) & set(tuo_nums):
        return False
    # 蓝球校验（如果有）
    if blue_min is not None and blue_max is not None:
        after_bracket = raw[bracket_match.end():]
        blue_match = re.search(r'\+([^+]+)$', after_bracket)
        if blue_match:
            blues = [int(x) for x in re.findall(r'\d+', blue_match.group(1))]
            if not all(blue_min <= n <= blue_max for n in blues):
                return False
    return True


def _validate_dantuo_dlt(raw, red_min, red_max, blue_min, blue_max):
    """大乐透胆拖校验：处理 [前区胆:... 拖:...] [后区胆:... 拖:...] 格式"""
    # 前区
    front_match = re.search(r'\[前区胆:([^\]]+)\]', raw)
    if not front_match:
        return False
    front_content = front_match.group(1)  # '20,22 拖:01,04,14,15'
    # 前区胆码在"拖:"之前，前区拖码在"拖:"之后
    if '拖:' in front_content:
        dan_part, tuo_part = front_content.split('拖:', 1)
        front_dan = [int(x) for x in re.findall(r'\d+', dan_part)]
        front_tuo = [int(x) for x in re.findall(r'\d+', tuo_part)]
    else:
        front_dan = [int(x) for x in re.findall(r'\d+', front_content)]
        front_tuo = []
    if not front_dan:
        return False
    if not all(red_min <= n <= red_max for n in front_dan + front_tuo):
        return False
    if set(front_dan) & set(front_tuo):
        return False
    # 后区
    back_match = re.search(r'\[后区胆:([^\]]+)\]', raw)
    if not back_match:
        return False
    back_content = back_match.group(1)  # '06 拖:04,08'
    if '拖:' in back_content:
        dan_part, tuo_part = back_content.split('拖:', 1)
        back_dan = [int(x) for x in re.findall(r'\d+', dan_part)]
        back_tuo = [int(x) for x in re.findall(r'\d+', tuo_part)]
    else:
        back_dan = [int(x) for x in re.findall(r'\d+', back_content)]
        back_tuo = []
    if not back_dan:
        return False
    if not all(blue_min <= n <= blue_max for n in back_dan + back_tuo):
        return False
    if set(back_dan) & set(back_tuo):
        return False
    return True


def prize_level(lot, hit_detail):
    """奖级复盘：根据命中详情返回奖级名称"""
    if lot == "双色球":
        red_hit = hit_detail.get("red_hit", 0)
        blue_hit = hit_detail.get("blue_hit", 0)
        if red_hit == 6 and blue_hit:
            return "一等奖"
        if red_hit == 6:
            return "二等奖"
        if red_hit == 5 and blue_hit:
            return "三等奖"
        if red_hit == 5 or (red_hit == 4 and blue_hit):
            return "四等奖"
        if red_hit == 4 or (red_hit == 3 and blue_hit):
            return "五等奖"
        if blue_hit:
            return "六等奖"
        return "未中奖"
    elif lot == "大乐透":
        red_hit = hit_detail.get("red_hit", 0)
        blue_hit = hit_detail.get("blue_hit", 0)
        if red_hit == 5 and blue_hit == 2:
            return "一等奖"
        if red_hit == 5 and blue_hit == 1:
            return "二等奖"
        if red_hit == 5:
            return "三等奖"
        if red_hit == 4 and blue_hit == 2:
            return "四等奖"
        if red_hit == 4 and blue_hit == 1:
            return "五等奖"
        if red_hit == 3 and blue_hit == 2:
            return "六等奖"
        if red_hit == 4 or (red_hit == 3 and blue_hit == 1) or (red_hit == 2 and blue_hit == 2):
            return "七等奖"
        if red_hit == 3 or (red_hit == 1 and blue_hit == 2) or (red_hit == 2 and blue_hit == 1) or blue_hit == 2:
            return "八等奖"
        if blue_hit == 1:
            return "九等奖"
        return "未中奖"
    elif lot in ["福彩3D", "排列三"]:
        hit_type = hit_detail.get("type", "none")
        if hit_type == "直选":
            return "直选奖"
        if hit_type == "组六" or hit_type == "组三":
            return "组选奖"
        return "未中奖"
    elif lot == "七星彩":
        seq = hit_detail.get("seq_hit", 0)
        if seq >= 6:
            return f"{'一二三四五六七八九'[min(seq-1,8)]}等奖"
        return "未中奖"
    elif lot == "快乐8":
        hit = hit_detail.get("hit", 0)
        mapping = {10: "一等奖", 9: "二等奖", 8: "三等奖", 7: "四等奖", 6: "五等奖", 5: "六等奖", 4: "七等奖", 0: "无"}
        return mapping.get(hit, f"选十中{hit}")
    return "未知"


def count_hits(lot, predict_nums, actual_nums):
    """计算预测号码与开奖号码的命中详情"""
    p_parts = str(predict_nums).split('+') if '+' in str(predict_nums) else [str(predict_nums)]
    a_parts = str(actual_nums).split('+') if '+' in str(actual_nums) else [str(actual_nums)]
    p_reds = set(int(x) for x in re.findall(r'\d+', p_parts[0]))
    a_reds = set(int(x) for x in re.findall(r'\d+', a_parts[0]))
    red_hit = len(p_reds & a_reds)
    result = {"red_hit": red_hit, "blue_hit": 0}
    if len(p_parts) > 1 and len(a_parts) > 1:
        p_blues = set(int(x) for x in re.findall(r'\d+', p_parts[1]))
        a_blues = set(int(x) for x in re.findall(r'\d+', a_parts[1]))
        result["blue_hit"] = len(p_blues & a_blues)
    return result


def sanitize_prediction(lot, nums_str, pred_type="单注"):
    """保存预测前统一清洗，拦截000/全同号等无效方案。

    原定义位于已废弃的 jinshuiyao.py，已迁移至此处供所有模块复用。
    """
    if not nums_str:
        return None
    raw = str(nums_str).strip()
    if '[' in raw and ']' in raw:
        return raw
    keep_structure = pred_type == "复式"
    cleaned = normalize_ticket(lot, raw, keep_structure=keep_structure)
    if not cleaned:
        return None
    if lot in ["福彩3D", "排列三"]:
        digits = [int(x) for x in re.findall(r'\d+', cleaned) if 0 <= int(x) <= 9]
        if pred_type == "单注":
            if len(digits) != 3:
                return None
            if len(set(digits)) == 1:
                return None
    if clean_nums(cleaned) in ("000", "000000", "00", "0"):
        return None
    return cleaned
