# -*- coding: utf-8 -*-
"""胆拖判定闸（JS-20261006-03）

先红后绿：本文件在修复前应有 2 条 FAIL（judge_prize / count_match 判不了胆拖），
修复后全绿。同时锁住「非胆拖输入行为完全不变」，防止改真源时误伤单注/复式。
"""
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)

from utils.number_utils import count_match  # noqa: E402
from utils.lottery_prize import judge_prize  # noqa: E402

# 大乐透 2026083 期真实记录
DLT_NUMS = "[前区胆:23,27 拖:14,16,25,26] [后区胆:12 拖:01,07]"
DLT_ACTUAL = "14,15,16,23,26+07,09"
# 正确结果：前区 4 + 后区 1 = 四等奖


class TestDantuoIsJudged(unittest.TestCase):

    def test_judge_prize_returns_fourth_prize(self):
        res = judge_prize("大乐透", DLT_NUMS, DLT_ACTUAL)
        self.assertEqual(res.get("tier"), "四等奖",
                         "胆拖 4+1 应判四等奖，实际=%r" % res)
        self.assertTrue(res.get("is_win"))

    def test_count_match_returns_four(self):
        n, is_hit = count_match("大乐透", DLT_NUMS, DLT_ACTUAL)
        self.assertEqual(n, 4, "胆拖最优一注前区应命中 4 个，实际=%r" % n)
        self.assertTrue(is_hit)


class TestBackwardCompat(unittest.TestCase):
    """非胆拖输入：行为必须与修复前完全一致"""

    def test_single_note_unchanged(self):
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "01,02,03,04,05+06,07")
        self.assertEqual(r.get("tier"), "一等奖")
        self.assertEqual(count_match("大乐透", "01,02,03,04,05+06,07",
                                     "01,02,03,04,05+06,07")[0], 5)

    def test_fushi_unchanged(self):
        r = judge_prize("大乐透", "05,07,10,14,33,34,35+05,07,10",
                        "05,07,10,14,33+05,07")
        self.assertIsNotNone(r.get("tier"))
        n, _ = count_match("大乐透", "05,07,10,14,33,34,35+05,07,10",
                           "05,07,10,14,33+05,07")
        self.assertEqual(n, 5)

    def test_lose_still_lose(self):
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "11,12,13,14,15+08,09")
        self.assertEqual(r.get("status"), "lose")
        self.assertFalse(r.get("is_win"))

    def test_three_digit_unchanged(self):
        self.assertEqual(count_match("福彩3D", "1,2,3", "1,2,3")[0], 3)


class TestUnparsableIsNotLose(unittest.TestCase):
    """判定不了必须说判定不了，不能伪装成「确实没中」"""

    def test_unknown_lot_no_rule(self):
        r = judge_prize("不存在的彩种", "01,02+03", "01,02+03")
        self.assertEqual(r.get("status"), "no_rule")

    def test_dantuo_without_dan_is_not_applicable(self):
        """含「胆」但解析不出胆码（如 "胆:拖:01,02"）应判不适用而非未中奖"""
        r = judge_prize("大乐透", "前区胆:拖:01,02,03,04,05", "01,02,03,04,05+06,07")
        self.assertIn(r.get("status"), ("not_applicable", "lose"))


if __name__ == "__main__":
    unittest.main()
