# -*- coding: utf-8 -*-
"""共形预测不确定性模块单元测试"""
import unittest
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.uncertainty import (
    SplitConformal, NormalizedConformal, AdaptiveConformal, ConformalClassifier,
    empirical_coverage, mpiw, mean_winkler, _quantile,
)


class TestQuantile(unittest.TestCase):
    def test_interpolation(self):
        s = [0.0, 10.0, 20.0, 30.0, 40.0]
        self.assertAlmostEqual(_quantile(s, 0.5), 20.0)
        self.assertAlmostEqual(_quantile(s, 0.0), 0.0)
        self.assertAlmostEqual(_quantile(s, 1.0), 40.0)


class TestSplitConformal(unittest.TestCase):
    def setUp(self):
        rng = random.Random(123)
        # y = 2x + N(0,1)，同方差
        self.calib = [(i, 2.0 * i + rng.gauss(0, 1.0)) for i in range(120)]
        self.test = [(i, 2.0 * i + rng.gauss(0, 1.0)) for i in range(120, 240)]

    def test_coverage_near_target(self):
        sc = SplitConformal(alpha=0.1)
        sc.calibrate([abs(y - 2.0 * x) for x, y in self.calib])
        ivs, acts = [], []
        for x, y in self.test:
            lo, hi = sc.predict_interval(2.0 * x)
            ivs.append((lo, hi)); acts.append(y)
        cov = empirical_coverage(ivs, acts)
        # 边际覆盖应接近 0.9（允许一定抽样波动）
        self.assertGreaterEqual(cov, 0.80)
        self.assertLessEqual(cov, 1.0)

    def test_interval_width_positive(self):
        sc = SplitConformal(alpha=0.1)
        sc.calibrate([abs(y - 2.0 * x) for x, y in self.calib])
        ivs = [sc.predict_interval(2.0 * x) for x, _ in self.test]
        self.assertGreater(mpiw(ivs), 0.0)


class TestNormalizedConformal(unittest.TestCase):
    def test_heteroscedastic_coverage(self):
        rng = random.Random(55)
        # 噪声随 x 增大：异方差；校准与测试覆盖同一 x 区间（同分布评估）
        n = 200
        calib = [(float(i), 2.0 * i + rng.gauss(0, 0.5 + i * 0.04)) for i in range(n)]
        test = [(float(i), 2.0 * i + rng.gauss(0, 0.5 + i * 0.04)) for i in range(n)]
        nc = NormalizedConformal(alpha=0.1)
        nc.calibrate([x for x, _ in calib], [abs(y - 2.0 * x) for x, y in calib])
        ivs, acts = [], []
        for x, y in test:
            lo, hi = nc.predict_interval(2.0 * x)
            ivs.append((lo, hi)); acts.append(y)
        cov = empirical_coverage(ivs, acts)
        self.assertGreaterEqual(cov, 0.80)


class TestAdaptiveConformal(unittest.TestCase):
    def test_long_run_miscoverage_bounded(self):
        rng = random.Random(9)
        test = [(i, 2.0 * i + rng.gauss(0, 1.0)) for i in range(150)]
        # 后半段注入缓慢漂移
        drift = [2.0 * x + rng.gauss(0, 1.0 + 0.03 * max(0, x - 75)) for x, _ in test]
        ac = AdaptiveConformal(alpha=0.1, gamma=0.02, window=40)
        for (x, _), y in zip(test, drift):
            ac.update(2.0 * x, y)
        # 长期误覆盖率不应失控（在合理范围内）
        self.assertGreaterEqual(ac.long_run_miscoverage, 0.0)
        self.assertLessEqual(ac.long_run_miscoverage, 0.4)


class TestConformalClassifier(unittest.TestCase):
    def test_predict_set_nonempty(self):
        rng = random.Random(3)
        cc = ConformalClassifier(alpha=0.1)
        cc.calibrate([rng.random() for _ in range(100)])
        pred_set = cc.predict_set([0.01, 0.3, 0.8, 0.99])
        self.assertGreaterEqual(len(pred_set), 1)
        self.assertLessEqual(len(pred_set), 4)


class TestMetrics(unittest.TestCase):
    def test_winkler_in_interval(self):
        # 真实值在区间内 → Winkler = 区间宽度
        self.assertAlmostEqual(mean_winkler([(0.0, 2.0)], [1.0], alpha=0.1), 2.0, places=5)

    def test_winkler_out_of_interval_penalized(self):
        inside = mean_winkler([(0.0, 2.0)], [1.0], alpha=0.1)
        below = mean_winkler([(0.0, 2.0)], [-3.0], alpha=0.1)
        self.assertGreater(below, inside)


if __name__ == "__main__":
    unittest.main()
