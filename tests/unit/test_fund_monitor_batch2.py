# -*- coding: utf-8 -*-
"""批2（JS-20260923-11）单元测试：区间收益 + 同类排名接线

测试内容：
  - 领域层 FundFetcher.get_rank(real_only=True) 真实数据缺失时返回 None，绝不编造模拟排名
  - analyzer.calculate_returns 各周期索引正确（近3月/6月/1年/3年）
  - 日报卡片渲染包含区间收益四列 + 同类排名栏；排名缺失显示「暂缺」，存在时显示「前X%」
"""
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from domains.fund.fetcher import FundFetcher  # noqa: E402
from domains.fund.analyzer import FundAnalyzer  # noqa: E402
from scripts.daily_fund_monitor import ReportGenerator, FUND_CONFIG  # noqa: E402


class TestRankRealOnly(unittest.TestCase):
    """诚实铁律：real_only=True 时真实数据不可用必须返回 None，不编造"""

    def _make_fetcher(self):
        f = FundFetcher()
        # 强制 akshare 不可用，使 get_rank 走降级分支，验证 real_only 拦截
        f._has_akshare = False
        return f

    def test_real_only_returns_none_when_unavailable(self):
        f = self._make_fetcher()
        self.assertIsNone(f.get_rank(real_only=True))

    def test_real_only_none_even_with_stale_cache(self):
        # 先写入模拟排名缓存，再确认 real_only=True 不会泄漏缓存（诚实铁律）
        f = self._make_fetcher()
        f.get_rank(real_only=False)  # 写入缓存（模拟）
        self.assertIsNone(f.get_rank(real_only=True))  # 仍应返回 None

    def test_non_real_only_returns_mock_when_unavailable(self):
        f = self._make_fetcher()
        df = f.get_rank(real_only=False)
        self.assertFalse(df.empty)
        self.assertIn("同类排名", df.columns)

    def test_real_only_none_on_fetch_failure(self):
        f = FundFetcher()
        f._has_akshare = True
        f._breaker = None

        def _boom(*a, **k):
            raise RuntimeError("offline")
        f._fetch_rank_from_akshare = _boom
        self.assertIsNone(f.get_rank(real_only=True))


class TestIntervalReturns(unittest.TestCase):
    """区间收益（近3月/6月/1年/3年）索引正确性"""

    def test_period_indexing(self):
        # 构造 800 个净值点，在关键位置埋入已知值，验证各周期只取对应端点
        navs = [1.0] * 800
        navs[673] = 1.03   # 近6月端点
        navs[736] = 1.05   # 近3月端点
        navs[547] = 1.10   # 近1年端点
        navs[799] = 1.164  # 最新
        r = FundAnalyzer().calculate_returns(navs)
        self.assertAlmostEqual(r["近3月"], 10.86, places=1)
        self.assertAlmostEqual(r["近6月"], 13.01, places=1)
        self.assertAlmostEqual(r["近1年"], 5.82, places=1)
        self.assertAlmostEqual(r["近3年"], 16.4, places=1)

    def test_insufficient_data_returns_error(self):
        r = FundAnalyzer().calculate_returns([1.0, 1.1])
        self.assertIn("error", r)


class TestReportCardIntervalRank(unittest.TestCase):
    """日报卡片渲染：区间收益四列 + 同类排名栏"""

    def _render(self, interval_returns, rank):
        code = FUND_CONFIG[0]["code"]
        data = {
            code: {
                "snapshot": {"nav_today": 1.234, "daily_return": 0.5,
                             "update_date": "2026-09-23"},
                "risks": {"max_drawdown": 5.0, "volatility": 10.0,
                          "sharpe": 1.2, "calmar": 0.8, "total_return": 3.0},
                "signals": {"take_profit": {"signal": False, "message": "未触发"},
                            "purchase_limit": {"is_limited": False, "status": "开放"},
                            "significant_drop": {"signal": False}},
                "config": FUND_CONFIG[0],
                "interval_returns": interval_returns,
                "rank": rank,
            }
        }
        html = ReportGenerator(_REPO_ROOT)._build_html(
            "2026-09-23", "09:00", data, {}, {})
        return html

    def test_interval_columns_present(self):
        html = self._render(
            {"近3月": 10.86, "近6月": 13.01, "近1年": 5.82, "近3年": 16.4},
            None,
        )
        for label in ("近3月", "近6月", "近1年", "近3年", "同类排名"):
            self.assertIn(label, html)

    def test_rank_missing_shows_placeholder(self):
        html = self._render(
            {"近3月": 10.86, "近6月": 13.01, "近1年": 5.82, "近3年": 16.4},
            None,
        )
        self.assertIn("暂缺", html)

    def test_rank_present_shows_percentile(self):
        html = self._render(
            {"近3月": 10.86, "近6月": 13.01, "近1年": 5.82, "近3年": 16.4},
            {"rank": "12/1500"},
        )
        # 12/1500 = 0.8%，证明有排名的基金走「前X%」渲染分支
        self.assertIn("前0.8%", html)


if __name__ == "__main__":
    unittest.main()
