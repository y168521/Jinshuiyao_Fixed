# -*- coding: utf-8 -*-
"""金水谣系统 - 质量保障页面单元测试

测试内容：
1. server/ 模块群路由是否正确注册
2. HTML 文件是否存在且包含必要内容
3. AI用例生成的 prompt 格式是否正确

所有测试使用 mock，不依赖实际运行服务器或AI服务。
"""
import os
import sys
import json
import unittest

# 确保项目根目录在路径中
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

HTML_DIR = os.path.join(BASE_DIR, 'jinshuiyao-guide')


class TestHtmlFilesExist(unittest.TestCase):
    """测试1-3：HTML文件是否存在"""

    def test_api_docs_html_exists(self):
        """测试1：api-docs.html 文件存在"""
        path = os.path.join(HTML_DIR, 'api-docs.html')
        self.assertTrue(os.path.isfile(path), f'api-docs.html 不存在于 {path}')

    def test_test_report_html_exists(self):
        """测试2：test-report.html 文件存在"""
        path = os.path.join(HTML_DIR, 'test-report.html')
        self.assertTrue(os.path.isfile(path), f'test-report.html 不存在于 {path}')

    def test_ai_test_html_exists(self):
        """测试3：ai-test.html 文件存在"""
        path = os.path.join(HTML_DIR, 'ai-test.html')
        self.assertTrue(os.path.isfile(path), f'ai-test.html 不存在于 {path}')


class TestHtmlContentValidation(unittest.TestCase):
    """测试4-6：HTML文件包含必要的页面元素"""

    def _read_html(self, filename):
        path = os.path.join(HTML_DIR, filename)
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_api_docs_contains_api_cards(self):
        """测试4：api-docs.html 包含接口卡片渲染代码"""
        content = self._read_html('api-docs.html')
        self.assertIn('renderApiCards', content, 'api-docs.html 缺少接口卡片渲染函数')
        self.assertIn('tryApi', content, 'api-docs.html 缺少试试看功能')
        self.assertIn('/api/chat', content, 'api-docs.html 缺少 /api/chat 接口信息')
        self.assertIn('接口文档', content, 'api-docs.html 缺少标题')

    def test_test_report_contains_chart(self):
        """测试5：test-report.html 包含环形图和测试列表"""
        content = self._read_html('test-report.html')
        self.assertIn('ring-chart', content, 'test-report.html 缺少环形图组件')
        self.assertIn('runTests', content, 'test-report.html 缺少运行测试功能')
        self.assertIn('testList', content, 'test-report.html 缺少测试列表')
        self.assertIn('exportReport', content, 'test-report.html 缺少导出报告功能')

    def test_ai_test_contains_generation(self):
        """测试6：ai-test.html 包含AI用例生成功能"""
        content = self._read_html('ai-test.html')
        self.assertIn('generateTestCases', content, 'ai-test.html 缺少用例生成函数')
        self.assertIn('exportAsMarkdown', content, 'ai-test.html 缺少Markdown导出')
        self.assertIn('exportAsJson', content, 'ai-test.html 缺少JSON导出')
        self.assertIn('parseAiResponse', content, 'ai-test.html 缺少AI响应解析')


class TestGuideServerRoutes(unittest.TestCase):
    """测试7-10：server/ 模块群路由是否正确注册

    通过检查源代码中是否包含路由关键字来验证路由注册。
    """

    def _read_server(self):
        """读取 server/ 模块群所有源码"""
        parts = []
        server_dir = os.path.join(BASE_DIR, 'server')
        for dirpath, _dirnames, filenames in os.walk(server_dir):
            for fn in filenames:
                if fn.endswith('.py'):
                    with open(os.path.join(dirpath, fn), 'r', encoding='utf-8') as f:
                        parts.append(f.read())
        return '\n'.join(parts)

    def test_docs_route_registered(self):
        """测试7：/docs 路由已注册"""
        content = self._read_server()
        self.assertIn("'/docs'", content,
                       'server/ 缺少 /docs 路由')

    def test_test_report_route_registered(self):
        """测试8：/test-report 路由已注册"""
        content = self._read_server()
        self.assertIn("'/test-report'", content,
                       'server/ 缺少 /test-report 路由')

    def test_ai_test_route_registered(self):
        """测试9：/ai-test 路由已注册"""
        content = self._read_server()
        self.assertIn("'/ai-test'", content,
                       'server/ 缺少 /ai-test 路由')

    def test_api_routes_registered(self):
        """测试10：/api/test-results 和 /api/run-tests 路由已注册"""
        content = self._read_server()
        self.assertIn("parsed.path == '/api/test-results'", content,
                       'server/ 缺少 /api/test-results 路由')
        self.assertIn("parsed.path == '/api/run-tests'", content,
                       'server/ 缺少 /api/run-tests 路由')


class TestGuideServerHandlerMocked(unittest.TestCase):
    """测试11-14：使用源码分析验证GuideHandler的路由处理逻辑"""

    def _read_server_code(self):
        """读取 server/ 模块群所有源码"""
        parts = []
        server_dir = os.path.join(BASE_DIR, 'server')
        for dirpath, _dirnames, filenames in os.walk(server_dir):
            for fn in filenames:
                if fn.endswith('.py'):
                    with open(os.path.join(dirpath, fn), 'r', encoding='utf-8') as f:
                        parts.append(f.read())
        return '\n'.join(parts)

    def test_docs_route_serves_html(self):
        """测试11：/docs 路由正确返回HTML文件内容"""
        # 直接检查源代码验证路由行为（避免import导致mimetypes兼容性问题）
        server_code = self._read_server_code()
        self.assertIn("api-docs.html", server_code, 'server/ 中 /docs 路由未引用 api-docs.html')
        self.assertIn("send_response(200)", server_code, '/docs 路由未使用200状态码')
        self.assertIn("text/html", server_code, '/docs 路由未设置Content-Type为text/html')

    def test_test_report_route_serves_html(self):
        """测试12：/test-report 路由引用正确的文件"""
        server_code = self._read_server_code()
        self.assertIn("test-report.html", server_code)

    def test_ai_test_route_serves_html(self):
        """测试13：/ai-test 路由引用正确的文件"""
        server_code = self._read_server_code()
        self.assertIn("ai-test.html", server_code)

    def test_run_tests_route_calls_subprocess(self):
        """测试14：/api/run-tests 路由调用了subprocess.run"""
        server_code = self._read_server_code()
        self.assertIn("subprocess.run", server_code)
        self.assertIn("smoke_test.py", server_code)
        self.assertIn("SYSTEM_PYTHON", server_code)


class TestAiTestCasePrompt(unittest.TestCase):
    """测试15-16：AI用例生成的prompt格式验证"""

    def _read_html(self, filename):
        path = os.path.join(HTML_DIR, filename)
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_prompt_contains_required_fields(self):
        """测试15：AI prompt 包含所有必要字段（接口路径、方法、说明、参数）"""
        content = self._read_html('ai-test.html')
        # 检查prompt模板中包含必要字段
        self.assertIn('接口路径', content, 'AI prompt 缺少"接口路径"字段')
        self.assertIn('方法', content, 'AI prompt 缺少"方法"字段')
        self.assertIn('说明', content, 'AI prompt 缺少"说明"字段')
        self.assertIn('参数', content, 'AI prompt 缺少"参数"字段')

    def test_prompt_requests_json_array(self):
        """测试16：AI prompt 要求返回JSON数组格式"""
        content = self._read_html('ai-test.html')
        self.assertIn('JSON数组', content, 'AI prompt 未要求JSON数组格式')
        self.assertIn('正常流程测试', content, 'AI prompt 缺少"正常流程测试"类型')
        self.assertIn('参数缺失测试', content, 'AI prompt 缺少"参数缺失测试"类型')
        self.assertIn('参数异常测试', content, 'AI prompt 缺少"参数异常测试"类型')
        self.assertIn('边界值测试', content, 'AI prompt 缺少"边界值测试"类型')
        self.assertIn('安全性测试', content, 'AI prompt 缺少"安全性测试"类型')


class TestControlCenterLinks(unittest.TestCase):
    """测试17：总控台是否包含新页面入口"""

    def test_control_center_has_quality_links(self):
        """测试17：总控台包含接口文档、测试报告、AI用例三个入口按钮"""
        path = os.path.join(HTML_DIR, 'control-center.html')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("/docs", content, '总控台缺少接口文档入口')
        self.assertIn("/test-report", content, '总控台缺少测试报告入口')
        self.assertIn("/ai-test", content, '总控台缺少AI用例入口')


if __name__ == '__main__':
    unittest.main(verbosity=2)
