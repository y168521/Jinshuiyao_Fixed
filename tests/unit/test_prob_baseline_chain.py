# -*- coding: utf-8 -*-
"""概率引擎接入调用链单元测试（先红后绿）

覆盖：
  1. get_probability_baseline() 对支持的彩种（大乐透）返回正确的理论基线
  2. 不支持的彩种优雅降级（绝不抛异常，返回 ok=False + reason）
  3. 接线闸：helper 必须被 prediction_service.generate() 真实调用
     （防止「写了却没接进调用链」——本轮主题的同类病：0 调用点）
"""
import os
import ast
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 大乐透理论值：C(35,5)=324632, C(12,2)=66
DLT_SAMPLE_SPACE = 324632 * 66
# 期望前区命中 = n*K/N = 5*5/35
DLT_EXPECTED_FRONT = 5 * 5 / 35.0


class TestBaselineValues(unittest.TestCase):
    def test_dlt_baseline_ok(self):
        from engines.prediction_service import get_probability_baseline
        r = get_probability_baseline("大乐透")
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r["lot"], "大乐透")
        self.assertEqual(r["sample_space_total"], DLT_SAMPLE_SPACE)
        self.assertAlmostEqual(r["jackpot_prob"], 1.0 / DLT_SAMPLE_SPACE)
        self.assertAlmostEqual(r["expected_front_hits"], DLT_EXPECTED_FRONT, places=6)
        # 任一奖级概率必须来自 prize_rules 单一真源
        self.assertTrue(r["win_any_prize_prob"].get("ok"), r["win_any_proze_prob"]
                        if "win_any_proze_prob" in r else r)
        # 诚实注记必须存在，杜绝被渲染成"中奖率提升"
        self.assertTrue(r.get("honest_note"))

    def test_unsupported_lot_degrades(self):
        from engines.prediction_service import get_probability_baseline
        r = get_probability_baseline("__不存在的彩种__")
        self.assertFalse(r.get("ok"))
        self.assertTrue(r.get("reason"))
        self.assertEqual(r["lot"], "__不存在的彩种__")


class TestBaselineWired(unittest.TestCase):
    def test_generate_calls_baseline(self):
        """AST 闸：generate() 必须真实调用 get_probability_baseline。"""
        src_path = os.path.join(ROOT, "engines", "prediction_service.py")
        with open(src_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        gen = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "generate":
                gen = node
                break
        self.assertIsNotNone(gen, "未找到 generate()")
        called = False
        returned = False
        for node in ast.walk(gen):
            if isinstance(node, ast.Call):
                fn = node.func
                name = getattr(fn, "id", None) or getattr(fn, "attr", None)
                if name == "get_probability_baseline":
                    called = True
            if isinstance(node, ast.Dict):
                for k in node.keys:
                    if isinstance(k, ast.Constant) and k.value == "probability_baseline":
                        returned = True
        self.assertTrue(called, "generate() 未调用 get_probability_baseline（孤立的 helper）")
        self.assertTrue(returned, "generate() 返回值未包含 probability_baseline")


if __name__ == "__main__":
    unittest.main()
