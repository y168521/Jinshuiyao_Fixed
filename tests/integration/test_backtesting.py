# -*- coding: utf-8 -*-
"""回测框架集成测试

测试覆盖：
  - BacktestEngine 股票回测
  - BacktestEngine 彩票回测
  - MetricsCalculator 指标计算
  - A/B策略对比
  - 状态重置
"""
import unittest
import sys
import os
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backtesting.engine import (
    BacktestEngine,
    fund_strategy_buy_hold,
    fund_strategy_dca,
    fund_strategy_ma_timing,
    stock_strategy_buy_hold,
    FUND_STRATEGIES,
)
from backtesting.metrics import MetricsCalculator


class TestBacktestEngineStock(unittest.TestCase):
    """测试股票回测"""

    def setUp(self):
        self.engine = BacktestEngine(name="test_stock", initial_capital=100000)

    def _generate_mock_stock_data(self, symbol, days=30, trend="random"):
        """生成模拟股票数据"""
        base = 100.0
        data = []
        for i in range(days):
            if trend == "up":
                change = random.gauss(0.005, 0.015)
            elif trend == "down":
                change = random.gauss(-0.005, 0.015)
            else:
                change = random.gauss(0, 0.02)

            if i > 0:
                base = data[-1]["close"] * (1 + change)
            else:
                base = base * (1 + change)

            open_p = base * (1 + random.gauss(0, 0.005))
            close_p = base
            high_p = max(open_p, close_p) * (1 + abs(random.gauss(0, 0.01)))
            low_p = min(open_p, close_p) * (1 - abs(random.gauss(0, 0.01)))

            data.append({
                "date": f"2024-01-{i+1:02d}",
                "open": round(open_p, 2),
                "close": round(close_p, 2),
                "high": round(high_p, 2),
                "low": round(low_p, 2),
                "volume": int(random.uniform(1e6, 1e8)),
            })
        return data

    def test_run_stock_basic(self):
        """基本股票回测应完成"""
        data = {
            "TEST001": self._generate_mock_stock_data("TEST001", days=20),
        }

        def strategy(ctx, sym, row, df):
            if ctx["day"] == 5:
                return {"action": "buy", "weight": 0.5}
            if ctx["day"] == 15:
                return {"action": "sell"}
            return {"action": "hold"}

        result = self.engine.run_stock(data, strategy)
        self.assertIn("total_return", result)
        self.assertIn("max_drawdown", result)
        self.assertGreaterEqual(len(result["trades"]), 2)

    def test_run_stock_with_multiple_symbols(self):
        """多股票回测"""
        data = {
            "A": self._generate_mock_stock_data("A", days=15, trend="up"),
            "B": self._generate_mock_stock_data("B", days=15, trend="down"),
        }

        def strategy(ctx, sym, row, df):
            if ctx["day"] == 3:
                return {"action": "buy", "weight": 0.3}
            if ctx["day"] == 12:
                return {"action": "sell"}
            return {"action": "hold"}

        result = self.engine.run_stock(data, strategy)
        self.assertTrue(result["trade_count"] >= 4)  # 每只股票买卖各一次

    def test_run_stock_no_trades(self):
        """无交易时回测应正常返回"""
        data = {
            "TEST": self._generate_mock_stock_data("TEST", days=10),
        }

        def strategy(ctx, sym, row, df):
            return {"action": "hold"}

        result = self.engine.run_stock(data, strategy)
        self.assertEqual(result["trade_count"], 0)
        self.assertEqual(result["total_return"], 0.0)

    def test_stock_strategy_buy_hold_buys_once(self):
        """stock_strategy_buy_hold 应在首个交易日满仓买入一次后一直持有。"""
        data = {
            "TEST": self._generate_mock_stock_data("TEST", days=15, trend="up"),
        }
        result = self.engine.run_stock(data, stock_strategy_buy_hold)
        # 买入持有：每个标的恰好一次买入（无卖出）
        self.assertEqual(result["trade_count"], 1)
        self.assertGreater(result["final_value"], 0)

    def test_engine_reset(self):
        """重置后状态应清空"""
        data = {
            "TEST": self._generate_mock_stock_data("TEST", days=10),
        }

        def strategy(ctx, sym, row, df):
            if ctx["day"] == 2:
                return {"action": "buy", "weight": 0.5}
            return {"action": "hold"}

        self.engine.run_stock(data, strategy)
        self.assertGreater(len(self.engine.trades), 0)

        self.engine.reset()
        self.assertEqual(len(self.engine.trades), 0)
        self.assertEqual(self.engine.cash, self.engine.initial_capital)


class TestBacktestEngineLottery(unittest.TestCase):
    """测试彩票回测"""

    def setUp(self):
        self.engine = BacktestEngine(name="test_lottery")

    def test_run_lottery_basic(self):
        """基本彩票回测（修正后：位置/顺序感知判定）"""
        history = [
            {"period": i, "nums": f"0{i%10},{(i+1)%10},{(i+2)%10}", "time": f"2024-01-{i+1:02d}"}
            for i in range(1, 21)
        ]

        def predictor(data, lot=None):
            # 简单预测：返回最后一条数据的号码（用于验证“直选/组选精确匹配”判定）
            if data:
                last = data[-1]
                return [{"nums": last["nums"]}]
            return [{"nums": "1,2,3"}]

        # 3D 类彩种：用组选/直选精确匹配；predictor 返回训练集末条（==目标期前一条），
        # 与目标期不同 → 不应命中，命中率应为 0（验证判定未被“任中1码”虚高）。
        result = self.engine.run_lottery(history, predictor, lot="福彩3D", top_n=1, min_hit=3)
        self.assertEqual(result["type"], "lottery")
        self.assertIn("hit_rate", result)
        self.assertGreaterEqual(result["total_tests"], 0)
        self.assertLessEqual(result["hit_rate"], 0.0)  # 预测≠实际开奖，命中率必须真实为0

    def test_run_lottery_empty_history(self):
        """空历史数据应不崩溃"""
        def predictor(data, lot=None):
            return [{"nums": "1,2,3"}]

        result = self.engine.run_lottery([], predictor, lot="测试彩种")
        self.assertEqual(result["total_tests"], 0)


class TestMetricsCalculator(unittest.TestCase):
    """测试指标计算器"""

    def test_return_metrics(self):
        """收益指标计算"""
        daily = [
            {"date": "2024-01-01", "value": 100000},
            {"date": "2024-01-02", "value": 102000},
            {"date": "2024-01-03", "value": 101000},
            {"date": "2024-01-04", "value": 105000},
        ]
        result = MetricsCalculator.return_metrics(daily, 100000)
        self.assertEqual(result["total_return"], 0.05)
        self.assertEqual(result["final_value"], 105000)

    def test_risk_metrics(self):
        """风险指标计算"""
        daily = [
            {"date": "2024-01-01", "value": 100000},
            {"date": "2024-01-02", "value": 105000},
            {"date": "2024-01-03", "value": 98000},
            {"date": "2024-01-04", "value": 102000},
        ]
        returns = MetricsCalculator._calc_returns(daily)
        result = MetricsCalculator.risk_metrics(daily, returns)
        self.assertIn("max_drawdown", result)
        self.assertIn("sharpe_ratio", result)
        self.assertGreaterEqual(result["max_drawdown"], 0)

    def test_max_drawdown_detail(self):
        """最大回撤区间计算"""
        daily = [
            {"date": "2024-01-01", "value": 100},
            {"date": "2024-01-02", "value": 110},
            {"date": "2024-01-03", "value": 90},
            {"date": "2024-01-04", "value": 95},
        ]
        dd, start, end = MetricsCalculator._max_drawdown_detail(daily)
        self.assertAlmostEqual(dd, 20 / 110, places=4)
        self.assertEqual(start, "2024-01-02")
        self.assertEqual(end, "2024-01-03")

    def test_trade_metrics(self):
        """交易指标计算"""
        trades = [
            {"date": "2024-01-01", "action": "buy", "shares": 100, "price": 10, "cost": 1000},
            {"date": "2024-01-02", "action": "sell", "shares": 100, "price": 15, "revenue": 1500, "cost": 1000},
            {"date": "2024-01-03", "action": "buy", "shares": 100, "price": 12, "cost": 1200},
            {"date": "2024-01-04", "action": "sell", "shares": 100, "price": 10, "revenue": 1000, "cost": 1200},
        ]
        result = MetricsCalculator.trade_metrics(trades)
        self.assertEqual(result["total_trades"], 4)
        self.assertEqual(result["win_count"], 1)
        self.assertEqual(result["loss_count"], 1)

    def test_return_distribution(self):
        """收益率分布"""
        returns = [0.01, -0.02, 0.015, -0.005, 0.03, -0.01]
        result = MetricsCalculator.return_distribution(returns)
        self.assertEqual(result["count"], 6)
        self.assertEqual(result["positive_days"], 3)
        self.assertEqual(result["negative_days"], 3)

    def test_compare_strategies(self):
        """A/B策略对比"""
        result_a = {"total_return": 0.15, "max_drawdown": 0.05, "sharpe_ratio": 1.2, "win_rate": 0.6, "trade_count": 10}
        result_b = {"total_return": 0.10, "max_drawdown": 0.08, "sharpe_ratio": 0.8, "win_rate": 0.5, "trade_count": 10}
        result = MetricsCalculator.compare_strategies(result_a, result_b)
        self.assertEqual(result["overall_winner"], "A")
        self.assertIn("recommendation", result)

    def test_calculate_all(self):
        """全套指标计算"""
        daily = [
            {"date": "2024-01-01", "value": 100000},
            {"date": "2024-01-02", "value": 102000},
            {"date": "2024-01-03", "value": 101000},
            {"date": "2024-01-04", "value": 105000},
        ]
        trades = [
            {"date": "2024-01-01", "action": "buy", "cost": 50000},
            {"date": "2024-01-04", "action": "sell", "revenue": 52000},
        ]
        result = MetricsCalculator.calculate_all(daily, trades, 100000)
        self.assertIn("returns", result)
        self.assertIn("risk", result)
        self.assertIn("trades", result)
        self.assertIn("distribution", result)


class TestBacktestEngineFund(unittest.TestCase):
    """测试基金净值回测（run_fund）"""

    def setUp(self):
        self.engine = BacktestEngine(name="test_fund", initial_capital=100000)

    def _gen_nav(self, code, days=60, annual=0.10, vol=0.12):
        """生成模拟基金净值（list[dict]，含 净值日期/单位净值）"""
        import random
        from datetime import date, timedelta
        random.seed(hash(code) % 1000)
        nav = 1.0
        rows = []
        start = date(2023, 1, 1)
        for i in range(days):
            d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
            shock = random.gauss(annual / 252, vol / (252 ** 0.5))
            nav = nav * (1 + shock)
            rows.append({"净值日期": d, "单位净值": round(nav, 4)})
        return rows

    def test_run_fund_buy_hold(self):
        """买入持有：首日满仓买入，应至少有1笔交易且产出指标"""
        result = self.engine.run_fund(
            {"F001": self._gen_nav("F001", 60)}, fund_strategy_buy_hold
        )
        self.assertEqual(result["type"], "fund")
        self.assertIn("total_return", result)
        self.assertIn("max_drawdown", result)
        self.assertGreater(result["trade_count"], 0)

    def test_run_fund_dca(self):
        """定投：每5日买入，应有多笔交易"""
        result = self.engine.run_fund(
            {"F002": self._gen_nav("F002", 60)}, fund_strategy_dca
        )
        self.assertEqual(result["type"], "fund")
        self.assertGreater(result["trade_count"], 5)

    def test_run_fund_ma_timing(self):
        """均线择时：应正常产出回测报告"""
        result = self.engine.run_fund(
            {"F003": self._gen_nav("F003", 80)}, fund_strategy_ma_timing
        )
        self.assertEqual(result["type"], "fund")
        self.assertIn("total_return", result)

    def test_run_fund_empty(self):
        """空净值数据应返回错误而非崩溃"""
        result = self.engine.run_fund({}, fund_strategy_buy_hold)
        self.assertIn("error", result)

    def test_fund_strategies_registered(self):
        """三种内置策略应全部注册"""
        for k in ("买入持有", "均线择时", "定投"):
            self.assertIn(k, FUND_STRATEGIES)


class TestBacktestEngineDCA(unittest.TestCase):
    """定投模拟引擎 simulate_dca 测试（微笑曲线：累计份额/成本摊薄/收益率曲线）"""

    def _nav(self, n, gen):
        """生成 {date, close} 净值序列（date 零填充保证字符串排序=时间顺序）"""
        return [{"date": f"d{i:03d}", "close": round(gen(i), 4)} for i in range(n)]

    def test_simulate_dca_rising(self):
        """上涨净值 → 正收益，累计份额为正，曲线长度=数据长度"""
        nav = self._nav(60, lambda i: 1.0 + i * 0.01)
        eng = BacktestEngine()
        r = eng.simulate_dca(nav, amount_per_period=1000, every=5, fee_rate=0.0)
        self.assertNotIn("error", r)
        self.assertEqual(r["type"], "dca")
        self.assertGreater(r["total_shares"], 0)
        self.assertEqual(r["num_purchases"], 12)  # i=1,6,...,56
        self.assertGreater(r["total_return"], 0)
        self.assertEqual(len(r["curve"]), 60)
        # 平均成本 = 总投入 / 累计份额
        self.assertAlmostEqual(r["avg_cost"], r["total_invested"] / r["total_shares"], places=3)

    def test_simulate_dca_falling(self):
        """下跌净值 → 负收益，但仍持续买入摊薄份额（微笑曲线左半段）"""
        nav = self._nav(60, lambda i: 2.0 - i * 0.02)
        eng = BacktestEngine()
        r = eng.simulate_dca(nav, amount_per_period=1000, every=5, fee_rate=0.0)
        self.assertLess(r["total_return"], 0)
        self.assertGreater(r["total_shares"], 0)

    def test_simulate_dca_empty(self):
        """空净值数据应返回错误而非崩溃"""
        eng = BacktestEngine()
        r = eng.simulate_dca([], amount_per_period=1000)
        self.assertIn("error", r)

    def test_simulate_dca_dict_form(self):
        """{code: df} 字典形式应自动取第一只基金"""
        nav = self._nav(30, lambda i: 1.0 + i * 0.005)
        eng = BacktestEngine()
        r = eng.simulate_dca({"000001": nav}, amount_per_period=1000, every=5, fee_rate=0.0)
        self.assertNotIn("error", r)
        self.assertEqual(r["num_purchases"], 6)  # i=1,6,...,26

    def test_simulate_dca_every1(self):
        """every=1 → 每个交易日定投"""
        nav = self._nav(20, lambda i: 1.0 + i * 0.01)
        eng = BacktestEngine()
        r = eng.simulate_dca(nav, amount_per_period=1000, every=1, fee_rate=0.0)
        self.assertEqual(r["num_purchases"], 20)

    def test_simulate_dca_fee_lowers_shares(self):
        """申购费计入成本 → 高费率买到更少份额"""
        nav = self._nav(10, lambda i: 1.0)
        r0 = BacktestEngine().simulate_dca(nav, amount_per_period=1000, every=1, fee_rate=0.0)
        r1 = BacktestEngine().simulate_dca(nav, amount_per_period=1000, every=1, fee_rate=0.15)
        self.assertLess(r1["total_shares"], r0["total_shares"])
        # fee=0 时份额 = 金额 / 净值
        self.assertAlmostEqual(r0["total_shares"], 10000.0, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
