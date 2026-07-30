# -*- coding: utf-8 -*-
"""穹武V1.0 铁律样本外诚实回测（JS-20260727）

背景：用户在 DeepSeek 上跑的「穹武V1.0」彩票模型，6/16-7/10 自报 +574 元，
共演进出 25 条铁律。本脚本对其中**可程序化验证的核心预测类铁律**做样本外检验：

  规则定义只用穹武运行期(≤2026-07-10, 期号≤2026181)的信息；
  检验只在样本外(2026182~最新, 7/11 之后)的真实开奖上进行。

被检验的规则（预测类）：
  R1 组选4码高频池 + 铁律二十四换血 + 铁律二十五胆码固定  （福彩3D/排列三）
  R2 铁律二十四「换血」触发后是否真的改善交集              （全历史统计）
  R3 铁律十一「遗漏超均值1.5倍强制补位」= 冷号回补假设      （全历史统计）
  R4 铁律十六 连号策略（双色球）实证出现率
  R5 铁律十八/十二 暂停机制 = 连续miss后命中率是否变化（独立性检验）
  R6 样本外 ROI 模拟：穹武式 3D 投注 15 期净值

对照基准：同期随机策略 Monte Carlo（2000次）+ 理论概率。
输出：JSON + 控制台摘要，供 HTML 报告引用。
"""
import os
import sys
import json
import random
import itertools
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "金水谣数据", "lot_data")

SPLIT_PERIOD_3D = 2026181   # 穹武最后一次运行 7/10；> 此期号即样本外
QW_START_3D = 2026157       # 6/16 前后穹武启动

random.seed(20260727)       # 可复现


def load(lot):
    p = os.path.join(DATA_DIR, f"{lot}.json")
    data = json.load(open(p, encoding="utf-8"))
    data.sort(key=lambda d: d.get("period", 0))
    return data


def digits_of(rec):
    """3D/排列三 开奖 -> [d1,d2,d3]"""
    return [int(x) % 10 for x in rec["nums"].split(",")]


# ---------------------------------------------------------------- R1
def top4_pool(history, window=10, fixed_dan=None):
    """穹武式高频4码池：最近 window 期数字频次 Top4；
    铁律二十五：fixed_dan（胆码）强制保留。"""
    cnt = Counter()
    for rec in history[-window:]:
        cnt.update(digits_of(rec))
    ranked = [d for d, _ in cnt.most_common()]
    pool = []
    if fixed_dan:
        pool.extend([d for d in fixed_dan if d in ranked or True][:2])
    for d in ranked:
        if d not in pool:
            pool.append(d)
        if len(pool) == 4:
            break
    # 数字不够时补随机
    while len(pool) < 4:
        d = random.randrange(10)
        if d not in pool:
            pool.append(d)
    return pool


def run_pool_strategy(records, start_idx, end_idx, use_huanxue=True, use_dan=True):
    """在 records[start_idx:end_idx] 上逐期运行穹武组选池策略。
    返回逐期 (pool, 交集数, 是否组六全中)"""
    rows = []
    zero_streak = 0
    pool = None
    dan = None
    for i in range(start_idx, end_idx):
        hist = records[:i]
        if pool is None or (use_huanxue and zero_streak >= 2):
            # 换血：重建池（触发时用短窗口5期，模拟"换血"激进性）
            win = 5 if pool is not None else 10
            pool = top4_pool(hist, window=win, fixed_dan=dan if use_dan else None)
            if use_dan:
                cnt = Counter()
                for rec in hist[-10:]:
                    cnt.update(digits_of(rec))
                dan = [d for d, _ in cnt.most_common(2)]
            zero_streak = 0
        actual = digits_of(records[i])
        uniq = set(actual)
        inter = len(uniq & set(pool))
        hit_z6 = (len(uniq) == 3 and uniq <= set(pool))  # 组六4码复式命中
        if inter == 0:
            zero_streak += 1
        else:
            zero_streak = 0
        rows.append({"period": records[i]["period"], "pool": list(pool),
                     "inter": inter, "hit_z6": hit_z6})
    return rows


def mc_random_pool(records, start_idx, end_idx, trials=2000):
    """随机4码池 Monte Carlo 基准"""
    hits_dist = []
    for _ in range(trials):
        hits = 0
        for i in range(start_idx, end_idx):
            pool = set(random.sample(range(10), 4))
            uniq = set(digits_of(records[i]))
            if len(uniq) == 3 and uniq <= pool:
                hits += 1
        hits_dist.append(hits)
    n = end_idx - start_idx
    mean_hits = sum(hits_dist) / trials
    return {"trials": trials, "periods": n,
            "mean_hits": round(mean_hits, 3),
            "mean_rate": round(mean_hits / n, 4) if n else 0,
            "dist": dict(sorted(Counter(hits_dist).items()))}


# ---------------------------------------------------------------- R2
def huanxue_effect(records, window=10):
    """全历史统计：换血触发（连续2期池与开奖零交集）后下一期交集
    vs 无条件平均交集。若换血有效，触发后交集应显著高于均值。"""
    inters = []
    trigger_next = []
    zero_streak = 0
    for i in range(window, len(records) - 1):
        pool = top4_pool(records[:i], window=window)
        uniq = set(digits_of(records[i]))
        inter = len(uniq & set(pool))
        inters.append(inter)
        if zero_streak >= 2:
            # 上两期零交集 -> 本期视为"换血后首期"（池已按最新历史重算）
            trigger_next.append(inter)
        if inter == 0:
            zero_streak += 1
        else:
            zero_streak = 0
    return {
        "overall_mean_inter": round(sum(inters) / len(inters), 3) if inters else 0,
        "n_total": len(inters),
        "n_trigger": len(trigger_next),
        "trigger_mean_inter": round(sum(trigger_next) / len(trigger_next), 3) if trigger_next else None,
    }


# ---------------------------------------------------------------- R3
def cold_number_test(records):
    """铁律十一：遗漏最大的数字下一期是否更容易出现？
    理论：数字在3位开奖中至少出现一次的概率 = 1-0.9^3 = 27.1%（独立同分布）"""
    last_seen = {d: -1 for d in range(10)}
    appear_after_max_miss = 0
    total = 0
    for i, rec in enumerate(records):
        if i >= 30:
            # 找当前遗漏最大的数字
            coldest = min(range(10), key=lambda d: last_seen[d])
            uniq = set(digits_of(rec))
            total += 1
            if coldest in uniq:
                appear_after_max_miss += 1
        for d in digits_of(rec):
            last_seen[d] = i
    return {"n": total,
            "coldest_appear_rate": round(appear_after_max_miss / total, 4) if total else 0,
            "theory_rate": 0.271}


# ---------------------------------------------------------------- R4
def lianma_test():
    """铁律十六：双色球开奖含连号的实证频率 vs 理论 66%"""
    recs = load("双色球")
    n = 0
    with_consec = 0
    for rec in recs:
        try:
            reds = sorted(int(x) for x in rec["nums"].split("+")[0].split(","))
        except Exception:
            continue
        if len(reds) != 6:
            continue
        n += 1
        if any(b - a == 1 for a, b in zip(reds, reds[1:])):
            with_consec += 1
    return {"n": n, "with_consec_rate": round(with_consec / n, 4) if n else 0,
            "theory_rate": 0.6598}


# ---------------------------------------------------------------- R5
def independence_test(rows):
    """铁律十八/十二：连续2期miss后的命中率 vs 总体命中率（组六口径太稀，
    用交集>=2 当"信号日"口径，样本更足）"""
    sig = [r["inter"] >= 2 for r in rows]
    overall = sum(sig) / len(sig) if sig else 0
    after2miss = [sig[i] for i in range(2, len(sig)) if not sig[i-1] and not sig[i-2]]
    rate2 = sum(after2miss) / len(after2miss) if after2miss else None
    return {"overall_rate": round(overall, 4), "n": len(sig),
            "after_2miss_rate": round(rate2, 4) if rate2 is not None else None,
            "n_after_2miss": len(after2miss)}


# ---------------------------------------------------------------- R6
def roi_simulation(records, start_idx, end_idx):
    """样本外 ROI：穹武式 3D 投注
    每期：直选3注(池前3数字的3种排列) 2元/注 + 组六4码复式4注 2元/注 = 14元
    奖金：直选1040 / 组六173"""
    rows = run_pool_strategy(records, start_idx, end_idx)
    spend = 0
    win = 0
    detail = []
    for r, i in zip(rows, range(start_idx, end_idx)):
        pool = r["pool"]
        # 直选3注：池前3数字的3个循环排列（确定性，模拟"位选"）
        p3 = pool[:3]
        zhixuan = [(p3[0], p3[1], p3[2]), (p3[1], p3[2], p3[0]), (p3[2], p3[0], p3[1])]
        actual = tuple(digits_of(records[i]))
        cost = 3 * 2 + 4 * 2
        prize = 0
        if actual in zhixuan:
            prize += 1040
        if r["hit_z6"]:
            prize += 173
        spend += cost
        win += prize
        detail.append({"period": r["period"], "cost": cost, "prize": prize})
    return {"periods": len(rows), "spend": spend, "win": win, "net": win - spend,
            "detail": detail}


# ---------------------------------------------------------------- main
def main():
    out = {"meta": {"split_period": SPLIT_PERIOD_3D,
                    "note": "规则参数只用<=2026181(7/10)确定；检验在2026182+(7/11后)样本外开奖"}}

    for lot in ["福彩3D", "排列三"]:
        recs = load(lot)
        idx_split = next(i for i, r in enumerate(recs) if r["period"] > SPLIT_PERIOD_3D)
        idx_qw = next(i for i, r in enumerate(recs) if r["period"] >= QW_START_3D)
        n_oos = len(recs) - idx_split

        # R1 样本外：穹武池策略 vs 随机池
        oos_rows = run_pool_strategy(recs, idx_split, len(recs))
        z6_hits = sum(1 for r in oos_rows if r["hit_z6"])
        mc = mc_random_pool(recs, idx_split, len(recs))
        # R1 样本内（对照展示：穹武运行期本身的表现）
        ins_rows = run_pool_strategy(recs, idx_qw, idx_split)
        z6_hits_ins = sum(1 for r in ins_rows if r["hit_z6"])

        out[lot] = {
            "oos_periods": n_oos,
            "R1_strategy_hits_oos": z6_hits,
            "R1_strategy_rate_oos": round(z6_hits / n_oos, 4),
            "R1_random_baseline": mc,
            "R1_insample_hits": z6_hits_ins,
            "R1_insample_periods": len(ins_rows),
            "R1_theory_rate": round(0.72 * 7 / 210, 4),  # 组六72% × 4码含3中奖码 7/210
            "R2_huanxue": huanxue_effect(recs),
            "R3_cold": cold_number_test(recs),
            "R5_independence": independence_test(run_pool_strategy(recs, 30, len(recs))),
            "oos_rows": oos_rows,
        }
        if lot == "福彩3D":
            out[lot]["R6_roi_oos"] = roi_simulation(recs, idx_split, len(recs))

    out["R4_ssq_lianma"] = lianma_test()

    path = os.path.join(ROOT, "金水谣数据", "backtest_results", "backtest_qiongwu_rules.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 控制台摘要
    print("=" * 70)
    print("穹武V1.0 铁律样本外诚实回测（样本外=2026-07-11之后真实开奖）")
    print("=" * 70)
    for lot in ["福彩3D", "排列三"]:
        r = out[lot]
        print(f"\n【{lot}】样本外 {r['oos_periods']} 期")
        print(f"  R1 组选4码池(高频+换血+胆码): 命中组六 {r['R1_strategy_hits_oos']}/{r['oos_periods']}"
              f" = {r['R1_strategy_rate_oos']:.2%}")
        print(f"     随机4码池基准(MC2000次): 平均 {r['R1_random_baseline']['mean_hits']:.2f} 次"
              f" = {r['R1_random_baseline']['mean_rate']:.2%} | 理论 {r['R1_theory_rate']:.2%}")
        print(f"     [样本内对照] 穹武运行期 {r['R1_insample_hits']}/{r['R1_insample_periods']} 次")
        h = r["R2_huanxue"]
        print(f"  R2 换血后首期平均交集 {h['trigger_mean_inter']} (n={h['n_trigger']})"
              f" vs 无条件平均 {h['overall_mean_inter']} (n={h['n_total']})")
        c = r["R3_cold"]
        print(f"  R3 最大遗漏数字下期出现率 {c['coldest_appear_rate']:.2%}"
              f" vs 理论 {c['theory_rate']:.1%} (n={c['n']})")
        ind = r["R5_independence"]
        print(f"  R5 连续2期弱交集后信号率 {ind['after_2miss_rate']} vs 总体 {ind['overall_rate']}"
              f" (n={ind['n_after_2miss']}/{ind['n']})")
    roi = out["福彩3D"]["R6_roi_oos"]
    print(f"\n【R6 样本外ROI模拟·福彩3D】{roi['periods']}期 投入{roi['spend']}元"
          f" 中奖{roi['win']}元 净值 {roi['net']:+d}元")
    sq = out["R4_ssq_lianma"]
    print(f"\n【R4 双色球连号】实证含连号率 {sq['with_consec_rate']:.2%}"
          f" vs 理论 {sq['theory_rate']:.2%} (n={sq['n']})")
    print(f"\n已写出: {path}")


if __name__ == "__main__":
    main()
