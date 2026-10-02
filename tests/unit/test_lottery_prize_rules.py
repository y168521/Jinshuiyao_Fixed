# -*- coding: utf-8 -*-
"""官方中奖规则判定回归测试（JS-20260924-34）

背景（真实缺陷，实测取证 2026-09-24）：系统的「命中」此前只是**号码重合了几个**
（`utils.number_utils.count_match`），与官方中奖规则**双向错位**：

| 情形（双色球）      | 系统判定 | 官方结果        |
|---------------------|----------|-----------------|
| 中 1 红球、没中蓝球 | 命中     | **无奖**        |
| 0 红球、只中蓝球    | 未中     | **六等奖 5 元** |

用户拍板走「并存」：保留 hits（号码重合数，供学习与既有统计），
**另外**按官方奖级判定并落 `prize_tier`。本文件的价值：
  1. 把官方奖级判定钉死（含快乐8「中 1~4 个无奖」这种最容易写错的边界）；
  2. 用**反证用例**证明两套口径确实不同，防止后人又把它们当成一回事；
  3. 规则过期只告警不改数字，且**读不出日期必须按过期处理**（静默才是敌人）。
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from utils.lottery_prize import (
    judge_prize, load_rules, rules_staleness,
    STATUS_WIN, STATUS_LOSE, STATUS_NO_RULE, STATUS_NOT_APPLICABLE,
    PRIZE_RULES_STALE_DAYS,
)


class TestOfficialPrizeJudge(unittest.TestCase):
    """按官方奖级判定"""

    def test_rules_file_loadable(self):
        rules = load_rules(force=True)
        self.assertIsInstance(rules, dict, "官方奖级规则文件读不到")
        self.assertIn("双色球", rules.get("rules", {}))

    def test_ssq_blue_only_is_sixth_prize(self):
        """只中蓝球：官方六等奖（系统的 count_match 会判未中）"""
        r = judge_prize("双色球", "01,02,03,04,05,06+07", "20,21,22,23,24,25+07")
        self.assertEqual(r["tier"], "六等奖")
        self.assertTrue(r["is_win"])

    def test_ssq_one_red_no_blue_is_no_prize(self):
        """中 1 红没中蓝：官方无奖（系统的 count_match 会判命中）"""
        r = judge_prize("双色球", "01,02,03,04,05,06+07", "01,11,12,13,14,15+16")
        self.assertEqual(r["tier"], None)
        self.assertEqual(r["status"], STATUS_LOSE)

    def test_ssq_two_red_blue_is_sixth_prize(self):
        r = judge_prize("双色球", "01,02,03,04,05,06+07", "01,02,11,12,13,14+07")
        self.assertEqual(r["tier"], "六等奖")

    def test_ssq_two_red_no_blue_is_no_prize(self):
        r = judge_prize("双色球", "01,02,03,04,05,06+07", "01,02,11,12,13,14+16")
        self.assertEqual(r["status"], STATUS_LOSE)

    def test_ssq_jackpot(self):
        r = judge_prize("双色球", "01,02,03,04,05,06+07", "01,02,03,04,05,06+07")
        self.assertEqual(r["tier"], "一等奖")

    def test_ssq_six_red_no_blue_is_second_prize(self):
        r = judge_prize("双色球", "01,02,03,04,05,06+07", "01,02,03,04,05,06+16")
        self.assertEqual(r["tier"], "二等奖")

    def test_dlt_only_one_back_is_no_prize(self):
        """新规（2026-01-31 起 7 奖级）：只中 1 个后区(0+1) 已不再中奖（旧九等奖取消）"""
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "11,12,13,14,15+06,09")
        self.assertEqual(r["status"], STATUS_LOSE)
        self.assertIsNone(r["tier"])

    def test_dlt_one_front_no_back_is_no_prize(self):
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "01,11,12,13,14+08,09")
        self.assertEqual(r["status"], STATUS_LOSE)

    def test_dlt_two_back_is_seventh_prize(self):
        """0+2（两个后区全中）属七等奖"""
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "11,12,13,14,15+06,07")
        self.assertEqual(r["tier"], "七等奖")

    def test_dlt_three_front_is_seventh_prize(self):
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "01,02,03,11,12+08,09")
        self.assertEqual(r["tier"], "七等奖")

    def test_dlt_five_front_is_third_prize(self):
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "01,02,03,04,05+08,09")
        self.assertEqual(r["tier"], "三等奖")

    def test_dlt_four_front_two_back_is_third_prize(self):
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "01,02,03,04,11+06,07")
        self.assertEqual(r["tier"], "三等奖")

    def test_dlt_four_front_one_back_is_fourth_prize(self):
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "01,02,03,04,11+06,09")
        self.assertEqual(r["tier"], "四等奖")

    def test_dlt_four_front_is_fifth_prize(self):
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "01,02,03,04,11+08,09")
        self.assertEqual(r["tier"], "五等奖")

    def test_dlt_three_front_two_back_is_fifth_prize(self):
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "01,02,03,11,12+06,07")
        self.assertEqual(r["tier"], "五等奖")

    def test_dlt_three_front_one_back_is_sixth_prize(self):
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "01,02,03,11,12+06,09")
        self.assertEqual(r["tier"], "六等奖")

    def test_dlt_two_front_two_back_is_sixth_prize(self):
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "01,02,11,12,13+06,07")
        self.assertEqual(r["tier"], "六等奖")

    def test_dlt_jackpot(self):
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "01,02,03,04,05+06,07")
        self.assertEqual(r["tier"], "一等奖")

    def test_dlt_second_prize(self):
        r = judge_prize("大乐透", "01,02,03,04,05+06,07", "01,02,03,04,05+06,09")
        self.assertEqual(r["tier"], "二等奖")

    def test_dlt_high_pool_prize_recorded(self):
        """奖池≥8亿 的上浮档须记录在 prize_high_pool 字段（不丢信息）"""
        rules = load_rules(force=True)
        dlt = rules["rules"]["大乐透"]
        tier3 = next(t for t in dlt["tiers"] if t["tier"] == "三等奖")
        self.assertEqual(tier3["prize"], 5000)
        self.assertEqual(tier3["prize_high_pool"], 6666)

    def test_qlc_one_hit_is_seventh_prize(self):
        """七乐彩最低奖：中 1 个基本号即七等奖（开奖数据不含特别号，后区恒 0）"""
        r = judge_prize("七乐彩", "04,06,07,08,12,16,25", "06,11,13,14,15,17,18")
        self.assertEqual(r["tier"], "七等奖")

    def test_3d_straight(self):
        r = judge_prize("福彩3D", "647", "647")
        self.assertEqual(r["tier"], "直选")

    def test_3d_group3_when_draw_has_pair(self):
        """开奖号含对子 → 组三（官方按开奖形态定，不按投注方式）"""
        r = judge_prize("福彩3D", "00,09,09", "09,09,00")
        self.assertEqual(r["tier"], "组三")

    def test_3d_group6_when_draw_all_distinct(self):
        r = judge_prize("排列三", "01,02,03", "03,02,01")
        self.assertEqual(r["tier"], "组六")

    def test_3d_complex_bet_not_applicable(self):
        """组六复式（5 码）套不上官方三位奖级 → 暂缺，不猜"""
        r = judge_prize("福彩3D", "00,04,06,07,09", "00,05,01")
        self.assertEqual(r["status"], STATUS_NOT_APPLICABLE)
        self.assertFalse(r["is_win"])

    def test_keno_all_ten(self):
        pred = ",".join("%02d" % i for i in range(1, 11))
        r = judge_prize("快乐8", pred, pred)
        self.assertEqual(r["tier"], "选十中十")

    def test_keno_zero_hit_is_prize(self):
        """官方特殊规则：选十全不中也中奖 2 元"""
        pred = ",".join("%02d" % i for i in range(1, 11))
        act = ",".join("%02d" % i for i in range(31, 51))
        r = judge_prize("快乐8", pred, act)
        self.assertEqual(r["tier"], "选十中零")
        self.assertTrue(r["is_win"])

    def test_keno_three_hit_is_no_prize(self):
        """最容易写错的边界：中 1~4 个无奖，只有中 5+ 或中 0 才有奖"""
        pred = ",".join("%02d" % i for i in range(1, 11))
        act = ",".join("%02d" % i for i in [1, 2, 3] + list(range(31, 48)))
        r = judge_prize("快乐8", pred, act)
        self.assertEqual(r["status"], STATUS_LOSE)
        self.assertFalse(r["is_win"])

    def test_keno_complex_bet_not_applicable(self):
        pred = ",".join("%02d" % i for i in range(1, 12))  # 11 码复式
        act = ",".join("%02d" % i for i in range(1, 21))
        r = judge_prize("快乐8", pred, act)
        self.assertEqual(r["status"], STATUS_NOT_APPLICABLE)

    def test_qxc_consecutive(self):
        r = judge_prize("七星彩", "01,07,01,07,05,08,07", "01,07,01,07,05,08,07")
        self.assertEqual(r["tier"], "一等奖")

    def test_unknown_lot_is_no_rule(self):
        r = judge_prize("不存在的彩种", "01", "01")
        self.assertEqual(r["status"], STATUS_NO_RULE)

    def test_missing_rules_is_no_rule(self):
        """规则读不到必须报暂缺，绝不猜一个奖级出来"""
        r = judge_prize("双色球", "01,02,03,04,05,06+07", "01,02,03,04,05,06+07", rules={})
        self.assertEqual(r["status"], STATUS_NO_RULE)
        self.assertFalse(r["is_win"])


class TestTwoCalibersCoexist(unittest.TestCase):
    """反证：官方口径与号码重合数口径确实不是一回事"""

    def test_ssq_blue_only_differs_from_count_match(self):
        from utils.number_utils import count_match
        pred, act = "01,02,03,04,05,06+07", "20,21,22,23,24,25+07"
        n, is_hit = count_match("双色球", pred, act)
        prize = judge_prize("双色球", pred, act)
        self.assertFalse(is_hit, "前置：号码重合数口径判未中")
        self.assertTrue(prize["is_win"], "官方口径判中奖")
        self.assertNotEqual(bool(is_hit), prize["is_win"],
                            "两套口径结果相同 → 说明官方判定没真正接线")

    def test_ssq_one_red_differs_from_count_match(self):
        from utils.number_utils import count_match
        pred, act = "01,02,03,04,05,06+07", "01,11,12,13,14,15+16"
        n, is_hit = count_match("双色球", pred, act)
        prize = judge_prize("双色球", pred, act)
        self.assertTrue(is_hit, "前置：号码重合数口径判命中")
        self.assertFalse(prize["is_win"], "官方口径判无奖")
        self.assertNotEqual(bool(is_hit), prize["is_win"])


class TestRulesStaleness(unittest.TestCase):
    """规则过期只告警，不改数字"""

    def test_fresh_rules_not_stale(self):
        today = datetime.now().strftime("%Y-%m-%d")
        s = rules_staleness({"updated_at": today, "stale_days": PRIZE_RULES_STALE_DAYS})
        self.assertFalse(s["is_stale"])
        self.assertEqual(s["days"], 0)

    def test_old_rules_is_stale(self):
        old = (datetime.now() - timedelta(days=PRIZE_RULES_STALE_DAYS + 1)).strftime("%Y-%m-%d")
        s = rules_staleness({"updated_at": old, "stale_days": PRIZE_RULES_STALE_DAYS})
        self.assertTrue(s["is_stale"])

    def test_missing_date_treated_as_stale(self):
        """读不出日期必须按过期处理 —— 不能因为缺字段就假装新鲜"""
        s = rules_staleness({"stale_days": PRIZE_RULES_STALE_DAYS})
        self.assertTrue(s["is_stale"])
        self.assertIsNone(s["days"])

    def test_missing_file_treated_as_stale(self):
        """规则文件读不到 → 按过期告警，不能假装新鲜"""
        import utils.lottery_prize as lp
        old = lp.RULES_FILE
        lp.RULES_FILE = os.path.join(ROOT, "config", "__不存在的规则文件__.json")
        try:
            s = rules_staleness(None)
        finally:
            lp.RULES_FILE = old
        self.assertTrue(s["is_stale"])
        self.assertTrue(s["missing"])


class TestReviewStampCarriesPrizeTier(unittest.TestCase):
    """复盘回写必须带上官方奖级（三条路径共用 stamp_review，改一处即全覆盖）"""

    def test_stamp_review_adds_prize_tier(self):
        from utils.review_writeback import stamp_review
        p = {"lot": "双色球", "nums": "01,02,03,04,05,06+07"}
        stamp_review(p, actual="01,02,03,04,05,06+07", hits=7)
        self.assertEqual(p.get("prize_tier"), "一等奖",
                         "复盘回写未落官方奖级 → 历史记录查不到真实中奖情况")

    def test_stamp_review_prize_tier_none_when_lost(self):
        from utils.review_writeback import stamp_review
        p = {"lot": "双色球", "nums": "01,02,03,04,05,06+07"}
        stamp_review(p, actual="01,11,12,13,14,15+16", hits=1)
        self.assertIsNone(p.get("prize_tier"))
        self.assertIn("prize_status", p)


if __name__ == "__main__":
    unittest.main()
