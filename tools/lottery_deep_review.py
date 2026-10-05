# -*- coding: utf-8 -*-
"""彩票深度复盘工具（常驻） —— JS-20261006-02

用途（两块，互不干扰，均只读、不改任何业务数据）：
  1) 全彩种「民间规律」检验：重号 / ±1 邻号 / ±1~±5 偏移谱 / 号码均匀性卡方 /
     和值 lag-1 自相关。对照**随机基线**算 z 与 p，并做 Bonferroni 多重比较校正。
  2) 系统历史预测复盘：predictions.json 逐条对照，按「玩法结构」算**理论中奖概率**
     （蒙特卡洛，与 judge_prize 同口径），再比实际中奖率，定位命中率根因。

设计原则（诚实铁律）：
  - 只报「全周期统计显著」的结论，不报小样本（如近 30 期）里看起来成立的偶然模式。
  - 理论概率走蒙特卡洛并**与 judge_prize 交叉验证**，避免口径漂移造成假结论。
  - 取不到的写「暂缺」，绝不编造。

用法：
    python tools/lottery_deep_review.py              # 全量
    python tools/lottery_deep_review.py --patterns   # 只跑规律检验
    python tools/lottery_deep_review.py --predict    # 只跑预测复盘
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from math import comb

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

LOT_DATA = os.path.join(BASE, "金水谣数据", "lot_data")
PRED_FILE = os.path.join(BASE, "金水谣数据", "predictions.json")

# 彩种参数：(前区号码池 N, 前区选号数 k, 后区池, 后区选号数)。位置型彩种单列。
SPEC = {
    "大乐透": (35, 5, 12, 2),
    "双色球": (33, 6, 16, 1),
    "七乐彩": (30, 7, 0, 0),
    "快乐8": (80, 20, 0, 0),
}


def p_of_z(z):
    """双尾 p 值（正态近似）"""
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
        rows.append((r["period"], r["time"], f, b))
    return rows


# ---------------------------------------------------------------- 规律检验
def offset_test(rows, N, k, max_off=5, field="front"):
    """本期号命中「上期号 +o」的个数 vs 超几何期望。返回 {o: {obs,exp,z,p}}"""
    res = {}
    idx = 2 if field == "front" else 3
    pairs = [(rows[i][idx], rows[i + 1][idx]) for i in range(len(rows) - 1)]
    for o in range(-max_off, max_off + 1):
        T = E = V = 0.0
        for prev, cur in pairs:
            S = {x + o for x in prev if 1 <= x + o <= N}
            K = len(S)
            if K == 0:
                continue
            T += len(set(cur) & S)
            p = K / N
            E += k * p
            V += k * p * (1 - p) * (N - k) / (N - 1)
        z = (T - E) / math.sqrt(V) if V > 0 else 0.0
        res[o] = {"obs": T, "exp": E, "z": z, "p": p_of_z(z)}
    return res, len(pairs)


def chi_square_uniform(rows, N, k, field="front"):
    """号码出现频次卡方均匀性检验

    ⚠️ 方差必须用**二项**方差 n·p·(1-p)，不能用泊松方差 exp：
    每期是从 N 个号里无放回抽 k 个，单个号码在每期最多出现 1 次，
    其出现次数服从 Binomial(n期数, p=k/N)，方差 = n·p·(1-p) < 期望值。
    若误用泊松方差（=期望），卡方会被系统性低估、chi/df 假性远小于 1，
    看起来像「比随机还均匀」——那是计算错误，不是发现。
    """
    idx = 2 if field == "front" else 3
    cnt = Counter()
    for r in rows:
        for x in r[idx]:
            cnt[x] += 1
    n = len(rows)
    p = k / N
    exp = n * p
    var = n * p * (1 - p)
    if var <= 0:
        return {"stat": 0.0, "df": N - 1, "chi_per_df": 0.0}
    stat = sum((cnt.get(i, 0) - exp) ** 2 / var for i in range(1, N + 1))
    df = N - 1
    return {"stat": stat, "df": df, "chi_per_df": stat / df}


def sum_autocorr(rows, field="front"):
    """和值序列 lag-1 自相关"""
    idx = 2 if field == "front" else 3
    s = [sum(r[idx]) for r in rows]
    n = len(s)
    if n < 10:
        return 0.0
    m = sum(s) / n
    num = sum((s[i] - m) * (s[i + 1] - m) for i in range(n - 1))
    den = sum((x - m) ** 2 for x in s)
    return num / den if den > 0 else 0.0


def run_patterns():
    print("=" * 78)
    print("【一】全彩种规律检验（对照随机基线，Bonferroni 校正）")
    print("=" * 78)
    all_tests = []
    for name in ("大乐透", "双色球", "七乐彩", "快乐8"):
        rows = load_draws(name + ".json")
        if len(rows) < 100:
            print("%s：数据不足，暂缺" % name)
            continue
        N, k, NB, KB = SPEC[name]
        print("\n--- %s（%d 期，%s ~ %s）---" % (name, len(rows), rows[0][1], rows[-1][1]))
        spec, ntr = offset_test(rows, N, k, 5, "front")
        print("  偏移谱（前区，%d 个转换）：o=0 为重号，±1 为邻号" % ntr)
        for o in sorted(spec):
            s = spec[o]
            all_tests.append(("%s 前区%+.d" % (name, o), s["z"], s["p"]))
            if abs(s["z"]) >= 1.5 or o in (-1, 0, 1):
                print("    %+d  实际 %5.0f  期望 %6.1f  z=%+.2f  p=%.4f" % (
                    o, s["obs"], s["exp"], s["z"], s["p"]))
        if NB:
            spec_b, _ = offset_test(rows, NB, KB, 5, "back")
            print("  后区（%d 选 %d）：" % (NB, KB))
            for o in sorted(spec_b):
                s = spec_b[o]
                all_tests.append(("%s 后区%+.d" % (name, o), s["z"], s["p"]))
                if abs(s["z"]) >= 1.5 or o == 0:
                    print("    %+d  实际 %5.0f  期望 %6.1f  z=%+.2f  p=%.4f" % (
                        o, s["obs"], s["exp"], s["z"], s["p"]))
        chi = chi_square_uniform(rows, N, k, "front")
        ac = sum_autocorr(rows, "front")
        print("  号码均匀性卡方/自由度 = %.3f（越接近 1 越均匀）" % chi["chi_per_df"])
        print("  和值 lag-1 自相关 = %+.4f（|.| > %.3f 才算显著）" % (ac, 2 / math.sqrt(len(rows))))
    m = len(all_tests)
    thr = 0.05 / m if m else 0.05
    sig = [t for t in all_tests if t[2] < thr]
    print("\n" + "=" * 78)
    print("合计 %d 项检验，Bonferroni 阈值 = %.5f" % (m, thr))
    if sig:
        print("显著项：")
        for nm, z, p in sorted(sig, key=lambda x: x[2]):
            print("   %-16s z=%+.2f p=%.5f → %s" % (nm, z, p, "偏多" if z > 0 else "偏少"))
    else:
        print("显著项：无 —— 全部与公平随机无显著偏离。")
    print("=" * 78)


# ---------------------------------------------------------------- 预测复盘
def load_rules():
    from utils.lottery_prize import load_rules as _lr
    return _lr()


def tier_of(rules, lot, hf, hb):
    """与 judge_prize 同口径：按 tiers 顺序首匹配（>= 语义）"""
    spec = (rules.get("rules") or {}).get(lot) or {}
    for t in spec.get("tiers", []):
        for cond in t.get("match", []):
            if len(cond) >= 2 and hf >= cond[0] and hb >= cond[1]:
                return t.get("tier")
    return None


def parse_structure(nums, ptype, lot=None):
    """解析预测结构 → (前区胆, 前区拖, 后区胆, 后区拖)

    统一模型（复式视作「胆为空、拖为全部选号」）：
      某注前区命中 = |胆 ∩ 开奖前区| + min(|拖 ∩ 开奖前区|, 需补个数)
    这样无需展开 C(拖,需补) 个组合，O(1) 即可求「最优一注」，避免组合爆炸。
    """
    s = str(nums or "")
    if "胆" in s:
        # 兼容两种写法：
        #   大乐透：[前区胆:20,22 拖:01,04,14,15] [后区胆:06 拖:04,08]
        #   双色球：[胆:04,24]拖:03,07,08,15,27+07,11
        import re
        def _nums(t):
            return [int(x) for x in t.split(",") if x.strip().isdigit()]
        # 两种写法的分隔符不同：大乐透是「胆:.. 拖:..」，双色球是「胆:..]拖:..」
        fm = re.search(r"(?:前区)?胆[:：]([\d,]+)\s*\]?\s*拖[:：]([\d,]*)", s)
        if not fm:
            return None
        fd = _nums(fm.group(1))
        ft = _nums(fm.group(2))
        bd = bt = []
        bm = re.search(r"后区胆[:：]([\d,]+)\s*拖[:：]([\d,]*)", s)
        if bm:
            bd, bt = _nums(bm.group(1)), _nums(bm.group(2))
        else:
            tail = s.split("+", 1)
            if len(tail) > 1:
                bd = _nums(tail[1])
        return (fd, ft, bd, bt)
    if "+" in s:
        a, b = s.split("+", 1)
        front = [int(x) for x in a.split(",") if x.strip()]
        back = [int(x) for x in b.split(",") if x.strip()]
        if len(front) > 5:  # 复式：胆为空，拖为全部
            fd, ft = [], front
        else:  # 单注：全部视作胆（必含）
            fd, ft = front, []
        if len(back) > 2:
            bd, bt = [], back
        else:
            bd, bt = back, []
        return (fd, ft, bd, bt)
    # 无后区彩种（如七乐彩 08,13,14,18,23,24,28）
    parts = [int(x) for x in s.split(",") if x.strip().isdigit()]
    if not parts:
        return None
    k = SPEC.get(lot, (0, 7, 0, 0))[1] if lot else 7
    return ([], parts, [], []) if len(parts) > k else (parts, [], [], [])


def mc_win_prob(lot, struct, N, k, NB, KB, rules, n_sim=50000, seed=12345):
    """蒙特卡洛算该结构的「至少中一个奖级」概率，与 tier_of 同口径"""
    fd, ft, bd, bt = struct
    mf = max(0, k - len(fd))
    mb = max(0, KB - len(bd))
    rng = random.Random(seed)
    sfd, sft, sbd, sbt = set(fd), set(ft), set(bd), set(bt)
    win = 0
    for _ in range(n_sim):
        af = rng.sample(range(1, N + 1), k)
        ab = rng.sample(range(1, NB + 1), KB) if NB else []
        hf = len(sfd.intersection(af)) + min(len(sft.intersection(af)), mf)
        hb = len(sbd.intersection(ab)) + min(len(sbt.intersection(ab)), mb) if NB else 0
        if tier_of(rules, lot, hf, hb):
            win += 1
    return win / n_sim


def run_predictions():
    print()
    print("=" * 78)
    print("【二】系统历史预测复盘（逐条对照，理论概率走蒙特卡洛）")
    print("=" * 78)
    if not os.path.exists(PRED_FILE):
        print("predictions.json 不存在，暂缺")
        return
    preds = json.load(io.open(PRED_FILE, encoding="utf-8"))
    rules = load_rules()
    groups = defaultdict(list)
    skipped = Counter()
    for p in preds:
        if not p.get("reviewed"):
            continue
        lot = p.get("lot")
        if lot not in SPEC:
            skipped[lot + "(非red_blue)"] += 1
            continue
        spec = (rules.get("rules") or {}).get(lot) or {}
        if spec.get("judge") != "red_blue":
            skipped[lot + "(非red_blue)"] += 1
            continue
        st = parse_structure(p.get("nums"), p.get("type"), lot)
        if not st:
            skipped[lot + "(结构解析失败)"] += 1
            continue
        groups[(lot, p.get("type"))].append((p, st))

    print("%-8s %-8s %6s %10s %10s %8s %8s" % (
        "彩种", "玩法", "样本", "实际中奖率", "理论概率", "z", "判定"))
    cache = {}
    for (lot, t), items in sorted(groups.items()):
        if len(items) < 20:
            continue
        N, k, NB, KB = SPEC[lot]
        theo_list = []
        for p, st in items:
            # 结构签名：只看胆/拖的**个数**，同结构共用一次模拟结果
            key = (lot, len(st[0]), len(st[1]), len(st[2]), len(st[3]))
            if key not in cache:
                cache[key] = mc_win_prob(lot, st, N, k, NB, KB, rules)
            theo_list.append(cache[key])
        theo = sum(theo_list) / len(theo_list)
        wins = sum(1 for p, _ in items if p.get("prize_tier"))
        n = len(items)
        rate = wins / n
        se = math.sqrt(theo * (1 - theo) / n) if 0 < theo < 1 else 0
        z = (rate - theo) / se if se > 0 else 0.0
        verdict = "显著偏低" if p_of_z(z) < 0.05 and z < 0 else (
            "显著偏高" if p_of_z(z) < 0.05 and z > 0 else "与理论一致")
        print("%-8s %-8s %6d %9.1f%% %9.1f%% %8.2f %8s" % (
            lot, t, n, 100 * rate, 100 * theo, z, verdict))

    print()
    print("说明：理论概率按每注实际选号结构（单注/复式/胆拖）蒙特卡洛模拟 5 万次得出，")
    print("      奖级判定与 utils/lottery_prize.py::judge_prize 同口径（已做 2000 次交叉自检）。")
    print("      「与理论一致」= 没跑赢也没跑输随机，符合「无预测力」定论。")
    if skipped:
        print("      未纳入（诚实标注，不做猜测）：" + "、".join(
            "%s %d 条" % (k, v) for k, v in sorted(skipped.items())))


def verify_consistency():
    """反证：蒙特卡洛判定 vs judge_prize 真源，抽样 2000 次必须一致"""
    rules = load_rules()
    from utils.lottery_prize import judge_prize
    rng = random.Random(999)
    bad = 0
    for _ in range(2000):
        pf = sorted(rng.sample(range(1, 36), 5))
        pb = sorted(rng.sample(range(1, 13), 2))
        af = sorted(rng.sample(range(1, 36), 5))
        ab = sorted(rng.sample(range(1, 13), 2))
        hf = len(set(pf) & set(af)); hb = len(set(pb) & set(ab))
        mine = tier_of(rules, "大乐透", hf, hb)
        ref = judge_prize("大乐透", "%s+%s" % (
            ",".join("%02d" % x for x in pf), ",".join("%02d" % x for x in pb)),
            "%s+%s" % (",".join("%02d" % x for x in af), ",".join("%02d" % x for x in ab)))
        if mine != ref.get("tier"):
            bad += 1
    print("\n【自检】蒙特卡洛判定 vs judge_prize 真源：2000 次抽样，不一致 %d 次" % bad)
    print("        → %s" % ("一致，口径可靠" if bad == 0 else "不一致！禁止采信本工具结论"))
    return bad == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patterns", action="store_true")
    ap.add_argument("--predict", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    ok = verify_consistency()
    if not ok:
        return 1
    if not a.predict:
        run_patterns()
    if not a.patterns:
        run_predictions()
    return 0


if __name__ == "__main__":
    sys.exit(main())
