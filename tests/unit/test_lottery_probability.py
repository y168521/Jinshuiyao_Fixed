# -*- coding: utf-8 -*-
"""大乐透概率引擎单元测试（JS-20261002-14）

核对目标：
  1. 闭式数值正确（头奖=1/21425712、前后区 pmf 和为 1、期望/方差）
  2. #10 超几何方差第二因子歧义 —— 用**模拟反证**确认应为 (N−M)/N
  3. 卡方 p 值精度（不依赖 scipy）
  4. 容斥 / 蒙特卡洛 / 随机性检验结构正确
"""
import os
import sys
import math
import random
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from engines.lottery_probability import (
    ProbabilityEngine, hypergeometric_variance, chi2_sf, norm_sf,
    inclusion_exclusion_union, total_combinations,
)

DLT_JACKPOT_DENOM = 324632 * 66  # C(35,5)=324632, C(12,2)=66


def _sim_var(N, K, n, trials=200000, seed=1):
    """模拟不放回抽取 n 个、含 K 个目标的命中数方差（总体方差）。"""
    rnd = random.Random(seed)
    vals = []
    marked = set(range(1, K + 1))
    for _ in range(trials):
        drawn = set(rnd.sample(range(1, N + 1), n))
        vals.append(len(drawn & marked))
    mean = sum(vals) / trials
    return sum((v - mean) ** 2 for v in vals) / trials


class TestClosedForm(unittest.TestCase):
    """闭式数值核对（与《概率工程》#01-#17 对照）"""

    def setUp(self):
        self.eng = ProbabilityEngine("大乐透")

    def test_sample_space(self):
        self.assertEqual(self.eng.total_sample_space(), DLT_JACKPOT_DENOM)
        self.assertEqual(total_combinations(35, 5, 12, 2), DLT_JACKPOT_DENOM)

    def test_jackpot_prob(self):
        self.assertAlmostEqual(self.eng.jackpot_prob(), 1.0 / DLT_JACKPOT_DENOM, places=15)

    def test_front_pmf_sums_to_one(self):
        s = sum(self.eng.front_hit_pmf().values())
        self.assertAlmostEqual(s, 1.0, places=12)

    def test_back_pmf_sums_to_one(self):
        s = sum(self.eng.back_hit_pmf().values())
        self.assertAlmostEqual(s, 1.0, places=12)

    def test_expected_front_hits(self):
        # #09 E[K_f] = 5·(5/35) = 5/7
        self.assertAlmostEqual(self.eng.expected_front_hits(), 5.0 / 7.0, places=12)

    def test_expected_back_hits(self):
        # #09 E[K_b] = 2·(2/12) = 1/3
        self.assertAlmostEqual(self.eng.expected_back_hits(), 2.0 * 2.0 / 12.0, places=12)

    def test_at_least_one_front(self):
        # #11 1 − C(30,5)/C(35,5)
        import math
        expected = 1.0 - math.comb(30, 5) / math.comb(35, 5)
        self.assertAlmostEqual(self.eng.at_least_one_front(), expected, places=12)

    def test_joint_sum_to_one(self):
        s = 0.0
        for k in range(0, 6):
            for l in range(0, 3):
                s += self.eng.front_hit_pmf()[k] * self.eng.back_hit_pmf()[l]
        self.assertAlmostEqual(s, 1.0, places=10)

    def test_summary_structure(self):
        sm = self.eng.probability_summary()
        for key in ("lot", "sample_space", "front_hit_pmf", "back_hit_pmf",
                    "expected_front_hits", "variance_front_hits", "jackpot_prob",
                    "at_least_one_front_prob", "honest_note"):
            self.assertIn(key, sm)
        self.assertIn("不预测", sm["honest_note"])


class TestVarianceFormula(unittest.TestCase):
    """#10 超几何方差：用模拟反证第二因子应为 (N−M)/N（非 M/N）"""

    def test_dlt_variance_matches_simulation(self):
        N, K, n = 35, 5, 5
        formula = hypergeometric_variance(N, K, n)
        sim = _sim_var(N, K, n, trials=300000, seed=7)
        # 容差 0.02（300k 模拟的标准误约 0.001 量级）
        self.assertLess(abs(formula - sim), 0.02,
                        f"方差公式 {formula:.4f} 与模拟 {sim:.4f} 偏差过大")

    def test_variance_other_config(self):
        for (N, K, n) in [(50, 10, 5), (80, 20, 10)]:
            formula = hypergeometric_variance(N, K, n)
            sim = _sim_var(N, K, n, trials=200000, seed=11)
            self.assertLess(abs(formula - sim), 0.03,
                            f"({N},{K},{n}) 公式 {formula:.4f} vs 模拟 {sim:.4f}")

    def test_wrong_factor_would_fail(self):
        """静态自检：若把第二因子写成 M/N（原图误读），会与模拟显著不符"""
        N, K, n = 35, 5, 5
        wrong = n * (K / N) * (K / N) * ((N - n) / (N - 1))
        sim = _sim_var(N, K, n, trials=300000, seed=7)
        # 错误式与模拟应明显不同（偏差 > 0.02）
        self.assertGreater(abs(wrong - sim), 0.02,
                           "错误因子 M/N 居然与模拟吻合，需复核测试")


class TestChiSquare(unittest.TestCase):
    """卡方 p 值精度（不依赖 scipy）"""

    def test_sf_zero_is_one(self):
        self.assertAlmostEqual(chi2_sf(0.0, 10), 1.0, places=9)

    def test_df1_quantile(self):
        # 3.841 是卡方(1) 的 0.95 分位 → 上尾 ≈ 0.05
        p = chi2_sf(3.841, 1)
        self.assertAlmostEqual(p, 0.05, delta=0.01)

    def test_large_df_median(self):
        # 卡方(df) 中位数 ≈ df·(1 − 2/(9df))^3；df=34 时约 33.6 → 上尾 ≈ 0.5
        p = chi2_sf(33.66, 34)
        self.assertAlmostEqual(p, 0.5, delta=0.05)

    def test_monotonic(self):
        self.assertGreater(chi2_sf(2.0, 10), chi2_sf(8.0, 10))

    def test_norm_sf(self):
        self.assertAlmostEqual(norm_sf(0.0), 0.5, places=9)
        self.assertAlmostEqual(norm_sf(1.959964), 0.025, delta=0.001)


class TestInclusionExclusion(unittest.TestCase):
    """#21 容斥原理（补全原图被裁切的第二行）"""

    def test_two_independent(self):
        # P(A∪B) = p+q − pq（独立近似） = 0.5+0.5−0.25 = 0.75
        self.assertAlmostEqual(inclusion_exclusion_union([0.5, 0.5]), 0.75, places=9)

    def test_empty(self):
        self.assertEqual(inclusion_exclusion_union([]), 0.0)

    def test_disjoint(self):
        # 独立近似：P(A∪B) = p+q − p·q = 0.2+0.3−0.06 = 0.44
        self.assertAlmostEqual(inclusion_exclusion_union([0.2, 0.3]), 0.2 + 0.3 - 0.2 * 0.3, places=9)


class TestWinAnyPrize(unittest.TestCase):
    """任一奖级概率：复用 prize_rules 单一真源"""

    def setUp(self):
        self.eng = ProbabilityEngine("大乐透")

    def test_structure_and_bounds(self):
        r = self.eng.win_any_prize_prob()
        self.assertTrue(r.get("ok"))
        total = r["total"]
        # 任一奖级概率必 > 头奖、且 < 1
        self.assertGreater(total, self.eng.jackpot_prob())
        self.assertLess(total, 1.0)
        # per_tier 之和应等于 total
        self.assertAlmostEqual(sum(r["per_tier"].values()), total, places=9)

    def test_known_tier_present(self):
        r = self.eng.win_any_prize_prob()
        fpmf = self.eng.front_hit_pmf()
        bpmf = self.eng.back_hit_pmf()
        # 七等奖（按 prize_rules 真源 7 奖级，2026-01-31 起）
        # = (3前,0后)+(2前,1后)+(1前,2后)+(0前,2后)
        expect_7 = (fpmf[3] * bpmf[0] + fpmf[2] * bpmf[1]
                    + fpmf[1] * bpmf[2] + fpmf[0] * bpmf[2])
        self.assertIn("七等奖", r["per_tier"])
        self.assertAlmostEqual(r["per_tier"]["七等奖"], expect_7, places=9)
        # 三等奖 = (5前,0后)+(4前,2后)
        expect_3 = fpmf[5] * bpmf[0] + fpmf[4] * bpmf[2]
        self.assertIn("三等奖", r["per_tier"])
        self.assertAlmostEqual(r["per_tier"]["三等奖"], expect_3, places=9)
        # 五等奖 = (4前,0后)+(3前,2后)
        expect_5 = fpmf[4] * bpmf[0] + fpmf[3] * bpmf[2]
        self.assertIn("五等奖", r["per_tier"])
        self.assertAlmostEqual(r["per_tier"]["五等奖"], expect_5, places=9)
        # 旧 9 奖级已取消：不应再出现八/九等奖
        self.assertNotIn("九等奖", r["per_tier"])
        self.assertNotIn("八等奖", r["per_tier"])


class TestRandomnessCheck(unittest.TestCase):
    """随机性检验：结构正确 + 卡方对人造非均匀数据能检出偏离"""

    def _fake_history(self, draws, seed=1):
        rnd = random.Random(seed)
        recs = []
        for _ in range(draws):
            front = rnd.sample(range(1, 36), 5)
            back = rnd.sample(range(1, 13), 2)
            recs.append({"nums": ",".join(f"{x:02d}" for x in sorted(front)) +
                                 "+" + ",".join(f"{x:02d}" for x in sorted(back))})
        return recs

    def test_structure_ok(self):
        eng = ProbabilityEngine("大乐透")
        rep = eng.randomness_check(self._fake_history(300), n_sim=20000)
        self.assertTrue(rep["ok"])
        self.assertIn("chi_square_front", rep)
        self.assertIn("runs_test", rep)
        self.assertIn("autocorrelation", rep)
        self.assertIn("monte_carlo_jackpot", rep)
        self.assertIsNotNone(rep["chi_square_front"]["stat"])

    def test_chi_square_detects_bias(self):
        # 人为偏置：前区号码 1-10 出现频率翻倍，卡方应显著（小 p）
        draws = []
        for _ in range(400):
            # 60% 概率塞入偏置号
            if random.Random(len(draws)).random() < 0.6:
                front = random.Random(len(draws)).sample(range(1, 11), 5)
            else:
                front = random.Random(len(draws) + 99).sample(range(1, 36), 5)
            back = random.Random(len(draws) + 7).sample(range(1, 13), 2)
            draws.append({"nums": ",".join(f"{x:02d}" for x in sorted(front)) +
                                  "+" + ",".join(f"{x:02d}" for x in sorted(back))})
        from engines.lottery_probability import chi_square_gof
        recs = []
        for d in draws:
            nums = d["nums"].split("+")[0]
            recs.append([int(x) for x in nums.split(",")])
        res = chi_square_gof(recs, 35, 5)
        self.assertLess(res["p_value"], 0.05)


if __name__ == "__main__":
    unittest.main()
