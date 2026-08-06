# -*- coding: utf-8 -*-
"""AI服务层扩展单元测试

本文件与 test_ai_agent.py 分开，专注测试 AIService 类的深层行为：
  - mock requests.Session.post 验证 API 调用逻辑
  - analyze 方法正确构建 prompt
  - quick 方法限制 token
  - 频率限制
  - 熔断器集成
  - API 错误时降级行为
  - 运行中切换供应商

注意：test_ai_agent.py 中已有 TestAIService 类（6个基础测试），本文件不重复。

修复记录(2026-07-20 Qoder)：
  原测试 mock urllib.request.urlopen，但 ai_service._call_api() 优先走
  requests.Session.post()（self._session 非 None 时），urllib 仅为降级路径。
  现改为 mock _session.post，与实际代码路径一致。
"""
import unittest
import json
import time
import os
from unittest.mock import MagicMock, patch, PropertyMock

from core.ai_service import AIService, PROVIDERS, _SUBSYSTEM_PROMPTS


def setUpModule():
    """测试环境全局禁用免费模型池（W63补38 free_first 引入后，避免测试打到真实硅基流动 API）。

    chat() 的 free-first 分支在函数体内 from core.free_model_pool import ...，
    调用时会实时读取模块属性，因此 patch 模块属性即可拦截。
    需验证免费优先行为的测试在方法内显式覆盖此 patch。
    """
    _patches = [
        patch("core.free_model_pool.get_free_provider_cfgs", return_value=[]),
    ]
    for p in _patches:
        p.start()
    global _MODULE_PATCHES
    _MODULE_PATCHES = _patches


def tearDownModule():
    for p in _MODULE_PATCHES:
        p.stop()


_MODULE_PATCHES = []


def _make_mock_response(content="ok", status_code=200, usage=None):
    """构造模拟的 requests.Response 对象"""
    resp = MagicMock()
    resp.status_code = status_code
    data = {"choices": [{"message": {"content": content}}]}
    if usage:
        data["usage"] = usage
    resp.json.return_value = data
    resp.text = json.dumps(data)
    return resp


def _make_error_response(status_code=500, text="Server Error"):
    """构造模拟的错误响应"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


def _create_test_svc(api_key="test-key-12345"):
    """创建测试用AIService实例（跳过Ollama网络探测，避免超时）"""
    with patch.object(AIService, '_detect_ollama'):
        svc = AIService(api_key=api_key)
    svc._ollama_available = False
    return svc


class TestAIServiceChatWithMock(unittest.TestCase):
    """mock requests.Session.post 验证 API 调用逻辑"""

    def setUp(self):
        self.svc = _create_test_svc()

    def test_chat_with_mock_server(self):
        """mock session.post，验证API调用成功逻辑"""
        mock_resp = _make_mock_response("这是模拟的AI回复")

        with patch.object(self.svc._session, 'post', return_value=mock_resp) as mock_post:
            result = self.svc.chat("你是助手", "你好")
            self.assertEqual(result, "这是模拟的AI回复")
            mock_post.assert_called_once()

    def test_chat_empty_api_key(self):
        """无API Key时返回空字符串"""
        with patch.object(AIService, '_detect_ollama'):
            svc = AIService(api_key="", key_file="/nonexistent/path.txt")
        svc.api_key = ""
        result = svc.chat("system", "user")
        self.assertEqual(result, "")

    def test_chat_builds_correct_request(self):
        """验证chat构建的请求包含正确的headers和payload"""
        mock_resp = _make_mock_response("ok")

        with patch.object(self.svc._session, 'post', return_value=mock_resp) as mock_post:
            self.svc.chat("系统提示", "用户输入")

            # 验证调用参数
            call_kwargs = mock_post.call_args
            # headers 验证
            headers = call_kwargs[1].get("headers") or call_kwargs.kwargs.get("headers", {})
            self.assertIn("Bearer test-key-12345", headers.get("Authorization", ""))

            # payload 验证（json参数）
            payload = call_kwargs[1].get("json") or call_kwargs.kwargs.get("json", {})
            self.assertEqual(payload["messages"][0]["role"], "system")
            self.assertEqual(payload["messages"][0]["content"], "系统提示")
            self.assertEqual(payload["messages"][1]["role"], "user")
            self.assertEqual(payload["messages"][1]["content"], "用户输入")

    def test_chat_custom_temperature_and_tokens(self):
        """验证自定义温度和token参数传递"""
        mock_resp = _make_mock_response("ok")

        with patch.object(self.svc._session, 'post', return_value=mock_resp) as mock_post:
            self.svc.chat("sys", "usr", temperature=0.1, max_tokens=500)

            payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json", {})
            self.assertEqual(payload["temperature"], 0.1)
            self.assertEqual(payload["max_tokens"], 500)

    def test_chat_http_error(self):
        """API HTTP错误时返回空字符串并记录失败"""
        mock_resp = _make_error_response(429, "Rate limit")

        with patch.object(self.svc._session, 'post', return_value=mock_resp):
            result = self.svc.chat("sys", "usr")
            self.assertEqual(result, "")
            self.assertEqual(self.svc._fail_count, 1)


class TestAIServiceAnalyze(unittest.TestCase):
    """analyze 方法构建 prompt 测试"""

    def setUp(self):
        self.svc = _create_test_svc()

    def test_analyze_builds_context(self):
        """验证analyze方法正确构建prompt（子系统模板+内容）"""
        mock_resp = _make_mock_response("分析结果")

        with patch.object(self.svc._session, 'post', return_value=mock_resp) as mock_post:
            self.svc.analyze("stock", "上证指数今日上涨了2%")

            payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json", {})
            system_content = payload["messages"][0]["content"]
            self.assertIn("A股市场分析师", system_content)

            user_content = payload["messages"][1]["content"]
            self.assertEqual(user_content, "上证指数今日上涨了2%")

    def test_analyze_with_extra_system_prompt(self):
        """验证 extra_system 追加到系统提示词后"""
        mock_resp = _make_mock_response("ok")

        with patch.object(self.svc._session, 'post', return_value=mock_resp) as mock_post:
            self.svc.analyze("lottery", "数据", extra_system="只关注红球")

            payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json", {})
            system_content = payload["messages"][0]["content"]
            self.assertIn("只关注红球", system_content)

    def test_analyze_unknown_subsystem_fallback(self):
        """未知子系统回退到general模板"""
        mock_resp = _make_mock_response("ok")

        with patch.object(self.svc._session, 'post', return_value=mock_resp) as mock_post:
            self.svc.analyze("nonexistent_subsystem", "test content")

            payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json", {})
            system_content = payload["messages"][0]["content"]
            self.assertIn("金水谣万物引擎", system_content)


class TestAIServiceQuick(unittest.TestCase):
    """quick 方法测试"""

    def setUp(self):
        self.svc = _create_test_svc()

    def test_quick_returns_short(self):
        """验证quick方法限制token为200"""
        mock_resp = _make_mock_response("简短回答")

        with patch.object(self.svc._session, 'post', return_value=mock_resp) as mock_post:
            self.svc.quick("lottery", "分析数据")

            payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json", {})
            self.assertEqual(payload["max_tokens"], 200)
            self.assertEqual(payload["temperature"], 0.3)

            system_content = payload["messages"][0]["content"]
            self.assertIn("一句话", system_content)


class TestAIServiceRateLimiting(unittest.TestCase):
    """频率限制测试"""

    def setUp(self):
        self.svc = _create_test_svc()
        self.svc._min_interval = 0.1  # 缩短间隔加速测试

    def test_rate_limiting(self):
        """验证频率限制：连续调用时有等待"""
        mock_resp = _make_mock_response("ok")

        with patch.object(self.svc._session, 'post', return_value=mock_resp):
            start = time.time()
            self.svc.chat("sys", "第一次调用")
            self.svc._last_call_time = time.time()

            self.svc._last_call_time = time.time()
            self.svc.chat("sys", "第二次调用")
            elapsed = time.time() - start

            self.assertTrue(elapsed >= 0.1)

    def test_rate_limit_no_wait_when_interval_passed(self):
        """间隔足够时不应等待"""
        mock_resp = _make_mock_response("ok")

        with patch.object(self.svc._session, 'post', return_value=mock_resp):
            self.svc._last_call_time = 0

            start = time.time()
            self.svc.chat("sys", "间隔足够的调用")
            elapsed = time.time() - start

            self.assertTrue(elapsed < 0.5)


class TestAIServiceCircuitBreaker(unittest.TestCase):
    """熔断器集成测试"""

    def setUp(self):
        self.svc = _create_test_svc()

    def test_circuit_breaker_integration(self):
        """验证连续失败触发熔断"""
        mock_resp = _make_error_response(500, "Server Error")

        with patch.object(self.svc._session, 'post', return_value=mock_resp):
            for i in range(5):
                result = self.svc.chat("sys", f"调用{i}")
                self.assertEqual(result, "")

            self.assertTrue(self.svc._is_breaker_open())

    def test_circuit_breaker_blocks_calls(self):
        """熔断器打开后，后续调用直接跳过"""
        mock_resp = _make_error_response(500, "Server Error")

        with patch.object(self.svc._session, 'post', return_value=mock_resp):
            for i in range(5):
                self.svc.chat("sys", f"调用{i}")

        # 熔断后调用（不再mock，因为应该被熔断器拦截，不会真正发请求）
        result = self.svc.chat("sys", "熔断后的调用")
        self.assertEqual(result, "")

    def test_circuit_breaker_resets_on_success(self):
        """成功调用后重置熔断计数"""
        # 先失败3次
        mock_err = _make_error_response(500, "Server Error")
        with patch.object(self.svc._session, 'post', return_value=mock_err):
            for i in range(3):
                self.svc.chat("sys", f"失败{i}")
        self.assertEqual(self.svc._fail_count, 3)

        # 成功1次
        mock_ok = _make_mock_response("ok")
        with patch.object(self.svc._session, 'post', return_value=mock_ok):
            self.svc.chat("sys", "成功")

        self.assertEqual(self.svc._fail_count, 0)


class TestAIServiceFallbackOnError(unittest.TestCase):
    """API错误时降级行为测试"""

    def setUp(self):
        self.svc = _create_test_svc()

    def test_fallback_on_error(self):
        """API连接异常时返回空字符串，不抛异常"""
        import requests as req_lib
        with patch.object(self.svc._session, 'post',
                          side_effect=req_lib.exceptions.ConnectionError("连接超时")):
            result = self.svc.chat("sys", "test")
            self.assertEqual(result, "")

    def test_fallback_malformed_response(self):
        """API返回格式错误时不崩溃"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("not valid json")
        mock_resp.text = "not valid json"

        with patch.object(self.svc._session, 'post', return_value=mock_resp):
            result = self.svc.chat("sys", "test")
            self.assertEqual(result, "")

    def test_fallback_missing_choices(self):
        """API返回无choices字段时不崩溃"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": "no choices"}
        mock_resp.text = '{"data": "no choices"}'

        with patch.object(self.svc._session, 'post', return_value=mock_resp):
            result = self.svc.chat("sys", "test")
            self.assertEqual(result, "")

    def test_stats_track_failures(self):
        """统计信息正确追踪失败"""
        import requests as req_lib
        with patch.object(self.svc._session, 'post',
                          side_effect=req_lib.exceptions.ConnectionError("error")):
            self.svc.chat("sys", "test1")
            self.svc.chat("sys", "test2")

        stats = self.svc.stats
        self.assertEqual(stats["total_calls"], 2)
        self.assertEqual(stats["total_success"], 0)
        self.assertEqual(stats["fail_count"], 2)

    def test_stats_track_success(self):
        """统计信息正确追踪成功"""
        mock_resp = _make_mock_response("ok")

        with patch.object(self.svc._session, 'post', return_value=mock_resp):
            self.svc.chat("sys", "test")

        stats = self.svc.stats
        self.assertEqual(stats["total_calls"], 1)
        self.assertEqual(stats["total_success"], 1)
        self.assertEqual(stats["fail_count"], 0)


class TestAIServiceProviderSwitch(unittest.TestCase):
    """运行中切换供应商测试"""

    def setUp(self):
        self.svc = _create_test_svc()

    def test_provider_switch_mid_session(self):
        """运行中切换供应商"""
        self.assertEqual(self.svc.provider, "deepseek")
        self.assertEqual(self.svc._config["model"], "deepseek-chat")

        self.svc.switch_provider("deepseek-reasoner")
        self.assertEqual(self.svc.provider, "deepseek-reasoner")
        self.assertEqual(self.svc._config["model"], "deepseek-reasoner")
        self.assertEqual(self.svc._config["max_tokens"], 4000)

    def test_provider_switch_uses_new_config_in_chat(self):
        """切换供应商后chat使用新配置"""
        mock_resp = _make_mock_response("reasoning response")

        self.svc.switch_provider("deepseek-reasoner")

        with patch.object(self.svc._session, 'post', return_value=mock_resp) as mock_post:
            self.svc.chat("sys", "test")

            payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json", {})
            self.assertEqual(payload["model"], "deepseek-reasoner")

    def test_provider_switch_invalid_ignores(self):
        """切换到无效供应商时保持当前供应商"""
        original_provider = self.svc.provider
        self.svc.switch_provider("nonexistent_provider")
        self.assertEqual(self.svc.provider, original_provider)

    def test_switch_preserves_stats(self):
        """切换供应商不影响调用统计"""
        mock_resp = _make_mock_response("ok")

        with patch.object(self.svc._session, 'post', return_value=mock_resp):
            self.svc.chat("sys", "test")

        self.assertEqual(self.svc.stats["total_calls"], 1)

        self.svc.switch_provider("deepseek-reasoner")

        self.assertEqual(self.svc.stats["total_calls"], 1)


class TestAIServiceFreeFirst(unittest.TestCase):
    """免费优先（W63补38）：chat() 先走免费池，失败才走本供应商（付费DeepSeek）"""

    def setUp(self):
        self.svc = _create_test_svc()

    def test_free_first_uses_free_pool_when_available(self):
        """免费池可用时优先使用免费模型，不再调用付费供应商"""
        _cfg = [{"_provider": "siliconflow", "_model_id": "THUDM/GLM-4-32B-0414"}]
        with patch("core.free_model_pool.get_free_provider_cfgs", return_value=_cfg), \
             patch("core.free_model_pool.call_ai_failover",
                   return_value=("免费模型回复", None, _cfg[0])) as mock_failover, \
             patch.object(self.svc._session, 'post') as mock_post:
            result = self.svc.chat("sys", "usr")
            self.assertEqual(result, "免费模型回复")
            mock_failover.assert_called_once()
            mock_post.assert_not_called()

    def test_free_first_falls_back_to_paid_when_free_down(self):
        """免费池全挂时回退到本供应商（付费DeepSeek）"""
        with patch("core.free_model_pool.get_free_provider_cfgs",
                   return_value=[{"_provider": "siliconflow", "_model_id": "m1"}]), \
             patch("core.free_model_pool.call_ai_failover",
                   return_value=(None, "ALL_FREE_DOWN", None)), \
             patch.object(self.svc._session, 'post',
                          return_value=_make_mock_response("付费回复")):
            result = self.svc.chat("sys", "usr")
            self.assertEqual(result, "付费回复")

    def test_free_first_disabled_explicitly(self):
        """free_first=False 时跳过免费池，直接走本供应商"""
        _cfg = [{"_provider": "siliconflow", "_model_id": "m1"}]
        with patch("core.free_model_pool.get_free_provider_cfgs", return_value=_cfg), \
             patch("core.free_model_pool.call_ai_failover") as mock_failover, \
             patch.object(self.svc._session, 'post',
                          return_value=_make_mock_response("直接付费回复")):
            result = self.svc.chat("sys", "usr", free_first=False)
            self.assertEqual(result, "直接付费回复")
            mock_failover.assert_not_called()


class TestAIServiceDashscopeWiring(unittest.TestCase):
    """百炼(dashscope)接线测试：切换供应商按平台密钥文件读取（JS-20260806 W63补49）"""

    def _patched_keydir(self, tmpdir, content=None):
        """临时密钥目录，返回 (daemon_path, orig) 供 with 使用"""
        from core import ai_service as m
        orig = m._SECRETS_DIR
        if content is not None:
            with open(os.path.join(tmpdir, "dashscope_key.txt"), "w",
                      encoding="utf-8") as f:
                f.write(content)
        m._SECRETS_DIR = tmpdir
        return orig

    def test_dashscope_provider_configured(self):
        """PROVIDERS 已注册 dashscope，端点为百炼 OpenAI兼容模式"""
        from core import ai_service as m
        self.assertIn("dashscope", m.PROVIDERS)
        self.assertTrue(
            m.PROVIDERS["dashscope"]["api_url"].startswith(
                "https://dashscope.aliyuncs.com/compatible-mode"))
        self.assertEqual(m.PROVIDERS["dashscope"]["model"], "qwen-plus")

    def test_fallback_chain_includes_dashscope(self):
        """fallback链包含百炼，完整顺序见 test_fallback_chain_order"""
        from core import ai_service as m
        self.assertIn("dashscope", m.FALLBACK_CHAIN)
        self.assertLess(m.FALLBACK_CHAIN.index("dashscope"),
                        m.FALLBACK_CHAIN.index("ollama"))

    def test_switch_dashscope_without_key_stays_empty(self):
        """未配置百炼密钥时切换 api_key 为空，不回退 deepseek 密钥"""
        import tempfile, shutil
        from core import ai_service as m
        tmpdir = tempfile.mkdtemp()
        old_secrets = m._SECRETS_DIR
        m._SECRETS_DIR = tmpdir
        svc = _create_test_svc()
        try:
            svc.switch_provider("dashscope")
            self.assertEqual(svc.provider, "dashscope")
            self.assertEqual(svc.api_key, "")
        finally:
            m._SECRETS_DIR = old_secrets
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_switch_dashscope_reads_own_key_file(self):
        """百炼密钥文件存在时切换到 dashscope 读入该平台密钥"""
        import tempfile, shutil
        from core import ai_service as m
        tmpdir = tempfile.mkdtemp()
        old_secrets = m._SECRETS_DIR
        m._SECRETS_DIR = tmpdir
        svc = _create_test_svc()
        try:
            with open(os.path.join(tmpdir, "dashscope_key.txt"), "w",
                      encoding="utf-8") as f:
                f.write("sk-dashscope-secret")
            svc.switch_provider("dashscope")
            self.assertEqual(svc.api_key, "sk-dashscope-secret")
        finally:
            m._SECRETS_DIR = old_secrets
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_zhipu_moonshot_providers_configured(self):
        """智谱/月之暗面已注册进 PROVIDERS，端点为官方 OpenAI兼容地址"""
        from core import ai_service as m
        self.assertIn("zhipu", m.PROVIDERS)
        self.assertEqual(
            m.PROVIDERS["zhipu"]["api_url"],
            "https://open.bigmodel.cn/api/paas/v4/chat/completions")
        self.assertTrue(m.PROVIDERS["zhipu"]["model"])
        self.assertIn("moonshot", m.PROVIDERS)
        self.assertEqual(
            m.PROVIDERS["moonshot"]["api_url"],
            "https://api.moonshot.cn/v1/chat/completions")
        self.assertTrue(m.PROVIDERS["moonshot"]["model"])

    def test_fallback_chain_order(self):
        """fallback链顺序：deepseek→reasoner→智谱→百炼→ollama"""
        from core import ai_service as m
        self.assertEqual(
            m.FALLBACK_CHAIN,
            ["deepseek", "deepseek-reasoner", "zhipu", "dashscope", "ollama"])

    def test_switch_zhipu_moonshot_key_isolation(self):
        """智谱/月之暗面密钥文件不存在时切换 api_key 为空（不回退）"""
        import tempfile, shutil
        from core import ai_service as m
        tmpdir = tempfile.mkdtemp()
        old_secrets = m._SECRETS_DIR
        m._SECRETS_DIR = tmpdir
        svc = _create_test_svc()
        try:
            svc.switch_provider("zhipu")
            self.assertEqual(svc.api_key, "")
            svc.switch_provider("moonshot")
            self.assertEqual(svc.api_key, "")
            # 写入后能读回
            with open(os.path.join(tmpdir, "zhipu_key.txt"), "w",
                      encoding="utf-8") as f:
                f.write("sk-zhipu-secret")
            svc.switch_provider("zhipu")
            self.assertEqual(svc.api_key, "sk-zhipu-secret")
        finally:
            m._SECRETS_DIR = old_secrets
            shutil.rmtree(tmpdir, ignore_errors=True)
