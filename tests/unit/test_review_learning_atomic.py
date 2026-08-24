# -*- coding: utf-8 -*-
"""review_learning 持久层回归测试（JS-20260823-03）

背景：_save_patterns 曾用 open("w") 裸写 pattern_library.json，进程中途被杀
即截断成 0 字节（08-20 15:46 实际事故，丢 22 个模式）。修复后改走
protected_write_json 原子写 + 加载容错。本文件锁死该行为不回退。
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools import review_learning as rl


class TestReviewLearningResilience(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rl_test_")
        self.lib = os.path.join(self.tmp, "pattern_library.json")
        self.metrics = os.path.join(self.tmp, "review_metrics.json")
        self._orig = (rl._PATTERN_LIB_PATH, rl._METRICS_FILE)
        rl._PATTERN_LIB_PATH = self.lib
        rl._METRICS_FILE = self.metrics

    def tearDown(self):
        rl._PATTERN_LIB_PATH, rl._METRICS_FILE = self._orig
        for p in (self.lib, self.metrics):
            if os.path.isfile(p):
                os.remove(p)
        os.rmdir(self.tmp)

    def test_corrupt_lib_loads_empty_without_crash(self):
        """0字节/损坏库不再炸初始化（事故现场形态）"""
        with open(self.lib, "w", encoding="utf-8") as f:
            f.write("")
        learner = rl.ReviewLearning()
        self.assertEqual(learner.patterns, {})

    def test_save_patterns_roundtrip_parseable(self):
        """保存后文件可解析且内容完整（原子写不留半截）"""
        learner = rl.ReviewLearning()
        learner.patterns["PAT-X"] = {"id": "PAT-X", "name": "测试模式"}
        learner._save_patterns()
        with open(self.lib, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["patterns"][0]["id"], "PAT-X")

    def test_corrupt_metrics_falls_back_to_default(self):
        with open(self.metrics, "w", encoding="utf-8") as f:
            f.write("not-json{")
        learner = rl.ReviewLearning()
        self.assertEqual(learner.metrics.get("total_reviews", -1), 0)

    def test_save_metrics_creates_valid_file(self):
        learner = rl.ReviewLearning()
        learner._save_metrics()
        self.assertTrue(os.path.isfile(self.metrics))
        with open(self.metrics, "r", encoding="utf-8") as f:
            json.load(f)


if __name__ == "__main__":
    unittest.main()
