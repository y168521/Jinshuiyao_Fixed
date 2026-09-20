# -*- coding: utf-8 -*-
"""/api/fund/profile 契约测试（JS-20260921-01）

覆盖「基金外围风险（经理变更 / 规模清盘 / 限购额度）接入 Web」的三条硬要求：
  1. **默认只读缓存、绝不联网**——cache_only=True、enabled 传 False
  2. **取不到就标 unavailable，绝不编造**——level=unknown，不伪造档位
  3. **聚合取最严重档位**、单只异常不拖垮整批
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from server.handlers import fund as h_fund

CONFIG = {
    "005698": {"code": "005698", "name": "华夏全球科技先锋混合(QDII)A",
               "manager": "李博", "investment": 3000},
    "270042": {"code": "270042", "name": "广发纳斯达克100指数A",
               "manager": "刘杰", "investment": 3000},
}


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


def _profile(code, mgr_level="info", scale_level="safe", limit_level="info",
             ok=True, stale=False):
    return {
        "code": code,
        "manager": {"ok": ok, "level": mgr_level, "message": "x"},
        "scale": {"ok": ok, "level": scale_level, "message": "x"},
        "limit": {"ok": ok, "level": limit_level, "message": "x"},
        "limit_change": "same",
        "stale": stale,
        "fetched_at": "2026-09-21 05:00:00",
    }


class _FakeFetcher:
    """记录实例化参数 + 按预设返回档案"""

    instances = []

    def __init__(self, delay=0.6, enabled=True, **kw):
        self.enabled = enabled
        self.delay = delay
        self.calls = []
        _FakeFetcher.instances.append(self)

    def get_profile(self, code, config_manager=None, plan_investment_monthly=3000,
                    use_cache=True):
        self.calls.append({"code": code, "use_cache": use_cache,
                           "plan": plan_investment_monthly})
        if code == "BOOM":
            raise RuntimeError("抓取炸了")
        return _RESULTS.get(code, _profile(code, ok=False))


_RESULTS = {}


class TestFundProfileAPI(unittest.TestCase):

    def setUp(self):
        _FakeFetcher.instances = []
        _RESULTS.clear()
        self._cfg_patch = mock.patch.object(
            h_fund, "_load_monitor_config", return_value=dict(CONFIG))
        self._cfg_patch.start()

    def tearDown(self):
        self._cfg_patch.stop()

    def _call(self, query="", body=None):
        h = FakeHandler(body or "")
        parsed = SimpleNamespace(path="/api/fund/profile", query=query)
        with mock.patch("domains.fund.fund_profile_risk.FundProfileFetcher", _FakeFetcher):
            h_fund.handle_profile(h, parsed)
        return h

    # ---------- 1. 默认只读缓存，绝不联网 ----------
    def test_default_is_cache_only(self):
        h = self._call(query="codes=005698")
        self.assertEqual(h.code, 200)
        self.assertTrue(h.payload["ok"])
        self.assertTrue(h.payload["cache_only"], "默认必须只读缓存")
        self.assertFalse(h.payload["refresh"])
        fetcher = _FakeFetcher.instances[0]
        self.assertFalse(fetcher.enabled, "默认模式必须 enabled=False（断网保险）")
        self.assertTrue(fetcher.calls[0]["use_cache"])

    def test_refresh_flag_turns_on_network(self):
        h = self._call(query="codes=005698&refresh=1")
        self.assertTrue(h.payload["refresh"])
        self.assertFalse(h.payload["cache_only"])
        self.assertTrue(_FakeFetcher.instances[0].enabled)
        self.assertFalse(_FakeFetcher.instances[0].calls[0]["use_cache"])

    def test_default_codes_come_from_monitor_config(self):
        h = self._call()
        self.assertEqual(h.payload["count"], 2)
        self.assertEqual([p["code"] for p in h.payload["profiles"]],
                         ["005698", "270042"])

    # ---------- 2. 取不到就标 unavailable，绝不编造 ----------
    def test_missing_data_marks_unavailable_not_fabricated(self):
        _RESULTS["005698"] = _profile("005698", ok=False)
        h = self._call(query="codes=005698")
        p = h.payload["profiles"][0]
        self.assertTrue(p["unavailable"])
        self.assertEqual(p["level"], "unknown", "无数据必须 unknown，不许假装有结论")
        self.assertEqual(h.payload["summary"]["unavailable"], 1)

    def test_stale_is_flagged(self):
        _RESULTS["005698"] = _profile("005698", stale=True)
        h = self._call(query="codes=005698")
        self.assertTrue(h.payload["profiles"][0]["stale"])
        self.assertEqual(h.payload["summary"]["stale"], 1)

    # ---------- 3. 聚合取最严重档位 ----------
    def test_level_is_worst_of_three(self):
        _RESULTS["005698"] = _profile("005698", mgr_level="warn",
                                      scale_level="danger", limit_level="info")
        h = self._call(query="codes=005698")
        self.assertEqual(h.payload["profiles"][0]["level"], "danger")
        self.assertEqual(h.payload["summary"]["danger"], 1)

        _RESULTS["270042"] = _profile("270042", mgr_level="notice",
                                      scale_level="safe", limit_level="warn")
        h = self._call(query="codes=270042")
        self.assertEqual(h.payload["profiles"][0]["level"], "warn")

    def test_info_and_safe_collapse_to_one_bucket(self):
        """info 与 safe 必须归一：否则汇总多一个 info 桶，前端「正常」会漏计"""
        _RESULTS["005698"] = _profile("005698", mgr_level="info",
                                      scale_level="safe", limit_level="info")
        h = self._call(query="codes=005698")
        self.assertEqual(h.payload["profiles"][0]["level"], "safe")
        self.assertNotIn("info", h.payload["summary"], "汇总里不应出现 info 桶")
        self.assertEqual(h.payload["summary"]["safe"], 1)

    # ---------- 4. 单只异常不拖垮整批 ----------
    def test_single_failure_does_not_break_batch(self):
        _RESULTS["270042"] = _profile("270042", mgr_level="warn")
        h = self._call(query="codes=BOOM,270042")
        self.assertEqual(h.code, 200)
        self.assertTrue(h.payload["ok"])
        self.assertEqual(h.payload["count"], 2)
        boom = [p for p in h.payload["profiles"] if p["code"] == "BOOM"][0]
        self.assertTrue(boom["unavailable"])
        self.assertEqual(boom["name"], "BOOM", "未配置时名称回退为代码，不报错")
        good = [p for p in h.payload["profiles"] if p["code"] == "270042"][0]
        self.assertEqual(good["level"], "warn")

    # ---------- 5. 参数与配置 ----------
    def test_plan_investment_comes_from_config(self):
        self._call(query="codes=005698")
        self.assertEqual(_FakeFetcher.instances[0].calls[0]["plan"], 3000)

    def test_no_codes_and_no_config_returns_400(self):
        self._cfg_patch.stop()
        with mock.patch.object(h_fund, "_load_monitor_config", return_value={}):
            h = self._call()
        self.assertEqual(h.code, 400)
        self.assertFalse(h.payload["ok"])
        self.assertIn("hint", h.payload)


if __name__ == "__main__":
    unittest.main()
