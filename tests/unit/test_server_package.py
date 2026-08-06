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


if __name__ == "__main__":
    unittest.main()
