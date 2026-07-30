# -*- coding: utf-8 -*-
"""AI测试生成器模块测试

测试内容：
  - 模板模式生成测试
  - 自动识别测试类型
  - 从文件生成测试
"""
import os
import sys
import json
import tempfile

import unittest

_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from knowledge.ai_test_generator import AITestGenerator


class TestAITestGeneratorInit(unittest.TestCase):
    """测试初始化"""

    def test_init_ok(self):
        """测试初始化"""
        generator = AITestGenerator()
        self.assertIsNotNone(generator)

    def test_default_mode_template(self):
        """测试默认模式"""
        generator = AITestGenerator()
        # 如无AI则为template
        self.assertFalse(generator.ai_available)

    def test_has_templates(self):
        """测试有模板"""
        self.assertIn("function", AITestGenerator.TEST_TEMPLATES)
        self.assertIn("class", AITestGenerator.TEST_TEMPLATES)
        self.assertIn("api", AITestGenerator.TEST_TEMPLATES)
        self.assertIn("security", AITestGenerator.TEST_TEMPLATES)


class TestAITestGeneratorTemplate(unittest.TestCase):
    """测试模板模式"""

    def setUp(self):
        self.generator = AITestGenerator()

    def test_generate_function(self):
        """测试生成函数测试"""
        result = self.generator.generate("测试计算器加法功能", "function")
        self.assertIn("test_code", result)
        self.assertIn("test_", result["test_code"])
        self.assertEqual(result["mode"], "template")
        self.assertGreater(result["test_count"], 0)

    def test_generate_security(self):
        """测试生成安全测试"""
        result = self.generator.generate("测试数据加密安全", "security")
        self.assertIn("test_code", result)
        self.assertIn("encryption", result["test_code"])

    def test_generate_class(self):
        """测试生成类测试"""
        result = self.generator.generate("测试数据管理器类", "class")
        self.assertIn("test_code", result)
        self.assertIn("test_", result["test_code"])

    def test_generate_api(self):
        """测试生成API测试"""
        result = self.generator.generate("测试用户接口API", "api")
        self.assertIn("test_code", result)
        self.assertIn("test_", result["test_code"])

    def test_auto_detect_security(self):
        """测试自动识别安全类别"""
        result = self.generator.generate("测试基金数据加密功能", "auto")
        self.assertIn("test_code", result)
        # 安全模板包含encryption
        self.assertIn("encryption", result["test_code"])

    def test_auto_detect_api(self):
        """测试自动识别API类别"""
        result = self.generator.generate("测试API接口功能", "auto")
        self.assertIn("test_code", result)

    def test_auto_detect_function(self):
        """测试自动识别函数类别"""
        result = self.generator.generate("测试普通功能", "auto")
        self.assertIn("test_code", result)


class TestAITestGeneratorFromFile(unittest.TestCase):
    """测试从文件生成"""

    def setUp(self):
        self.generator = AITestGenerator()

    def test_generate_from_file_not_found(self):
        """测试文件不存在"""
        result = self.generator.generate_from_file("/nonexistent/file.py")
        self.assertIn("error", result)

    def test_generate_from_empty_file(self):
        """测试空文件"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("# empty\n")
            f.flush()
            filepath = f.name

        try:
            result = self.generator.generate_from_file(filepath)
            self.assertIn("test_code", result)
            self.assertEqual(result["functions_found"], [])
            self.assertEqual(result["classes_found"], [])
        finally:
            os.unlink(filepath)

    def test_generate_from_file_with_code(self):
        """测试从有代码的文件生成"""
        code = """
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

class Calculator:
    def multiply(self, a, b):
        return a * b
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            filepath = f.name

        try:
            result = self.generator.generate_from_file(filepath)
            self.assertIn("test_code", result)
            self.assertGreater(result["test_count"], 0)
            self.assertIn("add", result["functions_found"])
            self.assertIn("Calculator", result["classes_found"])
        finally:
            os.unlink(filepath)


class TestAITestGeneratorEdge(unittest.TestCase):
    """测试边界情况"""

    def setUp(self):
        self.generator = AITestGenerator()

    def test_empty_description(self):
        """测试空描述"""
        result = self.generator.generate("", "function")
        self.assertIn("test_code", result)

    def test_short_description(self):
        """测试短描述"""
        result = self.generator.generate("测试", "function")
        self.assertIn("test_code", result)

    def test_special_chars(self):
        """测试特殊字符"""
        result = self.generator.generate("测试$%^&*()功能", "function")
        self.assertIn("test_code", result)
