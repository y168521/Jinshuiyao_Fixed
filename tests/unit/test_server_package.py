# -*- coding: utf-8 -*-
"""金水谣系统 - 导航服务器单元测试

测试 server/ 模块群的核心功能（不启动真实服务器）：
- 模块可导入
- jinshuiyao-guide 目录及总控台 HTML 存在
- 关键 API 路由字符串存在于代码中
- 系统 Python 路径配置

注：原 test_guide_server.py，guide_server.py 退役后改为直接测试 server 包。
"""
import os
import sys
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestGuideServer(unittest.TestCase):
    """测试 server/ 模块群（原 guide_server.py 已退役）"""

    @classmethod
    def setUpClass(cls):
        """加载 server/ 模块群所有源码字符串以便后续做字符串断言"""
        cls.project_root = os.path.join(os.path.dirname(__file__), "..", "..")
        # 读取 server/ 模块群全部 .py 文件
        source_parts = []
        server_dir = os.path.join(cls.project_root, "server")
        for dirpath, _dirnames, filenames in os.walk(server_dir):
            for fn in filenames:
                if fn.endswith('.py'):
                    fp = os.path.join(dirpath, fn)
                    with open(fp, "r", encoding="utf-8") as f:
                        source_parts.append(f.read())
        cls.source_code = '\n'.join(source_parts)

    def test_import(self):
        """能正常导入 server 包"""
        try:
            import server
        except Exception as e:
            self.fail("导入 server 包失败: %s" % e)
        self.assertTrue(hasattr(server, "PORT"))
        self.assertTrue(hasattr(server, "HTML_DIR"))

    def test_html_dir_exists(self):
        """jinshuiyao-guide 目录存在"""
        try:
            import server
        except Exception as e:
            self.skipTest("无法导入 server: %s" % e)
        self.assertTrue(os.path.isdir(server.HTML_DIR),
                        "jinshuiyao-guide 目录不存在: %s" % server.HTML_DIR)

    def test_control_center_exists(self):
        """总控台 HTML (control-center.html) 存在"""
        try:
            import server
        except Exception as e:
            self.skipTest("无法导入 server: %s" % e)
        self.assertTrue(os.path.isfile(server.CONTROL_CENTER),
                        "总控台HTML不存在: %s" % server.CONTROL_CENTER)

    def test_api_routes_defined(self):
        """关键路由字符串应存在于 server/ 源码中"""
        # 子系统状态API
        self.assertIn("/status", self.source_code, "缺少 /status 路由")
        # AI对话接口
        self.assertIn("/api/chat", self.source_code, "缺少 /api/chat 路由")
        # AI服务状态
        self.assertIn("/api/status", self.source_code, "缺少 /api/status 路由")
        # 视频文案提取
        self.assertIn("/api/extract", self.source_code, "缺少 /api/extract 路由")
        # 内容提炼
        self.assertIn("/api/refine", self.source_code, "缺少 /api/refine 路由")
        # 运行测试
        self.assertIn("/api/run-tests", self.source_code, "缺少 /api/run-tests 路由")
        # 基金通知
        self.assertIn("/api/fund-notification", self.source_code,
                      "缺少 /api/fund-notification 路由")
        # 测试结果
        self.assertIn("/api/test-results", self.source_code,
                      "缺少 /api/test-results 路由")

    def test_knowledge_routes(self):
        """知识库 API 路由应存在于 server/ 源码中"""
        # 知识库统计
        self.assertIn("/api/knowledge/stats", self.source_code,
                      "缺少 /api/knowledge/stats 路由")
        # 知识库搜索
        self.assertIn("/api/knowledge/search", self.source_code,
                      "缺少 /api/knowledge/search 路由")
        # 知识库列表
        self.assertIn("/api/knowledge/list", self.source_code,
                      "缺少 /api/knowledge/list 路由")
        # 知识库添加
        self.assertIn("/api/knowledge/add", self.source_code,
                      "缺少 /api/knowledge/add 路由")
        # URL 提取并归档
        self.assertIn("/api/knowledge/extract-archive", self.source_code,
                      "缺少 /api/knowledge/extract-archive 路由")

    def test_system_python(self):
        """系统Python路径配置应在代码中存在"""
        # _find_python 函数应存在
        self.assertIn("_find_python", self.source_code,
                      "缺少 _find_python 函数")
        # SYSTEM_PYTHON 应是模块属性
        try:
            import server
        except Exception as e:
            self.skipTest("无法导入 server: %s" % e)
        self.assertTrue(hasattr(server, "SYSTEM_PYTHON"),
                        "server 应有 SYSTEM_PYTHON 属性")
        self.assertTrue(hasattr(server, "SYSTEM_PYTHONW"),
                        "server 应有 SYSTEM_PYTHONW 属性")
        # SYSTEM_PYTHON 应是非空字符串
        self.assertIsInstance(server.SYSTEM_PYTHON, str)
        self.assertGreater(len(server.SYSTEM_PYTHON), 0)

    def test_guide_handler_class(self):
        """GuideHandler 类应定义"""
        try:
            import server
        except Exception as e:
            self.skipTest("无法导入 server: %s" % e)
        self.assertTrue(hasattr(server, "GuideHandler"),
                        "server 应有 GuideHandler 类")
        # 检查 GuideHandler 是类
        import http.server
        self.assertTrue(issubclass(server.GuideHandler,
                                   http.server.SimpleHTTPRequestHandler))

    def test_log_function(self):
        """log 函数应可调用"""
        try:
            import server
        except Exception as e:
            self.skipTest("无法导入 server: %s" % e)
        self.assertTrue(callable(getattr(server, "log", None)),
                        "server.log 应可调用")

    def test_open_local_file_function(self):
        """open_local_file 函数应可调用"""
        try:
            from server.utils import open_local_file
        except Exception as e:
            self.skipTest("无法导入 server.utils: %s" % e)
        self.assertTrue(callable(open_local_file),
                        "server.utils.open_local_file 应可调用")

    def test_fund_report_fallback(self):
        """基金日报回退：当天报告不存在→回退最新一期；存在→不回退；非报告→不动"""
        import os
        import tempfile
        import unittest.mock as mock
        from server import utils
        with tempfile.TemporaryDirectory() as td:
            reports_dir = os.path.join(td, "金水谣数据", "fund_reports")
            os.makedirs(reports_dir, exist_ok=True)
            for d in ("2026-08-04", "2026-08-05"):
                with open(os.path.join(reports_dir, f"fund_report_{d}.html"), "w", encoding="utf-8") as f:
                    f.write("<html></html>")
            base = mock.patch.object(utils, "BASE_DIR", td)
            with base:
                # 1. 当天不存在 → 回退最新一期
                rel, date, hint = utils._fund_report_fallback(
                    os.path.join("金水谣数据", "fund_reports", "fund_report_2026-08-06.html").replace(os.sep, "/"))
                self.assertEqual(date, "2026-08-05")
                self.assertTrue(rel.endswith("fund_report_2026-08-05.html"))
                self.assertIn("2026-08-05", hint)
                # 2. 已存在 → 不回退
                rel2, date2, _ = utils._fund_report_fallback(
                    os.path.join("金水谣数据", "fund_reports", "fund_report_2026-08-05.html").replace(os.sep, "/"))
                self.assertIsNone(date2)
                self.assertTrue(rel2.endswith("fund_report_2026-08-05.html"))
                # 3. 非基金报告 → 不动
                rel3, date3, _ = utils._fund_report_fallback("金水谣数据/log/经验收集箱.md")
                self.assertIsNone(date3)
                # 4. 目录无任何报告 → 不回退
                os.remove(os.path.join(reports_dir, "fund_report_2026-08-04.html"))
                os.remove(os.path.join(reports_dir, "fund_report_2026-08-05.html"))
                rel4, date4, _ = utils._fund_report_fallback(
                    os.path.join("金水谣数据", "fund_reports", "fund_report_2026-08-06.html").replace(os.sep, "/"))
                self.assertIsNone(date4)


    def test_keys_routes_registered(self):
        """密钥管理 API 路由应存在于 server/ 源码中"""
        self.assertIn("/api/keys", self.source_code, "缺少 /api/keys 路由")
        self.assertIn("/api/keys/save", self.source_code, "缺少 /api/keys/save 路由")
        self.assertIn("/api/keys/test", self.source_code, "缺少 /api/keys/test 路由")
        self.assertIn("/api/keys/identify", self.source_code, "缺少 /api/keys/identify 路由")

    def test_keys_slot_whitelist_and_roundtrip(self):
        """密钥槽位：白名单拒绝非法名 + 写入/读取/掩码往返"""
        from server.handlers import keys as h_keys
        import tempfile, shutil
        tmp = tempfile.mkdtemp(prefix="keys_ut_")
        old_dir = h_keys._SECRETS_DIR
        h_keys._SECRETS_DIR = tmp
        try:
            # 槽位齐全（含阿里云百炼/智谱/月之暗面）
            self.assertIn("deepseek_key", h_keys.KEY_SLOTS)
            self.assertIn("siliconflow_key", h_keys.KEY_SLOTS)
            self.assertIn("dashscope_key", h_keys.KEY_SLOTS)
            self.assertIn("zhipu_key", h_keys.KEY_SLOTS)
            self.assertIn("moonshot_key", h_keys.KEY_SLOTS)
            self.assertIn("tavily_key", h_keys.KEY_SLOTS)
            self.assertIn("douyin_cookie", h_keys.KEY_SLOTS)
            # 掩码
            self.assertEqual(h_keys._mask("sk-abcdef1234567890"), "sk-a…7890")
            self.assertEqual(h_keys._mask(""), "")
            # 路径穿越拒绝
            with self.assertRaises(ValueError):
                h_keys._slot_file("../evil")
            with self.assertRaises(ValueError):
                h_keys._slot_file("dashscope_key.txt/../../x")
            # 写入+读取往返
            p = h_keys._write_secret("dashscope_key", "sk-test-abc")
            self.assertTrue(os.path.isfile(p))
            self.assertEqual(h_keys._read_slot_value("dashscope_key"), "sk-test-abc")
            # 空值拒绝
            with self.assertRaises(ValueError):
                h_keys._write_secret("dashscope_key", "   ")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            h_keys._SECRETS_DIR = old_dir

    def test_keys_list_masks_secret(self):
        """GET /api/keys 列表：已配置槽位只回掩码，绝不回明文"""
        import tempfile, shutil, json
        from server.handlers import keys as h_keys
        tmp = tempfile.mkdtemp(prefix="keys_ut2_")
        old_dir = h_keys._SECRETS_DIR
        h_keys._SECRETS_DIR = tmp
        try:
            h_keys._write_secret("deepseek_key", "sk-SECRET-123456")
            items = []
            for slot, info in h_keys.KEY_SLOTS.items():
                val = h_keys._read_slot_value(slot)
                items.append({"slot": slot, "configured": bool(val), "masked": h_keys._mask(val)})
            ds = next(i for i in items if i["slot"] == "deepseek_key")
            self.assertTrue(ds["configured"])
            self.assertNotIn("sk-SECRET-123456", ds["masked"])
            self.assertIn("…3456", ds["masked"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            h_keys._SECRETS_DIR = old_dir

    def test_keys_identify_probes_all_llm_slots_with_manual_fallback(self):
        """智能识别：依次探测全部5个LLM平台，全部未命中时返回 manual_slots 兜底"""
        from server.handlers import keys as h_keys
        import json

        calls = []

        def fake_test(key, info, timeout=10):
            slot = [s for s, i in h_keys.KEY_SLOTS.items()
                    if i == info][0]
            calls.append(slot)
            # 只让 deepseek_key 命中
            if slot == "deepseek_key":
                return True, "HTTP 200"
            return False, "HTTP 401"

        class FakeHandler:
            def _read_body(self):
                return json.dumps({"value": "sk-probe-123"})

            def _send_json(self, payload):
                self.payload = payload

        h = FakeHandler()
        with unittest.mock.patch.object(h_keys, "_http_test", side_effect=fake_test):
            h_keys.handle_keys_identify(h)
        self.assertEqual(
            calls,
            ["deepseek_key", "siliconflow_key", "dashscope_key",
             "zhipu_key", "moonshot_key"])
        self.assertTrue(h.payload["ok"])
        self.assertEqual(h.payload["hits"][0]["slot"], "deepseek_key")
        self.assertEqual(len(h.payload["manual_slots"]), 5)

        # 全部未命中 → ok=False 且仍带 manual_slots
        calls.clear()

        def fake_test_none(key, info, timeout=10):
            return False, "HTTP 401"

        h2 = FakeHandler()
        with unittest.mock.patch.object(h_keys, "_http_test",
                                        side_effect=fake_test_none):
            h_keys.handle_keys_identify(h2)
        self.assertFalse(h2.payload["ok"])
        self.assertEqual(len(h2.payload["manual_slots"]), 5)

    def test_keys_manual_slot_verify_save_flow(self):
        """手动选择流程：任意 LLM 槽位可独立验证（test）后保存（save）"""
        from server.handlers import keys as h_keys
        import tempfile, shutil, json
        tmp = tempfile.mkdtemp(prefix="keys_ut3_")
        old_dir = h_keys._SECRETS_DIR
        h_keys._SECRETS_DIR = tmp
        try:
            for slot in ("zhipu_key", "moonshot_key"):
                info = h_keys.KEY_SLOTS[slot]
                self.assertIn("test_url", info)
                self.assertIn("test_headers", info)
                p = h_keys._write_secret(slot, "sk-manual-%s" % slot)
                self.assertEqual(h_keys._read_slot_value(slot), "sk-manual-%s" % slot)
                self.assertTrue(os.path.isfile(p))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            h_keys._SECRETS_DIR = old_dir


if __name__ == "__main__":
    unittest.main()
