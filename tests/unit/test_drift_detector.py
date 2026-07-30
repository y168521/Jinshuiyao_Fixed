# -*- coding: utf-8 -*-
"""概念漂移检测器单元测试"""
import unittest
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.drift_detector import (
    population_stability_index, ks_test, CUSUMDetector, evaluate_drift,
)


class TestPSI(unittest.TestCase):
    def test_no_drift_low_psi(self):
        rng = random.Random(1)
        ref = [rng.gauss(0, 1) for _ in range(500)]
        cur = [rng.gauss(0, 1) for _ in range(500)]
        psi = population_stability_index(ref, cur, n_bins=10)
        self.assertLess(psi, 0.1)

    def test_shift_high_psi(self):
        rng = random.Random(2)
        ref = [rng.gauss(0, 1) for _ in range(500)]
        cur = [rng.gauss(3, 1) for _ in range(500)]
        psi = population_stability_index(ref, cur, n_bins=10)
        self.assertGreater(psi, 0.25)


class TestKS(unittest.TestCase):
    def test_same_distribution_high_p(self):
        rng = random.Random(11)
        a = [rng.gauss(0, 1) for _ in range(400)]
        b = [rng.gauss(0, 1) for _ in range(400)]
        _, p = ks_test(a, b)
        self.assertGreater(p, 0.05)

    def test_shifted_distribution_low_p(self):
        rng = random.Random(12)
        a = [rng.gauss(0, 1) for _ in range(400)]
        b = [rng.gauss(4, 1) for _ in range(400)]
        D, p = ks_test(a, b)
        self.assertGreater(D, 0.2)
        self.assertLess(p, 0.01)


class TestCUSUM(unittest.TestCase):
    def test_no_alert_on_stable(self):
        rng = random.Random(21)
        base = [rng.gauss(10, 1) for _ in range(60)]
        # 显式控制限 8σ：平稳数据 50 步内确定性无误报（标准 CUSUM h=5σ 偶发误报属正常）
        cusum = CUSUMDetector(base, k=0.5, h=8.0)
        alerts = 0
        for _ in range(50):
            st = cusum.update(rng.gauss(10, 1))
            alerts += 1 if st["alert"] else 0
        self.assertEqual(alerts, 0)

    def test_alert_on_sustained_shift(self):
        rng = random.Random(22)
        base = [rng.gauss(10, 1) for _ in range(60)]
        cusum = CUSUMDetector(base, k=0.5, h=8.0)
        for _ in range(30):
            cusum.update(rng.gauss(10, 1))  # 先平稳
        alerts = 0
        for _ in range(60):
            st = cusum.update(rng.gauss(16, 1))  # 持续 +6σ 偏移
            alerts += 1 if st["alert"] else 0
        self.assertGreater(alerts, 0)


class TestDriftReport(unittest.TestCase):
    def test_severity_levels(self):
        rng = random.Random(31)
        ref = [rng.gauss(0, 1) for _ in range(400)]
        low = evaluate_drift(ref, [rng.gauss(0, 1) for _ in range(400)])
        self.assertIn(low["severity"], ("low", "medium"))
        high = evaluate_drift(ref, [rng.gauss(4, 1) for _ in range(400)])
        self.assertEqual(high["severity"], "high")
        self.assertIn("漂移等级", high["text"])


if __name__ == "__main__":
    unittest.main()
