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

from engines.lottery_stats import (hot_rank, number_follow_up, omission_table,
                                   rolling_hit_trend, trend_classification)
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


class TestHotRankEngine(unittest.TestCase):
    """冷热动态排行榜（W63补98 / JS-20260816-03）"""

    def test_window_counts_sorted(self):
        r = hot_rank(SSQ_HISTORY, 5)
        self.assertEqual(r["window"], 5)
        self.assertTrue(r["rank"])
        counts = [x["count"] for x in r["rank"]]
        self.assertEqual(counts, sorted(counts, reverse=True))
        # 窗口=最后5条(2026002~2024126)：12 出现2次（2026002/2026003），15 出现2次（2026002/2026004）
        by_num = {x["number"]: x for x in r["rank"]}
        self.assertEqual(by_num[12]["count"], 2)
        self.assertEqual(by_num[15]["count"], 2)

    def test_trend_direction(self):
        r = hot_rank(SSQ_HISTORY, 5)
        by_num = {x["number"]: x for x in r["rank"]}
        # 07 当前窗口2次(2026002/2026003) vs 前一窗口1次(2026001) → up
        self.assertEqual(by_num[7]["trend"], "up")
        self.assertIn(by_num[12]["trend"], ("up", "down", "flat", "new"))

    def test_empty_history(self):
        r = hot_rank([], 30)
        self.assertEqual(r["rank"], [])

    def test_window_capped(self):
        r = hot_rank(SSQ_HISTORY, 999)
        self.assertEqual(r["window"], 500)
        self.assertTrue(r["rank"])


PRED_FIXTURE = [
    # 双色球 3 期递增（2026004 未复盘必须剔除）
    {"lot": "双色球", "period": 2026001, "hits": 1, "coverage": 0.14, "reviewed": True},
    {"lot": "双色球", "period": 2026002, "hits": 2, "coverage": 0.29, "reviewed": True},
    {"lot": "双色球", "period": 2026003, "hits": 4, "coverage": 0.57, "reviewed": True},
    {"lot": "双色球", "period": 2026004, "hits": 7, "coverage": 1.0, "reviewed": False},
    # coverage 缺失 → hits/号码数兜底（3 码 → 1/3）
    {"lot": "福彩3D", "period": 2026217, "hits": 1, "nums": "02,03,05", "reviewed": True},
    # 无 period / 无 lot → 剔除
    {"lot": "快乐8", "hits": 2, "coverage": 0.1, "reviewed": True},
    {"period": 2026001, "hits": 2, "coverage": 0.1, "reviewed": True},
]


class TestRollingHitTrend(unittest.TestCase):
    """滚动命中率趋势（W63补107 / JS-20260823-01）"""

    def test_groups_periods_ascending_and_filters(self):
        r = rolling_hit_trend(PRED_FIXTURE, window=30)
        self.assertIn("双色球", r)
        ssq = r["双色球"]
        self.assertEqual([s["period"] for s in ssq["series"]], [2026001, 2026002, 2026003])
        self.assertEqual(ssq["latest_period"], 2026003)
        self.assertEqual(ssq["reviewed_total"], 3)
        self.assertNotIn("快乐8", r)  # 无 period 被剔除

    def test_coverage_fallback_from_nums(self):
        r = rolling_hit_trend(PRED_FIXTURE, window=30)
        d = r["福彩3D"]["series"][0]
        self.assertAlmostEqual(d["avg"], round(1 / 3, 4))
        self.assertEqual(d["count"], 1)

    def test_trend_up_down_flat(self):
        rising = [{"lot": "A", "period": i, "coverage": c, "reviewed": True}
                  for i, c in zip(range(2026001, 2026005), [0.1, 0.1, 0.5, 0.5])]
        falling = [{"lot": "B", "period": i, "coverage": c, "reviewed": True}
                   for i, c in zip(range(2026001, 2026005), [0.5, 0.5, 0.1, 0.1])]
        flat = [{"lot": "C", "period": i, "coverage": 0.3, "reviewed": True}
                for i in range(2026001, 2026005)]
        r = rolling_hit_trend(rising + falling + flat, window=2)
        self.assertEqual(r["A"]["trend"], "up")
        self.assertEqual(r["B"]["trend"], "down")
        self.assertEqual(r["C"]["trend"], "flat")
        self.assertEqual(r["A"]["delta"], round(0.5 - 0.1, 4))

    def test_insufficient_when_single_window(self):
        only_two = [{"lot": "A", "period": i, "coverage": 0.3, "reviewed": True}
                    for i in range(2026001, 2026003)]
        r = rolling_hit_trend(only_two, window=30)
        self.assertEqual(r["A"]["trend"], "insufficient")
        self.assertIsNone(r["A"]["avg_prev"])

    def test_adaptive_halving_when_history_short(self):
        recs = [{"lot": "A", "period": i, "coverage": c, "reviewed": True}
                for i, c in zip(range(2026001, 2026006), [0.1, 0.1, 0.5, 0.5, 0.5])]
        r = rolling_hit_trend(recs, window=30)
        self.assertEqual(r["A"]["window"], 2)  # 5期不足两窗 → 折半
        self.assertEqual(r["A"]["trend"], "up")
        self.assertIsNotNone(r["A"]["avg_prev"])

    def test_window_truncation_keeps_latest(self):
        many = [{"lot": "A", "period": i, "coverage": 0.3, "reviewed": True}
                for i in range(2026001, 2026011)]  # 10 期
        r = rolling_hit_trend(many, window=4)
        self.assertEqual(len(r["A"]["series"]), 4)
        self.assertEqual(r["A"]["series"][-1]["period"], 2026010)

    def test_empty_input(self):
        self.assertEqual(rolling_hit_trend([], 30), {})
        self.assertEqual(rolling_hit_trend(None, 30), {})


class TestPredictionHitTrendHandler(unittest.TestCase):
    """GET /api/prediction/hit-trend FakeHandler 契约"""

    def test_handler_contract(self):
        from server.handlers import prediction as h_pred
        with mock.patch.object(h_pred, "_load_lottery_predictions_raw",
                               return_value=PRED_FIXTURE):
            h = FakeHandler()
            h.path = "/api/prediction/hit-trend?window=30"
            h_pred.handle_prediction_hit_trend(h)
        self.assertEqual(h.code, 200)
        self.assertTrue(h.payload["ok"])
        self.assertIn("双色球", h.payload["lots"])
        lot = h.payload["lots"]["双色球"]
        for key in ("window", "series", "avg_recent", "trend", "reviewed_total"):
            self.assertIn(key, lot)

    def test_handler_bad_window_defaults(self):
        from server.handlers import prediction as h_pred
        with mock.patch.object(h_pred, "_load_lottery_predictions_raw",
                               return_value=PRED_FIXTURE):
            h = FakeHandler()
            h.path = "/api/prediction/hit-trend?window=abc"
            h_pred.handle_prediction_hit_trend(h)
        self.assertEqual(h.code, 200)
        self.assertTrue(h.payload["ok"])
        self.assertEqual(h.payload["window"], 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)