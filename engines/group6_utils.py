# -*- coding: utf-8 -*-
"""排列三 / 福彩3D 组选六复式 组合展开与校验（单一真源）。

为什么要有这个模块：
    此前全仓 C(n,3) 只存在于 format_gen.py 的**注释**里（"C(5,3)=10注"），
    系统从未真正展开或校验过复式组合 ⇒ 「5 码是否真的覆盖 10 注组六、
    有无重复、有无混入组三/豹子」全靠人眼。本模块把它变成可断言的代码。

组选六规则（唯一定义，其余模块一律引用本文件）：
    - 号码池 = 若干个 0-9 的**互异**数字（复式记法，如 "01,03,04,07,09"）
    - 展开 = 从池中任取 3 个的不同组合，共 C(n,3) 注
    - 每一注的 3 个数字必须互不相同 ⇒ 天然排除组三（2同1异）与豹子号（3同）
    - 开奖号为 3 个互异数字且集合与该注相同 ⇒ 中奖（不计顺序）

诚实声明：本模块只保证「组合完整、无重复、符合规则」这类**结构性正确性**，
不提升任何命中率——选号无超越随机的能力（项目既有定论，勿误读）。
"""
from __future__ import annotations

import math
from itertools import combinations
from typing import List, Sequence, Tuple

# 组六复式合法码数范围：少于 3 码无意义（C(n,3)=0），多于 8 码成本失控
MIN_POOL_SIZE = 3
MAX_POOL_SIZE = 8

# 3D/排列三 复式的标准码数（gui/play_plans.py 与之对齐：5码=10注=20元）
DEFAULT_DIGIT_COUNT = 5


def group6_bet_count(n: int) -> int:
    """复式 n 码展开后的注数 = C(n,3)。n<3 时为 0。"""
    if n < 3:
        return 0
    return math.comb(n, 3)


def expand_group6(pool: Sequence[int]) -> List[Tuple[int, int, int]]:
    """把复式码池展开为全部组六单注。

    返回按 (数字升序) 排序的去重组合列表。因为输入先做了去重，
    每个组合的 3 个数字必然互异 ⇒ 天然排除组三与豹子号。
    """
    digits = normalize_pool(pool)
    return [tuple(c) for c in combinations(digits, 3)]


def normalize_pool(pool: Sequence[int]) -> List[int]:
    """归一化号码池：转 int、过滤非法值、去重、升序。

    不做静默截断——过滤掉的非法元素由调用方通过 validate_* 显式感知。
    """
    out = []
    for x in pool or ():
        try:
            v = int(x)
        except (TypeError, ValueError):
            continue
        if 0 <= v <= 9 and v not in out:
            out.append(v)
    return sorted(out)


def complete_pool(pool: Sequence[int], target_size: int,
                  prefer: Sequence[int] = ()) -> List[int]:
    """把号码池补齐到 target_size 个互异数字（不削减）。

    补位顺序：优先用 prefer（如热度/共识排序靠前者），其余按 0-9 升序补。
    target_size 超出合法范围时抛 ValueError（不静默夹取）。
    """
    if not MIN_POOL_SIZE <= target_size <= MAX_POOL_SIZE:
        raise ValueError(
            "目标码数 %r 越界（合法 %d-%d）" % (target_size, MIN_POOL_SIZE, MAX_POOL_SIZE))
    out = normalize_pool(pool)
    for x in list(prefer) + list(range(10)):
        if len(out) >= target_size:
            break
        try:
            v = int(x)
        except (TypeError, ValueError):
            continue
        if 0 <= v <= 9 and v not in out:
            out.append(v)
    return sorted(out)


def validate_group6_fushi(pool: Sequence[int],
                          expected_size: int = DEFAULT_DIGIT_COUNT
                          ) -> Tuple[bool, List[str]]:
    """校验一个组六复式码池是否完整、无重复、符合规则。

    Returns
    -------
    (ok, issues)
        issues 为可读问题列表，空列表表示通过。
    """
    issues: List[str] = []
    digits = normalize_pool(pool)

    if len(digits) != expected_size:
        issues.append(
            "码数应为 %d，实际 %d（展开注数 %d，应为 %d）"
            % (expected_size, len(digits),
               group6_bet_count(len(digits)), group6_bet_count(expected_size)))

    bets = expand_group6(digits)
    expected_bets = group6_bet_count(expected_size)
    if len(bets) != expected_bets:
        issues.append("展开注数 %d != 预期 %d" % (len(bets), expected_bets))

    if len(set(bets)) != len(bets):
        issues.append("展开结果存在重复注")

    for b in bets:
        if len(set(b)) != 3:
            issues.append("注 %s 含重复数字，非组六（组三/豹子号）" % (b,))

    return (not issues), issues


def coverage_report(pool: Sequence[int], draws: Sequence[Sequence[int]]
                    ) -> dict:
    """给定历史开奖，统计该复式对「组六开奖」的覆盖命中情况。

    只统计开奖号为 3 个互异数字（即组六开奖）的期次；
    组三/豹子开奖不计入分母（那本就不是组六的覆盖范围）。
    """
    digits = normalize_pool(pool)
    bets = set(expand_group6(digits))
    total_group6 = 0
    hit = 0
    for d in draws or ():
        nums = normalize_pool(d)
        if len(nums) != 3:
            continue  # 组三/豹子开奖：不在组六覆盖范围内
        total_group6 += 1
        if tuple(sorted(nums)) in bets:
            hit += 1
    return {
        "pool": digits,
        "bet_count": len(bets),
        "group6_draws": total_group6,
        "hit_draws": hit,
        "hit_rate": (hit / total_group6) if total_group6 else 0.0,
    }
