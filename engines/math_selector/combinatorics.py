# -*- coding: utf-8 -*-
"""组合数学：候选池缩水（数学模型选号模块-组合数学维）

诚实定位：本模块不做任何"预测"。仅用组合数学把"要买的注数"从全集合
（大乐透 C(35,5)*C(12,2)=2143万）缩小到预算能覆盖的候选集组合。
缩水=用"候选号池"替代"全集合"，必然牺牲"全中"保证换取"部分中"覆盖。
彩票本质随机，缩水不改变每注等概率，只改变你购买的集合。
"""
from itertools import combinations


def enumerate_combos(front_pool, front_k, back_pool=None, back_k=0):
    front_pool = sorted(front_pool)
    for f in combinations(front_pool, front_k):
        if back_pool:
            for b in combinations(sorted(back_pool), back_k):
                yield (f, b)
        else:
            yield (f, ())


def shrink(front_pool, front_k, back_pool=None, back_k=0, budget=149):
    """缩水主函数：枚举候选池全部组合并按预算截断。

    Args:
        front_pool: 前区候选号（如历史热号Top M，M>front_k）
        front_k: 前区选几（大乐透5/双色球6）
        back_pool: 后区候选号（大乐透2/双色球1），无则 None
        back_k: 后区选几
        budget: 最大注数预算
    Returns:
        dict: {tickets, total_combos, kept, truncated, budget, note}
    """
    try:
        from math import comb as _comb
        total = _comb(len(front_pool), front_k)
        if back_pool:
            total *= _comb(len(back_pool), back_k)
    except Exception:
        total = sum(1 for _ in enumerate_combos(front_pool, front_k, back_pool, back_k))

    tickets = []
    truncated = False
    for f, b in enumerate_combos(front_pool, front_k, back_pool, back_k):
        if len(tickets) >= budget:
            truncated = True
            break
        if b:
            tickets.append(",".join(f"{x:02d}" for x in f) + "+" + ",".join(f"{x:02d}" for x in b))
        else:
            tickets.append(",".join(f"{x:02d}" for x in f))

    note = ("组合数学缩水：候选池全部组合已在预算内，未截断。"
            if not truncated else
            "组合数学缩水：候选池组合超出预算已截断；截断部分未保证覆盖，"
            "缩小候选池（如前区候选数）可完整覆盖。")
    return {"tickets": tickets, "total_combos": total, "kept": len(tickets),
            "truncated": truncated, "budget": budget, "note": note}
