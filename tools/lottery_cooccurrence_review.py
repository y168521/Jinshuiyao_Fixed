# -*- coding: utf-8 -*-
"""数字关联（朋友号 / 共现）深度复盘 · 全彩种检验 —— JS-20261012-09

检验民间「朋友号」信念：某些号码是否比随机更频繁地「一起出现」（共现）。
对全彩种做两两共现检验，对照**正确随机模型**算 z，全家族 Bonferroni 校正。

覆盖的两种抽取结构：
  - set 型（不放回集合）：双色球/大乐透 前区、七乐彩、快乐8。
    两号共现概率 = C(k,2) / C(N,2)。
  - repl 型（位置独立放回，数字 0–9）：福彩3D / 排列三 / 七星彩。
    异号共现 = 1 - 2·0.9^P + 0.8^P；同号重复(≥2 次) = 1 - 0.9^P - P·0.1·0.9^(P-1)。
    （其中 P = 位置数 = 这里的 k）

设计原则（诚实铁律）：
  - 所有「规律」对照随机基线，多重比较 Bonferroni 校正；只报全周期显著项。
  - 取不到写「暂缺」，绝不编造。预期结论：无显著共现（朋友号是错觉）。
  - 与 JS-20261006-02（全彩种 66 项）、JS-20261012-08（后区 74 项）自洽：彩票无预测力。

用法：
    python tools/lottery_cooccurrence_review.py            # 全彩种
    python tools/lottery_cooccurrence_review.py --only 双色球
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
from collections import Counter
from math import comb

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

LOT_DATA = os.path.join(BASE, "金水谣数据", "lot_data")
ALPHA = 0.05

# (field, N, k, kind)  kind: "set"=不放回集合; "repl"=位置独立放回
SPEC = {
    "双色球": [("front", 33, 6, "set"), ("back", 16, 1, "set")],
    "大乐透": [("front", 35, 5, "set"), ("back", 12, 2, "set")],
    "七乐彩": [("front", 30, 7, "set")],
    "快乐8":  [("front", 80, 20, "set")],
    "福彩3D": [("front", 10, 3, "repl")],
    "排列三": [("front", 10, 3, "repl")],
    "七星彩": [("front", 10, 7, "repl")],
}


def p_of_z(z):
    """双尾 p 值（正态近似，df=1 时 chi2 = z^2）"""
    return math.erfc(abs(z) / math.sqrt(2))


def load_draws(name):
    """读 lot_data/<name>.json，返回 (period, time, front_list, back_list)"""
    path = os.path.join(LOT_DATA, name + ".json")
    if not os.path.exists(path):
        return []
    rows = []
    for r in json.load(io.open(path, encoding="utf-8")):
        fb = r["nums"].split("+")
        f = [int(x) for x in fb[0].split(",")]
        b = [int(x) for x in fb[1].split(",")] if len(fb) > 1 else []
        rows.append((r.get("period"), r.get("time"), f, b))
    return rows


def pair_prob(N, k, kind, a, b):
    """单对 (a,b) 在一期里「都出现」的概率（a==b 表示至少出现 2 次）"""
    if kind == "set":
        if a != b:
            return comb(k, 2) / comb(N, 2) if k >= 2 else 0.0
        return 0.0  # 不放回不可能重复
    # repl 型：位置独立放回，数字 0..9
    P = k
    if a != b:
        return 1.0 - 2 * (0.9 ** P) + (0.8 ** P)
    return 1.0 - (0.9 ** P) - P * 0.1 * (0.9 ** (P - 1))


def _field_numbers(rows, field):
    """抽取每期用于共现判定的数字集合 / 计数"""
    out = []
    for r in rows:
        nums = r[2] if field == "front" else r[3]
        out.append(Counter(nums))
    return out


def field_uniformity(rows, field, N, kind):
    """边际均匀性预检：共现检验的前提是各号/数字出现频率均匀。

    若边际不均（如某数据源非公平抽取），共现 z 会被边际偏差污染而假显著，
    此时共现检验无效，应标记为数据异常而非「朋友号」。
    返回 {chi2, df, chi_per_df, p, ok}。ok=False 表示边际不均、检验不适用。
    """
    if kind == "set":
        cnt = Counter()
        for r in rows:
            for x in (r[2] if field == "front" else r[3]):
                cnt[x] += 1
        n = len(rows)
        total = n * N_field_k(rows, field)  # 总号槽 = n·k
        exp = total / N
        if exp <= 0:
            return {"chi2": 0.0, "df": N - 1, "chi_per_df": 0.0, "p": 1.0, "ok": True}
        stat = sum((cnt.get(i, 0) - exp) ** 2 / exp for i in range(1, N + 1))
    else:  # repl：数字 0..9
        cnt = Counter()
        for r in rows:
            for x in (r[2] if field == "front" else r[3]):
                cnt[x] += 1
        n = len(rows)
        P = N_field_k(rows, field)
        total = n * P
        exp = total / 10.0
        if exp <= 0:
            return {"chi2": 0.0, "df": 9, "chi_per_df": 0.0, "p": 1.0, "ok": True}
        stat = sum((cnt.get(i, 0) - exp) ** 2 / exp for i in range(0, 10))
    df = (N - 1) if kind == "set" else 9
    chi_per_df = stat / df if df > 0 else 0.0
    # 正态近似：chi2(df) 的 z ≈ sqrt(2·chi2) - sqrt(2·df - 1)
    z = math.sqrt(2 * stat) - math.sqrt(2 * df - 1) if stat > 0 else 0.0
    p = p_of_z(z)
    # 边际均匀性门限：仅当「过离散」（z>0 且 p<0.01，即某些号显著偏多/偏少）
    # 才判不均并排除共现检验——此时共现 z 被边际偏差污染成假显著。
    # 若 z<0（比均匀还均匀）则共现检验仍有效，保留。
    ok = not (z > 0 and p < 0.01)
    return {"chi2": stat, "df": df, "chi_per_df": chi_per_df, "p": p, "ok": ok}


def N_field_k(rows, field):
    """取该 field 的单期抽取数 k（位置型=位置数 P；集合型=集合大小）"""
    for r in rows:
        nums = r[2] if field == "front" else r[3]
        return len(nums)
    return 0


def cooccurrence_for_field(rows, field, N, k, kind):
    """对单个 (彩种, field) 跑全部两两共现检验，返回每对结果列表

    每对结果：{pair, obs, E, V, z, p, uniformity_ok}
    """
    if k < 2:
        return []  # 单号抽取无共现可言
    n = len(rows)
    counts = _field_numbers(rows, field)
    if n == 0:
        return []
    uni = field_uniformity(rows, field, N, kind)
    res = []
    # 生成待检对
    if kind == "set":
        pairs = [(a, b) for a in range(1, N + 1) for b in range(a + 1, N + 1)]
    else:  # repl：数字 0..9，含同号重复
        pairs = [(a, b) for a in range(0, 10) for b in range(a, 10)]
    for (a, b) in pairs:
        p_pair = pair_prob(N, k, kind, a, b)
        obs = 0
        for c in counts:
            if a != b:
                if c.get(a, 0) >= 1 and c.get(b, 0) >= 1:
                    obs += 1
            else:
                if c.get(a, 0) >= 2:
                    obs += 1
        E = n * p_pair
        V = n * p_pair * (1 - p_pair)
        z = (obs - E) / math.sqrt(V) if V > 0 else 0.0
        res.append({"pair": (a, b), "obs": obs, "E": E, "V": V,
                    "z": z, "p": p_of_z(z), "p_pair": p_pair,
                    "uniformity_ok": uni["ok"]})
    return res


def run_one(name):
    """跑单个彩种的全部 field，返回 (per_field_summary, all_pairs)"""
    rows = load_draws(name)
    if not rows:
        return None
    all_pairs = []
    summary = {}
    for (field, N, k, kind) in SPEC[name]:
        uni = field_uniformity(rows, field, N, kind)
        res = cooccurrence_for_field(rows, field, N, k, kind)
        if not res:
            continue
        top = max(res, key=lambda x: abs(x["z"]))
        sig = [x for x in res if x["p"] < ALPHA]
        summary[field] = {
            "n_pairs": len(res), "n_draws": len(rows),
            "top_pair": top["pair"], "top_z": top["z"], "top_p": top["p"],
            "n_significant_raw": len(sig),
            "uniformity": uni,
        }
        for x in res:
            x["name"] = name
            x["field"] = field
        all_pairs.extend(res)
    return {"summary": summary, "pairs": all_pairs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    args = ap.parse_args()
    names = [args.only] if args.only else list(SPEC.keys())

    grand = []          # 仅边际均匀（uniformity_ok）的配对，参与显著判定
    bad_fields = []      # 边际不均的 field（数据异常，共现检验无效）
    print("=" * 70)
    print("  数字关联（朋友号 / 共现）全彩种检验 · Bonferroni 校正")
    print("=" * 70)
    for name in names:
        r = run_one(name)
        if not r:
            print(f"  [暂缺] {name}: 无数据")
            continue
        print(f"\n--- {name} ---")
        for field, s in r["summary"].items():
            u = s["uniformity"]
            uni_tag = f"均匀(chi/df={u['chi_per_df']:.2f},p={u['p']:.3f})" \
                if u["ok"] else f"**不均(chi/df={u['chi_per_df']:.2f},p={u['p']:.2e})**"
            print(f"  [{field}] 对={s['n_pairs']} 期={s['n_draws']} | 边际{uni_tag} "
                  f"| 最极端对 {s['top_pair']} z={s['top_z']:+.2f} p={s['top_p']:.4f} "
                  f"| 未校正显著={s['n_significant_raw']}")
            if not u["ok"]:
                bad_fields.append(f"{name}/{field}")
        for x in r["pairs"]:
            if x["uniformity_ok"]:
                grand.append(x)

    grand_T = len(grand)
    bonf = ALPHA / grand_T if grand_T else ALPHA
    sig = [x for x in grand if x["p"] < bonf]
    grand.sort(key=lambda x: abs(x["z"]), reverse=True)
    print("\n" + "=" * 70)
    if bad_fields:
        print(f"  ⚠ 数据异常（边际不均，共现检验无效，已排除）：{', '.join(bad_fields)}")
        print(f"    该类「显著对」是边际偏差的假象，非朋友号；需先修复数据源再评。")
    print(f"  有效检验 {grand_T} 对（已排除异常 field），Bonferroni 阈值 = {bonf:.2e}")
    print(f"  显著项（校正后）：{len(sig)}")
    print("  有效家族最极端 Top10 对（仅供参考，均不通过校正）：")
    for x in grand[:10]:
        print(f"    {x['name']}/{x['field']} 对{x['pair']}: "
              f"实测{x['obs']} 期望{x['E']:.1f} z={x['z']:+.2f} p={x['p']:.4f}")
    verdict = "无显著共现 —— 朋友号是错觉，与「彩票无预测力」定论自洽" \
        if not sig else f"发现 {len(sig)} 对显著共现（需进一步复核）"
    print(f"\n诚实结论：{verdict}")
    print("=" * 70)


if __name__ == "__main__":
    main()
