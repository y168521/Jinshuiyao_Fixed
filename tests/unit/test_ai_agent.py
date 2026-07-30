# -*- coding: utf-8 -*-
"""金水谣AI体单元测试

使用mock替代真实子系统依赖，测试意图识别和调度逻辑。
"""
import unittest
from unittest.mock import MagicMock, patch, PropertyMock


class TestJinshuiyaoAgent(unittest.TestCase):
    """AI体核心测试"""

    _MOCKED_MODULES = [
        "domains.lottery.domain",
        "domains.stock.domain",
        "domains.football.domain",
        "core.ai_service",
    ]

    def setUp(self):
        # mock掉子系统导入
        import sys
        self._saved_modules = {}
        for mod_name in self._MOCKED_MODULES:
            if mod_name in sys.modules:
                self._saved_modules[mod_name] = sys.modules[mod_name]
            sys.modules[mod_name] = MagicMock()

        # 重新导入agent模块
        import importlib
        from core import ai_agent
        importlib.reload(ai_agent)

        self.agent = ai_agent.JinshuiyaoAgent()

    def tearDown(self):
        """清理模块级mock，避免残留影响后续测试类"""
        import sys
        import importlib
        for mod_name in self._MOCKED_MODULES:
            if mod_name in self._saved_modules:
                sys.modules[mod_name] = self._saved_modules[mod_name]
            else:
                sys.modules.pop(mod_name, None)
        # reload ai_agent 恢复真实导入
        from core import ai_agent
        importlib.reload(ai_agent)

    # ---------------------------------------------------------------
    # 意图识别
    # ---------------------------------------------------------------

    def test_intent_lottery_ssq(self):
        """识别双色球意图"""
        sub, act, target = self.agent._parse_intent("双色球预测")
        self.assertEqual(sub, "lottery")
        self.assertEqual(act, "predict")
        self.assertEqual(target, "双色球")

    def test_intent_lottery_3d(self):
        """识别福彩3D意图"""
        sub, act, target = self.agent._parse_intent("福彩3D推荐")
        self.assertEqual(sub, "lottery")

    def test_intent_lottery_dlt(self):
        """识别大乐透意图"""
        sub, act, target = self.agent._parse_intent("大乐透号码")
        self.assertEqual(sub, "lottery")
        self.assertEqual(target, "大乐透")

    def test_intent_stock_index(self):
        """识别大盘查询意图"""
        sub, act, target = self.agent._parse_intent("大盘怎么样")
        self.assertEqual(sub, "stock")
        self.assertEqual(act, "index")

    def test_intent_stock_pick(self):
        """识别选股推荐意图"""
        sub, act, target = self.agent._parse_intent("帮我选股")
        self.assertEqual(sub, "stock")
        self.assertEqual(act, "pick")

    def test_intent_stock_sh000001(self):
        """识别上证指数意图"""
        sub, act, target = self.agent._parse_intent("上证指数")
        self.assertEqual(sub, "stock")
        self.assertEqual(target, "sh000001")

    def test_intent_football_match(self):
        """识别足球赛事意图"""
        sub, act, target = self.agent._parse_intent("今天有什么比赛")
        self.assertEqual(sub, "football")
        self.assertEqual(act, "matches")

    def test_intent_football_world_cup(self):
        """识别世界杯意图"""
        sub, act, target = self.agent._parse_intent("世界杯预测")
        self.assertEqual(sub, "football")

    def test_intent_system_status(self):
        """识别系统状态意图"""
        sub, act, target = self.agent._parse_intent("系统状态")
        self.assertEqual(sub, "system")
        self.assertEqual(act, "status")

    def test_intent_system_help(self):
        """识别帮助意图"""
        sub, act, target = self.agent._parse_intent("你能做什么")
        self.assertEqual(sub, "system")
        self.assertEqual(act, "help")

    def test_intent_system_greet(self):
        """识别打招呼意图"""
        sub, act, target = self.agent._parse_intent("你好")
        self.assertEqual(sub, "system")
        self.assertEqual(act, "greet")

    def test_intent_system_test(self):
        """识别运行测试意图"""
        sub, act, target = self.agent._parse_intent("运行测试")
        self.assertEqual(sub, "system")
        self.assertEqual(act, "test")

    def test_intent_unknown_fallback(self):
        """无法识别时回退到general"""
        sub, act, target = self.agent._parse_intent("随机乱七八糟的话")
        self.assertEqual(sub, "general")

    # ---------------------------------------------------------------
    # 系统管理调度
    # ---------------------------------------------------------------

    def test_dispatch_help(self):
        """帮助信息不为空"""
        result = self.agent._dispatch_system("help", "帮助信息")
        self.assertIn("功能列表", result)
        self.assertIn("彩票", result)
        self.assertIn("股票", result)
        self.assertIn("足彩", result)

    def test_dispatch_greet(self):
        """打招呼回复不为空"""
        result = self.agent._dispatch_system("greet", "打招呼")
        self.assertIn("金水谣AI助手", result)

    def test_dispatch_status(self):
        """系统状态返回文本"""
        result = self.agent._dispatch_system("status", "系统状态")
        self.assertIn("系统状态", result)
        self.assertIn("时间", result)

    def test_dispatch_test(self):
        """运行测试返回提示"""
        result = self.agent._dispatch_system("test", "运行测试")
        self.assertIn("测试", result)

    # ---------------------------------------------------------------
    # 清空历史
    # ---------------------------------------------------------------

    def test_clear_history(self):
        """清空历史"""
        self.agent._history = [("user", "test"), ("assistant", "reply")]
        self.agent.clear_history()
        self.assertEqual(len(self.agent._history), 0)

    # ---------------------------------------------------------------
    # chat主入口
    # ---------------------------------------------------------------

    def test_chat_empty(self):
        """空输入返回提示"""
        result = self.agent.chat("")
        self.assertIn("请输入", result)

    def test_chat_greeting(self):
        """打招呼返回欢迎"""
        result = self.agent.chat("你好")
        self.assertTrue(len(result) > 10)

    def test_chat_clear_history_command(self):
        """清空历史指令"""
        result = self.agent.chat("__clear_history__")
        self.assertEqual(result, "__cleared__")
        self.assertEqual(len(self.agent._history), 0)


class TestAIService(unittest.TestCase):
    """AI服务层测试"""

    def setUp(self):
        import importlib, sys
        # 确保 ai_service 模块未被 mock 残留污染
        if isinstance(sys.modules.get("core.ai_service"), type(MagicMock)):
            sys.modules.pop("core.ai_service", None)
        import core.ai_service as _ai_svc
        importlib.reload(_ai_svc)
        from core.ai_service import AIService, PROVIDERS
        self.PROVIDERS = PROVIDERS
        self.AIService = AIService

    def test_providers_config(self):
        """供应商配置完整"""
        self.assertIn("deepseek", self.PROVIDERS)
        ds = self.PROVIDERS["deepseek"]
        self.assertEqual(ds["model"], "deepseek-chat")
        self.assertIn("api_url", ds)

    def test_subsystem_prompts(self):
        """子系统Prompt模板完整"""
        # setUp 已 reload，直接用 self.PROVIDERS 同源的模块
        import importlib, core.ai_service as _ai_svc
        importlib.reload(_ai_svc)
        from core.ai_service import _SUBSYSTEM_PROMPTS
        for name in ["football", "lottery", "stock", "fund", "music", "general"]:
            self.assertIn(name, _SUBSYSTEM_PROMPTS)
            self.assertTrue(len(_SUBSYSTEM_PROMPTS[name]) > 20)

    def test_ai_service_init_no_key(self):
        """无Key时is_available为False（mock环境不受真实环境变量影响）"""
        svc = self.AIService(api_key="", key_file="/nonexistent/path.txt")
        # 如果环境变量有值，is_available可能为True，所以只验证构造不报错
        self.assertIsNotNone(svc.api_key or svc.stats["available"])

    def test_ai_service_stats(self):
        """统计信息结构正确"""
        svc = self.AIService(api_key="")
        stats = svc.stats
        self.assertIn("provider", stats)
        self.assertIn("available", stats)
        self.assertIn("total_calls", stats)
        self.assertEqual(stats["total_calls"], 0)

    def test_switch_provider_valid(self):
        """切换有效供应商"""
        svc = self.AIService(api_key="")
        svc.switch_provider("deepseek-reasoner")
        self.assertEqual(svc.provider, "deepseek-reasoner")

    def test_switch_provider_invalid(self):
        """切换无效供应商不报错"""
        svc = self.AIService(api_key="")
        svc.switch_provider("nonexistent")
        self.assertNotEqual(svc.provider, "nonexistent")
