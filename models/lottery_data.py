# -*- coding: utf-8 -*-
"""金水谣系统 - 数据存储层"""
import os
import re
import json
import threading
from utils.number_utils import is_valid_period, parse_reds
from config import DATA_SAVE, LOTTERY_RULES
from utils.locks import json_lock, preds_lock
from utils.safe_json import safe_load_json


class Data:
    _cache = {}           # {name: data} — 缓存按彩种名隔离（当前subsystem的彩种不会与其他subsystem冲突）
    _cache_lock = threading.Lock()

    @staticmethod
    def load(name):
        p = os.path.join(DATA_SAVE, f"{name}.json")
        if not os.path.exists(p):
            return []
        with Data._cache_lock:
            if name in Data._cache:
                return Data._cache[name]
        with json_lock:
            data = safe_load_json(p, default=[])
        diag = {"name": name, "from_file": len(data)}
        data = [d for d in data if is_valid_period(name, d.get("period", 0))]
        diag["after_period_filter"] = len(data)
        rule = LOTTERY_RULES.get(name, {})
        red_rule = rule.get("red", (0, 99))
        if isinstance(red_rule[0], tuple):
            seg_ranges = red_rule
        else:
            seg_ranges = [red_rule]
        overall_min = min(s[0] for s in seg_ranges)
        overall_max = max(s[1] for s in seg_ranges)
        if overall_max < 99:
            clean = []
            blue_rule = rule.get("blue")
            diag["no_num"] = 0
            diag["none_null"] = 0
            diag["no_digit"] = 0
            diag["no_plus_comma"] = 0
            diag["red_range"] = 0
            diag["blue_range"] = 0
            for d in data:
                nums_str = str(d.get("nums", "")).strip()
                # 拒绝空号码（公告栏空白问题修复）
                if not nums_str or nums_str == "+":
                    diag["no_num"] += 1
                    continue
                if "none" in nums_str.lower() or "null" in nums_str.lower():
                    diag["none_null"] += 1
                    continue
                if not re.search(r'\d', nums_str):
                    diag["no_digit"] += 1
                    continue
                # 自动格式化：统一转为逗号分隔的标准格式（支持空格分隔、无分隔符拼接、各种格式）
                if name in ["双色球", "大乐透"]:
                    # 先剥离HTML标签（500/乐彩返回的数据含HTML）
                    stripped = re.sub(r'<[^>]+>', '', nums_str)
                    all_nums = re.findall(r'\d+', stripped)
                    red_rule_cfg = rule.get("red", (1, 33, 6))
                    blue_rule_cfg = rule.get("blue", (1, 16, 1))
                    red_count = red_rule_cfg[2] if len(red_rule_cfg) > 2 else 6
                    blue_count = blue_rule_cfg[2] if len(blue_rule_cfg) > 2 else 1
                    total_needed = red_count + blue_count
                    # 如果提取到的数字组不够，但原始字符串全是数字，按2位一组拆分
                    if len(all_nums) < total_needed and stripped.isdigit() and len(stripped) >= total_needed * 2:
                        all_nums = [stripped[i:i+2] for i in range(0, len(stripped), 2)]
                    if all_nums and len(all_nums) >= total_needed:
                        reds = all_nums[:red_count]
                        blues = all_nums[red_count:red_count + blue_count]
                        d["nums"] = ",".join(reds) + "+" + ",".join(blues)
                        nums_str = d["nums"]
                # 格式校验：排除HTML/乱码
                if name in ["双色球", "大乐透"]:
                    if "+" not in nums_str or "," not in nums_str:
                        diag["no_plus_comma"] += 1
                        continue
                    fmt_parts = nums_str.split("+")
                    fmt_reds = [int(x) for x in re.findall(r'\d+', fmt_parts[0])]
                    fmt_blues = [int(x) for x in re.findall(r'\d+', fmt_parts[1])] if len(fmt_parts) > 1 else []
                    red_rule = rule.get("red", (1, 33, 6))
                    blue_rule = rule.get("blue", (1, 16, 1))
                    if not (red_rule[0] <= min(fmt_reds) <= max(fmt_reds) <= red_rule[1] and len(fmt_reds) >= 3):
                        diag["red_range"] += 1
                        continue
                    if fmt_blues and not (blue_rule[0] <= min(fmt_blues) <= max(fmt_blues) <= blue_rule[1]):
                        diag["blue_range"] += 1
                        continue
                parts = nums_str.split("+") if "+" in nums_str else [nums_str]
                valid = True
                for seg_idx, seg_range in enumerate(seg_ranges):
                    smin, smax = seg_range[0], seg_range[1]
                    seg_str = parts[seg_idx] if seg_idx < len(parts) else ""
                    seg_nums = [int(x) for x in seg_str.split(",") if x.strip().isdigit()]
                    if not all(smin <= n <= smax for n in seg_nums):
                        valid = False
                        break
                if valid and blue_rule and len(parts) > len(seg_ranges):
                    bmin, bmax, _ = blue_rule
                    blue_str = parts[len(seg_ranges)]
                    blues = [int(x) for x in blue_str.split(",") if x.strip().isdigit()]
                    if not all(bmin <= n <= bmax for n in blues):
                        valid = False
                if valid:
                    clean.append(d)
            data = clean
            diag["final"] = len(data)
            # 仅在丢弃了脏数据时打印诊断（正常加载零噪音，异常时可定位）
            if diag["from_file"] > 0 and (diag["no_num"] + diag["none_null"] + diag["no_digit"]
                                          + diag["no_plus_comma"] + diag["red_range"] + diag["blue_range"]) > 0:
                print(f"[DIAG-Data.load] {name}: 文件={diag['from_file']} 期号过滤后={diag['after_period_filter']} 空号码={diag['no_num']} NoneNull={diag['none_null']} 无数字={diag['no_digit']} 缺+,={diag['no_plus_comma']} 红球异常={diag['red_range']} 蓝球异常={diag['blue_range']} 最终={diag['final']}")
        with Data._cache_lock:
            Data._cache[name] = data
        return data

    @staticmethod
    def invalidate_cache(name=None):
        with Data._cache_lock:
            if name:
                Data._cache.pop(name, None)
            else:
                Data._cache.clear()

    @staticmethod
    def latest(name):
        a = Data.load(name)
        return max((x["period"] for x in a), default=0)

    @staticmethod
    def result(name, period):
        for x in Data.load(name):
            if x["period"] == period:
                return x["nums"], x.get("time", "")
        return None, None

    @staticmethod
    def has_period(name, period):
        return any(x["period"] == period for x in Data.load(name))

    @staticmethod
    def freshness_minutes(name, now=None):
        """数据距上次更新的分钟数（用于新鲜度门禁）。

        主信号：数据文件 mtime（与 S6 /api/lottery/sources-health 一致，
        避免“最新一期 time 缺失”导致误判陈旧）。time 字段仅作兜底。
        返回 None 表示无数据/无法解析。
        """
        import time as _time
        from config import DATA_SAVE
        now = now if now is not None else _time.time()
        path = os.path.join(DATA_SAVE, f"{name}.json")
        if os.path.exists(path):
            return int((now - os.path.getmtime(path)) / 60)
        # 兜底：最新一期 time
        arr = Data.load(name)
        latest = None
        for d in arr:
            ts = _parse_time_to_ts(d.get("time"))
            if ts and (latest is None or ts > latest):
                latest = ts
        if latest is None:
            return None
        return int((now - latest) / 60)

    @staticmethod
    def is_fresh(name, threshold_min=1440, now=None):
        """数据是否够新（距上次写入 <= threshold_min 分钟）。无数据视为不新鲜。"""
        fm = Data.freshness_minutes(name, now=now)
        if fm is None:
            return False
        return fm <= threshold_min


def _parse_time_to_ts(t):
    """把 'YYYY-MM-DD HH:MM:SS' / 'YYYY-MM-DD' 等解析为时间戳；失败返回 None。"""
    import time as _time
    if not t:
        return None
    s = str(t).strip().replace("T", " ")
    # 去掉可能的时区后缀
    s = s.split("+")[0].split("Z")[0].strip()
    fmts = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")
    for f in fmts:
        try:
            return _time.mktime(_time.strptime(s, f))
        except Exception:
            continue
    return None