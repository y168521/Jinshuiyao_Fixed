# -*- coding: utf-8 -*-
"""tools/lottery_deep_review.py 的行为闸（JS-20261006-02）

锁三件事：
  1. 胆拖/复式/单注三种 nums 都能被 parse_structure 正确解析；
  2. 蒙特卡洛奖级判定与 utils/lottery_prize.py::judge_prize 真源一致（防口径漂移）；
  3. **已知缺陷**：judge_prize 无法判定胆拖（按逗号切分会把「[前区胆:20」当号码），
     导致胆拖预测 hits 与 prize_tier 双双失真。该缺陷用 skipTest 显式留证，
     修复后须改为真断言（见报告与经验箱条目）。
"""
import io
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "tools"))

from lottery_deep_review import (  # noqa: E402
    parse_structure, tier_of, mc_win_prob, load_rules, SPEC)


class TestParseStructure(unittest.TestCase):
    """三种写法的 nums 都要能解析出 (前区胆, 前区拖, 后区胆, 后区拖)"""

    def test_danzhuo_dlt(self):
        st = parse_structure("[前区胆:20,22 拖:01,04,14,15] [后区胆:06 拖:04,08]", "胆拖", "大乐透")
        self.assertEqual(st[0], [20, 22])
        self.assertEqual(st[1], [1, 4, 14, 15])
        self.assertEqual(st[2], [6])
        self.assertEqual(st[3], [4, 8])

    def test_danzhuo_ssq_without_prefix(self):
        """双色球写法没有「前区/后区」前缀：[胆:04,24]拖:03,07,08,15,27+07,11"""
        st = parse_structure("[胆:04,24]拖:03,07,08,15,27+07,11", "胆拖", "双色球")
        self.assertEqual(st[0], [4, 24])
        self.assertEqual(st[1], [3, 7, 8, 15, 27])
        self.assertEqual(sorted(st[2]), [7, 11])

    def test_fushi_expands_as_all_tuo(self):
        """复式 = 胆为空、拖为全部选号"""
        st = parse_structure("05,07,10,14,33,34,35+05,07,10", "复式", "大乐透")
        self.assertEqual(st[0], [])
        self.assertEqual(len(st[1]), 7)
        self.assertEqual(len(st[3]), 3)

    def test_danzhu_all_as_dan(self):
        st = parse_structure("01,06,15,26,31+05,12", "单注", "大乐透")
        self.assertEqual(len(st[0]), 5)
        self.assertEqual(st[1], [])

    def test_no_back_area(self):
        """七乐彩没有后区"""
        st = parse_structure("08,13,14,18,23,24,28", "单注", "七乐彩")
        self.assertEqual(len(st[0]), 7)
        self.assertEqual(st[2], [])


class TestJudgeConsistency(unittest.TestCase):
    """蒙特卡洛判定必须与 judge_prize 真源同口径"""

    def test_tier_matches_judge_prize(self):
        from utils.lottery_prize import judge_prize
        rules = load_rules()
        cases = [(5, 2), (5, 1), (4, 2), (4, 1), (3, 2), (2, 1), (1, 2), (0, 0)]
        for hf, hb in cases:
            mine = tier_of(rules, "大乐透", hf, hb)
            ref = judge_prize("大乐透", "01,02,03,04,05+06,07", "%s+%s" % (
                ",".join("%02d" % x for x in ([1, 2, 3, 4, 5][:hf] + [30, 31, 32, 33, 34][:5 - hf])),
                ",".join("%02d" % x for x in ([6, 7][:hb] + [8, 9][:2 - hb]))))
            self.assertEqual(mine, ref.get("tier"), "hf=%d hb=%d 口径不一致" % (hf, hb))

    def test_single_note_prob_near_theory(self):
        """单注中奖概率应接近 6.67%（大乐透理论值）"""
        rules = load_rules()
        p = mc_win_prob("大乐透", ([1, 2, 3, 4, 5], [], [6, 7], []), 35, 5, 12, 2, rules,
                        n_sim=30000)
        self.assertAlmostEqual(p, 0.0667, delta=0.01)


class TestDantuoDefectFixed(unittest.TestCase):
    """胆拖缺陷已修复 —— 本类由「已知缺陷留证」改造为回归锁（JS-20261006-03 / JS-20261007-02）

    原缺陷：judge_prize / count_match 按逗号切分号码串，判不了胆拖。
    证据（大乐透 2026083 期）：nums=[前区胆:23,27 拖:14,16,25,26] [后区胆:12 拖:01,07]
    正确结果 = 前区 4 + 后区 1 = 四等奖；修复前系统判定 = 未中奖（hits=1）。
    统计佐证：大乐透胆拖平均命中修复前 0.241，修复后 0.897。
    现已修复并把历史记录重算到位，故断言改为「必须正确」，防止回退。
    """

    DANTUO_NUMS = "[前区胆:23,27 拖:14,16,25,26] [后区胆:12 拖:01,07]"
    DANTUO_ACTUAL = "14,15,16,23,26+07,09"

    def test_judge_prize_handles_dantuo(self):
        """修复后：judge_prize 必须能解析胆拖并判出四等奖"""
        from utils.lottery_prize import judge_prize
        res = judge_prize("大乐透", self.DANTUO_NUMS, self.DANTUO_ACTUAL)
        self.assertEqual(res.get("tier"), "四等奖")

    def test_system_record_is_now_correct(self):
        """修复并重算后：历史记录必须是 hits=4 / 四等奖 / win"""
        import json
        preds = json.load(io.open(os.path.join(
            BASE, "金水谣数据", "predictions.json"), encoding="utf-8"))
        hit = [p for p in preds if p.get("lot") == "大乐透"
               and p.get("period") == 2026083 and p.get("type") == "胆拖"]
        self.assertTrue(hit, "该期胆拖记录应存在")
        self.assertEqual(hit[0].get("hits"), 4,
                         "重算后应为 4；若为 1 说明修复或重算被回退")
        self.assertEqual(hit[0].get("prize_tier"), "四等奖")
        self.assertEqual(hit[0].get("prize_status"), "win")

    def test_correct_algorithm_finds_the_prize(self):
        """正确算法确实算出 4+1 四等奖 —— 证明上面那条 skip 不是误报"""
        rules = load_rules()
        fd, ft, bd, bt = parse_structure(self.DANTUO_NUMS, "胆拖", "大乐透")
        af = set(int(x) for x in self.DANTUO_ACTUAL.split("+")[0].split(","))
        ab = set(int(x) for x in self.DANTUO_ACTUAL.split("+")[1].split(","))
        hf = len(set(fd) & af) + min(len(set(ft) & af), 5 - len(fd))
        hb = len(set(bd) & ab) + min(len(set(bt) & ab), 2 - len(bd))
        self.assertEqual((hf, hb), (4, 1))
        self.assertEqual(tier_of(rules, "大乐透", hf, hb), "四等奖")


if __name__ == "__main__":
    unittest.main()
