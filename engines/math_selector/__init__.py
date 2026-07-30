# -*- coding: utf-8 -*-
"""数学模型选号 · 统一入口

调度六维方法（组合数学/统计推断/蒙特卡洛/时间序列/误差分析/偏离波动），
基于真实历史数据做"历史筛选 + 纪律化缩水 + 策略证伪"。
诚实定位：所有方法仅用于筛选与理解，不预测中奖；每注中奖概率恒等于随机基准。
"""
from config import LOTTERY_RULES, LOT_ALL
from models.lottery_data import Data

ALL_METHODS = ["combinatorics", "stats", "timeseries", "montecarlo", "calibration"]


def _parse_history(lot, arr):
    rule = LOTTERY_RULES.get(lot, {})
    is_digit = rule.get("digit", False)
    front, back, sums = [], [], []
    for d in arr:
        nums = str(d.get("nums", "")).split("+")
        rf = [int(x) for x in nums[0].split(",") if x.strip().isdigit()]
        front.append(rf)
        if len(nums) > 1 and not is_digit:
            rb = [int(x) for x in nums[1].split(",") if x.strip().isdigit()]
            back.append(rb)
        if rf:
            sums.append(sum(rf))
    return {"front": front, "back": back, "sums": sums}


def _freq_top(pools, top_k):
    from collections import Counter
    c = Counter()
    for p in pools:
        c.update(p)
    return [n for n, _ in c.most_common(top_k)]


def run_math_model(lot, methods=None, budget=149, front_candidates=None,
                   back_candidates=None, n_sim=20000):
    if lot not in LOT_ALL:
        return {"ok": False, "error": f"不支持彩种 {lot}", "supported": LOT_ALL}
    rule = LOTTERY_RULES[lot]
    fk = rule["red"][2] if len(rule["red"]) > 2 else 5
    fr = (rule["red"][0], rule["red"][1])
    bk, br = 0, None
    if rule.get("blue"):
        bk = rule["blue"][2]
        br = (rule["blue"][0], rule["blue"][1])

    arr = Data.load(lot)
    if not arr:
        return {"ok": False, "error": f"{lot} 无历史数据", "supported": LOT_ALL}

    hist = _parse_history(lot, arr)
    methods = methods or ALL_METHODS
    result = {"ok": True, "lot": lot, "methods": {}, "meta": {},
              "disclaimer": "候选集·非购买建议：本接口仅输出候选号码集与统计证伪，不预测中奖，每注中奖概率恒等于随机基准，请勿据此下单。"}

    # 候选池（缩水/策略依据）：默认取历史频次最高者
    if front_candidates is None:
        front_candidates = _freq_top(hist["front"], fk + 5)
    if back_candidates is None and br:
        back_candidates = _freq_top(hist["back"], bk + 3)

    # 1 组合数学：候选池缩水
    if "combinatorics" in methods:
        from .combinatorics import shrink
        result["methods"]["combinatorics"] = shrink(
            front_candidates, fk, back_candidates if br else None, bk, budget)

    # 2 统计推断 + 3 偏离波动
    if "stats" in methods:
        from . import stats
        from collections import Counter
        allf = Counter()
        for p in hist["front"]:
            allf.update(p)
        lo, hi = fr
        observed = [allf.get(n, 0) for n in range(lo, hi + 1)]
        chi = stats.chi2_uniform(observed)
        # 各号遗漏（距最新一期的期数）
        N = len(hist["front"])
        last = {}
        for idx, p in enumerate(hist["front"]):
            for n in set(p):
                if n not in last:
                    last[n] = N - 1 - idx
        miss_vals = [last.get(n, N) for n in range(lo, hi + 1)]
        zdev = stats.zscore_deviation(miss_vals)
        result["methods"]["stats"] = {"chi2_uniform": chi, "zscore_deviation": zdev}

    # 4 时间序列：平稳性
    if "timeseries" in methods:
        from . import timeseries
        result["methods"]["timeseries"] = timeseries.stationarity_report(hist["sums"])

    # 5 蒙特卡洛 + 6 误差校准（共享模拟）
    if "montecarlo" in methods or "calibration" in methods:
        from . import montecarlo
        strat_front = tuple(sorted(front_candidates[:fk]))
        strat_back = tuple(sorted(back_candidates[:bk])) if (br and back_candidates) else ()
        result["methods"]["_strategy"] = {"front": list(strat_front), "back": list(strat_back)}

        def _strat():
            return (strat_front, strat_back)

        bt = montecarlo.backtest_strategy(
            _strat, fr[0], fr[1], fk, br[0] if br else None, br[1] if br else None, bk, n_sim=n_sim)
        if "montecarlo" in methods:
            result["methods"]["montecarlo"] = bt
        if "calibration" in methods:
            import random
            from collections import Counter as _C
            hits = []
            random.seed(12345)
            for _ in range(n_sim):
                drawn = montecarlo._draw_uniform(fr[0], fr[1], fk, br[0] if br else None, br[1] if br else None, bk)
                fh = len(set(strat_front) & set(drawn[0]))
                bh = len(set(strat_back) & set(drawn[1])) if strat_back else 0
                hits.append(fh + bh)
            dist = _C(hits)
            max_h = fk + bk
            dist_pct = {k: round(dist.get(k, 0) / n_sim, 4) for k in range(max_h + 1)}
            result["methods"]["calibration"] = {
                "hit_distribution": dist_pct,
                "note": "策略注单在随机开奖下命中k个号的概率分布；与随机注单分布一致即说明策略无优势。",
            }

    result["meta"] = {
        "front_candidates": front_candidates,
        "back_candidates": back_candidates if br else None,
        "front_k": fk, "back_k": bk,
        "n_periods": len(arr),
        "honest_note": "候选集·非购买建议：所有方法仅用于历史筛选+纪律化缩水+策略证伪，不预测中奖；每注中奖概率恒等于随机基准。",
    }
    return result
