# -*- coding: utf-8 -*-
"""基金外围风险模块测试（JS-20260920-04）

测试内容：
  - HTML 解析：基金经理变动一览 / 规模变动
  - 评估逻辑：经理变更预警、规模·清盘预警分级
  - 诚实度：数据缺失时必须 ok=False 并提示"暂缺"，不得编造
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from domains.fund.fund_profile_risk import (
    parse_manager_history,
    parse_scale_history,
    eval_manager_change,
    eval_scale_risk,
    SCALE_DANGER_YI,
    SCALE_WARN_YI,
)

# 与线上页面结构一致的样本（class 为 "w782 comm jloff"）
MANAGER_HTML = """
<table class="w782 comm  jloff">
<thead><tr><th>起始期</th><th>截止期</th><th>基金经理</th><th>任职期间</th><th>任职回报</th></tr></thead>
<tbody>
<tr><td>2026-08-01</td><td>至今</td><td>张三 李四</td><td>50天</td><td>3.21%</td></tr>
<tr><td>2022-01-01</td><td>2026-07-31</td><td>王五</td><td>4年又210天</td><td>-12.30%</td></tr>
</tbody>
</table>
<table class="w782 comm jloff">
<thead><tr><th>基金代码</th><th>基金名称</th></tr></thead>
<tbody><tr><td>000001</td><td>测试基金</td></tr></tbody>
</table>
"""

SCALE_RAW = (
    'var gmbd_apidata={ content:"<table class=\'w782 comm gmbd\'><thead><tr>'
    '<th>日期</th><th>期间申购（亿份）</th><th>期间赎回（亿份）</th>'
    '<th>期末总份额（亿份）</th><th>期末净资产（亿元）</th><th>净资产变动率</th>'
    '</tr></thead><tbody>'
    '<tr><td>2026-06-30</td><td class=\'tor\'>1.49</td><td class=\'tor\'>3.36</td>'
    '<td class=\'tor\'>24.06</td><td class=\'tor\'>39.38</td><td class=\'tor\'>48.93%</td></tr>'
    '<tr><td>2026-03-31</td><td class=\'tor\'>1.25</td><td class=\'tor\'>2.44</td>'
    '<td class=\'tor\'>25.92</td><td class=\'tor\'>26.44</td><td class=\'tor\'>-9.96%</td></tr>'
    '</tbody></table>",arryear:[2026,2025]};'
)


class TestParse(unittest.TestCase):
    def test_parse_manager_history(self):
        rows = parse_manager_history(MANAGER_HTML)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["基金经理"], "张三 李四")
        self.assertEqual(rows[0]["起始期"], "2026-08-01")
        self.assertEqual(rows[1]["任职回报"], "-12.30%")

    def test_parse_manager_history_empty(self):
        self.assertEqual(parse_manager_history(""), [])
        self.assertEqual(parse_manager_history("<html></html>"), [])

    def test_parse_scale_history(self):
        rows = parse_scale_history(SCALE_RAW)
        self.assertEqual(len(rows), 2)
        self.assertIn("2026-06-30", str(rows[0]))
        self.assertEqual(rows[0].get("期末净资产（亿元）"), "39.38")
        self.assertEqual(rows[1].get("净资产变动率"), "-9.96%")

    def test_parse_scale_history_empty(self):
        self.assertEqual(parse_scale_history(""), [])
        self.assertEqual(parse_scale_history("var apidata="), [])


class TestManagerEval(unittest.TestCase):
    def test_recent_change_warn(self):
        rows = parse_manager_history(MANAGER_HTML)
        r = eval_manager_change(rows, today=datetime(2026, 9, 20))
        self.assertTrue(r["ok"])
        self.assertTrue(r["changed_recently"])
        self.assertEqual(r["level"], "warn")
        self.assertEqual(r["prev_managers"], "王五")
        self.assertIn("变更", r["message"])

    def test_old_change_info(self):
        rows = parse_manager_history(MANAGER_HTML)
        # 把"今天"推远，180 天窗口外
        r = eval_manager_change(rows, today=datetime(2028, 1, 1))
        self.assertFalse(r["changed_recently"])
        self.assertEqual(r["level"], "info")

    def test_config_mismatch_is_notice(self):
        """配置与线上不符 = notice（提示核对配置），不应与"近期真变更"混为同一级"""
        rows = parse_manager_history(MANAGER_HTML)
        r = eval_manager_change(rows, config_manager="赵六", today=datetime(2028, 1, 1))
        self.assertTrue(r["mismatch_config"])
        self.assertEqual(r["level"], "notice")
        self.assertIn("配置", r["message"])

    def test_recent_change_wins_over_mismatch(self):
        rows = parse_manager_history(MANAGER_HTML)
        r = eval_manager_change(rows, config_manager="赵六", today=datetime(2026, 9, 20))
        self.assertTrue(r["changed_recently"])
        self.assertEqual(r["level"], "warn")

    def test_missing_data_honest(self):
        r = eval_manager_change([])
        self.assertFalse(r["ok"])
        self.assertIn("暂缺", r["message"])
        self.assertNotIn("现任经理", r["message"])


class TestScaleEval(unittest.TestCase):
    @staticmethod
    def _rows(asset, pct):
        return [
            {"日期": "2026-06-30", "期末净资产（亿元）": str(asset), "净资产变动率": str(pct)},
            {"日期": "2026-03-31", "期末净资产（亿元）": str(asset), "净资产变动率": "-1.00%"},
        ]

    def test_safe(self):
        r = eval_scale_risk(self._rows(97.51, "2.10%"))
        self.assertTrue(r["ok"])
        self.assertEqual(r["level"], "safe")
        self.assertAlmostEqual(r["net_asset"], 97.51)

    def test_warn_mini_fund(self):
        r = eval_scale_risk(self._rows(1.5, "1.00%"))
        self.assertEqual(r["level"], "warn")
        self.assertIn("迷你基金", r["message"])

    def test_danger_liquidation_line(self):
        r = eval_scale_risk(self._rows(0.3, "1.00%"))
        self.assertEqual(r["level"], "danger")
        self.assertIn("清盘", r["message"])

    def test_big_drop_upgrade(self):
        r = eval_scale_risk(self._rows(10.0, "-45.00%"))
        self.assertIn(r["level"], ("warn", "danger"))
        self.assertIn("赎回压力", r["message"])

    def test_consecutive_down(self):
        rows = [
            {"日期": "2026-06-30", "期末净资产（亿元）": "10.0", "净资产变动率": "-5.00%"},
            {"日期": "2026-03-31", "期末净资产（亿元）": "10.5", "净资产变动率": "-6.00%"},
            {"日期": "2025-12-31", "期末净资产（亿元）": "11.2", "净资产变动率": "3.00%"},
        ]
        r = eval_scale_risk(rows)
        self.assertEqual(r["consecutive_down"], 2)
        self.assertEqual(r["level"], "warn")

    def test_missing_data_honest(self):
        r = eval_scale_risk([])
        self.assertFalse(r["ok"])
        self.assertIn("暂缺", r["message"])
        self.assertIsNone(r["net_asset"])

    def test_estimated_marker(self):
        """东财季度表用 * 标记未确认/估算值：数值要保留，但要提示"""
        rows = [{
            "日期": "2026-06-30",
            "期末净资产（亿元）": "122.23*",
            "净资产变动率": "25.81%",
        }]
        r = eval_scale_risk(rows)
        self.assertTrue(r["estimated"])
        self.assertAlmostEqual(r["net_asset"], 122.23)
        self.assertIn("估算", r["message"])

    def test_thresholds_constants(self):
        # 5000 万清盘线 / 2 亿迷你基金线，口径不得漂移
        self.assertEqual(SCALE_DANGER_YI, 0.5)
        self.assertEqual(SCALE_WARN_YI, 2.0)


if __name__ == "__main__":
    unittest.main()
