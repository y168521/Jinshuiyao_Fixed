"""多维参考特征引擎（福彩3D / 排列三）。

诚实声明：以下均为历史开奖的「描述性统计」（遗漏 / 冷热 / 振幅 / 奇偶 / 大小 /
区间 / 和值 / 跨度），用于辅助理解号码分布，绝不构成预测信号或中奖概率。
彩票本质近随机，任何维度都不改变随机性。

输出结构（dict）：
{
  "lot": str, "supported": bool,
  "positions": { 百位/十位/个位: {最近遗漏Top冷, 近期热号Top, 振幅均值, 奇偶比, 大小比, 三区比} },
  "summary": { 和值均值, 和值近期, 跨度均值 },
  "feature_coverage": int(0-100),   # 已计算维度覆盖度，供 SQI 使用
  "note": str
}
"""
from collections import Counter

DIGITS = list(range(10))


def _parse_3d_nums(d):
    """从开奖记录 d 提取三位数字列表，失败返回 None。"""
    try:
        s = str(d.get("nums", "")).split("+")[0]
        parts = [int(x) for x in s.split(",") if x.strip().isdigit()]
        if len(parts) >= 3:
            return parts[:3]
        return None
    except Exception:
        return None


def _miss_counts(seq):
    """每位数字(0-9)距最新一期的遗漏期数（最新一期视为已出现，遗漏0）。"""
    last_idx = {d: -1 for d in DIGITS}
    for i, v in enumerate(seq):
        last_idx[v] = i
    n = len(seq)
    return {d: (n - 1 - last_idx[d]) if last_idx[d] >= 0 else n for d in DIGITS}


def _freq(seq, window=30):
    recent = seq[-window:]
    c = Counter(recent)
    total = len(recent) or 1
    return {d: c.get(d, 0) for d in DIGITS}, total


def _amplitude(seq):
    if len(seq) < 2:
        return 0.0
    diffs = [abs(seq[i] - seq[i - 1]) for i in range(1, len(seq))]
    return sum(diffs) / len(diffs)


def analyze(lot, arr, window=30):
    """返回多维参考特征字典。仅福彩3D/排列三有效，其他返回 supported=False。"""
    if lot not in ("福彩3D", "排列三") or not arr:
        return {"lot": lot, "supported": False, "positions": {},
                "note": "暂仅支持福彩3D/排列三"}
    pos_seqs = [[], [], []]
    sums, spans = [], []
    for d in arr:
        nums = _parse_3d_nums(d)
        if not nums:
            continue
        for i in range(3):
            pos_seqs[i].append(nums[i])
        sums.append(sum(nums))
        spans.append(max(nums) - min(nums))
    if not pos_seqs[0]:
        return {"lot": lot, "supported": False, "positions": {},
                "note": "无有效开奖数据"}

    positions = {}
    pos_names = ["百位", "十位", "个位"]
    dims_computed = 0
    for idx, pname in enumerate(pos_names):
        seq = pos_seqs[idx]
        miss = _miss_counts(seq)
        freq, total = _freq(seq, window)
        cold = sorted(miss.items(), key=lambda kv: kv[1], reverse=True)[:3]
        hot = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:3]
        odd = sum(1 for v in seq[-window:] if v % 2 == 1)
        even = total - odd
        small = sum(1 for v in seq[-window:] if v <= 4)
        big = total - small
        z1 = sum(1 for v in seq[-window:] if 0 <= v <= 3)
        z2 = sum(1 for v in seq[-window:] if 4 <= v <= 6)
        z3 = sum(1 for v in seq[-window:] if 7 <= v <= 9)
        amp = round(_amplitude(seq), 2)
        positions[pname] = {
            "最近遗漏Top冷": [f"{d:02d}({m}期)" for d, m in cold],
            "近期热号Top": [f"{d:02d}({c}次)" for d, c in hot],
            "振幅均值": amp,
            "奇偶比": [odd, even],
            "大小比": [small, big],
            "三区比": [z1, z2, z3],
        }
        dims_computed += 7

    sum_recent = sums[-window:]
    span_recent = spans[-window:]
    summary = {
        "和值均值": round(sum(sum_recent) / len(sum_recent), 1) if sum_recent else 0,
        "和值近期": sums[-10:],
        "跨度均值": round(sum(span_recent) / len(span_recent), 2) if span_recent else 0,
    }
    dims_computed += 2
    coverage = min(100, int(dims_computed / 23 * 100))  # 23 = 3位*7 + 2汇总
    return {
        "lot": lot,
        "supported": True,
        "positions": positions,
        "summary": summary,
        "feature_coverage": coverage,
        "note": "描述性统计（遗漏/冷热/振幅/奇偶/大小/区间/和值/跨度），辅助理解分布，非预测信号。彩票本质近随机。",
    }
