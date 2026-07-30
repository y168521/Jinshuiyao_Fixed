# -*- coding: utf-8 -*-
"""工具函数测试"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from utils.number_utils import (
    get_red_count, get_blue_count, clean_nums, parse_reds,
    fmt_period, fix_period_5to7, is_valid_period, rpick
)
from config import LOTTERY_RULES


class TestNumberUtils(unittest.TestCase):
    def test_get_red_count_ssq(self):
        rule = LOTTERY_RULES["双色球"]
        self.assertEqual(get_red_count(rule), 6)

    def test_get_red_count_dlt(self):
        rule = LOTTERY_RULES["大乐透"]
        self.assertEqual(get_red_count(rule), 5)

    def test_get_red_count_3d(self):
        rule = LOTTERY_RULES["福彩3D"]
        self.assertEqual(get_red_count(rule), 3)

    def test_clean_nums_removes_spaces(self):
        self.assertEqual(clean_nums(" 1 , 2 , 3 "), "1,2,3")

    def test_parse_reds_comma(self):
        self.assertEqual(parse_reds("01,02,15"), [1, 2, 15])

    def test_parse_reds_no_comma(self):
        self.assertEqual(parse_reds("010512"), [1, 5, 12])

    def test_fmt_period(self):
        self.assertEqual(fmt_period("双色球", 2026066), "2026066")

    def test_fix_period_5to7(self):
        self.assertEqual(fix_period_5to7(26066), 2026066)

    def test_is_valid_period(self):
        self.assertTrue(is_valid_period("双色球", 2026066))
        self.assertFalse(is_valid_period("双色球", 2026066 + 1000))  # 超期号范围

    def test_rpick(self):
        result = rpick([1, 2, 3, 4, 5], 3)
        self.assertEqual(len(result), 3)
        self.assertTrue(all(x in [1, 2, 3, 4, 5] for x in result))

    def test_rpick_exceeds_length(self):
        result = rpick([1, 2], 5)
        self.assertEqual(len(result), 2)
