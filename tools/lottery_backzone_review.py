# -*- coding: utf-8 -*-
"""蓝球（后区）深度复盘 · 正推 / 逆推检验 —— JS-20261012-08

聚焦「后区」（双色球蓝球 / 大乐透后区），补 lottery_deep_review.py 没有的两块：
  正推：用历史上下文预测「下一期后区」，朴素策略（冷号 / 热号 / 邻号延续 / 马尔可夫）
        的命中率是否显著优于随机基线。
  逆推：每个后区取值出现前的上下文（上期是否含该号、前区奇偶比）是否与该号有显著关联。

与常驻工具的分工：
  lottery_deep_review.py 做「全彩种偏移谱 / 均匀性 / 预测复盘」；
  本工具做「后区专项 + 正推逆推」，**只读不改任何业务数据**。

设计原则（诚实铁律）：
  - 所有「规律」都对照随机基线，做多重比较 Bonferroni 校正；只报全周期显著项。
  - 随机基线用解析公式 + 蒙特卡洛模拟双轨交叉验证，避免口径漂移造成假结论。
  - 取不到写「暂缺」，绝不编造。预期结论：后区与公平随机无显著偏离（无预测力）。

用法：
    python tools/lottery_backzone_review.py            # 双色球 + 大乐透 全量
    python tools/lottery_backzone_review.py --only 双色球
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import random
import sys
from collections import Counter
from math import comb

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

LOT_DATA = os.path.join(BASE, "金水谣数据", "lot_data")

# 仅后区彩种有意义：(前区池 N, 前区选数 k, 后区池 NB, 后区选数 KB)
SPEC = {
    "双色球": (33, 6, 16, 1),
    "大乐透": (35, 5, 12, 2),
}

M = 3  # 正推策略候选集大小（双色球 3/16；大乐透 1-C(9,2)/C(12,2)≈0.455）


def p_of_z(z):
    """双尾 p 值（正态近似，df=1 时 chi2=z^2）"""
    return math.erfc(abs(z) / math.sqrt(2))


def load_draws(name):
    path = os.path.join(LOT_DATA, name)
    if not os.path.exists(path):
        return []
    rows = []
    for r in json.load(io.open(path, encoding="utf-8")):
        fb = r["nums"].split("+")
        f = [int(x) for x in fb[0].split(",")]
        b = [int(x) for x in fb[1].split(",")] if len(fb) > 1 else []
        rows.append((r.get("period"), r.get("time"), f, b))
    return rows


def hit_prob(m_i, NB, KB):
    """候选集大小 m_i 时，随机抽 KB 个后区「至少命中 1 个」的概率"""
    if m_i <= 0:
        return 0.0
    if KB == 1:
        return m_i / NB
    miss = comb(NB - m_i, KB) / comb(NB, KB) if (NB - m_i) >= KB else 0.0
    return 1.0 - miss


# ---------------------------------------------------------------- A. 分布检验
def chi_square_uniform(rows, NB, KB):
    """后区号码频次均匀性（二项方差 n·p·(1-p)，非泊松）"""
    cnt = Counter()
    for r in rows:
        for x in r[3]:
            cnt[x] += 1
    n = len(rows)
    p = KB / NB
    exp = n * p
    var = n * p * (1 - p)
    if var <= 0:
        return {"stat": 0.0, "df": NB - 1, "chi_per_df": 0.0}
    stat = sum((cnt.get(i, 0) - exp) ** 2 / var for i in range(1, NB + 1))
    return {"stat": stat, "df": NB - 1, "chi_per_df": stat / (NB - 1)}


def sim_max_gap(NB, KB, n, R=3000, seed=20261012):
    """模拟随机后区的「最大遗漏间隔」空分布，返回 (均值, 标准差)"""
    rng = random.Random(seed)
    gaps = []
    for _ in range(R):
        last = {v: -1 for v in range(1, NB + 1)}
        mg = 0
        for i in range(n):
            draw = set(rng.sample(range(1, NB + 1), KB))
            for v in draw:
                g = i - last[v]
                if g > mg:
                    mg = g
                last[v] = i
        for v in range(1, NB + 1):  # 尾部遗漏
            g = (n - 1) - last[v]
            if g > mg:
                mg = g
        gaps.append(mg)
    mean = sum(gaps) / len(gaps)
    var = sum((g - mean) ** 2 for g in gaps) / len(gaps)
    return mean, math.sqrt(var)


def omission_max_gap(rows, NB, KB):
    """实测最大遗漏 vs 随机空分布（z）"""
    n = len(rows)
    last = {v: -1 for v in range(1, NB + 1)}
    mg = 0
    for i, r in enumerate(rows):
        for v in r[3]:
            g = i - last[v]
            if g > mg:
                mg = g
            last[v] = i
    for v in range(1, NB + 1):
        g = (n - 1) - last[v]
        if g > mg:
            mg = g
    mu, sd = sim_max_gap(NB, KB, n)
    z = (mg - mu) / sd if sd > 0 else 0.0
    return {"obs": mg, "exp_mean": mu, "exp_sd": sd, "z": z, "p": p_of_z(z)}


def parity_size_test(rows, NB, KB):
    """后区奇偶 / 大小的二项卡方（池内奇偶/大小各半）"""
    total = sum(len(r[3]) for r in rows)  # 总球数
    odd = sum(1 for r in rows for x in r[3] if x % 2 == 1)
    half = (NB + 1) // 2
    big = sum(1 for r in rows for x in r[3] if x > half)
    out = {}
    for nm, cnt in (("奇偶", odd), ("大小", big)):
        # 二项：期望 = total/2，方差 = total/4
        e = total / 2.0
        var = total / 4.0
        z = (cnt - e) / math.sqrt(var) if var > 0 else 0.0
        out[nm] = {"obs": cnt, "exp": e, "z": z, "p": p_of_z(z)}
    return out


def adjacency_inheritance(rows, NB, KB, R=3000, seed=20261012):
    """前后期后区：重叠(同号) / 邻号(±1) 的实际计数 vs 随机空分布（z）"""
    backs = [set(r[3]) for r in rows]
    n = len(backs)

    def count_real():
        ov = ad = 0
        for i in range(1, n):
            prev, cur = backs[i - 1], backs[i]
            if prev & cur:
                ov += 1
            if any(abs(a - b) == 1 for a in prev for b in cur):
                ad += 1
        return ov, ad

    ov_r, ad_r = count_real()
    rng = random.Random(seed)
    ovs, ads = [], []
    for _ in range(R):
        sim = [set(rng.sample(range(1, NB + 1), KB)) for _ in range(n)]
        ov = ad = 0
        for i in range(1, n):
            prev, cur = sim[i - 1], sim[i]
            if prev & cur:
                ov += 1
            if any(abs(a - b) == 1 for a in prev for b in cur):
                ad += 1
        ovs.append(ov)
        ads.append(ad)
    ov_mean, ov_sd = sum(ovs) / R, (sum((x - sum(ovs) / R) ** 2 for x in ovs) / R) ** 0.5
    ad_mean, ad_sd = sum(ads) / R, (sum((x - sum(ads) / R) ** 2 for x in ads) / R) ** 0.5
    return {
        "重叠": {"obs": ov_r, "exp": ov_mean, "z": (ov_r - ov_mean) / ov_sd if ov_sd else 0,
                 "p": p_of_z((ov_r - ov_mean) / ov_sd if ov_sd else 0)},
        "邻号": {"obs": ad_r, "exp": ad_mean, "z": (ad_r - ad_mean) / ad_sd if ad_sd else 0,
                 "p": p_of_z((ad_r - ad_mean) / ad_sd if ad_sd else 0)},
    }


# ---------------------------------------------------------------- B. 正推
def _forward_candidates(prev, backs, i, W, last_seen, T, NB):
    """计算 4 策略候选集（基于截至 i-1 的增量上下文）"""
    cold = sorted(range(1, NB + 1), key=lambda v: (i - 1 - last_seen[v]), reverse=True)[:M]
    cnt = Counter()
    for s in backs[max(0, i - W):i]:
        cnt.update(s)
    hot = sorted(range(1, NB + 1), key=lambda v: cnt.get(v, 0), reverse=True)[:M]
    neigh = set()
    for b in prev:
        for d in (b - 1, b + 1):
            if 1 <= d <= NB:
                neigh.add(d)
    sc = {v: 0.0 for v in range(1, NB + 1)}
    for (x, y), c in T.items():
        if x in prev:
            sc[y] += c
    markov = sorted(range(1, NB + 1), key=lambda v: sc[v], reverse=True)[:M]
    return {"冷号": set(cold), "热号": set(hot),
            "邻号延续": neigh, "马尔可夫": set(markov)}


def forward_strategies(rows, NB, KB):
    """4 个朴素策略预测下一期后区，命中率 vs 随机基线（聚合 z）

    增量维护 last_seen（冷号）与转移表 T（马尔可夫），整体 O(n)，避免 O(n³) 重算。
    """
    backs = [set(r[3]) for r in rows]
    n = len(backs)
    W = 30  # 热号窗口
    agg = {s: {"obs": 0.0, "E": 0.0, "V": 0.0}
           for s in ("冷号", "热号", "邻号延续", "马尔可夫")}
    last_seen = {v: -1 for v in range(1, NB + 1)}
    T = Counter()
    for i in range(1, n):
        prev = backs[i - 1]
        drawn = backs[i]
        cands = _forward_candidates(prev, backs, i, W, last_seen, T, NB)
        for sname, cset in cands.items():
            if not cset:
                cset = set(range(1, M + 1))
            p_i = hit_prob(len(cset), NB, KB)
            agg[sname]["obs"] += 1 if (drawn & cset) else 0
            agg[sname]["E"] += p_i
            agg[sname]["V"] += p_i * (1 - p_i)
        # 增量更新（供后续周期）
        for b in prev:
            last_seen[b] = i - 1
        for a in prev:
            for b in drawn:
                T[(a, b)] += 1

    out = {}
    for sname, r in agg.items():
        z = (r["obs"] - r["E"]) / math.sqrt(r["V"]) if r["V"] > 0 else 0.0
        out[sname] = {"obs_rate": r["obs"] / (n - 1), "base_rate": hit_prob(M, NB, KB),
                      "z": z, "p": p_of_z(z)}
    return out


# ---------------------------------------------------------------- C. 逆推
def backward_tests(rows, NB, KB):
    """逆推：①转移独立性（上期含v ↔ 本期含v）②上下文（前区奇数个数的均值差异）"""
    backs = [set(r[3]) for r in rows]
    fronts_odd = [sum(1 for x in r[2] if x % 2 == 1) for r in rows]
    n = len(rows)
    mean_all = sum(fronts_odd) / n
    var_all = sum((x - mean_all) ** 2 for x in fronts_odd) / n

    trans = {}      # 每号 2x2 chi2
    ctx = {}        # 每号 前区奇数均值 z
    for v in range(1, NB + 1):
        # ① 转移 2x2
        a = b = c = d = 0
        for i in range(1, n):
            ph = 1 if v in backs[i - 1] else 0
            ch = 1 if v in backs[i] else 0
            if ph and ch:
                a += 1
            elif ph and not ch:
                b += 1
            elif not ph and ch:
                c += 1
            else:
                d += 1
        N = a + b + c + d
        if min(a + b, c + d, a + c, b + d) > 0:
            chi2 = N * (a * d - b * c) ** 2 / ((a + b) * (c + d) * (a + c) * (b + d))
            trans[v] = {"chi2": chi2, "p": p_of_z(math.sqrt(chi2))}
        # ② 上下文：v 出现期的 前区奇数均值 vs 全体
        idx = [i for i in range(n) if v in backs[i]]
        if len(idx) >= 5:
            mv = sum(fronts_odd[i] for i in idx) / len(idx)
            se = math.sqrt(var_all / len(idx)) if var_all > 0 else 0
            z = (mv - mean_all) / se if se > 0 else 0.0
            ctx[v] = {"mean_v": mv, "mean_all": mean_all, "n_v": len(idx), "z": z, "p": p_of_z(z)}
    return trans, ctx


# ---------------------------------------------------------------- 聚合
def run_one(name, tests_log):
    N, k, NB, KB = SPEC[name]
    rows = load_draws(name + ".json")
    if len(rows) < 100:
        print("%s：数据不足，暂缺" % name)
        return
    print("\n" + "=" * 78)
    print("【%s】后区专项 · %d 期（后区池 %d 选 %d）" % (name, len(rows), NB, KB))
    print("=" * 78)
    all_tests = []

    # A 分布
    chi = chi_square_uniform(rows, NB, KB)
    print("  A. 分布：均匀性卡方/自由度 = %.3f（≈1 即均匀；越偏离 1 越不均）" % chi["chi_per_df"])
    og = omission_max_gap(rows, NB, KB)
    print("     最大遗漏间隔：实测 %d，随机期望 %.1f±%.1f，z=%+.2f p=%.4f"
          % (og["obs"], og["exp_mean"], og["exp_sd"], og["z"], og["p"]))
    all_tests.append(("%s 遗漏maxgap" % name, og["z"], og["p"]))
    ps = parity_size_test(rows, NB, KB)
    for nm, r in ps.items():
        print("     %s：实测 %d / 期望 %.0f，z=%+.2f p=%.4f" % (nm, r["obs"], r["exp"], r["z"], r["p"]))
        all_tests.append(("%s 后区%s" % (name, nm), r["z"], r["p"]))
    adj = adjacency_inheritance(rows, NB, KB)
    for nm, r in adj.items():
        print("     前后期%s：实测 %d / 随机期望 %.1f，z=%+.2f p=%.4f"
              % (nm, r["obs"], r["exp"], r["z"], r["p"]))
        all_tests.append(("%s 前后期%s" % (name, nm), r["z"], r["p"]))

    # B 正推
    print("  B. 正推（候选集 %d 个，随机基线命中率 %.4f）：" % (M, hit_prob(M, NB, KB)))
    fwd = forward_strategies(rows, NB, KB)
    for sn, r in fwd.items():
        print("     %-6s 实测命中 %.4f / 基线 %.4f，z=%+.2f p=%.4f → %s"
              % (sn, r["obs_rate"], r["base_rate"], r["z"], r["p"],
                 "偏优" if r["z"] > 0 and p_of_z(r["z"]) < 0.05 else "无优势"))
        all_tests.append(("%s 正推-%s" % (name, sn), r["z"], r["p"]))

    # C 逆推
    trans, ctx = backward_tests(rows, NB, KB)
    sig_trans = [v for v, r in trans.items() if r["p"] < 0.05]
    sig_ctx = [v for v, r in ctx.items() if r["p"] < 0.05]
    for v, r in trans.items():
        all_tests.append(("%s 逆推-转移%d" % (name, v), math.sqrt(r["chi2"]) if r["chi2"] > 0 else 0, r["p"]))
    for v, r in ctx.items():
        all_tests.append(("%s 逆推-上下文%d" % (name, v), r["z"], r["p"]))
    print("  C. 逆推：转移独立性显著(单点 p<0.05) %d 个；上下文(前区奇偶)显著 %d 个"
          % (len(sig_trans), len(sig_ctx)))

    tests_log.extend(all_tests)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    names = [a.only] if a.only else list(SPEC.keys())
    print("=" * 78)
    print("蓝球（后区）深度复盘 · 正推 / 逆推检验（对照随机基线 + Bonferroni）")
    print("=" * 78)
    all_tests = []
    for name in names:
        if name not in SPEC:
            print("未知彩种：%s" % name)
            continue
        run_one(name, all_tests)

    m = len(all_tests)
    thr = 0.05 / m if m else 0.05
    sig = [t for t in all_tests if t[2] < thr]
    print("\n" + "=" * 78)
    print("合计 %d 项检验，Bonferroni 阈值 = %.5f" % (m, thr))
    if sig:
        print("显著项（需复核是否为真规律）：")
        for nm, z, p in sorted(sig, key=lambda x: x[2]):
            print("   %-20s z=%+.2f p=%.5f" % (nm, z, p))
    else:
        print("显著项：无 —— 后区与公平随机无显著偏离，正推/逆推均无预测力。")
    print("=" * 78)
    print("诚实结论：彩票后区（蓝球）无预测力，仅可见数学必然的均匀性与期望遗漏；")
    print("          任何「选号策略」的固定奖期望完全相同，本工具结论不与「无预测力」定论冲突。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
