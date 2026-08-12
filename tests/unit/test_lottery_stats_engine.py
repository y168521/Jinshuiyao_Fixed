# -*- coding: utf-8 -*-
"""彩票 4 引擎 API 契约测试（JS-20260812-07 补充，W63补71）

覆盖 servers/handlers/lottery.py 接通的历史死链 API：
- POST /api/lottery/omission-table         遗漏表格（7 字段契约）
- POST /api/lottery/historical-same-period 历史同期（date|month 双模式）
- POST /api/lottery/number-follow-up       号码跟随（概率矩阵 + 对角 0）
- POST /api/lottery/trend-classification   近期开奖序列

引擎纯函数见 engines/lottery_stats.py；handler 用 FakeHandler 模式（不启 HTTP 服务）。
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from engines.lottery_stats import (number_follow_up, omission_table,
                                   trend_classification)
from server.handlers import lottery as h_lottery

SSQ_HISTORY = [
    {"period": 2026001, "lottery": "双色球", "nums": "01,05,12,20,25,30+07", "time": "2026-01-01"},
    {"period": 2026002, "lottery": "双色球", "nums": "02,07,12,15,22,33+11", "time": "2026-01-04"},
    {"period": 2026003, "lottery": "双色球", "nums": "01,08,12,18,27,31+07", "time": "2026-01-06"},
    {"period": 2026004, "lottery": "双色球", "nums": "03,09,15,21,24,30+02", "time": "2026-01-08"},
    {"period": 2025004, "lottery": "双色球", "nums": "04,10,16,22,28,33+05", "time": "2025-01-08"},
    {"period": 2024126, "lottery": "双色球", "nums": "05,11,17,23,29,32+08", "time": "2024-11-03"},
]


class FakeHandler:
    """模拟 GuideHandler：捕获 _send_json 的 payload 与状态码"""

    def __init__(self, body=""):
        self.payload = None
        self.code = None
        self.headers = {}
        self.rfile = mock.MagicMock()
        if body:
            self.headers["Content-Length"] = str(len(body))
            self.rfile.read.return_value = body.encode("utf-8")

    def _send_json(self, payload, code=200):
        self.payload = payload
        self.code = code


def _call(handler_fn, body_dict):
    h = FakeHandler(json.dumps(body_dict, ensure_ascii=False))
    handler_fn(h)
    return h


class TestOmissionTableEngine(unittest.TestCase):
    def test_fields_complete(self):
        rows = omission_table(SSQ_HISTORY, "双色球")
        self.assertEqual(len(rows), 33)
        for row in rows:
            self.assertEqual(set(row.keys()),
                             {"number", "current", "max", "avg", "frequency",
                              "lastAppear", "hotLevel"})
            self.assertIn(row["hotLevel"], ("极热", "热", "温", "冷"))

    def test_frequency_counts(self):
        rows = omission_table(SSQ_HISTORY, "双色球")
        by_num = {r["number"]: r for r in rows}
        self.assertEqual(by_num[1]["frequency"], 2)   # 01 出现在 2 期
        self.assertEqual(by_num[7]["frequency"], 3)   # 红7×1期 + 蓝7×2期
        self.assertEqual(by_num[3]["frequency"], 1)   # 03 出现 1 期
        self.assertEqual(by_num[33]["frequency"], 2)  # 33 出现 2 期

    def test_last_appear_is_latest(self):
        rows = omission_table(SSQ_HISTORY, "双色球")
        by_num = {r["number"]: r for r in rows}
        self.assertEqual(by_num[1]["lastAppear"], "2026-01-06")


class TestSamePeriodEngine(unittest.TestCase):
    def test_date_mode_cross_year(self):
        rows = omission_table  # noqa 占位防误用
        from engines.lottery_stats import historical_same_period
        hits = historical_same_period(SSQ_HISTORY, "2026-01-08", "date")
        self.assertEqual(len(hits), 2)  # 2026-01-08 与 2025-01-08
        for r in hits:
            self.assertEqual(set(r.keys()), {"date", "drawNum", "reds", "blues"})
            self.assertIsInstance(r["reds"], list)
            self.assertIsInstance(r["blues"], list)

    def test_month_mode(self):
        from engines.lottery_stats import historical_same_period
        hits = historical_same_period(SSQ_HISTORY, "2026-11-05", "month")
        self.assertEqual(len(hits), 1)  # 只有 2024-11-03 是 11 月
        self.assertEqual(hits[0]["drawNum"], "2024126")

    def test_no_match_returns_empty_list(self):
        from engines.lottery_stats import historical_same_period
        self.assertEqual(historical_same_period(SSQ_HISTORY, "2026-02-02", "date"), [])


class TestFollowUpEngine(unittest.TestCase):
    def test_matrix_shape_and_diagonal_zero(self):
        data = number_follow_up(SSQ_HISTORY, gap=1, lot_type="双色球")
        self.assertEqual(len(data), 33)
        for i, row in data.items():
            self.assertEqual(len(row), 33)
            self.assertEqual(row[i], 0)  # 页面显示 "—"

    def test_probabilities_sum_bounded(self):
        data = number_follow_up(SSQ_HISTORY, gap=1, lot_type="双色球")
        for i, row in data.items():
            total = sum(row.values())
            self.assertLessEqual(total, 1.0 + 1e-2)  # 归一化行和 ≈ 1（含舍入容差）


class TestTrendEngine(unittest.TestCase):
    def test_count_truncation(self):
        rows = trend_classification(SSQ_HISTORY, count=3)
        self.assertEqual(len(rows), 3)
        for r in rows:
            self.assertEqual(set(r.keys()), {"drawNum", "numbers"})
            self.assertTrue(all(isinstance(n, int) for n in r["numbers"]))

    def test_max_count_cap(self):
        rows = trend_classification(SSQ_HISTORY, count=9999)
        self.assertLessEqual(len(rows), 500)


class TestLotteryStatsHandlers(unittest.TestCase):
    """FakeHandler 契约：4 个 API 的 ok/data 结构 + 参数校验"""

    def test_omission_table_handler(self):
        h = _call(h_lottery.handle_omission_table, {"lottery": "双色球"})
        self.assertEqual(h.code, 200)
        self.assertTrue(h.payload["ok"])
        self.assertIsInstance(h.payload["data"], list)
        if h.payload["data"]:
            self.assertIn("hotLevel", h.payload["data"][0])

    def test_same_period_handler(self):
        h = _call(h_lottery.handle_historical_same_period,
                  {"lottery": "双色球", "date": "2026-01-08", "mode": "date"})
        self.assertEqual(h.code, 200)
        self.assertTrue(h.payload["ok"])
        self.assertEqual(h.payload["mode"], "date")
        self.assertIsInstance(h.payload["data"], list)

    def test_same_period_missing_date_400(self):
        h = _call(h_lottery.handle_historical_same_period, {"lottery": "双色球"})
        self.assertEqual(h.code, 400)
        self.assertFalse(h.payload["ok"])

    def test_follow_up_handler(self):
        h = _call(h_lottery.handle_number_follow_up, {"lottery": "双色球", "gap": 1})
        self.assertEqual(h.code, 200)
        self.assertTrue(h.payload["ok"])
        self.assertEqual(h.payload["gap"], 1)
        self.assertIn("honest_note", h.payload)

    def test_trend_handler(self):
        h = _call(h_lottery.handle_trend_classification, {"lottery": "双色球", "count": 10})
        self.assertEqual(h.code, 200)
        self.assertTrue(h.payload["ok"])
        self.assertIsInstance(h.payload["data"], list)

    def test_unsupported_lottery_400(self):
        h = _call(h_lottery.handle_omission_table, {"lottery": "不存在彩种"})
        self.assertEqual(h.code, 400)
        self.assertFalse(h.payload["ok"])

    def test_missing_lottery_400(self):
        h = _call(h_lottery.handle_omission_table, {})
        self.assertEqual(h.code, 400)
        self.assertFalse(h.payload["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)