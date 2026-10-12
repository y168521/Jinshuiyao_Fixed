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

# ── JS-20261012-20：新鲜度阈值按彩种开奖节奏动态计算 ──
# 背景（真实缺陷）：原全仓固定 1440 分钟（24h）。而大乐透 draw_days=[0,2,5]
# 相邻开奖最长间隔 3 天（4320 分钟）⇒ **数据是新的也被判陈旧** ⇒
# domains/lottery/domain.py 的 generate() 整批返回 stale_data 拒绝出号。
# 实测取证（2026-10-12 21:05，周一，各彩种今晚均未到开奖时刻）：
# 7 个彩种 is_fresh(1440) **全部 False**，而数据其实都是最新的 ⇒ 纯属误杀。
# 正确语义：阈值应 ≥ 该彩种「相邻开奖日的最大间隔」，再加一段延迟缓冲。
# 取向说明：**宁可晚发现陈旧（保守放行），不可天天误杀新鲜数据**——
# 误杀会让「该开奖日整批没生成」这种真缺陷被伪装成「数据陈旧」而长期看不见。
FRESH_SLACK_MINUTES = 720  # 12h：容忍抓取延迟 + 纯日期解析的误差，且仍能在一个完整开奖日后发现陈旧


def suggest_fresh_threshold(name):
    """按彩种开奖节奏给出新鲜度阈值（分钟）。

    规则：阈值 = 相邻开奖日最大间隔(天) × 1440 + FRESH_SLACK_MINUTES。
    - `draw_days="daily"` / 缺失 / 非法 → 按 1 天（1440+720=2160）
    - 每周只开一天 → 间隔 7 天
    - 多天：按环形相邻差的最大值（含跨周，如 [0,2,5] 的周六→周一）

    返回纯计算结果，不读写文件，便于单测。
    """
    rule = LOTTERY_RULES.get(name) or {}
    days = rule.get("draw_days")
    gap_days = 1
    if isinstance(days, (list, tuple)) and len(days) >= 1:
        ds = sorted(int(d) for d in days if isinstance(d, int) and 0 <= d <= 6)
        if len(ds) == 1:
            gap_days = 7            # 一周只开一次
        elif len(ds) >= 2:
            gaps = [ds[i + 1] - ds[i] for i in range(len(ds) - 1)]
            gaps.append(7 - ds[-1] + ds[0])   # 跨周回环（周六→周一）
            gap_days = max(gaps)
    return gap_days * 1440 + FRESH_SLACK_MINUTES


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

        JS-20260917-04：主信号改为「最新一期开奖 time」。
        旧逻辑只看文件 mtime——抓取器若连抓失败却仍重写文件（哪怕写入相同
        内容），mtime 照样刷新，门禁会误判“新鲜”放行陈旧预测（假新鲜）。
        开奖 time 不随重写前进，故“期号停滞/日期不更新”能被正确判陈旧。
        仅当 time 全空（历史兼容）才回退到文件 mtime。
        返回 None 表示无数据/无法解析。
        """
        import time as _time
        from config import DATA_SAVE
        now = now if now is not None else _time.time()
        path = os.path.join(DATA_SAVE, f"{name}.json")
        arr = Data.load(name)
        latest = None
        for d in arr:
            # day_end=True：time 多为纯日期，按零点会虚增近 1 天 freshness（JS-20261012-20）
            ts = _parse_time_to_ts(d.get("time"), day_end=True)
            if ts and (latest is None or ts > latest):
                latest = ts
        if latest is not None:
            return int((now - latest) / 60)
        # 兜底：time 全空时退回文件 mtime
        if os.path.exists(path):
            return int((now - os.path.getmtime(path)) / 60)
        return None

    @staticmethod
    def is_fresh(name, threshold_min=None, now=None):
        """数据是否够新（距上次更新 <= threshold_min 分钟）。无数据视为不新鲜。

        threshold_min 省略时按**该彩种开奖节奏**动态取值（见 suggest_fresh_threshold）。
        JS-20261012-20：原默认固定 1440，导致非每日型彩种在开奖日恒判陈旧。
        """
        if threshold_min is None:
            threshold_min = suggest_fresh_threshold(name)
        fm = Data.freshness_minutes(name, now=now)
        if fm is None:
            return False
        return fm <= threshold_min


def _parse_time_to_ts(t, day_end=False):
    """把 'YYYY-MM-DD HH:MM:SS' / 'YYYY-MM-DD' 等解析为时间戳；失败返回 None。

    day_end=True：纯日期（无时刻）按**当日 23:59:59** 解析。
    JS-20261012-20：本仓各彩种 time 字段全是纯日期（如 '2026-10-11'）。估算
    「距今多久」时若按零点解析，会把当天已流逝的时间全部计入 freshness，
    系统性虚增近 1 天（实测 daily 彩种虚增约 21 小时）⇒ 新鲜数据被判陈旧。
    用当日结束时刻才符合「这期数据在这一天开奖后才可用」的语义。
    默认 False **保持原行为**，不影响其他调用方（新增逻辑不侵入既有代码）。
    """
    import time as _time
    if not t:
        return None
    s = str(t).strip().replace("T", " ")
    # 去掉可能的时区后缀
    s = s.split("+")[0].split("Z")[0].strip()
    fmts = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")
    for f in fmts:
        try:
            st = _time.strptime(s, f)
        except Exception:
            continue
        if day_end and f == "%Y-%m-%d":
            st = _time.struct_time((st.tm_year, st.tm_mon, st.tm_mday,
                                    23, 59, 59, st.tm_wday, st.tm_yday, -1))
        return _time.mktime(st)
    return None