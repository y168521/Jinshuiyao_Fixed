# -*- coding: utf-8 -*-
"""复盘回写回归测试（JS-20260921-04）

背景（真实缺陷）：`LotteryDomain.review()` 回写 predictions.json 时原按 **期号** 单键
匹配，而期号在不同彩种之间会重复（实测双色球 2026109 与七星彩 2026109 并存）→
跨彩种串写 reviewed/hits，造成「复盘张冠李戴」：A 彩种的命中数被写到 B 彩种头上。
修复后改为 (lot, period) 复合键，并回存开奖号码 `actual`（使历史命中可事后复核）。

本文件的价值：把「串写」这个静默错误钉死——它不报错，只是让命中率统计悄悄失真，
正是「预测质量看起来下降」类问题最难查的那一类。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestReviewWritebackIsolation(unittest.TestCase):
    """复盘回写必须按 (彩种, 期号) 隔离，且回存开奖号"""

    def setUp(self):
        from domains.lottery.domain import LotteryDomain
        self.domain = LotteryDomain()
        self.domain.setup()

    def _run_review_with_stub(self, store):
        """用桩替换 safe_load/safe_write，返回 (被写回的数据, 复盘结果)"""
        import utils.safe_json as sj

        written = {}

        def _load(path, default=None):
            return list(store)

        def _write(path, data):
            written["data"] = data
            return True

        old_load, old_write = sj.safe_load_json, sj.safe_write_json
        sj.safe_load_json, sj.safe_write_json = _load, _write
        try:
            res = self.domain.review(
                predictions=[{"lot": "双色球", "period": 2026109, "nums": "01,02,03,04,05,06+07"}],
                actual={"nums": "01,02,03,04,05,06+07"},
            )
        finally:
            sj.safe_load_json, sj.safe_write_json = old_load, old_write
        return written.get("data"), res

    def test_cross_lot_same_period_not_overwritten(self):
        """同号不同彩种：七星彩记录不得被双色球的复盘结果串写"""
        store = [
            {"lot": "双色球", "period": 2026109, "nums": "01,02,03,04,05,06+07"},
            {"lot": "七星彩", "period": 2026109, "nums": "1,2,3,4,5,6,7"},
        ]
        data, res = self._run_review_with_stub(store)
        self.assertIsNotNone(data, "应发生回写")
        by_lot = {d["lot"]: d for d in data}
        # 修复后：七星彩不应被标记已复盘（另一彩种同期号不构成它的复盘）
        self.assertNotEqual(by_lot["七星彩"].get("reviewed"), True,
                           "七星彩被同期号的双色球复盘串写了（跨彩种污染）")
        # 双色球自己应被正确标记
        self.assertEqual(by_lot["双色球"].get("reviewed"), True)
        self.assertEqual(res.get("status"), "ok")

    def test_actual_is_persisted(self):
        """回写必须保存开奖号码，否则历史命中无法复核"""
        store = [{"lot": "双色球", "period": 2026109, "nums": "01,02,03,04,05,06+07"}]
        data, _ = self._run_review_with_stub(store)
        self.assertEqual(data[0].get("actual"), "01,02,03,04,05,06+07",
                         "未回存开奖号码，历史命中无法事后重算")


if __name__ == "__main__":
    unittest.main()
