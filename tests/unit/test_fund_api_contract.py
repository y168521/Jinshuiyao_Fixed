# -*- coding: utf-8 -*-
"""基金新增 API 契约测试（JS-20260812-03 补充）

覆盖 server/handlers/fund.py 三个真实数据 API 的返回结构契约：
- /api/fund/pool        基金池名称+代码
- /api/fund/nav-series  净值序列+区间指标+诚实 mode 标记
- /api/fund/holdings    持仓穿透（available=false 诚实降级）
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from server.handlers import fund as h_fund


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


class FakeFetcher:
    def get_fund_names_map(self):
        return {"000001": "华夏成长混合", "000002": "华夏大盘精选混合"}


class FakeAnalyzer:
    def analyze_holdings(self, holdings_df):
        return {
            "行业分布": {"制造业": 45.0, "金融业": 30.0},
            "十大重仓占比": 55.9,
            "第一大重仓占比": 8.5,
            "持仓集中度(HHI)": 1200,
            "持股数量": 42,
            "风格倾向": "均衡型",
            "集中度评价": "适中",
        }


class FakeDomain:
    DEFAULT_FUNDS = ["000001", "000002"]
    _data_mode = {"000001": "real", "000002": "mock"}

    def __init__(self, data_cache, analyzer=None, fetcher=None):
        self._data_cache = data_cache
        self._analyzer = analyzer
        self._fetcher = fetcher
        self.fetched = []

    def fetch(self, codes=None):
        self.fetched.append(list(codes or []))

    def active_funds(self):
        return ["000001"]


class TestFundPoolContract(unittest.TestCase):

    def test_pool_default_source(self):
        """持仓为空时回退内置池，source=default，名称来自名称映射"""
        domain = FakeDomain(data_cache={}, fetcher=FakeFetcher())
        with mock.patch.object(h_fund, "get_fund_domain", return_value=domain), \
             mock.patch.object(h_fund, "_get_portfolio_manager", return_value=None):
            h = FakeHandler()
            h_fund.handle_pool(h, None)
        self.assertEqual(h.code, 200)
        p = h.payload
        self.assertTrue(p["ok"])
        self.assertEqual(p["source"], "default")
        self.assertEqual(p["count"], 2)
        names = {f["code"]: f["name"] for f in p["pool"]}
        self.assertEqual(names["000001"], "华夏成长混合")
        self.assertEqual(names["000002"], "华夏大盘精选混合")

    def test_pool_holdings_source(self):
        """持仓存在时以持仓为真源，source=holdings"""
        domain = FakeDomain(data_cache={}, fetcher=FakeFetcher())
        mgr = mock.MagicMock()
        mgr.get_holdings.return_value = [
            {"code": "110011", "name": "易方达中小盘混合"},
            {"code": "161725", "name": "招商中证白酒"},
        ]
        with mock.patch.object(h_fund, "get_fund_domain", return_value=domain), \
             mock.patch.object(h_fund, "_get_portfolio_manager", return_value=mgr):
            h = FakeHandler()
            h_fund.handle_pool(h, None)
        self.assertEqual(h.code, 200)
        p = h.payload
        self.assertTrue(p["ok"])
        self.assertEqual(p["source"], "holdings")
        self.assertEqual([f["code"] for f in p["pool"]], ["110011", "161725"])

    def test_pool_domain_unavailable(self):
        with mock.patch.object(h_fund, "get_fund_domain", return_value=None):
            h = FakeHandler()
            h_fund.handle_pool(h, None)
        self.assertEqual(h.code, 503)
        self.assertFalse(h.payload["ok"])


class TestFundNavSeriesContract(unittest.TestCase):

    def _make_nav_df(self):
        import pandas as pd
        from datetime import datetime, timedelta
        base = datetime.now()
        dates = [
            (base - timedelta(days=365)).strftime("%Y-%m-%d"),
            (base - timedelta(days=275)).strftime("%Y-%m-%d"),
            (base - timedelta(days=180)).strftime("%Y-%m-%d"),
            (base - timedelta(days=90)).strftime("%Y-%m-%d"),
            base.strftime("%Y-%m-%d"),
        ]
        return pd.DataFrame({
            "净值日期": dates,
            "单位净值": [1.0000, 1.1000, 1.0500, 1.2000, 1.3000],
        })

    def test_nav_series_real(self):
        """真实缓存：mode=real，序列+区间指标齐全"""
        nav_df = self._make_nav_df()
        domain = FakeDomain(data_cache={
            "000001": {"nav": nav_df, "info": {"基金名称": "华夏成长混合"}},
        })
        with mock.patch.object(h_fund, "get_fund_domain", return_value=domain):
            h = FakeHandler()
            h_fund.handle_nav_series(h, None)
        self.assertEqual(h.code, 200)
        p = h.payload
        self.assertTrue(p["ok"])
        self.assertEqual(p["count"], 1)
        f = p["funds"][0]
        self.assertEqual(f["code"], "000001")
        self.assertEqual(f["name"], "华夏成长混合")
        self.assertEqual(f["mode"], "real")
        self.assertEqual(f["points"], 5)
        self.assertEqual(len(f["nav_series"]), 5)
        self.assertAlmostEqual(f["metrics"]["period_return"], 0.3, places=3)
        self.assertLess(f["metrics"]["max_drawdown"], 0)  # 有回撤，为负
        self.assertEqual(p["mock_count"], 0)

    def test_nav_series_mock_count(self):
        """mock 兜底数据带诚实标记，mock_count 正确统计"""
        nav_df = self._make_nav_df()
        domain = FakeDomain(data_cache={
            "000001": {"nav": nav_df, "info": {}},
            "000002": {"nav": nav_df, "info": {}},
        })
        with mock.patch.object(h_fund, "get_fund_domain", return_value=domain):
            h = FakeHandler()
            h_fund.handle_nav_series(h, None)
        p = h.payload
        self.assertEqual(p["count"], 2)
        modes = {f["code"]: f["mode"] for f in p["funds"]}
        self.assertEqual(modes["000001"], "real")
        self.assertEqual(modes["000002"], "mock")
        self.assertEqual(p["mock_count"], 1)

    def test_nav_series_unknown_code_skipped(self):
        """无缓存代码跳过，不返回假数据"""
        domain = FakeDomain(data_cache={})
        with mock.patch.object(h_fund, "get_fund_domain", return_value=domain):
            h = FakeHandler()
            h_fund.handle_nav_series(h, None)
        self.assertEqual(h.code, 200)
        self.assertTrue(h.payload["ok"])
        self.assertEqual(h.payload["count"], 0)

    def test_nav_series_period_cutoff(self):
        """period=1m 时序列按 cutoff 过滤"""
        import pandas as pd
        nav_df = pd.DataFrame({
            "净值日期": ["2025-08-12", "2026-07-20", "2026-08-01", "2026-08-12"],
            "单位净值": [1.0, 1.1, 1.05, 1.3],
        })
        domain = FakeDomain(data_cache={"000001": {"nav": nav_df, "info": {}}})
        with mock.patch.object(h_fund, "get_fund_domain", return_value=domain):
            h = FakeHandler()
            h_fund.handle_nav_series(h, None)
        p = h.payload
        self.assertEqual(p["period"], "1y")
        f = p["funds"][0]
        self.assertLessEqual(f["points"], 4)


class TestFundHoldingsContract(unittest.TestCase):

    def _make_holdings_df(self):
        import pandas as pd
        return pd.DataFrame({
            "股票名称": ["贵州茅台", "宁德时代", "招商银行"],
            "股票代码": ["600519", "300750", "600036"],
            "占净值比例": [8.5, 6.2, 5.1],
            "持仓市值": [100000000, 80000000, 60000000],
            "持股数": [50000, 200000, 1500000],
        })

    def test_holdings_available(self):
        """真实持仓：available=True，前十重仓+集中度指标+行业分布"""
        domain = FakeDomain(
            data_cache={"000001": {"holdings": self._make_holdings_df(), "info": {"基金名称": "华夏成长混合"}}},
            analyzer=FakeAnalyzer(),
        )
        with mock.patch.object(h_fund, "get_fund_domain", return_value=domain):
            h = FakeHandler(body='{"code": "000001"}')
            h_fund.handle_holdings_detail(h, None)
        self.assertEqual(h.code, 200)
        p = h.payload
        self.assertTrue(p["ok"])
        self.assertTrue(p["available"])
        self.assertEqual(p["mode"], "real")
        self.assertEqual(p["name"], "华夏成长混合")
        self.assertEqual(len(p["stocks"]), 3)
        self.assertEqual(p["stocks"][0]["name"], "贵州茅台")
        self.assertEqual(p["stocks"][0]["ratio"], 8.5)
        self.assertEqual(p["industry"]["制造业"], 45.0)
        self.assertEqual(p["concentration"]["top10_ratio"], 55.9)
        self.assertEqual(p["concentration"]["style"], "均衡型")

    def test_holdings_unavailable_honest(self):
        """无持仓数据时诚实返回 available=false，不编造"""
        domain = FakeDomain(data_cache={"000001": {}})
        with mock.patch.object(h_fund, "get_fund_domain", return_value=domain):
            h = FakeHandler(body='{"code": "000001"}')
            h_fund.handle_holdings_detail(h, None)
        self.assertEqual(h.code, 200)
        p = h.payload
        self.assertTrue(p["ok"])
        self.assertFalse(p["available"])
        self.assertEqual(p["mode"], "none")

    def test_holdings_missing_code_400(self):
        domain = FakeDomain(data_cache={})
        with mock.patch.object(h_fund, "get_fund_domain", return_value=domain):
            h = FakeHandler(body='{"code": ""}')
            h_fund.handle_holdings_detail(h, None)
        self.assertEqual(h.code, 400)

    def test_holdings_fetch_trigger(self):
        """缓存无持仓时触发 fetch([code]) 后再查"""
        import pandas as pd
        holdings_df = pd.DataFrame({"股票名称": ["贵州茅台"], "占净值比例": [8.5]})
        domain = FakeDomain(data_cache={}, analyzer=FakeAnalyzer())
        with mock.patch.object(h_fund, "get_fund_domain", return_value=domain):
            h = FakeHandler(body='{"code": "000001"}')
            h_fund.handle_holdings_detail(h, None)
        self.assertEqual(domain.fetched, [["000001"]])
        # fetch 后仍无数据 → 诚实降级
        p = h.payload
        self.assertTrue(p["ok"])
        self.assertFalse(p["available"])


if __name__ == "__main__":
    unittest.main()
