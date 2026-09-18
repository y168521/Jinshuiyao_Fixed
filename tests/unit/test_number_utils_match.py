# -*- coding: utf-8 -*-
"""命中计数单一真源 count_match 的回归测试（JS-20260917-02）。

锁定三个历史 bug：
  1. 福彩3D/排列三 用 set 去重 → 组三/豹子号（06,06,02）被误判未命中
  2. 七星彩 用「任意1码命中」→ 7 位数字在 0–9 空间下随机也必中（历史命中率恒 100%）
  3. 三处实现（domain.py / gui / backtesting）口径打架 → 统一收敛到 count_match
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.number_utils import count_match


class TestDigitalLotteryMultiset:
    """福彩3D/排列三：必须用多重集，set 去重会少算重复数字。"""

    def test_group3_pair_not_deduped(self):
        """组三 06,06,02 全中应判命中（set 去重只算 2 个，旧口径误判未中）。"""
        n, hit = count_match("福彩3D", "06,06,02", "06,06,02")
        assert n == 3
        assert hit is True

    def test_group3_order_irrelevant(self):
        """组选不要求顺序：08,08,01 vs 08,01,08 应算 3 个。"""
        n, hit = count_match("福彩3D", "08,08,01", "08,01,08")
        assert n == 3
        assert hit is True

    def test_pl3_triple_pair(self):
        """排列三 00,05,00 豹子+对子混合，多重集应算 3 个。"""
        n, hit = count_match("排列三", "00,05,00", "00,05,00")
        assert n == 3
        assert hit is True

    def test_partial_multiset_counts_repeats(self):
        """预测两个 8、开奖一个 8 → 只能算 1 个，不能算 2 个。"""
        n, hit = count_match("福彩3D", "08,08,01", "08,02,03")
        assert n == 1
        assert hit is False

    def test_no_match(self):
        n, hit = count_match("福彩3D", "01,02,03", "04,05,06")
        assert n == 0
        assert hit is False


class TestSevenStarPositional:
    """七星彩：必须按位匹配，否则 7 位数字随机也必中。"""

    def test_positional_match(self):
        n, hit = count_match("七星彩", "1,2,3,4,5,6,7", "1,2,3,9,9,9,9")
        assert n == 3
        assert hit is True

    def test_same_digits_wrong_position_is_zero(self):
        """数字相同但位置全错 → 按位匹配 0，旧集合口径会算成 7。"""
        n, hit = count_match("七星彩", "1,2,3,4,5,6,7", "7,6,5,4,3,2,1")
        assert n == 1  # 仅第 4 位 4==4
        assert hit is False

    def test_not_always_hit(self):
        """旧口径下任意一期都 is_hit=True（命中率恒 100%），新口径必须能判未中。"""
        n, hit = count_match("七星彩", "03,06,06,07,06,09,06+14", "02,04,09,06,01,03,04")
        assert hit is False

    def test_back_area_ignored(self):
        """预测串带 +后区 时只比前 7 位，后区不参与计数。"""
        n1, _ = count_match("七星彩", "1,2,3,4,5,6,7+14", "1,2,3,9,9,9,9")
        n2, _ = count_match("七星彩", "1,2,3,4,5,6,7", "1,2,3,9,9,9,9")
        assert n1 == n2 == 3


class TestBallLotteries:
    def test_happy8_threshold(self):
        """快乐8 命中 5 码才算命中。"""
        n, hit = count_match("快乐8", "01,02,03,04,05,06,07,08,09,10",
                             "01,02,03,04,05,11,12,13,14,15")
        assert n == 5
        assert hit is True
        n2, hit2 = count_match("快乐8", "01,02,03,04,05,06,07,08,09,10",
                               "01,02,03,04,11,12,13,14,15,16")
        assert n2 == 4
        assert hit2 is False

    def test_ssq_any_hit(self):
        n, hit = count_match("双色球", "03,06,14,16,25,27+11", "03,07,15,17,26,28+12")
        assert n == 1
        assert hit is True

    def test_ssq_full_front(self):
        n, hit = count_match("双色球", "03,06,14,16,25,27+11", "03,06,14,16,25,27+11")
        assert n == 6
        assert hit is True


class TestRobustness:
    def test_empty_input(self):
        assert count_match("福彩3D", "", "01,02,03") == (0, False)
        assert count_match("福彩3D", "01,02,03", "") == (0, False)

    def test_unknown_lot_falls_back_to_set(self):
        """未知彩种走默认分支（集合交集），不抛异常。"""
        n, hit = count_match("未知彩", "01,02,03", "01,09,09")
        assert n == 1
        assert hit is True

    def test_malformed_nums_no_crash(self):
        assert count_match("福彩3D", "abc", "01,02,03") == (0, False)
