# -*- coding: utf-8 -*-
"""W63补100 / JS-20260817-01：llm_budget 按 provider:model 三级定价测试

免费模型（glm-4.5-air）成本记 0；付费模型（deepseek / 智谱视觉模型）按价目计费；
未知 provider 回退 deepseek 默认价。
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.llm_budget import get_guard


class TestLLMBudgetPricing(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.g = get_guard()

    def test_glm45_air_free(self):
        """智谱免费模型 glm-4.5-air 成本必须为 0"""
        self.assertEqual(self.g.record("zhipu", 1000, 500, model="glm-4.5-air"), 0.0)

    def test_deepseek_priced(self):
        """deepseek 按价目计费：1M in × 0.5 + 1M out × 4.0 = 4.5 元"""
        self.assertAlmostEqual(self.g.record("deepseek", 1_000_000, 1_000_000), 4.5, places=4)

    def test_unknown_provider_fallback(self):
        """未知 provider 回退 deepseek 默认价（与旧行为一致）"""
        self.assertAlmostEqual(self.g.record("some_vendor", 1_000_000, 1_000_000), 4.5, places=4)

    def test_zhipu_vision_priced(self):
        """智谱付费视觉模型（glm-4.1v-thinking-flashx）仍计费"""
        self.assertGreater(self.g.record("zhipu", 1000, 500, model="glm-4.1v-thinking-flashx"), 0.0)

    def test_siliconflow_ollama_free(self):
        """siliconflow / ollama 免费池恒为 0"""
        self.assertEqual(self.g.record("siliconflow", 1000, 500), 0.0)
        self.assertEqual(self.g.record("ollama", 1000, 500), 0.0)

    def test_no_model_provider_price(self):
        """不带 model 时按 provider 级价目（zhipu 未配 provider 级 → 回退默认，与旧行为一致）"""
        self.assertGreater(self.g.record("zhipu", 1000, 500), 0.0)


if __name__ == "__main__":
    unittest.main()