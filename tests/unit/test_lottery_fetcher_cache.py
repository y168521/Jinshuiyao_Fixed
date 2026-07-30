# -*- coding: utf-8 -*-
"""彩票抓取器（fetchers.fetcher.Fetcher）HTTP 缓存层单元测试

验证 stage3 接入的 cache_manager 网络缓存：
  - 相同幂等 GET 请求命中缓存，跳过重复网络调用
  - 不同 params / headers 视为不同键（MISS）
  - _CachedHTTPResponse 与原 requests.Response 在使用处等价（.text/.json/.status_code/.encoding）
  - 环境变量 TIANSHU_DISABLE_HTTP_CACHE 关闭缓存
全程 mock 网络层，不发起真实请求。
"""
import os
import sys
import json
import unittest
from unittest.mock import MagicMock

_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_test_dir))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


class FakeResp:
    """模拟 requests.Response，仅实现 fetcher 实际使用的接口。"""
    def __init__(self, text, status_code=200, encoding="utf-8"):
        self.text = text
        self.status_code = status_code
        self.encoding = encoding
        self.apparent_encoding = encoding

    def json(self):
        return json.loads(self.text)


def _make_fetcher_with_fake_get(counter, payload="{\"ok\": true}"):
    """构造 Fetcher 并把 self.s.get 替换成计数型 fake。"""
    from fetchers.fetcher import Fetcher
    f = Fetcher()

    def fake_get(url, params=None, timeout=None, headers=None):
        counter["n"] += 1
        return FakeResp(payload)

    f.s.get = MagicMock(side_effect=fake_get)
    return f


class TestLotteryFetcherHttpCache(unittest.TestCase):
    """HTTP 缓存层核心行为。"""

    def test_cache_hit_skips_network(self):
        """相同 URL 连续请求：第二次命中缓存，网络只调用 1 次。"""
        counter = {"n": 0}
        f = _make_fetcher_with_fake_get(counter)
        r1 = f._request_with_retry("https://example.com/lottery/ssq")
        r2 = f._request_with_retry("https://example.com/lottery/ssq")
        self.assertEqual(counter["n"], 1)
        self.assertEqual(r1.text, r2.text)
        self.assertEqual(r1.status_code, 200)

    def test_cached_response_equiv_response(self):
        """命中缓存返回的对象与原响应接口等价。"""
        counter = {"n": 0}
        payload = '{"data": [1, 2, 3], "name": "双色球"}'
        f = _make_fetcher_with_fake_get(counter, payload=payload)
        r1 = f._request_with_retry("https://example.com/api")
        r2 = f._request_with_retry("https://example.com/api")
        # .json() 可解析且一致
        self.assertEqual(r1.json(), r2.json())
        self.assertEqual(r2.json()["name"], "双色球")
        # .encoding 被保留
        self.assertEqual(r2.encoding, "utf-8")

    def test_different_params_miss(self):
        """不同 params 生成不同缓存键，两次都走网络。"""
        counter = {"n": 0}
        f = _make_fetcher_with_fake_get(counter)
        f._request_with_retry("https://example.com/a", params={"x": 1})
        f._request_with_retry("https://example.com/a", params={"x": 2})
        self.assertEqual(counter["n"], 2)

    def test_different_url_miss(self):
        counter = {"n": 0}
        f = _make_fetcher_with_fake_get(counter)
        f._request_with_retry("https://example.com/a")
        f._request_with_retry("https://example.com/b")
        self.assertEqual(counter["n"], 2)

    def test_kill_switch_disables_cache(self):
        """TIANSHU_DISABLE_HTTP_CACHE=1 时关闭缓存，相同 URL 也每次走网络。"""
        os.environ["TIANSHU_DISABLE_HTTP_CACHE"] = "1"
        import importlib
        import fetchers.fetcher as mod
        importlib.reload(mod)
        try:
            counter = {"n": 0}
            f = _make_fetcher_with_fake_get(counter)
            f._request_with_retry("https://example.com/a")
            f._request_with_retry("https://example.com/a")
            self.assertEqual(counter["n"], 2)
        finally:
            del os.environ["TIANSHU_DISABLE_HTTP_CACHE"]
            importlib.reload(mod)


if __name__ == "__main__":
    unittest.main()
