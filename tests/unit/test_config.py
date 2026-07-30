# -*- coding: utf-8 -*-
"""配置一致性测试

验证 config.py 是唯一的配置源，无重复定义。
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import config


class TestConfig(unittest.TestCase):
    def test_lottery_rules_has_7_lots(self):
        self.assertEqual(len(config.LOTTERY_RULES), 7)

    def test_lottery_all_matches_rules(self):
        for lot in config.LOT_ALL:
            self.assertIn(lot, config.LOTTERY_RULES)

    def test_engine_names_not_empty(self):
        self.assertGreater(len(config.ENGINE_NAMES), 5)

    def test_budget_positive(self):
        self.assertGreater(config.DEFAULT_MAX_BUDGET, 0)
        self.assertGreater(config.MAX_BUDGET_LIMIT, config.DEFAULT_MAX_BUDGET)

    def test_directories_exist(self):
        import os
        self.assertTrue(os.path.isdir(config.BASE_DIR))
        self.assertTrue(os.path.isdir(config.DATA_SAVE))
