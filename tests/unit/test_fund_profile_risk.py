# -*- coding: utf-8 -*-
"""基金外围风险模块测试（JS-20260920-04 建，JS-20260920-08 扩）

测试内容：
  - HTML 解析：基金经理变动一览 / 规模变动 / 申购限额（限购额度）
  - 评估逻辑：经理变更预警、规模·清盘与暴增预警、限购对定投的影响与变化方向
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
    parse_purchase_limit,
    eval_manager_change,
    eval_scale_risk,
    eval_purchase_limit,
    FundProfileFetcher,
    SCALE_DANGER_YI,
    SCALE_WARN_YI,
    SCALE_SURGE_WARN_PCT,
)

# JS-20260923-02 批 1：日报配置与止盈两档制测试需要仓库根下的 scripts 模块
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
import pandas as pd  # noqa: E402  (check_take_profit 需要 pd.Series)
from scripts.daily_fund_monitor import (  # noqa: E402
    SignalDetector,
    FUND_CONFIG,
    TARGET_PROFIT_DEFAULT,
    WARN_LINE_DEFAULT,
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
        self.assertEqual(SCALE_SURGE_WARN_PCT, 100.0)


# ===========================================================================
# JS-20260920-08：限购额度解析/评估 + 规模暴增预警
# ===========================================================================
class TestPurchaseLimit(unittest.TestCase):
    """限购额度：解析 + 定投影响评估 + 变化检测"""

    def test_parse_yuan_cap(self):
        """270042 型：<span>单日累计购买上限2元</span>"""
        r = parse_purchase_limit('<span>单日累计购买上限2元</span>')
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["daily_limit_yuan"], 2.0)
        self.assertEqual(r["status"], "限大额")

    def test_parse_wan_cap(self):
        """011369 型：单日累计购买上限200.00万元 → 2,000,000 元"""
        r = parse_purchase_limit('<span>单日累计购买上限200.00万元</span>')
        self.assertAlmostEqual(r["daily_limit_yuan"], 2000000.0)

    def test_parse_open_no_cap(self):
        """无限额：走「开放申购」分支，daily_limit_yuan 必须是 None（不是 0）"""
        r = parse_purchase_limit('交易状态：<span>开放申购</span>')
        self.assertTrue(r["ok"])
        self.assertIsNone(r["daily_limit_yuan"])
        self.assertEqual(r["status"], "开放")

    def test_parse_paused(self):
        r = parse_purchase_limit('交易状态：<span>暂停申购</span>')
        self.assertIsNone(r["daily_limit_yuan"])
        self.assertEqual(r["status"], "暂停")

    def test_parse_empty_html_is_not_ok(self):
        r = parse_purchase_limit("")
        self.assertFalse(r["ok"])

    def test_eval_below_plan_is_warn(self):
        """限购 2 元 < 计划日投 100 元 → 定投执行受影响"""
        lim = {"ok": True, "daily_limit_yuan": 2, "status": "限大额"}
        r = eval_purchase_limit(lim, plan_investment_monthly=3000)
        self.assertEqual(r["level"], "warn")
        self.assertTrue(r["affected"])
        self.assertEqual(r["plan_daily"], 100)
        self.assertIn("无法全额执行", r["message"])

    def test_eval_sufficient_is_info(self):
        lim = {"ok": True, "daily_limit_yuan": 5000, "status": "限大额"}
        r = eval_purchase_limit(lim, plan_investment_monthly=3000)
        self.assertEqual(r["level"], "info")
        self.assertFalse(r["affected"])

    def test_eval_open_is_info(self):
        lim = {"ok": True, "daily_limit_yuan": None, "status": "开放"}
        r = eval_purchase_limit(lim, plan_investment_monthly=10000)
        self.assertEqual(r["level"], "info")
        self.assertIn("无单日限额", r["message"])

    def test_eval_paused_is_warn(self):
        lim = {"ok": True, "daily_limit_yuan": None, "status": "暂停"}
        r = eval_purchase_limit(lim)
        self.assertEqual(r["level"], "warn")

    def test_eval_change_note(self):
        lim = {"ok": True, "daily_limit_yuan": 2, "status": "限大额"}
        r = eval_purchase_limit(lim, plan_investment_monthly=3000, change="tighter")
        self.assertIn("收紧", r["message"])

    def test_limit_change_direction(self):
        f = FundProfileFetcher(enabled=False)
        self.assertEqual(f._limit_change(None, {"daily_limit_yuan": 2}), "new")
        self.assertEqual(f._limit_change({"daily_limit_yuan": 10}, {"daily_limit_yuan": 2}),
                         "tighter")
        self.assertEqual(f._limit_change({"daily_limit_yuan": 10}, {"daily_limit_yuan": 5000}),
                         "loosened")
        self.assertEqual(f._limit_change({"daily_limit_yuan": 10}, {"daily_limit_yuan": 10}),
                         "same")
        self.assertEqual(f._limit_change({"daily_limit_yuan": None}, {"daily_limit_yuan": 2}),
                         "changed")


class TestScaleSurge(unittest.TestCase):
    """规模暴增预警（原只判下跌，JS-20260920-08 补）"""

    def test_surge_upgrade_to_warn(self):
        rows = [{"日期": "2026-06-30", "期末净资产（亿元）": "90.16", "净资产变动率": "241.65%"}]
        r = eval_scale_risk(rows)
        self.assertEqual(r["level"], "warn")
        self.assertIn("规模显著扩张", r["message"])

    def test_moderate_growth_stays_safe(self):
        rows = [{"日期": "2026-06-30", "期末净资产（亿元）": "53.03", "净资产变动率": "44.83%"}]
        r = eval_scale_risk(rows)
        self.assertEqual(r["level"], "safe")

    def test_drop_still_wins(self):
        """暴跌 + 仍在迷你线下：drop 分支不受暴增分支影响"""
        rows = [{"日期": "2026-06-30", "期末净资产（亿元）": "1.2", "净资产变动率": "-40.00%"}]
        r = eval_scale_risk(rows)
        self.assertEqual(r["level"], "warn")
        self.assertIn("赎回压力", r["message"])


class TestPlanBuyAmount(unittest.TestCase):
    """单次买入定投口径（JS-20260923-02 批 1：修 017641 限购误报）"""

    def test_daily_invest_at_limit_is_ok(self):
        """日投 10 元 vs 限购 10 元 → 刚好满额可执行，不再误报"""
        lim = {"ok": True, "daily_limit_yuan": 10, "status": "限大额"}
        r = eval_purchase_limit(lim, plan_buy_amount=10)
        self.assertEqual(r["level"], "info")
        self.assertFalse(r["affected"])
        self.assertIn("计划单次买入 10 元", r["message"])

    def test_weekly_buy_over_limit_is_warn(self):
        """周投 70 元一次性买入 vs 单日限额 50 元 → 真实受影响，保留 warn"""
        lim = {"ok": True, "daily_limit_yuan": 50, "status": "限大额"}
        r = eval_purchase_limit(lim, plan_buy_amount=70)
        self.assertEqual(r["level"], "warn")
        self.assertTrue(r["affected"])

    def test_monthly_fallback_unchanged(self):
        """不传 plan_buy_amount 时保持旧 ÷30 口径（兼容旧调用方）"""
        lim = {"ok": True, "daily_limit_yuan": 2, "status": "限大额"}
        r = eval_purchase_limit(lim, plan_investment_monthly=3000)
        self.assertEqual(r["plan_daily"], 100)
        self.assertTrue(r["affected"])


class TestManagerConfigMatch(unittest.TestCase):
    """配置经理逐名匹配（JS-20260923-02 批 1：双经理不因分隔符不同误报 notice）"""

    def test_dual_manager_different_separator_not_mismatch(self):
        """配置「蔡唯峰、周岳洋」(顿号) vs 线上「蔡唯峰,周岳洋」(逗号) → 不算失配"""
        history = [{"基金经理": "蔡唯峰,周岳洋", "起始期": "2020-01-01", "任职回报": "12%"}]
        r = eval_manager_change(history, config_manager="蔡唯峰、周岳洋",
                                today=datetime(2026, 9, 23))
        self.assertFalse(r["mismatch_config"])
        self.assertEqual(r["level"], "info")

    def test_wrong_name_still_mismatch(self):
        """配置确实是离职前任 → 仍要报 mismatch"""
        history = [{"基金经理": "张明昕", "起始期": "2025-03-04", "任职回报": "30%"}]
        r = eval_manager_change(history, config_manager="周海栋",
                                today=datetime(2026, 9, 23))
        self.assertTrue(r["mismatch_config"])


class TestTakeProfitTwoLines(unittest.TestCase):
    """止盈两档制 + 不止盈 + 口径诚实化（JS-20260923-02 批 1）"""

    @staticmethod
    def _series():
        # 区间首日净值 1.0：现值 1.15 → +15%（过 12% 预警、未到 16.4% 止盈）
        return pd.Series([1.0, 1.1, 1.2])

    def test_warn_line_triggers_before_target(self):
        r = SignalDetector.check_take_profit(1.15, 0, 0.164, self._series(),
                                             warn_line=0.12)
        self.assertTrue(r["warn"])
        self.assertFalse(r["signal"])
        self.assertIn("预警线", r["message"])
        self.assertIn("非持仓实际收益", r["message"])

    def test_signal_at_target(self):
        r = SignalDetector.check_take_profit(1.20, 0, 0.164, self._series(),
                                             warn_line=0.12)
        self.assertTrue(r["signal"])
        self.assertIn("止盈目标", r["message"])

    def test_none_target_means_no_take_profit(self):
        """015942 不止盈：中短债常态收益（+5%）不触预警，只显示区间收益"""
        r = SignalDetector.check_take_profit(1.05, 0, None, self._series(),
                                             warn_line=0.12)
        self.assertFalse(r["signal"])
        self.assertFalse(r["warn"])
        self.assertIn("不止盈", r["message"])
        self.assertIsNone(r["target_return"])

    def test_warn_without_target_no_fake_take_profit_line(self):
        """不止盈基金若真涨过预警线：文案不得编造止盈线"""
        r = SignalDetector.check_take_profit(1.20, 0, None, self._series(),
                                             warn_line=0.12)
        self.assertTrue(r["warn"])
        self.assertIn("该基金设定不止盈", r["message"])
        self.assertNotIn("止盈线", r["message"])

    def test_config_two_tier_and_dca(self):
        """8 只全部两档制 + 定投计划 + 4 只经理名修正 + 015942 不止盈"""
        plan = {f["code"]: f for f in FUND_CONFIG}
        for code, f in plan.items():
            if f["target_profit"] is not None:
                self.assertEqual(f["target_profit"], TARGET_PROFIT_DEFAULT, code)
            self.assertEqual(f["warn_line"], WARN_LINE_DEFAULT, code)
        self.assertIsNone(plan["015942"]["target_profit"])
        dca = {c: (f.get("dca_amount"), f.get("dca_freq"))
               for c, f in plan.items()}
        self.assertEqual(dca["005698"], (10, "daily"))
        self.assertEqual(dca["017641"], (10, "daily"))
        self.assertEqual(dca["270042"], (10, "daily"))
        self.assertEqual(dca["011369"], (70, "weekly"))
        self.assertEqual(dca["015942"], (70, "weekly"))
        self.assertEqual(dca["009051"], (70, "weekly"))
        self.assertEqual(dca["000216"], (10, "weekly"))
        self.assertEqual(dca["013308"], (20, "weekly"))
        fixed = {"005698": "李湘杰", "011369": "张明昕",
                 "015942": "蔡唯峰、周岳洋", "013308": "刘依姗、成曦"}
        for code, name in fixed.items():
            self.assertEqual(plan[code]["manager"], name, code)
        self.assertEqual(plan["005698"]["related_index"], "全球科技(主动)")


if __name__ == "__main__":
    unittest.main()
