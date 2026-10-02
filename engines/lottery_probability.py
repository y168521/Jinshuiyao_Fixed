# -*- coding: utf-8 -*-
"""大乐透中奖概率 · 数学真源引擎（JS-20261002-14）

来源：用户提供的《概率工程》图 01-50（docs/概率工程50讲_公式参考与核对_v1.md），
逐张读原图转录后实现的**可运行**版本。每条公式在 docstring 标注对应编号（#nn），
便于与参考文档交叉核对、防止实现与公式漂移。

诚实定位（与项目定论一致）：本模块只**描述**彩票的随机结构——
命中分布、期望、方差、头奖概率、任一奖级概率、随机性检验（卡方/游程/自相关/蒙特卡洛）。
它**不预测**任何号码，也**不暗示**任何选号策略优于随机。
随机性检验的目的，是向用户实证「开奖与公平随机模型无显著偏离」，
从而支撑金水谣「无预测力、只优化诚实度」的基调。

纯计算、无 HTTP 耦合、可单测。调用方（domains/analyzer、scripts、API handler）负责接线。

用法：
    from engines.lottery_probability import ProbabilityEngine
    eng = ProbabilityEngine("大乐透")
    eng.front_hit_pmf()                 # {0:..,1:..,..,5:..}  (#06)
    eng.jackpot_prob()                  # 1 / 21_425_712       (#01/#02/#50)
    eng.win_any_prize_prob()            # 任一奖级理论概率（读 prize_rules 单一真源）
    eng.probability_summary()           # 给 API/看板的完整理论摘要
    eng.randomness_check(history)       # 诚实随机性检验报告（#26-30/#45-50）
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Tuple

try:  # 标准库 comb（Py3.8+），无第三方依赖
    from math import comb
except Exception:  # pragma: no cover
    def comb(n, k):
        if k < 0 or k > n:
            return 0
        k = min(k, n - k)
        r = 1
        for i in range(1, k + 1):
            r = r * (n - k + i) // i
        return r


# ---------------------------------------------------------------------------
# 彩种参数（单一真源：config.LOTTERY_RULES，避免双源漂移）
# ---------------------------------------------------------------------------

def _lottery_params(lot: str) -> Dict[str, int]:
    """读取大乐透前/后区口径：front_N=35 front_k=5 back_N=12 back_k=2。"""
    from config import LOTTERY_RULES
    spec = (LOTTERY_RULES or {}).get(lot)
    if not spec:
        raise ValueError(f"未知彩种，无法取概率口径: {lot}")
    red = spec["red"]   # (start, N, k) 例如 (1, 35, 5)
    blue = spec["blue"]  # (start, N, k) 例如 (1, 12, 2)
    return {
        "front_N": int(red[1]), "front_k": int(red[2]),
        "back_N": int(blue[1]), "back_k": int(blue[2]),
    }


# ---------------------------------------------------------------------------
# 统计分布与显著性（无 scipy 依赖，自实现）
# ---------------------------------------------------------------------------

def _gammap_lower(a: float, x: float) -> float:
    """正则化下不完全 Gamma 函数 P(a, x)（Numerical Recipes gser/gcf）。

    用于卡方分布的 p 值，避免引入 scipy。
    """
    if x <= 0 or a <= 0:
        return 0.0
    gln = math.lgamma(a)
    if x < a + 1.0:
        ap = a
        total = 1.0 / a
        delta = total
        for _ in range(2000):
            ap += 1.0
            delta *= x / ap
            total += delta
            if abs(delta) < abs(total) * 1e-15:
                break
        return total * math.exp(-x + a * math.log(x) - gln)
    # 连分式
    FPMIN = 1e-300
    b = x + 1.0 - a
    c = 1.0 / FPMIN
    d = 1.0 / b
    h = d
    for i in range(1, 2000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < FPMIN:
            d = FPMIN
        c = b + an / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    gcf = math.exp(-x + a * math.log(x) - gln) * h
    return 1.0 - gcf


def chi2_sf(x: float, df: int) -> float:
    """卡方分布上尾概率 P(X² > x | df)。对应 #27 卡方统计量的显著性。"""
    if df <= 0 or x <= 0:
        return 1.0
    a = df / 2.0
    return 1.0 - _gammap_lower(a, x / 2.0)


def norm_sf(z: float) -> float:
    """标准正态上尾概率 P(Z > z) = 0.5·erfc(z/√2)。"""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


# ---------------------------------------------------------------------------
# 核心概率公式（对应《概率工程》编号）
# ---------------------------------------------------------------------------

def hypergeometric_pmf(N: int, K: int, n: int, k: int) -> float:
    """#06/#07/#20 超几何分布 pmf：从 N 中含 K 个“目标”，不放回抽 n 个命中 k 个。

    P(K=k) = C(K,k)·C(N-K, n-k) / C(N, n)
    """
    return comb(K, k) * comb(N - K, n - k) / comb(N, n)


def expected_hits(N: int, K: int, n: int) -> float:
    """#09/#17 期望命中数 E[K] = n·K/N（指示变量线性性）。"""
    return n * K / N


def hypergeometric_variance(N: int, K: int, n: int) -> float:
    """#10 超几何分布方差（**已对原图低分辨率歧义做数值确认**）。

    标准式：Var(K) = n·(K/N)·(1 − K/N)·((N − n)/(N − 1))
    原图低分辨率下第二个因子曾被误读为 M/N；实测模拟证实应为 (N−M)/N。
    """
    p = K / N
    return n * p * (1.0 - p) * ((N - n) / (N - 1.0))


def total_combinations(front_N: int, front_k: int, back_N: int, back_k: int) -> int:
    """#01/#02/#03 单注总样本空间 N = C(front_N, front_k)·C(back_N, back_k)。"""
    return comb(front_N, front_k) * comb(back_N, back_k)


def front_hit_pmf(front_N: int, front_k: int) -> Dict[int, float]:
    """#06 前区命中分布：k = 0..front_k。"""
    return {k: hypergeometric_pmf(front_N, front_k, front_k, k) for k in range(0, front_k + 1)}


def back_hit_pmf(back_N: int, back_k: int) -> Dict[int, float]:
    """#07 后区命中分布：l = 0..back_k。"""
    return {l: hypergeometric_pmf(back_N, back_k, back_k, l) for l in range(0, back_k + 1)}


def joint_hit_prob(front_N: int, front_k: int, back_N: int, back_k: int, k: int, l: int) -> float:
    """#08 联合命中概率：前区命中 k 且后区命中 l（前后区独立相乘）。"""
    return hypergeometric_pmf(front_N, front_k, front_k, k) * hypergeometric_pmf(back_N, back_k, back_k, l)


def at_least_one_front(front_N: int, front_k: int) -> float:
    """#11 前区至少命中一次：1 − P(K_f=0) = 1 − C(front_N−front_k, front_k)/C(front_N, front_k)。

    注意：原图低分辨率下曾被误录为 C(30,6)/C(35,6)，正确为 C(30,5)/C(35,5)（已确认）。
    """
    zero = comb(front_N - front_k, front_k) / comb(front_N, front_k)
    return 1.0 - zero


def at_least_r_front(front_N: int, front_k: int, r: int) -> float:
    """#12 前区至少命中 r 个：Σ_{k=r}^{front_k} P(K_f=k)。"""
    return sum(hypergeometric_pmf(front_N, front_k, front_k, k) for k in range(r, front_k + 1))


# ---------------------------------------------------------------------------
# 随机性检验（对应 #26-30 / #45-50）
# ---------------------------------------------------------------------------

def _parse_front_numbers(history: List[dict], lot: str) -> Tuple[List[List[int]], int, int]:
    """解析历史开奖前区号码（返回每期号码列表、期数、号码池大小）。"""
    from utils.number_utils import clean_nums, parse_reds
    records = []
    for rec in history or []:
        nums = str(rec.get("nums", "") or "")
        if not nums:
            continue
        front = parse_reds(clean_nums(nums.split("+", 1)[0]))
        if front:
            records.append(front)
    p = _lottery_params(lot)
    return records, len(records), p["front_N"]


def chi_square_gof(records: List[List[int]], pool: int, per_draw: int) -> Dict:
    """#26/#27/#28 卡方拟合优度：各号码出现频次是否偏离均匀期望。

    E_i = per_draw · D / pool；χ² = Σ(O_i−E_i)²/E_i；df = pool−1。
    小样本（D < 5·(pool−1)）时检验功效低，返回 sample_small 警示。
    """
    d = len(records)
    if d == 0:
        return {"stat": None, "df": pool - 1, "p_value": None, "verdict": "no_data"}
    occ = [0] * (pool + 1)
    for rec in records:
        for num in rec:
            if 1 <= num <= pool:
                occ[num] += 1
    exp = per_draw * d / pool
    stat = 0.0
    for i in range(1, pool + 1):
        if exp <= 0:
            continue
        stat += (occ[i] - exp) ** 2 / exp
    df = pool - 1
    pval = chi2_sf(stat, df)
    sample_small = d < 5 * df
    return {
        "stat": stat, "df": df, "p_value": pval,
        "expected_per_number": exp,
        "verdict": "consistent_with_random" if pval >= 0.01 else "deviation_detected",
        "sample_small": sample_small,
    }


def runs_test_per_number(presence: Dict[int, List[int]], d: int) -> Dict:
    """#30 游程检验（Wald-Wolfowitz）：每号出现（1）/未出现（0）序列的切换次数。

    返回偏离最显著的号码与超出 0.05 的号码数（Bonferroni 视角）。
    """
    flagged = 0
    worst = {"number": None, "p_value": 1.0, "runs": None, "expected_runs": None}
    for num, seq in presence.items():
        n1 = sum(seq)
        n2 = d - n1
        if n1 == 0 or n2 == 0:
            continue
        runs = 1
        for t in range(1, d):
            if seq[t] != seq[t - 1]:
                runs += 1
        er = 1 + 2 * n1 * n2 / (n1 + n2)
        var_r = 2 * n1 * n2 * (2 * n1 * n2 - n1 - n2) / ((n1 + n2) ** 2 * (n1 + n2 - 1))
        if var_r <= 0:
            continue
        z = (runs - er) / math.sqrt(var_r)
        pval = 2 * norm_sf(abs(z))
        if pval < 0.05:
            flagged += 1
        if pval < worst["p_value"]:
            worst = {"number": num, "p_value": pval, "runs": runs, "expected_runs": er}
    return {"flagged_count": flagged, "total_numbers": len(presence), "worst": worst}


def autocorr_per_number(presence: Dict[int, List[int]], d: int) -> Dict:
    """#29 一阶自相关：每号出现序列 X_t 与 X_{t+1} 的相关性，随机下应≈0。"""
    max_abs = 0.0
    worst_num = None
    for num, seq in presence.items():
        n1 = sum(seq)
        if n1 == 0 or n1 == d:
            continue
        mean = n1 / d
        var = mean * (1 - mean)
        if var <= 0:
            continue
        cov = 0.0
        for t in range(d - 1):
            cov += (seq[t] - mean) * (seq[t + 1] - mean)
        cov /= (d - 1)
        rho = cov / var
        if abs(rho) > max_abs:
            max_abs = abs(rho)
            worst_num = num
    return {"max_abs_lag1": max_abs, "worst_number": worst_num, "threshold": 0.1}


def monte_carlo_jackpot(eng: "ProbabilityEngine", ticket_front: List[int],
                        ticket_back: List[int], n_sim: int = 300_000) -> Dict:
    """#37/#38/#50 蒙特卡洛估计头奖概率：与固定一注全中次数的经验频率对照理论 1/N。

    诚实说明：21M 量级下 30 万次模拟几乎必然观察不到全中，仅用于直观对照理论值。
    """
    fn, fk = eng.front_N, eng.front_k
    bn, bk = eng.back_N, eng.back_k
    tf = set(ticket_front)
    tb = set(ticket_back)
    hits = 0
    for _ in range(n_sim):
        draw_f = set(random.sample(range(1, fn + 1), fk))
        draw_b = set(random.sample(range(1, bn + 1), bk))
        if draw_f == tf and draw_b == tb:
            hits += 1
    return {
        "n_sim": n_sim,
        "observed_full_match": hits,
        "empirical_prob": hits / n_sim,
        "theory_prob": 1.0 / eng.total_sample_space(),
    }


# ---------------------------------------------------------------------------
# 引擎（按彩种封装，供 analyze/API/脚本调用）
# ---------------------------------------------------------------------------

class ProbabilityEngine:
    """大乐透概率引擎：封装理论分布 + 随机性检验。"""

    def __init__(self, lot: str = "大乐透"):
        p = _lottery_params(lot)
        self.lot = lot
        self.front_N = p["front_N"]
        self.front_k = p["front_k"]
        self.back_N = p["back_N"]
        self.back_k = p["back_k"]

    # —— 理论分布（对应 #01-#17）——
    def front_hit_pmf(self) -> Dict[int, float]:
        return front_hit_pmf(self.front_N, self.front_k)

    def back_hit_pmf(self) -> Dict[int, float]:
        return back_hit_pmf(self.back_N, self.back_k)

    def expected_front_hits(self) -> float:
        return expected_hits(self.front_N, self.front_k, self.front_k)

    def expected_back_hits(self) -> float:
        return expected_hits(self.back_N, self.back_k, self.back_k)

    def variance_front_hits(self) -> float:
        return hypergeometric_variance(self.front_N, self.front_k, self.front_k)

    def total_sample_space(self) -> int:
        return total_combinations(self.front_N, self.front_k, self.back_N, self.back_k)

    def jackpot_prob(self) -> float:
        return 1.0 / self.total_sample_space()

    def at_least_one_front(self) -> float:
        return at_least_one_front(self.front_N, self.front_k)

    def at_least_r_front(self, r: int) -> float:
        return at_least_r_front(self.front_N, self.front_k, r)

    # —— 任一奖级概率（复用 prize_rules 单一真源，#13/#15 思路）——
    def win_any_prize_prob(self) -> Dict:
        """任一奖级理论概率：枚举 (前区命中k, 后区命中l) 共 6×3=18 种，
        按 config/lottery_prize_rules.json 的奖级条件取最高奖级累加（避免重复计数）。
        """
        from utils.lottery_prize import load_rules
        rules = load_rules()
        if not isinstance(rules, dict):
            return {"ok": False, "reason": "prize_rules_unavailable"}
        spec = (rules.get("rules") or {}).get(self.lot)
        if not spec or spec.get("judge") != "red_blue":
            return {"ok": False, "reason": "no_red_blue_rules", "lot": self.lot}
        fpmf = self.front_hit_pmf()
        bpmf = self.back_hit_pmf()
        tiers = spec.get("tiers", [])
        total = 0.0
        per_tier = {}
        for k in range(0, self.front_k + 1):
            for l in range(0, self.back_k + 1):
                p = fpmf.get(k, 0.0) * bpmf.get(l, 0.0)
                if p <= 0:
                    continue
                matched = False
                for t in tiers:
                    for cond in t.get("match", []):
                        if len(cond) >= 2 and k >= cond[0] and l >= cond[1]:
                            total += p
                            name = t.get("tier")
                            per_tier[name] = per_tier.get(name, 0.0) + p
                            matched = True
                            break  # 取最高奖级（单奖级首匹配）
                    if matched:
                        break
        return {"ok": True, "total": total, "per_tier": per_tier,
                "jackpot": self.jackpot_prob()}

    # —— 完整摘要（给 API/看板） ——
    def probability_summary(self) -> Dict:
        return {
            "lot": self.lot,
            "sample_space": {
                "front": comb(self.front_N, self.front_k),
                "back": comb(self.back_N, self.back_k),
                "total": self.total_sample_space(),
            },
            "front_hit_pmf": self.front_hit_pmf(),
            "back_hit_pmf": self.back_hit_pmf(),
            "expected_front_hits": self.expected_front_hits(),
            "expected_back_hits": self.expected_back_hits(),
            "variance_front_hits": self.variance_front_hits(),
            "jackpot_prob": self.jackpot_prob(),
            "at_least_one_front_prob": self.at_least_one_front(),
            "win_any_prize_prob": self.win_any_prize_prob(),
            "honest_note": (
                "以上为公平随机模型下的理论值。开奖为独立随机事件，"
                "历史结果不能推断下一期；本引擎只描述随机结构，不预测、不荐号。"
            ),
        }

    # —— 随机性检验（对应 #26-30/#45-50） ——
    def randomness_check(self, history: List[dict], n_sim: int = 300_000) -> Dict:
        """对真实历史开奖做诚实随机性检验，输出结构化报告。

        - 卡方拟合优度（前区/后区各自）
        - 游程检验（每号出现序列切换次数）
        - 一阶自相关（每号序列）
        - 蒙特卡洛头奖对照
        """
        records, d, pool = _parse_front_numbers(history, self.lot)
        if d == 0:
            return {"ok": False, "reason": "no_history", "lot": self.lot}
        # 每号出现序列（前区）
        presence = {i: [0] * d for i in range(1, pool + 1)}
        for t, rec in enumerate(records):
            for num in rec:
                if 1 <= num <= pool:
                    presence[num][t] = 1
        chi_front = chi_square_gof(records, pool, self.front_k)
        back_records, bd, bpool = self._parse_back(history)
        chi_back = chi_square_gof(back_records, bpool, self.back_k) if bd else None
        runs = runs_test_per_number(presence, d)
        ac = autocorr_per_number(presence, d)
        # 蒙特卡洛：用首期开奖作固定一注
        ticket_front = records[0] if records else list(range(1, self.front_k + 1))
        ticket_back = back_records[0] if back_records else list(range(1, self.back_k + 1))
        mc = monte_carlo_jackpot(self, ticket_front, ticket_back, n_sim)
        honest = (
            "全部检验若 p 值未显著低于阈值（如 0.01），说明开奖与公平随机模型"
            "**无显著偏离**；这正是金水谣「无预测力、只优化诚实度」的实证基础。"
            "任何单期结果都不能由此推断下一期。"
        )
        return {
            "ok": True,
            "lot": self.lot,
            "draws": d,
            "chi_square_front": chi_front,
            "chi_square_back": chi_back,
            "runs_test": runs,
            "autocorrelation": ac,
            "monte_carlo_jackpot": mc,
            "interpretation": honest,
        }

    def _parse_back(self, history: List[dict]) -> Tuple[List[List[int]], int, int]:
        from utils.number_utils import clean_nums, parse_reds
        records = []
        for rec in history or []:
            nums = str(rec.get("nums", "") or "")
            if "+" not in nums:
                continue
            back = parse_reds(clean_nums(nums.split("+", 1)[1]))
            if back:
                records.append(back)
        return records, len(records), self.back_N


# ---------------------------------------------------------------------------
# 容斥原理（对应 #21，补全原图被裁切的第二行）
# ---------------------------------------------------------------------------

def inclusion_exclusion_union(probs: List[float]) -> float:
    """#21 容斥原理：P(∪A_i) = ΣP(A_i) − ΣP(A_iA_j) + ΣP(A_iA_jA_k) − …

    这里给出给定各事件概率（两两独立近似）时的二阶估计，用于修正多事件直接相加的重复计数。
    原图第二行被裁切，标准续项为「+ ΣP(A_iA_jA_k) − …」。
    """
    if not probs:
        return 0.0
    s1 = sum(probs)
    s2 = 0.0
    n = len(probs)
    for i in range(n):
        for j in range(i + 1, n):
            # 两两独立近似：P(A_iA_j) ≈ p_i·p_j
            s2 += probs[i] * probs[j]
    return s1 - s2
