# -*- coding: utf-8 -*-
"""金水谣系统 - 彩票统计分析引擎（W63补71 / JS-20260812-07 新建）

为 4 个历史死链 API 提供纯计算支撑（无 HTTP 耦合，可单测）：
  - omission_table         遗漏表格（current/max/avg/frequency/lastAppear/hotLevel）
  - historical_same_period 历史同期（date|month 两种模式）
  - number_follow_up       号码跟随（前号 → 后号转移概率矩阵）
  - trend_classification   近期开奖序列（012路/质合/五行分类在前端本地做）

数据契约：与 fetchers/fetcher.py 存储格式一致
  {"period": 2026087, "lottery": "双色球", "nums": "02,04,15,23,25,27+03", "time": "2026-07-30"}
统一经 models/lottery_data.Data.load(lot) 读取。
"""
import re

from utils.number_utils import clean_nums, parse_reds

# 各彩种号码池范围（与 engines/miss_analyzer.MissAnalyzer._RANGE_MAP 对齐）
_LOT_RANGES = {
    "福彩3D": range(0, 10),
    "排列三": range(0, 10),
    "双色球": range(1, 34),
    "大乐透": range(1, 36),
    "七乐彩": range(1, 31),
    "快乐8": range(1, 81),
    "七星彩": range(1, 36),
}

_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def get_num_range(lot):
    """按彩种返回号码池 range（未知彩种按大盘兜底）。"""
    for key, rng in _LOT_RANGES.items():
        if key in lot:
            return rng
    return range(1, 36)


def split_nums(nums_str):
    """拆分 "02,04,15,23,25,27+03" → (reds=[2,4,15,23,25,27], blues=[3] or None)。"""
    if not nums_str:
        return [], None
    parts = str(nums_str).split("+", 1)
    reds = parse_reds(clean_nums(parts[0]))
    blues = parse_reds(clean_nums(parts[1])) if len(parts) > 1 else None
    return reds, blues


def omission_table(history, lot):
    """遗漏表格：每号 {number, current, max, avg, frequency, lastAppear, hotLevel}。

    - current/max/avg 复用 MissAnalyzer 口径（current=最近出现距最新一期距离）
    - frequency = 历史出现次数；lastAppear = 最近出现时间（time 字段，无则 null）
    - hotLevel = 按频次分位四档（极热/热/温/冷）
    """
    from engines.miss_analyzer import MissAnalyzer

    num_range = range(get_num_range(lot).start, get_num_range(lot).stop)
    analyzer = MissAnalyzer(lot if "七星彩" not in lot else "七星彩前区")
    miss = analyzer.analyze(history) if history else {}

    total = max(len(history), 1)
    num_occ = {n: 0 for n in num_range}
    last_times = {}
    for rec in history:
        nums_str = str(rec.get("nums", ""))
        reds, blues = split_nums(nums_str)
        nums = reds + (blues or [])
        tm = rec.get("time", "")
        for n in set(nums):
            if n in num_occ:
                num_occ[n] += 1
                if tm:
                    last_times[n] = tm

    freq_sorted = sorted(num_occ.items(), key=lambda kv: kv[1])
    n = max(len(freq_sorted), 1)
    cut_hot = max(int(n * 0.6), 1)
    cut_cold = max(int(n * 0.2), 1)
    rows = []
    for num in num_range:
        info = miss.get(num, {})
        freq = num_occ[num]
        if freq >= freq_sorted[-cut_hot][1] and freq > 0:
            hot = "极热"
        elif freq >= freq_sorted[-cut_cold][1] and freq > 0:
            hot = "热"
        elif freq > 0:
            hot = "温"
        else:
            hot = "冷"
        rows.append({
            "number": num,
            "current": info.get("current_miss", 0),
            "max": info.get("max_miss", 0),
            "avg": info.get("avg_miss", 0),
            "frequency": freq,
            "lastAppear": last_times.get(num),
            "hotLevel": hot,
        })
    return rows


def historical_same_period(history, date_str, mode="date"):
    """历史同期：按日期匹配历史开奖 ± 同年月。

    mode=date   → 返回与 date_str 同月同日（跨年份）的所有期
    mode=month  → 返回与 date_str 同月（跨年份）的所有期
    """
    if not date_str:
        return []
    m = _DATE_RE.search(str(date_str))
    if not m:
        return []
    target_month = m.group(2)
    target_day = m.group(3)
    rows = []
    for rec in history:
        tm = str(rec.get("time", ""))
        rm = _DATE_RE.search(tm)
        if not rm:
            continue
        if mode == "month":
            if rm.group(2) == target_month:
                rows.append(_fmt_record(rec))
        else:
            if rm.group(2) == target_month and rm.group(3) == target_day:
                rows.append(_fmt_record(rec))
    return rows


def _fmt_record(rec):
    reds, blues = split_nums(rec.get("nums", ""))
    return {
        "date": rec.get("time", ""),
        "drawNum": str(rec.get("period", "")),
        "reds": reds,
        "blues": blues or [],
    }


def number_follow_up(history, gap=1, lot_type=""):
    """号码跟随：{前号i: {后号j: 概率}}，i 出现后第 gap 期开出的号 j。

    概率 = count(i→j) / 行内归一化（i 后 gap 期号码总和）；i == j 恒为 0；
    未出现过的号码给全 0 行（页面矩阵完整）。
    """
    gap = max(1, int(gap or 1))
    order = list(reversed(history))
    num_range = get_num_range(lot_type)
    actual_range = range(num_range.start, num_range.stop)
    cnt = {n: 0 for n in actual_range}
    pair = {}
    if len(order) > gap:
        for k in range(len(order) - gap):
            reds, blues = split_nums(order[k].get("nums", ""))
            cur_nums = reds + (blues or [])
            reds2, blues2 = split_nums(order[k + gap].get("nums", ""))
            next_nums = reds2 + (blues2 or [])
            for i in set(cur_nums):
                if i not in cnt:
                    continue
                cnt[i] += 1
                pm = pair.setdefault(i, {j: 0 for j in actual_range})
                for j in set(next_nums):
                    if j != i and j in pm:
                        pm[j] += 1
    data = {}
    for i in actual_range:
        if cnt[i] <= 0:
            data[i] = {j: 0 for j in actual_range}
            continue
        pm = pair.get(i, {})
        total_next = sum(pm.values())
        if total_next <= 0:
            data[i] = {j: 0 for j in actual_range}
            continue
        data[i] = {j: round(pm[j] / total_next, 4) for j in actual_range}
    return data


def hot_rank(history, count=30):
    """冷热动态排行榜：最近 count 期各号码出现次数 + 与前一窗口对比趋势。

    返回: {
        "window": count,
        "rank": [{"number": 1, "count": 5, "trend": "up|down|flat|new"}, ...] 按 count 降序
    }
    trend: up=比前一窗口多, down=少, flat=持平, new=前一窗口未出现（新冒头）
    """
    def _counts(seq):
        c = {}
        for rec in seq:
            nums_str = str(rec.get("nums", ""))
            reds, blues = split_nums(nums_str)
            for n in reds + (blues or []):
                c[n] = c.get(n, 0) + 1
        return c

    count = max(1, min(int(count), 500))
    total = len(history)
    if total == 0:
        return {"window": count, "rank": []}
    win = min(count, total)
    cur_seq = history[-win:]
    prev_win = min(win, total - win)
    prev_seq = history[-win - prev_win:-win] if prev_win > 0 else []

    cur = _counts(cur_seq)
    prev = _counts(prev_seq)
    seen = set(cur) | set(prev)
    rank = []
    for n in seen:
        c = cur.get(n, 0)
        p = prev.get(n, 0)
        trend = "up" if (c > p and p > 0) else ("down" if c < p else ("new" if p == 0 and c > 0 else "flat"))
        rank.append({"number": n, "count": c, "trend": trend})
    rank.sort(key=lambda x: (-x["count"], x["number"]))
    return {"window": count, "rank": rank}


def trend_classification(history, count=30):
    """近期开奖序列：最近 count 期，每期 {drawNum, numbers}。"""
    count = max(1, min(int(count or 30), 500))
    rows = []
    for rec in history[:count]:
        reds, blues = split_nums(rec.get("nums", ""))
        rows.append({
            "drawNum": str(rec.get("period", "")),
            "numbers": reds + (blues or []),
        })
    return rows