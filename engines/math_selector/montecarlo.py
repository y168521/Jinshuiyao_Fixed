# -*- coding: utf-8 -*-
"""蒙特卡洛：策略回测引擎（数学模型选号模块-诚实证伪核心）

对任意选号策略做 N 次随机模拟，估计其相对随机基线的期望命中增益。
预期结论：增益≈0（若开奖真随机）。
"""
import random


def _draw_uniform(front_lo, front_hi, front_k, back_lo=None, back_hi=None, back_k=0):
    f = tuple(sorted(random.sample(range(front_lo, front_hi + 1), front_k)))
    if back_lo is not None:
        b = tuple(sorted(random.sample(range(back_lo, back_hi + 1), back_k)))
        return (f, b)
    return (f, ())


def _hit_count(my_combo, drawn):
    f_mine, b_mine = my_combo
    f_draw, b_draw = drawn
    fh = len(set(f_mine) & set(f_draw))
    bh = len(set(b_mine) & set(b_draw)) if b_mine else 0
    return fh + bh


def backtest_strategy(strategy_fn, front_lo, front_hi, front_k,
                      back_lo=None, back_hi=None, back_k=0,
                      n_sim=20000, seed=None):
    """对 strategy_fn 生成的固定注单做蒙特卡洛回测。

    strategy_fn: 返回 (front_tuple, back_tuple) 的注单（不依赖随机开奖=策略固定）
    对比：相同注单对 N 次均匀随机开奖的命中 vs 随机基线期望命中。
    返回 {strategy_hit_rate, random_baseline_rate, gain, n_sim, note}
    """
    if seed is not None:
        random.seed(seed)
    my = strategy_fn()
    strat_hits = []
    base_hits = []
    for _ in range(n_sim):
        drawn = _draw_uniform(front_lo, front_hi, front_k, back_lo, back_hi, back_k)
        strat_hits.append(_hit_count(my, drawn))
        rnd = _draw_uniform(front_lo, front_hi, front_k, back_lo, back_hi, back_k)
        base_hits.append(_hit_count(rnd, drawn))
    strat_rate = sum(1 for h in strat_hits if h >= 1) / n_sim
    base_rate = sum(1 for h in base_hits if h >= 1) / n_sim
    gain = round(strat_rate - base_rate, 4)
    return {
        "strategy_hit_rate": round(strat_rate, 4),
        "random_baseline_rate": round(base_rate, 4),
        "gain": gain,
        "n_sim": n_sim,
        "note": ("蒙特卡洛回测：你的策略相对随机基线增益=%.4f（应接近0）。"
                 "随机抽取下几乎必然≈0；若显著>0 才值得深究。" % gain),
    }
