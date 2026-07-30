# -*- coding: utf-8 -*-
"""股票子系统集成测试

测试覆盖：
  - 生命周期（setup/teardown）
  - 完整预测流程（fetch -> analyze -> generate）
  - 降级模式（无akshare时模拟数据）
  - 复盘与状态查询
  - predict_full 便捷方法
  - 与彩票子系统的隔离性
"""
import unittest
import sys
import os

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from domains.stock.domain import StockDomain
from domains.lottery.domain import LotteryDomain
from core.context import get_current_subsystem


class TestStockDomainLifecycle(unittest.TestCase):
    """测试股票子系统生命周期"""

    def test_setup_initializes_successfully(self):
        """setup应成功初始化（降级模式）"""
        domain = StockDomain()
        result = domain.setup()
        self.assertTrue(result)
        self.assertTrue(domain._initialized)

    def test_teardown_cleans_up(self):
        """teardown应正确清理资源"""
        domain = StockDomain()
        domain.setup()
        result = domain.teardown()
        self.assertTrue(result)
        self.assertFalse(domain._initialized)

    def test_setup_idempotent(self):
        """多次setup不应崩溃"""
        domain = StockDomain()
        self.assertTrue(domain.setup())
        self.assertTrue(domain.setup())  # 再次setup不应失败


class TestStockDomainFetch(unittest.TestCase):
    """测试数据抓取"""

    def setUp(self):
        self.domain = StockDomain()
        self.domain.setup()

    def tearDown(self):
        self.domain.teardown()

    def test_fetch_default_indexes(self):
        """fetch默认返回3个指数数据"""
        result = self.domain.fetch()
        self.assertTrue(result["success"])
        self.assertEqual(len(result["data"]), 3)
        self.assertIn("sh000001", result["data"])
        self.assertIn("sz399001", result["data"])
        self.assertIn("sh000300", result["data"])

    def test_fetch_mock_mode(self):
        """fetch应返回数据（real或mock模式取决于akshare是否可用）"""
        result = self.domain.fetch()
        for sym, df in result["data"].items():
            self.assertGreater(len(df), 60)  # 无论real/mock都应有足够数据

    def test_fetch_custom_symbols(self):
        """fetch支持自定义股票代码"""
        result = self.domain.fetch(symbols=["sh000001"])
        self.assertTrue(result["success"])
        self.assertEqual(len(result["data"]), 1)


class TestStockDomainAnalyze(unittest.TestCase):
    """测试指标分析"""

    def setUp(self):
        self.domain = StockDomain()
        self.domain.setup()
        self.fetch_result = self.domain.fetch()

    def tearDown(self):
        self.domain.teardown()

    def test_analyze_returns_indicators(self):
        """analyze应返回技术指标"""
        result = self.domain.analyze(self.fetch_result["data"])
        self.assertEqual(result["status"], "ok")
        self.assertIn("results", result)

        for sym, r in result["results"].items():
            self.assertIn("indicators", r)
            self.assertIn("trend", r)
            self.assertIn("signals", r)

    def test_analyze_trend_direction(self):
        """趋势方向应为up/down/sideways之一"""
        result = self.domain.analyze(self.fetch_result["data"])
        for sym, r in result["results"].items():
            direction = r["trend"].get("direction")
            self.assertIn(direction, ["up", "down", "sideways", "unknown"])

    def test_analyze_subsystem_context(self):
        """分析应在stock子系统上下文中执行"""
        result = self.domain.analyze(self.fetch_result["data"])
        # 分析完成后，当前子系统应恢复
        self.assertEqual(get_current_subsystem(), "lottery")  # 默认是lottery


class TestStockDomainGenerate(unittest.TestCase):
    """测试方案生成"""

    def setUp(self):
        self.domain = StockDomain()
        self.domain.setup()
        fetch = self.domain.fetch()
        self.analysis = self.domain.analyze(fetch["data"])

    def tearDown(self):
        self.domain.teardown()

    def test_generate_returns_predictions(self):
        """generate应返回选股推荐"""
        result = self.domain.generate(params=self.analysis, top_n=3)
        self.assertEqual(result["status"], "ok")
        self.assertLessEqual(len(result["predictions"]), 3)

    def test_generate_actions_valid(self):
        """推荐action应为buy/hold/watch之一"""
        result = self.domain.generate(params=self.analysis, top_n=10)
        for pred in result["predictions"]:
            self.assertIn(pred["action"], ["buy", "hold", "watch"])
            self.assertTrue(0 <= pred["confidence"] <= 100)

    def test_generate_no_data(self):
        """无分析数据时应返回友好提示"""
        result = self.domain.generate(params=None)
        self.assertEqual(result["status"], "no_data")


class TestStockDomainReview(unittest.TestCase):
    """测试复盘功能"""

    def setUp(self):
        self.domain = StockDomain()
        self.domain.setup()

    def tearDown(self):
        self.domain.teardown()

    def test_review_empty_predictions(self):
        """空预测记录应返回零值"""
        result = self.domain.review(predictions=[])
        self.assertEqual(result["reviews"], 0)
        self.assertTrue(result["updated"])

    def test_review_with_predictions(self):
        """有预测记录时应计算指标"""
        predictions = [
            {"symbol": "sh000001", "action": "buy", "confidence": 80},
            {"symbol": "sz399001", "action": "hold", "confidence": 60},
        ]
        result = self.domain.review(predictions=predictions)
        self.assertEqual(result["reviews"], 2)
        self.assertIn("metrics", result)


class TestStockDomainStatus(unittest.TestCase):
    """测试状态查询"""

    def test_status_before_setup(self):
        """setup前状态应为未就绪"""
        domain = StockDomain()
        status = domain.status()
        self.assertFalse(status["ready"])
        self.assertEqual(status["domain_id"], "stock")

    def test_status_after_setup(self):
        """setup后状态应为就绪"""
        domain = StockDomain()
        domain.setup()
        status = domain.status()
        self.assertTrue(status["ready"])
        self.assertEqual(status["cache_size"], 0)
        domain.teardown()


class TestStockDomainFullFlow(unittest.TestCase):
    """测试完整预测流程"""

    def test_predict_full_mock_mode(self):
        """predict_full应在降级模式下完成全流程"""
        domain = StockDomain()
        result = domain.predict_full()
        self.assertIn("predictions", result)
        self.assertIn("summary", result)
        domain.teardown()


class TestStockLotteryIsolation(unittest.TestCase):
    """测试股票与彩票子系统隔离"""

    def test_domains_independent(self):
        """两个子系统的状态互不影响"""
        stock = StockDomain()
        lottery = LotteryDomain()

        stock.setup()
        lottery.setup()

        # 各自fetch不应影响对方
        stock_fetch = stock.fetch()
        lottery_fetch = lottery.fetch(lots=["双色球"])

        self.assertTrue(stock_fetch["success"])
        self.assertTrue(lottery_fetch["success"])

        # 子系统标识不同
        self.assertEqual(stock.status()["domain_id"], "stock")
        self.assertEqual(lottery.status()["domain_id"], "lottery")

        stock.teardown()
        lottery.teardown()


class TestStockDomainScreen(unittest.TestCase):
    """测试股票真实池筛选（多因子选股，替换原3指数空壳）"""

    def setUp(self):
        self.domain = StockDomain()
        self.domain.setup()
        # 强制模拟数据模式，避免测试中访问网络（筛选逻辑与数据模式无关）
        self.domain._fetcher = None

    def tearDown(self):
        self.domain.teardown()

    def test_screen_uses_default_pool(self):
        """screen 默认应使用 DEFAULT_STOCK_POOL（24只）"""
        result = self.domain.screen()
        self.assertTrue(result["success"])
        self.assertEqual(result["total_pool"], len(self.domain.DEFAULT_STOCK_POOL))
        self.assertIn(result["mode"], ("real", "mock"))

    def test_screen_returns_screened_list(self):
        """screen 应返回筛选后的股票列表，每条带名称与评分"""
        result = self.domain.screen(top_n=5)
        self.assertTrue(result["success"])
        self.assertLessEqual(len(result["screened"]), 5)
        for item in result["screened"]:
            self.assertIn("symbol", item)
            self.assertIn("name", item)
            self.assertTrue("score" in item or "total_score" in item)
            score_key = "score" if "score" in item else "total_score"
            self.assertGreaterEqual(item[score_key], 0)

    def test_screen_custom_pool(self):
        """screen 支持自定义股票池"""
        result = self.domain.screen(pool=[("600519", "贵州茅台"), ("000858", "五粮液")])
        self.assertTrue(result["success"])
        self.assertEqual(result["total_pool"], 2)

    def test_screen_stricter_criteria_fewer(self):
        """更严格的强度阈值应通过数更少或相等"""
        loose = self.domain.screen(criteria={"min_strength": 0, "require_signal": False})
        strict = self.domain.screen(criteria={"min_strength": 95, "require_signal": True})
        self.assertGreaterEqual(loose["passed"], strict["passed"])

    def test_screen_no_data(self):
        """数据获取失败时优雅返回 no_data"""
        # 模拟 fetch 失败
        self.domain.fetch = lambda *a, **k: {"success": False, "data": {}}
        result = self.domain.screen()
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "no_data")


class TestStockDomainBacktest(unittest.TestCase):
    """股票回测（P2-8 股基 API 端点落点）"""

    def setUp(self):
        self.domain = StockDomain()
        self.domain.setup()

    def tearDown(self):
        self.domain.teardown()

    def test_backtest_buy_hold_offline(self):
        """买入持有回测在离线 mock 数据下应能产出报告。"""
        result = self.domain.backtest(strategy="买入持有")
        self.assertTrue(result.get("success"), msg=result)
        self.assertIn("report", result)
        report = result["report"]
        # 报告应包含回测关键指标
        for key in ("final_value", "total_return", "max_drawdown", "sharpe_ratio"):
            self.assertIn(key, report)
        self.assertEqual(report.get("type"), "stock")

    def test_backtest_no_data_graceful(self):
        """无数据时优雅返回 no_data。"""
        self.domain._data_cache = {}
        self.domain.fetch = lambda *a, **k: {"success": True, "data": {}}
        result = self.domain.backtest()
        self.assertFalse(result.get("success"))
        self.assertEqual(result.get("status"), "no_data")


if __name__ == "__main__":
    unittest.main(verbosity=2)
