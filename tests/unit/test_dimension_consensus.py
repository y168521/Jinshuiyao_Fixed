# -*- coding: utf-8 -*-
"""维度共识引擎单元测试 (engines/dimension_consensus.py)

覆盖:
- 路数守恒 (012路/大中路) 强弱统计
- 位置热码 (百/十/个 近10期>=2次)
- 五码位置热码覆盖率 + 缺口提示
- 逐号码共识度 (打分/标签)
- 冲突检测 (偏冷/强路缺口/Top5建议)
- 数据不足优雅降级
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from engines.dimension_consensus import DimensionConsensus  # noqa: E402


def _make_3d_history(n=40, bias=(6, 7, 4)):
    """构造 n 期3D历史，近10期偏置到 bias 附近，旧期均匀分散"""
    history = []
    for i in range(n):
        is_recent = i >= n - 10
        if is_recent:
            nums = [bias[(i - (n - 10)) % 3],
                    bias[(i - (n - 10) + 1) % 3],
                    bias[(i - (n - 10) + 2) % 3]]
        else:
            nums = [(i * 3) % 10, (i * 3 + 1) % 10, (i * 3 + 2) % 10]
        history.append({"period": 2026000 + i + 1, "nums": ",".join("%d" % x for x in nums)})
    return history


class TestDimensionConsensus(unittest.TestCase):

    def setUp(self):
        self.hist = _make_3d_history()
        self.dc = DimensionConsensus("福彩3D")

    def test_route_stats(self):
        r = self.dc.analyze(self.hist, five=[6, 7, 4, 1, 2])
        route = r["route"]
        self.assertIn("012路", route)
        self.assertIn("大中路", route)
        # 近10期都是 6,7,4 → 012路成员 {0,3,6,9}/{1,4,7}/{2,5,8} 均应出现多次
        for kind in ("012路", "大中路"):
            self.assertEqual(sum(route[kind]["stats"].values()) >= 3, True)
            self.assertIn("stats", route[kind])

    def test_pos_hot(self):
        r = self.dc.analyze(self.hist, five=[6, 7, 4, 1, 2])
        for pn in ("百", "十", "个"):
            self.assertIn(pn, r["pos_hot"])
            self.assertTrue(r["pos_hot"][pn])

    def test_five_cover(self):
        r = self.dc.analyze(self.hist, five=[6, 7, 4, 1, 2])
        fc = r["five_cover"]
        self.assertEqual(fc["five"], sorted([6, 7, 4, 1, 2]))
        self.assertGreaterEqual(fc["rate"], 0.0)
        self.assertLessEqual(fc["rate"], 1.0)

    def test_consensus_scoring(self):
        r = self.dc.analyze(self.hist, five=[6, 7, 4, 1, 2])
        self.assertEqual(len(r["consensus"]), 10)
        for c in r["consensus"]:
            self.assertGreaterEqual(c["score"], 0)
            self.assertLessEqual(c["score"], 100)
            self.assertIn("labels", c)
        # 排名前5必须恰好5个
        self.assertEqual(len(r["suggest_top5"]), 5)

    def test_conflict_cold_five(self):
        r = self.dc.analyze(self.hist, five=[0, 1, 8, 9, 2])  # 近10期全是6/7/4,其余全冷
        joined = "；".join(r["conflicts"])
        self.assertIn("偏冷", joined)

    def test_degrade_short_history(self):
        short = _make_3d_history(n=5)
        r = self.dc.analyze(short, five=[1, 2, 3])
        self.assertIn("不足", r["summary"])


if __name__ == "__main__":
    unittest.main()
