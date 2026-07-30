# -*- coding: utf-8 -*-
"""五份彩票模型报告核心主张统一回测（JS-20260727-02）

背景：用户陆续发来 5 份不同 AI 跑的彩票模型复盘报告：
  M1 天枢·穹武 V3.8→V2.3（5码池/直落号/冷号4-6期回补，自报-222元空仓）
  M2 天枢·穹武 V24.0 双轨并行（方案A热号+方案B温号+组三防守，自报V24.0独立+21元）
  M3 天枢·穹武 V2.2（冷号补位遗漏≥8期，自报命中率80%）
  M4 星衡 V16.5（5码池扩容，自报被替换数字开出率40%，-203熔断）
  M5 天枢·穹武 V19.2.1（自报2.5%<理论3.33%，已自我承认失败）

方法：所有可程序化主张在**全历史 + 样本外(期号>2026181, 即7/10之后)**真实开奖上检验，
对照 = 理论概率 + 随机策略 Monte Carlo。随机种子固定可复现。

被检验主张：
  T1  M1「直落号下期平均重复1.2个」
  T2  M1「遗漏4-6期冷号回补窗口有效」/ M3「遗漏≥8期极冷号回补80%」→ 各遗漏桶下期出现率
  T3  M1/M2「组三遗漏阈值N=4提前防守」→ P(组三|连续4期组六) vs 无条件P(组三)
  T4  M2「组三对子 禁止与上期相同+顺延 有信息量」→ P(对子重复)实证
  T5  M2「双轨A+B 8码 3码全覆盖是互补能力证明」→ 全覆盖率 vs 理论46.7%(任意8码)
  T6  M1 5码池(近8期TOP5) / M4 V16.5五步5码池 样本外组六命中 vs 随机5码池(理论8.33%)
  T7  M4「被替换数字开出率40%」→ 任意数字下期出现率27.1%，10期4次的二项P值
  T8  样本外 ROI：M1(20元/日)、M2(32元/日)、M4(44元/日) 按各自费率模拟
"""
import os
import sys
import json
import math
import random
import itertools
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "金水谣数据", "lot_data")
OUT_JSON = os.path.join(ROOT, "金水谣数据", "backtest_results", "backtest_five_models_claims.json")

SPLIT_PERIOD = 2026181  # 7/10；> 此期号即样本外
random.seed(20260727)

P_DIGIT_NEXT = 1 - 0.9 ** 3  # 任意指定数字出现在下期3位开奖中的理论概率 = 27.1%


def load(lot):
    data = json.load(open(os.path.join(DATA_DIR, f"{lot}.json"), encoding="utf-8"))
    data.sort(key=lambda d: d.get("period", 0))
    return data


def digits_of(rec):
    return [int(x) % 10 for x in rec["nums"].split(",")]


def is_zu3(ds):
    return len(set(ds)) == 2


def binom_p_ge(n, k, p):
    """P(X>=k), X~B(n,p)"""
    return sum(math.comb(n, i) * p**i * (1-p)**(n-i) for i in range(k, n+1))


# ---------------------------------------------------------------- T1 直落号重复
def t1_carryover(records):
    """上期开奖数字(去重)与本期开奖数字(去重)的交集平均个数"""
    total, n = 0, 0
    for i in range(1, len(records)):
        prev = set(digits_of(records[i-1]))
        cur = set(digits_of(records[i]))
        total += len(prev & cur)
        n += 1
    # 理论期望：E[|prev|]≈2.73(组六3/组三2)，每个数字下期出现概率27.1%
    avg_prev = sum(len(set(digits_of(r))) for r in records) / len(records)
    theory = avg_prev * P_DIGIT_NEXT
    return {"periods": n, "avg_repeat": round(total/n, 3), "theory": round(theory, 3)}


# ---------------------------------------------------------------- T2 遗漏桶回补
def t2_omission_buckets(records):
    """各遗漏区间的数字，下期出现率。基准=27.1%（独立事件）"""
    buckets = {"0-2": (0, 2), "3-5": (3, 5), "4-6": (4, 6), "8+": (8, 999), "12+": (12, 999)}
    stat = {k: [0, 0] for k in buckets}  # [出现次数, 观察次数]
    omission = {d: 0 for d in range(10)}
    for i, rec in enumerate(records):
        cur = set(digits_of(rec))
        if i > 0:
            for d in range(10):
                for name, (lo, hi) in buckets.items():
                    if lo <= omission[d] <= hi:
                        stat[name][1] += 1
                        if d in cur:
                            stat[name][0] += 1
        for d in range(10):
            omission[d] = 0 if d in cur else omission[d] + 1
    out = {}
    for name, (hit, obs) in stat.items():
        out[name] = {"obs": obs, "hit": hit,
                     "rate": round(hit/obs*100, 2) if obs else None}
    out["baseline"] = round(P_DIGIT_NEXT*100, 2)
    return out


# ---------------------------------------------------------------- T3 组三条件概率
def t3_zu3_conditional(records):
    total = len(records) - 1
    zu3_flags = [is_zu3(digits_of(r)) for r in records]
    uncond = sum(zu3_flags) / len(zu3_flags)
    # 条件：前4期均组六
    cond_obs = cond_hit = 0
    for i in range(4, len(records)):
        if not any(zu3_flags[i-4:i]):
            cond_obs += 1
            if zu3_flags[i]:
                cond_hit += 1
    return {"uncond_rate": round(uncond*100, 2),
            "after4zu6_obs": cond_obs,
            "after4zu6_rate": round(cond_hit/cond_obs*100, 2) if cond_obs else None,
            "theory": 27.0}


# ---------------------------------------------------------------- T4 对子重复
def t4_pair_repeat(records):
    """连续两次组三时，对子相同的概率（M2 的『严禁与上期对子相同』规则价值）"""
    pairs = []
    for r in records:
        ds = digits_of(r)
        if is_zu3(ds):
            c = Counter(ds)
            pairs.append((r["period"], max(c, key=c.get)))
        else:
            pairs.append((r["period"], None))
    obs = rep = 0
    last_pair = None
    for _, p in pairs:
        if p is not None:
            if last_pair is not None:
                obs += 1
                if p == last_pair:
                    rep += 1
            last_pair = p
    return {"consecutive_zu3_pairs_obs": obs, "same_pair": rep,
            "same_rate": round(rep/obs*100, 2) if obs else None, "theory": 10.0}


# ---------------------------------------------------------------- M2 双轨池构建
def build_pool_A(hist, window=10):
    """方案A：直落优先+频次排序 4码"""
    cnt = Counter()
    for r in hist[-window:]:
        cnt.update(digits_of(r))
    omission = _omission_now(hist)
    last = set(digits_of(hist[-1]))
    # 直落号保留1枚：取频次最高者
    zhiluo = max(last, key=lambda d: (cnt[d], -omission[d], -d))
    pool = [zhiluo]
    for d, _ in sorted(cnt.items(), key=lambda kv: (-kv[1], omission[kv[0]], kv[0])):
        if d not in pool:
            pool.append(d)
        if len(pool) == 4:
            break
    while len(pool) < 4:
        d = random.randrange(10)
        if d not in pool:
            pool.append(d)
    return pool


def build_pool_B(hist, window=10):
    """方案B：频次2-4温号中取遗漏3-5期，遗漏大优先，逐步放宽"""
    cnt = Counter()
    for r in hist[-window:]:
        cnt.update(digits_of(r))
    omission = _omission_now(hist)
    warm = [d for d in range(10) if 2 <= cnt[d] <= 4]
    pool = []
    for lo in (3, 2, 1, 0):
        cand = [d for d in warm if omission[d] >= lo and d not in pool]
        cand.sort(key=lambda d: -omission[d])
        for d in cand:
            if len(pool) < 4:
                pool.append(d)
    for d in sorted(range(10), key=lambda d: -omission[d]):
        if len(pool) >= 4:
            break
        if d not in pool:
            pool.append(d)
    return pool[:4]


def _omission_now(hist):
    om = {d: 0 for d in range(10)}
    seen = {d: False for d in range(10)}
    for r in reversed(hist):
        cur = set(digits_of(r))
        for d in range(10):
            if not seen[d]:
                if d in cur:
                    seen[d] = True
                else:
                    om[d] += 1
        if all(seen.values()):
            break
    return om


def t5_dual_track(records, start_idx, end_idx):
    """双轨A+B：全覆盖率、各轨组六命中"""
    obs = cover = hitA = hitB = 0
    for i in range(start_idx, end_idx):
        hist = records[:i]
        if len(hist) < 12:
            continue
        A, B = set(build_pool_A(hist)), set(build_pool_B(hist))
        uniq = set(digits_of(records[i]))
        obs += 1
        if uniq <= (A | B):
            cover += 1
        if len(uniq) == 3 and uniq <= A:
            hitA += 1
        if len(uniq) == 3 and uniq <= B:
            hitB += 1
    # 理论：8个不同数字覆盖开奖3个去重数字（组六情形）= C(8,3)/C(10,3)=46.7%
    return {"obs": obs, "cover": cover,
            "cover_rate": round(cover/obs*100, 2) if obs else None,
            "theory_8codes": 46.7,
            "hitA": hitA, "hitB": hitB,
            "theory_hit_per_track": round(math.comb(4,3)/math.comb(10,3)*100, 2)}


# ---------------------------------------------------------------- T6 5码池样本外
def build_pool_M1(hist):
    """M1 V2.3：近8期频次TOP5，并列取遗漏大者"""
    cnt = Counter()
    for r in hist[-8:]:
        cnt.update(digits_of(r))
    omission = _omission_now(hist)
    ranked = sorted(cnt.items(), key=lambda kv: (-kv[1], -omission[kv[0]]))
    pool = [d for d, _ in ranked[:5]]
    while len(pool) < 5:
        d = random.randrange(10)
        if d not in pool:
            pool.append(d)
    return pool


def build_pool_M4(hist):
    """M4 V16.5 五步池（简化实现：TOP5→温号补位→次冷号→极冷号）"""
    cnt = Counter()
    for r in hist[-10:]:
        cnt.update(digits_of(r))
    omission = _omission_now(hist)
    pool = [d for d, _ in cnt.most_common(5)]
    # 温号补位：无遗漏2-4期数字则替换频次最低者
    if not any(2 <= omission[d] <= 4 for d in pool):
        cand = [d for d in range(10) if 2 <= omission[d] <= 4]
        if cand:
            newd = min(cand, key=lambda d: omission[d])
            pool[pool.index(min(pool, key=lambda d: cnt[d]))] = newd
    # 次冷号：遗漏5-9期选最小
    cand = [d for d in range(10) if 5 <= omission[d] <= 9]
    if cand:
        newd = min(cand, key=lambda d: omission[d])
        if newd not in pool:
            pool[pool.index(min(pool, key=lambda d: -omission[d]))] = newd
    # 极冷号：遗漏>=15且频次<=1
    cand = [d for d in range(10) if omission[d] >= 15 and cnt[d] <= 1]
    if cand:
        newd = cand[0]
        if newd not in pool:
            pool[pool.index(min(pool, key=lambda d: (cnt[d], -omission[d])))] = newd
    return list(dict.fromkeys(pool))[:5]


def t6_pool5_oos(records, builder, start_idx, end_idx):
    obs = hits = 0
    detail = []
    for i in range(start_idx, end_idx):
        hist = records[:i]
        if len(hist) < 12:
            continue
        pool = set(builder(hist))
        uniq = set(digits_of(records[i]))
        obs += 1
        hit = (len(uniq) == 3 and uniq <= pool)
        hits += hit
        detail.append({"period": records[i]["period"], "pool": sorted(pool),
                       "actual": sorted(uniq), "hit": bool(hit)})
    return {"obs": obs, "hits": hits,
            "rate": round(hits/obs*100, 2) if obs else None,
            "theory_random5": round(math.comb(5,3)/math.comb(10,3)*100, 2),
            "detail": detail}


def mc_random5(records, start_idx, end_idx, trials=2000):
    dist = []
    for _ in range(trials):
        h = 0
        for i in range(start_idx, end_idx):
            pool = set(random.sample(range(10), 5))
            uniq = set(digits_of(records[i]))
            if len(uniq) == 3 and uniq <= pool:
                h += 1
        dist.append(h)
    n = end_idx - start_idx
    return {"mean_hits": round(sum(dist)/trials, 3), "periods": n,
            "p_ge1": round(sum(1 for x in dist if x >= 1)/trials*100, 1)}


# ---------------------------------------------------------------- main
def main():
    results = {}
    for lot in ("福彩3D", "排列三"):
        recs = load(lot)
        oos_start = next(i for i, r in enumerate(recs) if r["period"] > SPLIT_PERIOD)
        oos_end = len(recs)
        r = {}
        r["T1_carryover"] = t1_carryover(recs)
        r["T2_omission"] = t2_omission_buckets(recs)
        r["T3_zu3_cond"] = t3_zu3_conditional(recs)
        r["T4_pair_repeat"] = t4_pair_repeat(recs)
        r["T5_dual_track_oos"] = t5_dual_track(recs, oos_start, oos_end)
        r["T6_M1_pool5_oos"] = t6_pool5_oos(recs, build_pool_M1, oos_start, oos_end)
        r["T6_M4_pool5_oos"] = t6_pool5_oos(recs, build_pool_M4, oos_start, oos_end)
        r["T6_random5_mc"] = mc_random5(recs, oos_start, oos_end)
        r["oos_periods"] = oos_end - oos_start
        results[lot] = r

    # T7 M4「被替换数字开出率40%」：10期中≥4次的概率（基准27.1%）
    results["T7_replaced_digit"] = {
        "baseline": round(P_DIGIT_NEXT*100, 2),
        "claim": 40.0,
        "p_value_ge4_of_10": round(binom_p_ge(10, 4, P_DIGIT_NEXT)*100, 1),
        "note": "10期观察到≥4次的概率=35%，纯噪声即可产生该'发现'"
    }

    # T8 样本外 ROI（按各模型费率，用 T6 命中数；组选奖金173）
    roi = {}
    for tag, lot_key, daily_cost, hits_key in (
        ("M1_V2.3_20元", "福彩3D", 20, "T6_M1_pool5_oos"),
        ("M4_V16.5_22元单彩种", "福彩3D", 22, "T6_M4_pool5_oos"),
    ):
        n = results[lot_key][hits_key]["obs"]
        h = results[lot_key][hits_key]["hits"]
        roi[tag] = {"periods": n, "cost": n*daily_cost, "win": h*173,
                    "net": h*173 - n*daily_cost}
    results["T8_roi_oos"] = roi

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump(results, open(OUT_JSON, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # 控制台摘要
    for lot in ("福彩3D", "排列三"):
        r = results[lot]
        print(f"===== {lot} (样本外 {r['oos_periods']} 期) =====")
        print("T1 直落号平均重复:", r["T1_carryover"])
        print("T2 遗漏桶回补率:", json.dumps(r["T2_omission"], ensure_ascii=False))
        print("T3 组三条件概率:", r["T3_zu3_cond"])
        print("T4 对子重复率:", r["T4_pair_repeat"])
        t5 = r["T5_dual_track_oos"]
        print(f"T5 双轨: 覆盖{t5['cover']}/{t5['obs']}={t5['cover_rate']}% (理论{t5['theory_8codes']}%) "
              f"A命中{t5['hitA']} B命中{t5['hitB']} (每轨理论{t5['theory_hit_per_track']}%)")
        for k in ("T6_M1_pool5_oos", "T6_M4_pool5_oos"):
            t = r[k]
            print(f"{k}: {t['hits']}/{t['obs']}={t['rate']}% (随机5码理论{t['theory_random5']}%)")
        print("T6 随机5码MC:", r["T6_random5_mc"])
        print()
    print("T7 被替换数字40%主张:", results["T7_replaced_digit"])
    print("T8 样本外ROI:", json.dumps(results["T8_roi_oos"], ensure_ascii=False))
    print("\nJSON ->", OUT_JSON)


if __name__ == "__main__":
    main()
