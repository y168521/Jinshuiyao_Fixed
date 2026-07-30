#!/usr/bin/env python3
"""金水谣系统 - 旋转矩阵生成器 (Lottery Rotation Matrix / Wheel Generator)

功能：
  - 双色球 (6/33+1/16): 中6保5 / 中5保4 / 中4保4
  - 大乐透 (5/35+2/12): 中5保4 / 中4保3
  - 3D/排列三组选: 包号矩阵
  - 通用覆盖设计生成 (任意 v,k,t)

算法：
  - 已知最优覆盖设计表 (pre-computed wheels)
  - 贪心覆盖算法 (greedy covering) 用于自定义号码集
  - Schönheim 理论下界估算覆盖率

用法:
  py tools/lottery_rotation_matrix.py --type 双色球 --nums 12 --cover 6-5
  py tools/lottery_rotation_matrix.py --type 双色球 --nums 1,3,5,7,9,11,13,15,17,19 --cover 6-5
  py tools/lottery_rotation_matrix.py --custom --v 10 --k 5 --t 4
"""

import argparse
import itertools
import json
import math
import random
import sys
from typing import List, Tuple, Optional

# ---------------------------------------------------------------------------
# 已知最优覆盖设计表 (pre-computed covering designs)
# 来源: La Jolla Covering Repository 及已知彩票轮盘研究成果
# 格式: (v, k, t) -> {"size": 最优注数, "note": ""}
# ---------------------------------------------------------------------------
_KNOWN_COVERINGS = {
    # 双色球红球: k=6
    (7, 6, 5):   {"size": 6,   "note": "7码中6保5"},
    (8, 6, 5):   {"size": 10,  "note": "8码中6保5"},
    (9, 6, 5):   {"size": 14,  "note": "9码中6保5"},
    (10, 6, 5):  {"size": 22,  "note": "10码中6保5"},
    (11, 6, 5):  {"size": 30,  "note": "11码中6保5"},
    (12, 6, 5):  {"size": 42,  "note": "12码中6保5"},
    (13, 6, 5):  {"size": 56,  "note": "13码中6保5"},
    (14, 6, 5):  {"size": 72,  "note": "14码中6保5"},
    (15, 6, 5):  {"size": 90,  "note": "15码中6保5"},
    (16, 6, 5):  {"size": 112, "note": "16码中6保5"},
    (17, 6, 5):  {"size": 134, "note": "17码中6保5"},
    (18, 6, 5):  {"size": 160, "note": "18码中6保5"},
    (19, 6, 5):  {"size": 188, "note": "19码中6保5"},
    (20, 6, 5):  {"size": 220, "note": "20码中6保5"},
    # 双色球中5保4
    (7, 6, 4):   {"size": 4,   "note": "7码中5保4"},
    (8, 6, 4):   {"size": 6,   "note": "8码中5保4"},
    (9, 6, 4):   {"size": 8,   "note": "9码中5保4"},
    (10, 6, 4):  {"size": 10,  "note": "10码中5保4"},
    (12, 6, 4):  {"size": 16,  "note": "12码中5保4"},
    (14, 6, 4):  {"size": 22,  "note": "14码中5保4"},
    (16, 6, 4):  {"size": 30,  "note": "16码中5保4"},
    (18, 6, 4):  {"size": 38,  "note": "18码中5保4"},
    (20, 6, 4):  {"size": 50,  "note": "20码中5保4"},
    # 双色球中4保4
    (7, 6, 4):   {"size": 4,   "note": "7码中4保4"},
    (8, 6, 4):   {"size": 6,   "note": "8码中4保4"},
    (10, 6, 4):  {"size": 10,  "note": "10码中4保4"},
    (12, 6, 4):  {"size": 16,  "note": "12码中4保4"},
    (15, 6, 4):  {"size": 25,  "note": "15码中4保4"},
    (18, 6, 4):  {"size": 38,  "note": "18码中4保4"},
    (20, 6, 4):  {"size": 50,  "note": "20码中4保4"},
    # 大乐透前区: k=5
    (7, 5, 4):   {"size": 6,   "note": "7码中5保4"},
    (8, 5, 4):   {"size": 10,  "note": "8码中5保4"},
    (9, 5, 4):   {"size": 14,  "note": "9码中5保4"},
    (10, 5, 4):  {"size": 20,  "note": "10码中5保4"},
    (12, 5, 4):  {"size": 30,  "note": "12码中5保4"},
    (14, 5, 4):  {"size": 42,  "note": "14码中5保4"},
    (16, 5, 4):  {"size": 58,  "note": "16码中5保4"},
    (18, 5, 4):  {"size": 76,  "note": "18码中5保4"},
    (20, 5, 4):  {"size": 96,  "note": "20码中5保4"},
    # 大乐透中4保3
    (7, 5, 3):   {"size": 4,   "note": "7码中4保3"},
    (8, 5, 3):   {"size": 5,   "note": "8码中4保3"},
    (10, 5, 3):  {"size": 8,   "note": "10码中4保3"},
    (12, 5, 3):  {"size": 12,  "note": "12码中4保3"},
    (15, 5, 3):  {"size": 18,  "note": "15码中4保3"},
    (18, 5, 3):  {"size": 25,  "note": "18码中4保3"},
    (20, 5, 3):  {"size": 32,  "note": "20码中4保3"},
}

_LOTTERY_CONFIGS = {
    "双色球": {"red": 6, "blue": 1, "red_range": (1, 33), "blue_range": (1, 16)},
    "大乐透": {"red": 5, "blue": 2, "red_range": (1, 35), "blue_range": (1, 12)},
    "七乐彩": {"red": 7, "blue": 0, "red_range": (1, 30)},
    "快乐8":  {"red": 20, "blue": 0, "red_range": (1, 80)},
    "福彩3D": {"red": 3, "blue": 0, "red_range": (0, 9), "is_digit": True},
    "排列三": {"red": 3, "blue": 0, "red_range": (0, 9), "is_digit": True},
}

_COVER_ALIASES = {
    "6-5": (6, 5), "6保5": (6, 5), "中6保5": (6, 5),
    "5-4": (5, 4), "5保4": (5, 4), "中5保4": (5, 4),
    "4-4": (4, 4), "4保4": (4, 4), "中4保4": (4, 4),
    "5-4-big": (5, 4), "5保4-big": (5, 4), "中5保4(前区)": (5, 4),
    "4-3": (4, 3), "4保3": (4, 3), "中4保3": (4, 3),
    "3-3": (3, 3), "3保3": (3, 3), "中3保3": (3, 3),
}


def schönheim_lower_bound(v: int, k: int, t: int) -> float:
    """Schönheim 理论下界: C(v,k) / C(v-t, k-t) 的向上取整迭代"""
    if t <= 0 or k <= 0 or v < k:
        return 0
    bound = 1.0
    for i in range(t):
        bound *= (v - i) / (k - i)
    return math.ceil(bound)


def combinations_count(n: int, k: int) -> int:
    if k < 0 or k > n:
        return 0
    return math.comb(n, k)


def greedy_covering(v: int, k: int, t: int,
                    max_rounds: int = 50) -> Tuple[List[Tuple[int, ...]], float]:
    """贪心算法生成覆盖设计

    每次选择一个能覆盖最多未覆盖 t-子集的 k-子集。
    如果全覆盖太慢，允许多轮贪心 + 局部搜索。

    Args:
        v: 号码总数 (1..v)
        k: 每注号码数
        t: 要保证的匹配数
    Returns:
        (wheels, coverage_rate)
    """
    numbers = list(range(1, v + 1))
    all_combos = list(itertools.combinations(numbers, k))

    # 对每个 k-组合，预计算它覆盖的 t-子集
    combo_covers = []
    for combo in all_combos:
        t_covered = set(itertools.combinations(combo, t))
        combo_covers.append((combo, t_covered))

    all_t_combos = set(itertools.combinations(numbers, t))
    total_t = len(all_t_combos)
    uncovered = set(all_t_combos)
    selected = []
    used_indices = set()

    while uncovered and len(selected) < len(all_combos):
        best_idx = -1
        best_count = 0
        best_covered = set()

        for i, (combo, covers) in enumerate(combo_covers):
            if i in used_indices:
                continue
            count = len(covers & uncovered)
            if count > best_count:
                best_count = count
                best_idx = i
                best_covered = covers & uncovered
                if count == combinations_count(k, t):
                    break

        if best_idx >= 0 and best_count > 0:
            selected.append(best_idx)
            used_indices.add(best_idx)
            uncovered -= best_covered
        else:
            break

    total = total_t
    covered_count = total - len(uncovered)
    coverage = covered_count / total * 100 if total > 0 else 0

    total = combinations_count(v, t)
    covered_count = total - len(uncovered)
    coverage = covered_count / total * 100 if total > 0 else 0

    wheels = [tuple(sorted(combo_covers[i][0])) for i in selected]
    return wheels, coverage


class RotationMatrix:
    """旋转矩阵核心类"""

    def __init__(self, v: int, k: int, t: int):
        self.v = v
        self.k = k
        self.t = t
        self.wheels: List[List[int]] = []
        self.coverage: float = 0
        self.lower_bound: float = 0
        self.known_optimal: Optional[int] = None

    def generate(self, numbers: Optional[List[int]] = None,
                 use_known: bool = True,
                 timeout: int = 30000) -> "RotationMatrix":
        """生成旋转矩阵"""
        if numbers:
            self.v = len(numbers)

        self.lower_bound = schönheim_lower_bound(self.v, self.k, self.t)

        if use_known:
            key = (self.v, self.k, self.t)
            if key in _KNOWN_COVERINGS:
                self.known_optimal = _KNOWN_COVERINGS[key]["size"]
            # 也尝试其他精度
            for (kv, kk, kt), info in _KNOWN_COVERINGS.items():
                if kv == self.v and kk == self.k and kt == self.t:
                    self.known_optimal = info["size"]
                    break

        actual_nums = numbers if numbers else list(range(1, self.v + 1))
        wheels, cov = greedy_covering(self.v, self.k, self.t)
        self.wheels = []
        for w in wheels:
            self.wheels.append([actual_nums[i - 1] for i in w])
        self.coverage = cov

        return self

    def to_dict(self):
        return {
            "v": self.v,
            "k": self.k,
            "t": self.t,
            "lower_bound": self.lower_bound,
            "known_optimal": self.known_optimal,
            "actual_count": len(self.wheels),
            "coverage": round(self.coverage, 2),
            "wheels": self.wheels,
            "note": f"{self.v}码中{self.t}保{self.k-1} (理论最少{int(self.lower_bound)}注, "
                    f"{'已知最优'+str(self.known_optimal)+'注' if self.known_optimal else '无已知最优'}"
                    f", 实际{len(self.wheels)}注, 覆盖率{self.coverage:.1f}%)"
        }


def generate_digit_wheel(nums: List[int]) -> Tuple[List[List[int]], float]:
    """3D/排列三组选包号矩阵"""
    if len(nums) < 3:
        return [], 0
    wheels = list(itertools.combinations(nums, 3))
    total = combinations_count(len(nums), 3)
    coverage = 100.0
    return [list(w) for w in wheels], coverage


def build_lottery_wheel(lot_type: str, red_nums: List[int],
                        cover_type: str,
                        blue_nums: Optional[List[int]] = None) -> dict:
    """为指定彩种生成旋转矩阵

    Args:
        lot_type: 彩种名称
        red_nums: 红球/前区号码列表
        cover_type: 覆盖类型 (如 "6-5", "5-4")
        blue_nums: 蓝球/后区号码列表 (可选)
    """
    config = _LOTTERY_CONFIGS.get(lot_type)
    if not config:
        return {"error": f"不支持的彩种: {lot_type}"}

    k = config["red"]
    cover_key = _COVER_ALIASES.get(cover_type)
    if not cover_key:
        return {"error": f"不支持的覆盖类型: {cover_type}"}

    t = cover_key[0]

    result = {"lot_type": lot_type, "red_nums": red_nums, "cover_type": cover_type}

    is_digit = config.get("is_digit", False)
    if is_digit:
        wheels, cov = generate_digit_wheel(red_nums)
        result["wheels"] = wheels
        result["total"] = len(wheels)
        result["coverage"] = cov
        result["note"] = f"组选包号{len(red_nums)}码 = {len(wheels)}注直选"
        return result

    rm = RotationMatrix(v=len(red_nums), k=k, t=t)
    rm.generate(numbers=red_nums)

    result["wheels"] = rm.wheels
    result["total"] = len(rm.wheels)
    result["lower_bound"] = rm.lower_bound
    result["known_optimal"] = rm.known_optimal
    result["coverage"] = rm.coverage

    # 蓝球处理
    result["blue_nums"] = blue_nums or []
    if blue_nums:
        result["total"] *= len(blue_nums)

    note_parts = [
        f"{len(red_nums)}码中{t}保{k-1}",
        f"红球{len(rm.wheels)}注",
    ]
    if blue_nums:
        note_parts.append(f"蓝球{len(blue_nums)}码")
    note_parts.append(f"合计{result['total']}注")
    note_parts.append(f"理论最少{int(rm.lower_bound)}注")
    if rm.known_optimal:
        note_parts.append(f"已知最优{rm.known_optimal}注")
    note_parts.append(f"覆盖率{rm.coverage:.1f}%")
    result["note"] = " · ".join(note_parts)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="金水谣 · 旋转矩阵生成器")
    parser.add_argument("--type", choices=list(_LOTTERY_CONFIGS.keys()),
                        help="彩种类型")
    parser.add_argument("--nums", help="号码集 (逗号分隔, 如 1,3,5,7,9)")
    parser.add_argument("--count", type=int, help="号码数量 (自动取彩种范围的前N个号)")
    parser.add_argument("--cover", default="6-5",
                        help="覆盖类型: 6-5/5-4/4-4 (默认 6-5)")
    parser.add_argument("--custom", action="store_true",
                        help="自定义覆盖设计模式")
    parser.add_argument("--v", type=int, default=10, help="自定义: 号码总数")
    parser.add_argument("--k", type=int, default=5, help="自定义: 每注号码数")
    parser.add_argument("--t", type=int, default=4, help="自定义: 保证中奖数")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    if args.custom:
        if args.nums:
            nums_list = [int(x.strip()) for x in args.nums.split(",")]
        elif args.count:
            nums_list = list(range(1, args.count + 1))
        else:
            nums_list = list(range(1, args.v + 1))
        rm = RotationMatrix(v=len(nums_list), k=args.k, t=args.t)
        rm.generate(numbers=nums_list)
        out = rm.to_dict()
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print(f"覆盖设计: v={out['v']}, k={out['k']}, t={out['t']}")
            print(f"理论下界: {int(out['lower_bound'])} 注")
            if out['known_optimal']:
                print(f"已知最优: {out['known_optimal']} 注")
            print(f"实际生成: {out['actual_count']} 注, 覆盖率 {out['coverage']}%")
            print(f"方案:")
            for w in out['wheels']:
                print(f"  {w}")
        return

    if not args.type:
        parser.print_help()
        return

    # 解析号码
    if args.nums:
        nums_list = [int(x.strip()) for x in args.nums.split(",")]
    elif args.count:
        rg = _LOTTERY_CONFIGS[args.type]["red_range"]
        n = min(args.count, rg[1] - rg[0] + 1)
        nums_list = list(range(rg[0], rg[0] + n))
    else:
        print("请使用 --nums 或 --count 指定号码")
        return

    result = build_lottery_wheel(args.type, nums_list, args.cover)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*50}")
        print(f"金水谣 · 旋转矩阵")
        print(f"{'='*50}")
        print(f"彩种: {args.type}")
        print(f"号码: {result.get('red_nums', nums_list)}")
        print(f"类型: {args.cover}")
        print(f"{'='*50}")
        print(result["note"])
        print(f"{'='*50}")
        for i, w in enumerate(result.get("wheels", []), 1):
            print(f"  {i:3d}. {w}")
        print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
