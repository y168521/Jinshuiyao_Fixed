# -*- coding: utf-8 -*-
"""基金子系统单元测试

测试内容：
  1. FundAnalyzer 单元测试（不依赖外部数据）
  2. FundDomain 基本测试（用 mock 替代 fetcher）

注意：使用 unittest.TestCase 格式，测试数据用手动构造。
"""
import os
import sys
import unittest

# 确保项目根目录在 sys.path 中
_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.normpath(os.path.join(_this_dir, "..", ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

# 尝试导入 pandas，不可用时降级
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

from domains.fund.analyzer import FundAnalyzer
from domains.fund.domain import FundDomain
from domains.base import DomainBase


# ===========================================================================
# 辅助：构造测试数据
# ===========================================================================

def _make_nav_list(start=1.0, daily_return=0.001, days=300):
    """构造一个稳定上涨的净值序列（纯 Python 列表）"""
    navs = []
    nav = start
    for _ in range(days):
        nav = nav * (1 + daily_return)
        navs.append(round(nav, 4))
    return navs


def _make_nav_with_drawdown():
    """构造一个有明显回撤的净值序列（先涨后跌再修复）"""
    navs = []
    # 上涨阶段：1.0 -> 1.5（100天）
    nav = 1.0
    for _ in range(100):
        nav *= 1.00405
        navs.append(round(nav, 4))
    # 下跌阶段：1.5 -> 1.0（50天，最大回撤约33%）
    for _ in range(50):
        nav *= 0.992
        navs.append(round(nav, 4))
    # 修复阶段：1.0 -> 1.6（100天）
    for _ in range(100):
        nav *= 1.0047
        navs.append(round(nav, 4))
    return navs


def _make_dates(days=300):
    """构造日期列表"""
    from datetime import datetime, timedelta
    dates = []
    d = datetime.now() - timedelta(days=days)
    for _ in range(days):
        d += timedelta(days=1)
        dates.append(d.strftime("%Y-%m-%d"))
    return dates


def _make_nav_df(navs, dates=None):
    """构造净值 DataFrame（如果 pandas 可用）"""
    if not PANDAS_AVAILABLE:
        return None
    if dates is None:
        dates = _make_dates(len(navs))
    return pd.DataFrame({
        "净值日期": dates,
        "单位净值": navs,
        "累计净值": [n * 1.2 for n in navs],
        "日增长率": [0.0] + [
            round((navs[i] - navs[i-1]) / navs[i-1] * 100, 2)
            for i in range(1, len(navs))
        ],
    })


def _make_holdings_df():
    """构造持仓 DataFrame"""
    if not PANDAS_AVAILABLE:
        return None
    return pd.DataFrame([
        {"股票代码": "600519", "股票名称": "贵州茅台", "占净值比例": 9.85},
        {"股票代码": "000858", "股票名称": "五粮液", "占净值比例": 8.32},
        {"股票代码": "601318", "股票名称": "中国平安", "占净值比例": 6.75},
        {"股票代码": "000333", "股票名称": "美的集团", "占净值比例": 5.42},
        {"股票代码": "600036", "股票名称": "招商银行", "占净值比例": 4.98},
        {"股票代码": "002594", "股票名称": "比亚迪", "占净值比例": 4.56},
        {"股票代码": "300750", "股票名称": "宁德时代", "占净值比例": 4.21},
        {"股票代码": "601899", "股票名称": "紫金矿业", "占净值比例": 3.89},
        {"股票代码": "002415", "股票名称": "海康威视", "占净值比例": 3.56},
        {"股票代码": "600900", "股票名称": "长江电力", "占净值比例": 3.21},
    ])


# ===========================================================================
# FundAnalyzer 单元测试
# ===========================================================================

class TestFundAnalyzer(unittest.TestCase):
    """基金分析引擎单元测试

    所有测试均使用手动构造的数据，不依赖外部数据源。
    """

    @classmethod
    def setUpClass(cls):
        cls.analyzer = FundAnalyzer()

    # ---------------------------------------------------------------
    # 收益率计算
    # ---------------------------------------------------------------

    def test_calculate_returns_basic(self):
        """测试基础收益率计算：稳定上涨的净值序列"""
        navs = _make_nav_list(start=1.0, daily_return=0.001, days=300)
        returns = self.analyzer.calculate_returns(navs)

        # 必须包含的关键字段
        required_keys = ["近1周", "近1月", "近3月", "近6月", "近1年", "近3年",
                         "今年来", "成立来", "年化收益率"]
        for key in required_keys:
            self.assertIn(key, returns, f"收益率结果缺少字段: {key}")

        # 稳定上涨 → 所有周期收益率应为正数
        self.assertGreater(returns["近1周"], 0)
        self.assertGreater(returns["近1月"], 0)
        self.assertGreater(returns["近3月"], 0)
        self.assertGreater(returns["近6月"], 0)
        self.assertGreater(returns["成立来"], 0)
        self.assertGreater(returns["年化收益率"], 0)

        # 长周期收益率应大于短周期（持续上涨假设下）
        self.assertGreater(returns["近6月"], returns["近1月"])
        self.assertGreater(returns["成立来"], returns["近1年"])

    def test_calculate_returns_with_dates(self):
        """测试带日期参数的收益率计算"""
        navs = _make_nav_list(days=300)
        dates = _make_dates(300)
        returns = self.analyzer.calculate_returns(navs, dates)

        self.assertIn("今年来", returns)
        self.assertIsInstance(returns["今年来"], (int, float))

    def test_calculate_returns_insufficient_data(self):
        """测试数据不足时返回错误"""
        result = self.analyzer.calculate_returns([])
        self.assertIn("error", result)

        result = self.analyzer.calculate_returns([1.0, 1.1])
        self.assertIn("error", result)

    def test_calculate_returns_negative(self):
        """测试下跌行情的收益率计算"""
        navs = _make_nav_list(start=2.0, daily_return=-0.002, days=100)
        returns = self.analyzer.calculate_returns(navs)

        self.assertLess(returns["近1月"], 0)
        self.assertLess(returns["成立来"], 0)
        self.assertLess(returns["年化收益率"], 0)

    # ---------------------------------------------------------------
    # 风险评估
    # ---------------------------------------------------------------

    def test_calculate_risk_basic(self):
        """测试风险评估：波动率、最大回撤等指标"""
        navs = _make_nav_with_drawdown()
        risk = self.analyzer.calculate_risk(navs)

        required_keys = ["波动率(年化)", "最大回撤", "最大回撤期数",
                         "下行波动率", "正收益占比", "盈亏比"]
        for key in required_keys:
            self.assertIn(key, risk, f"风险结果缺少字段: {key}")

        # 波动率应为正数（百分比）
        self.assertGreater(risk["波动率(年化)"], 0)
        self.assertGreater(risk["下行波动率"], 0)

        # 最大回撤应为正数（表示回撤深度百分比）
        self.assertGreater(risk["最大回撤"], 0)

        # 正收益占比在 0-100 之间
        self.assertGreaterEqual(risk["正收益占比"], 0)
        self.assertLessEqual(risk["正收益占比"], 100)

        # 最大回撤期数应为正整数
        self.assertGreater(risk["最大回撤期数"], 0)
        self.assertIsInstance(risk["最大回撤期数"], int)

    def test_calculate_risk_insufficient_data(self):
        """测试风险评估数据不足"""
        result = self.analyzer.calculate_risk([])
        self.assertIn("error", result)

        result = self.analyzer.calculate_risk([1.0, 1.1, 1.2])
        self.assertIn("error", result)

    def test_calculate_risk_stable(self):
        """测试极稳定净值的风险指标（低波动）"""
        # 极小幅稳定上涨
        navs = _make_nav_list(start=1.0, daily_return=0.0001, days=200)
        risk = self.analyzer.calculate_risk(navs)

        # 波动率应该很低
        self.assertLess(risk["波动率(年化)"], 10)

    # ---------------------------------------------------------------
    # 夏普比率
    # ---------------------------------------------------------------

    def test_calculate_sharpe_basic(self):
        """测试夏普比率计算"""
        navs = _make_nav_list(start=1.0, daily_return=0.001, days=300)
        sharpe_result = self.analyzer.calculate_sharpe(navs)

        required_keys = ["夏普比率", "索提诺比率", "卡玛比率",
                         "特雷诺比率", "信息比率", "年化超额收益"]
        for key in required_keys:
            self.assertIn(key, sharpe_result, f"夏普比率结果缺少字段: {key}")

        # 稳定上涨 → 夏普比率应为正
        self.assertGreater(sharpe_result["夏普比率"], 0)
        self.assertGreater(sharpe_result["年化超额收益"], 0)

        # 特雷诺比率和信息比率因缺少基准数据应为 None
        self.assertIsNone(sharpe_result["特雷诺比率"])
        self.assertIsNone(sharpe_result["信息比率"])

    def test_calculate_sharpe_custom_risk_free(self):
        """测试自定义无风险利率"""
        navs = _make_nav_list(days=300)
        result_low = self.analyzer.calculate_sharpe(navs, risk_free=0.01)
        result_high = self.analyzer.calculate_sharpe(navs, risk_free=0.05)

        # 无风险利率越高，夏普比率越低
        self.assertGreater(result_low["夏普比率"], result_high["夏普比率"])

    def test_calculate_sharpe_insufficient_data(self):
        """测试夏普比率数据不足"""
        result = self.analyzer.calculate_sharpe([])
        self.assertIn("error", result)

        result = self.analyzer.calculate_sharpe([1.0, 1.1, 1.2])
        self.assertIn("error", result)

    # ---------------------------------------------------------------
    # 回撤分析
    # ---------------------------------------------------------------

    def test_calculate_drawdown_basic(self):
        """测试回撤分析"""
        navs = _make_nav_with_drawdown()
        dd = self.analyzer.calculate_drawdown(navs)

        self.assertIn("最大回撤", dd)
        self.assertIn("回撤次数", dd)
        self.assertIn("平均回撤", dd)

        # 最大回撤应为正数（表示回撤深度百分比）
        self.assertGreater(dd["最大回撤"], 0)

        # 回撤次数 >= 0
        self.assertGreaterEqual(dd["回撤次数"], 0)

    def test_calculate_drawdown_with_dates(self):
        """测试带日期的回撤分析"""
        navs = _make_nav_with_drawdown()
        dates = _make_dates(len(navs))
        dd = self.analyzer.calculate_drawdown(navs, dates)

        self.assertIn("最大回撤开始", dd)
        self.assertIn("最大回撤底部", dd)
        # 该序列有修复，应该有修复日期
        self.assertIn("最大回撤修复日期", dd)
        self.assertIn("修复天数(交易日)", dd)

    def test_calculate_drawdown_unrecovered(self):
        """测试尚未修复的回撤"""
        # 构造一个下跌后未修复的序列
        navs = []
        nav = 1.0
        for _ in range(50):
            nav *= 1.005
            navs.append(round(nav, 4))
        for _ in range(50):
            nav *= 0.99
            navs.append(round(nav, 4))

        dates = _make_dates(len(navs))
        dd = self.analyzer.calculate_drawdown(navs, dates)

        self.assertEqual(dd.get("修复状态"), "尚未修复")
        self.assertIn("持续天数(交易日)", dd)

    def test_calculate_drawdown_insufficient_data(self):
        """测试回撤分析数据不足"""
        result = self.analyzer.calculate_drawdown([])
        self.assertIn("error", result)

    # ---------------------------------------------------------------
    # 综合评分
    # ---------------------------------------------------------------

    def test_composite_score_good_fund(self):
        """测试优质基金的综合评分"""
        # 构造一个好基金的分析结果
        analysis = {
            "returns": {
                "年化收益率": 20.0,
                "近1年": 22.0,
            },
            "risk": {
                "最大回撤": -10.0,
                "波动率(年化)": 15.0,
            },
            "risk_adjusted": {
                "夏普比率": 1.5,
            },
        }
        score = self.analyzer.composite_score(analysis)

        self.assertIn("总分", score)
        self.assertIn("收益得分", score)
        self.assertIn("风险得分", score)
        self.assertIn("性价比得分", score)
        self.assertIn("等级", score)
        self.assertIn("建议", score)

        # 好基金总分应该较高
        self.assertGreater(score["总分"], 60)
        # 等级应该在 A+/A/B 级别
        self.assertIn(score["等级"], ("A+", "A", "B"))

    def test_composite_score_poor_fund(self):
        """测试差基金的综合评分"""
        analysis = {
            "returns": {"年化收益率": -10.0},
            "risk": {"最大回撤": -40.0},
            "risk_adjusted": {"夏普比率": -0.5},
        }
        score = self.analyzer.composite_score(analysis)

        self.assertLess(score["总分"], 50)
        self.assertIn(score["等级"], ("C", "D"))

    def test_composite_score_error_input(self):
        """测试错误输入的综合评分"""
        score = self.analyzer.composite_score(None)
        self.assertEqual(score["总分"], 0)
        self.assertEqual(score["等级"], "N/A")

        score = self.analyzer.composite_score({"error": "数据不足"})
        self.assertEqual(score["总分"], 0)

    def test_composite_score_range(self):
        """测试综合评分范围在0-100之间"""
        # 构造多种不同表现的基金
        test_cases = [
            {"returns": {"年化收益率": 50}, "risk": {"最大回撤": -5},
             "risk_adjusted": {"夏普比率": 3.0}},
            {"returns": {"年化收益率": -30}, "risk": {"最大回撤": -60},
             "risk_adjusted": {"夏普比率": -1.5}},
            {"returns": {"年化收益率": 5}, "risk": {"最大回撤": -15},
             "risk_adjusted": {"夏普比率": 0.5}},
        ]
        for case in test_cases:
            score = self.analyzer.composite_score(case)
            self.assertGreaterEqual(score["总分"], 0)
            self.assertLessEqual(score["总分"], 100)

    # ---------------------------------------------------------------
    # 综合净值分析入口
    # ---------------------------------------------------------------

    @unittest.skipUnless(PANDAS_AVAILABLE, "pandas 不可用，跳过 DataFrame 测试")
    def test_analyze_nav_with_dataframe(self):
        """测试使用 DataFrame 的综合净值分析"""
        navs = _make_nav_list(days=300)
        df = _make_nav_df(navs)
        result = self.analyzer.analyze_nav(df)

        self.assertIn("returns", result)
        self.assertIn("risk", result)
        self.assertIn("risk_adjusted", result)
        self.assertIn("drawdown", result)
        self.assertIn("summary", result)
        self.assertNotIn("error", result)

    def test_analyze_nav_empty(self):
        """测试空数据的净值分析"""
        result = self.analyzer.analyze_nav(None)
        self.assertIn("error", result)

    def test_analyze_nav_too_short(self):
        """测试数据量不足的净值分析"""
        navs = _make_nav_list(days=10)
        result = self.analyzer.analyze_nav(
            [{"单位净值": n, "净值日期": "2026-01-01"} for n in navs]
        )
        self.assertIn("error", result)


    # ---------------------------------------------------------------
    # 基金经理任职年限（真实数据优先 · 修复成立日期冒充任职期）
    # ---------------------------------------------------------------

    def test_manager_tenure_uses_provided_tenure_date(self):
        """任职日期应优先于成立日期（不再用成立日期冒充任职期）"""
        info = {
            "基金经理": "张三",
            "基金规模(亿元)": 100,
            "成立日期": "2005-01-01",   # 基金成立很久
            "任职日期": "2020-06-01",   # 经理 2020 年才上任
        }
        # 不传 code → 不会联网，直接用任职日期
        result = self.analyzer.evaluate_manager(info)
        # 2020-06-01 至今约 6 年，而非 2005 成立至今的 21 年
        self.assertGreater(result["任职年限"], 4)
        self.assertLess(result["任职年限"], 8)
        self.assertEqual(result["任职年限来源"], "provided")

    def test_manager_tenure_falls_back_to_founding_when_no_tenure(self):
        """无任职日期时回退成立日期，但来源必须标注 estimate_founding（非冒充）"""
        info = {
            "基金经理": "李四",
            "基金规模(亿元)": 50,
            "成立日期": "2015-03-01",
        }
        result = self.analyzer.evaluate_manager(info)
        self.assertEqual(result["任职年限来源"], "estimate_founding")
        self.assertGreater(result["任职年限"], 5)

    def test_manager_tenure_with_code_degrades_gracefully(self):
        """传 code 但 akshare 不可用时，不应抛异常，应降级为 provided/estimate"""
        info = {
            "基金经理": "王五",
            "基金规模(亿元)": 80,
            "成立日期": "2018-01-01",
            "任职日期": "2021-01-01",
        }
        # 本环境 akshare 静默不可用 → 应降级到 provided
        result = self.analyzer.evaluate_manager(info, code="003096")
        self.assertIn(result["任职年限来源"], ("real", "provided", "estimate_founding"))
        self.assertIsInstance(result["任职年限"], (int, float))

    def test_fetch_real_manager_tenure_fails_safe(self):
        """_fetch_real_manager_tenure 在 akshare 不可用时必须返回 None（fail-safe）"""
        self.assertIsNone(self.analyzer._fetch_real_manager_tenure("003096"))


# ===========================================================================
# FundDomain 基本测试
# ===========================================================================

class TestFundDomain(unittest.TestCase):
    """基金子系统域测试

    使用 mock 替代真实数据获取，确保测试快速稳定。
    """

    def setUp(self):
        """每个测试前创建一个新的 FundDomain 实例"""
        # 使用临时数据目录
        import tempfile
        self.temp_dir = tempfile.mkdtemp()
        self.domain = FundDomain(config={"data_dir": self.temp_dir})

    def tearDown(self):
        """清理临时目录"""
        import shutil
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    # ---------------------------------------------------------------
    # 继承关系
    # ---------------------------------------------------------------

    def test_domain_inherits_base(self):
        """验证 FundDomain 继承自 DomainBase"""
        self.assertTrue(issubclass(FundDomain, DomainBase))
        self.assertIsInstance(self.domain, DomainBase)

    # ---------------------------------------------------------------
    # 抽象方法实现
    # ---------------------------------------------------------------

    def test_domain_has_all_methods(self):
        """验证所有 DomainBase 抽象方法都已实现"""
        abstract_methods = [
            "setup", "teardown", "fetch", "analyze",
            "generate", "review", "status"
        ]
        for method in abstract_methods:
            self.assertTrue(
                hasattr(self.domain, method),
                f"FundDomain 缺少方法: {method}"
            )
            self.assertTrue(
                callable(getattr(self.domain, method)),
                f"FundDomain.{method} 不可调用"
            )

    # ---------------------------------------------------------------
    # setup 方法
    # ---------------------------------------------------------------

    def test_domain_setup(self):
        """测试 setup 方法能正常执行"""
        result = self.domain.setup()
        # setup 应该返回 True（即使部分模块降级也应成功）
        self.assertIsInstance(result, bool)
        # 初始化标志应正确设置
        self.assertEqual(self.domain._initialized, result)

    def test_domain_setup_sets_analyzer(self):
        """测试 setup 后 analyzer 应被加载"""
        self.domain.setup()
        # analyzer 应该被加载（纯 Python 模块，不依赖外部资源）
        self.assertIsNotNone(self.domain._analyzer)

    # ---------------------------------------------------------------
    # status 方法
    # ---------------------------------------------------------------

    def test_domain_status_structure(self):
        """测试 status 返回结构完整"""
        self.domain.setup()
        status = self.domain.status()

        required_keys = [
            "ready", "domain_id", "description", "engines",
            "cache_size", "analysis_cache_size", "last_run",
            "review_count", "default_funds", "errors"
        ]
        for key in required_keys:
            self.assertIn(key, status, f"status 缺少字段: {key}")

    def test_domain_status_before_setup(self):
        """测试 setup 前 status 的 ready 为 False"""
        status = self.domain.status()
        self.assertFalse(status["ready"])
        self.assertEqual(status["domain_id"], "fund")
        self.assertEqual(status["cache_size"], 0)
        self.assertEqual(status["review_count"], 0)

    def test_domain_status_after_setup(self):
        """测试 setup 后 status 的 ready 为 True"""
        self.domain.setup()
        status = self.domain.status()
        self.assertTrue(status["ready"])
        self.assertEqual(status["domain_id"], "fund")
        self.assertIsInstance(status["engines"], list)
        self.assertGreater(len(status["engines"]), 0)

    def test_domain_status_default_funds(self):
        """测试默认基金池数量"""
        status = self.domain.status()
        self.assertEqual(status["default_funds"], len(self.domain.DEFAULT_FUNDS))
        self.assertGreater(status["default_funds"], 0)

    # ---------------------------------------------------------------
    # teardown 方法
    # ---------------------------------------------------------------

    def test_domain_teardown(self):
        """测试 teardown 方法"""
        self.domain.setup()
        self.assertTrue(self.domain._initialized)
        result = self.domain.teardown()
        self.assertTrue(result)
        self.assertFalse(self.domain._initialized)

    # ---------------------------------------------------------------
    # review 方法
    # ---------------------------------------------------------------

    def test_review_empty_predictions(self):
        """测试空预测的复盘"""
        self.domain.setup()
        result = self.domain.review(predictions=[])
        self.assertEqual(result["reviews"], 0)
        self.assertEqual(result["hits"], 0)
        self.assertTrue(result["updated"])
        self.assertEqual(result["review_count"], 1)

    def test_review_increments_count(self):
        """测试复盘计数递增"""
        self.domain.setup()
        self.domain.review(predictions=None)
        self.assertEqual(self.domain._review_count, 1)
        self.domain.review(predictions=None)
        self.assertEqual(self.domain._review_count, 2)

    def test_review_with_predictions_and_actual(self):
        """测试带预测和实际数据的复盘"""
        self.domain.setup()
        predictions = [
            {"fund_code": "000001", "action": "buy", "confidence": 80, "timestamp": "2026-01-01"},
            {"fund_code": "110011", "action": "watch", "confidence": 30, "timestamp": "2026-01-01"},
            {"fund_code": "161725", "action": "hold", "confidence": 60, "timestamp": "2026-01-01"},
        ]
        actual = {
            "000001": {"return_pct": 5.0},   # 买入且正收益 = 命中
            "110011": {"return_pct": -3.0},  # 观望且负收益 = 命中
            "161725": {"return_pct": 1.0},   # 持有 = 命中
        }
        result = self.domain.review(predictions=predictions, actual=actual)

        self.assertEqual(result["reviews"], 3)
        self.assertEqual(result["hits"], 3)  # 三个都命中
        self.assertIn("metrics", result)
        self.assertIn("win_rate", result["metrics"])
        self.assertIn("avg_actual_return", result["metrics"])

    # ---------------------------------------------------------------
    # compare_funds 横向对比视图（P2-8）
    # ---------------------------------------------------------------

    @unittest.skipUnless(PANDAS_AVAILABLE, "pandas 不可用，跳过对比视图测试")
    def test_compare_funds_default_pool(self):
        """测试默认基金池横向对比（离线 mock 数据）。"""
        self.domain.setup()
        result = self.domain.compare_funds()
        self.assertTrue(result.get("success"))
        self.assertIn("comparison", result)
        comp = result["comparison"]
        self.assertGreater(len(comp), 0)
        # 每行应包含关键对比字段
        row = comp[0]
        for key in ("code", "name", "annual_return", "max_drawdown", "sharpe", "score", "grade"):
            self.assertIn(key, row)
        # 应按综合评分降序
        scores = [r.get("score") or 0 for r in comp]
        self.assertEqual(scores, sorted(scores, reverse=True))

    @unittest.skipUnless(PANDAS_AVAILABLE, "pandas 不可用，跳过对比视图测试")
    def test_compare_funds_top_n(self):
        """测试 top_n 截断。"""
        self.domain.setup()
        result = self.domain.compare_funds(top_n=3)
        self.assertTrue(result.get("success"))
        self.assertLessEqual(len(result["comparison"]), 3)

    @unittest.skipUnless(PANDAS_AVAILABLE, "pandas 不可用，跳过对比视图测试")
    def test_compare_funds_tenure_source_present(self):
        """对比视图应携带基金经理任职年限来源（复用 JS-20260724-10 字段）。"""
        self.domain.setup()
        result = self.domain.compare_funds(codes=["000001"])
        self.assertTrue(result.get("success"))
        row = result["comparison"][0]
        self.assertIn("tenure_source", row)
        self.assertIsNotNone(row.get("tenure_source"))

    # ---------------------------------------------------------------
    # 模拟数据生成
    # ---------------------------------------------------------------

    @unittest.skipUnless(PANDAS_AVAILABLE, "pandas 不可用，跳过模拟数据测试")
    def test_generate_mock_fund_data(self):
        """测试模拟基金数据生成"""
        mock_data = self.domain._generate_mock_fund_data("000001")

        self.assertIn("nav", mock_data)
        self.assertIn("info", mock_data)
        self.assertIn("holdings", mock_data)

        # 净值数据应该是 DataFrame 且有数据
        self.assertFalse(mock_data["nav"].empty)
        self.assertIn("单位净值", mock_data["nav"].columns)

        # 基本信息应该包含关键字段
        self.assertIn("基金代码", mock_data["info"])
        self.assertEqual(mock_data["info"]["基金代码"], "000001")

        # 持仓数据应该有数据
        self.assertFalse(mock_data["holdings"].empty)

    # ---------------------------------------------------------------
    # 推荐分类
    # ---------------------------------------------------------------

    def test_classify_action_buy(self):
        """测试 A 级且回撤可控 → 买入"""
        item = {"score": 85, "grade": "A", "max_drawdown": -10.0}
        action = self.domain._classify_action(item)
        self.assertEqual(action, "buy")

    def test_classify_action_hold(self):
        """测试 B 级 → 持有"""
        item = {"score": 65, "grade": "B", "max_drawdown": -20.0}
        action = self.domain._classify_action(item)
        self.assertEqual(action, "hold")

    def test_classify_action_watch(self):
        """测试 C 级 → 观望"""
        item = {"score": 40, "grade": "C", "max_drawdown": -35.0}
        action = self.domain._classify_action(item)
        self.assertEqual(action, "watch")

    # ---------------------------------------------------------------
    # 推荐理由生成
    # ---------------------------------------------------------------

    def test_generate_reason_not_empty(self):
        """测试推荐理由不为空"""
        item = {
            "annual_return": 15.0,
            "max_drawdown": -10.0,
            "sharpe": 1.2,
            "manager_rating": "优秀",
            "manager": "张三",
            "style": "成长",
        }
        reason = self.domain._generate_reason(item)
        self.assertTrue(len(reason) > 0)
        self.assertIsInstance(reason, str)

    # ---------------------------------------------------------------
    # 基础净值分析（降级模式）
    # ---------------------------------------------------------------

    @unittest.skipUnless(PANDAS_AVAILABLE, "pandas 不可用，跳过基础分析测试")
    def test_basic_nav_analysis(self):
        """测试降级模式下的基础净值分析"""
        navs = _make_nav_list(days=100)
        df = _make_nav_df(navs)
        result = self.domain._basic_nav_analysis(df)

        self.assertIn("returns", result)
        self.assertIn("risk", result)
        self.assertIn("summary", result)
        self.assertNotIn("error", result)


if __name__ == "__main__":
    unittest.main()
