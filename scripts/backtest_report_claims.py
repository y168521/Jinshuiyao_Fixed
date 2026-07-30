# -*- coding: utf-8 -*-
"""审查外部模型报告的"已验证有效"claims —— 用真实开奖数据做基准对照。

针对用户提交的《天枢·穹武审查系统》42种方法/6条通用规律报告，挑出可编程的
核心主张，逐条计算"真实数据表现 vs 随机基准/理论概率"，证伪或证实。

结论若 表现≈基准 → 该"规律"零信息量（幸存者偏差/事后归因）。
纯离线、独立进程，不碰运行中的 server。
"""
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from models.lottery_data import Data  # noqa: E402


def _digits(rec):
    """解析 3D/排三 开奖三位。兼容 '02,05,04'(零填充逗号) 与 '520'(拼接) 两种格式。"""
    s = str(rec.get("nums", "") or "")
    toks = re.findall(r"\d+", s)
    if len(toks) >= 3:
        return [int(t) for t in toks[:3]]
    if len(toks) == 1 and len(toks[0]) >= 3:
        return [int(c) for c in toks[0][:3]]
    return None


def _pattern(ds):
    """3D 形态：组六(3不同) / 组三(2同) / 豹子(3同)。"""
    c = Counter(ds)
    if len(c) == 3:
        return "组六"
    if len(c) == 1:
        return "豹子"
    return "组三"


def claim_zusan_then_zuliu(records, k=2):
    """主张：'福彩3D组三密集后必开组六'。
    检验：P(组六) 总体 vs P(组六 | 前 k 期连续组三)。若接近→零信息量。
    """
    seq = [_pattern(d) for d in (_digits(r) for r in records) if d]
    n = len(seq)
    zuliu_total = sum(1 for p in seq if p == "组六")
    p_base = zuliu_total / n if n else 0
    cond_hit = cond_n = 0
    for i in range(k, n):
        if all(seq[i - j - 1] == "组三" for j in range(k)):
            cond_n += 1
            if seq[i] == "组六":
                cond_hit += 1
    p_cond = cond_hit / cond_n if cond_n else 0
    return {
        "claim": f"组三连续{k}期后必开组六",
        "P_组六_总体": round(p_base, 4),
        "P_组六_理论": 0.72,
        "P_组六_条件": round(p_cond, 4),
        "条件样本数": cond_n,
        "样本总数": n,
        "结论": ("零信息量：条件概率≈总体≈72%理论值，'组三后开组六'只是组六本身占比高"
                if abs(p_cond - p_base) < 0.1 else
                f"条件概率{p_cond:.1%}与总体{p_base:.1%}有差异，需更大样本复核"),
    }


def claim_cold_digit_base_rate():
    """主张：'冷号回补命中率87.5%(7/8)'。给出单个数字在一期3D出现的理论基准。"""
    p_appear = 1 - (0.9 ** 3)  # 某指定数字出现在3位中至少1次
    return {
        "claim": "冷号补位命中率 7/8=87.5%",
        "单数字出现理论基准": round(p_appear, 4),
        "样本量": 8,
        "95%置信区间(7/8)": "约 47%~99.7%（威尔逊区间，n=8 极宽）",
        "结论": ("n=8 极小样本、无样本外、无'所有冷补尝试'分母；单个数字每期本就有 27% 概率出现，"
                "7/8 属可被随机+挑样本轻易复现的幻觉，不能称'已验证有效'"),
    }


def claim_pool_coverage(records, pool, mode="组六"):
    """主张：'高频池{0,2,5,8,9}全中'。检验固定池覆盖开奖的真实频率 vs 理论/随机池均值。"""
    pool = set(pool)
    draws = [d for d in (_digits(r) for r in records) if d]
    target = [d for d in draws if _pattern(d) == mode]
    covered = sum(1 for d in target if set(d) <= pool)
    emp = covered / len(target) if target else 0
    # 理论：固定 m 码池覆盖一个"3不同"开奖 = (m/10)(m-1/9)(m-2/8)
    m = len(pool)
    theo = (m / 10) * ((m - 1) / 9) * ((m - 2) / 8) if m >= 3 else 0
    return {
        "claim": f"固定池{sorted(pool)}({m}码)覆盖{mode}开奖",
        "真实覆盖率": round(emp, 4),
        "理论/随机池均值": round(theo, 4),
        f"{mode}开奖样本": len(target),
        "命中数": covered,
        "结论": ("真实覆盖率≈理论随机池均值→固定高频池无超额能力，两次中奖是事后挑样本"
                if abs(emp - theo) < 0.05 else
                f"真实{emp:.1%} vs 理论{theo:.1%} 有偏离，需复核是否数据窗口选择偏差"),
    }


def main():
    print("=" * 70)
    print("外部模型报告 claims 真实数据审查")
    print("=" * 70)
    tests = {}

    d3 = Data.load("福彩3D") or []
    p3 = Data.load("排列三") or []
    print(f"福彩3D 历史={len(d3)} 期，排列三 历史={len(p3)} 期\n")

    r1 = claim_zusan_then_zuliu(d3, k=2)
    tests["组三后必开组六"] = r1
    print(f"[1] {r1['claim']}")
    print(f"    P(组六)总体={r1['P_组六_总体']:.1%} 理论={r1['P_组六_理论']:.0%} "
          f"条件={r1['P_组六_条件']:.1%} (条件样本 {r1['条件样本数']})")
    print(f"    => {r1['结论']}\n")

    r2 = claim_cold_digit_base_rate()
    tests["冷号补位87.5%"] = r2
    print(f"[2] {r2['claim']}")
    print(f"    单数字出现理论基准={r2['单数字出现理论基准']:.1%} 置信区间={r2['95%置信区间(7/8)']}")
    print(f"    => {r2['结论']}\n")

    r3 = claim_pool_coverage(d3, [0, 2, 5, 8, 9], "组六")
    tests["高频池052890覆盖3D"] = r3
    print(f"[3] {r3['claim']}")
    print(f"    真实覆盖率={r3['真实覆盖率']:.1%} 理论随机池均值={r3['理论/随机池均值']:.1%} "
          f"(组六样本 {r3['组六开奖样本']})")
    print(f"    => {r3['结论']}\n")

    r4 = claim_pool_coverage(p3, [2, 4, 5, 9], "组六")
    tests["4码池2459覆盖排三"] = r4
    print(f"[4] {r4['claim']}")
    print(f"    真实覆盖率={r4['真实覆盖率']:.1%} 理论随机池均值={r4['理论/随机池均值']:.1%} "
          f"(组六样本 {r4['组六开奖样本']})")
    print(f"    => {r4['结论']}\n")

    import json
    ts = __import__("time").strftime("%Y%m%d_%H%M%S")
    path = os.path.join(ROOT, "金水谣数据", "backtest_results", f"report_claims_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tests, f, ensure_ascii=False, indent=2)
    print(f"已写出: {path}")
    return tests


if __name__ == "__main__":
    main()
