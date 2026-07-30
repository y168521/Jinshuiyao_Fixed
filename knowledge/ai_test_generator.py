# -*- coding: utf-8 -*-
"""AI测试用例生成器

根据用户输入的功能描述，自动生成可执行的测试用例代码。
支持两种模式：
  1. AI模式（调用DeepSeek API）：使用AI知识库的Prompt模板生成智能测试用例
  2. 模板模式（离线）：基于预设模板生成基础测试用例

使用方式：
  from knowledge.ai_test_generator import AITestGenerator
  generator = AITestGenerator()
  tests = generator.generate("测试基金数据加密功能")
"""
import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AITestGenerator:
    """AI测试用例生成器"""

    TEST_TEMPLATES = {
        "function": {
            "name": "函数测试",
            "template": '''
def test_{name}_basic():
    """测试{name}基本功能"""
    result = {func_call}
    assert result is not None
    assert isinstance(result, {return_type})

def test_{name}_edge_empty():
    """测试{name}空值/边界"""
    result = {func_call_empty}
    assert result == {empty_expected}

def test_{name}_error_input():
    """测试{name}异常输入"""
    try:
        result = {func_call_error}
        assert False, "应该抛出异常"
    except {error_type}:
        pass
''',
        },
        "class": {
            "name": "类测试",
            "template": '''
def test_{name}_init():
    """测试{name}初始化"""
    obj = {class_name}()
    assert obj is not None

def test_{name}_method_{method}():
    """测试{name}.{method}方法"""
    obj = {class_name}()
    # 准备测试数据
    result = obj.{method}({method_args})
    # 验证结果
    assert result is not None

def test_{name}_method_{method}_edge():
    """测试{name}.{method}边界情况"""
    obj = {class_name}()
    result = obj.{method}({edge_args})
    assert result is not None
''',
        },
        "api": {
            "name": "API测试",
            "template": '''
def test_{name}_success():
    """测试{name}正常返回"""
    # 构建请求
    data = {request_data}
    # 调用
    result = {api_call}(data)
    # 验证
    assert result.get("status") == "success"

def test_{name}_invalid_params():
    """测试{name}参数错误"""
    try:
        result = {api_call}({invalid_data})
        assert False, "应该抛出异常"
    except Exception:
        pass
''',
        },
        "security": {
            "name": "安全测试",
            "template": '''
def test_{name}_encryption():
    """测试{name}数据加密"""
    sensitive_data = "{sensitive}"
    # 加密
    encrypted = {encrypt_func}(sensitive_data)
    # 验证加密后不等于原文
    assert encrypted != sensitive_data
    # 验证可解密
    decrypted = {decrypt_func}(encrypted)
    assert decrypted == sensitive_data

def test_{name}_access_control():
    """测试{name}访问控制"""
    # 验证敏感数据不可直接访问
    with open({private_file}, "r") as f:
        content = f.read()
    # 检查是否加密
    assert "amount" not in content or content.startswith("gAAA")
''',
        },
    }

    def __init__(self):
        self.ai_available = False
        self._check_ai_available()

    def _check_ai_available(self):
        """检查AI服务是否可用"""
        try:
            from core.ai_service import check_ai_available as check_ai
            self.ai_available = check_ai()
        except Exception:
            self.ai_available = False

    def generate(self, description: str, test_type: str = "auto") -> Dict:
        """根据描述生成测试用例

        参数:
            description: 功能描述，如"测试基金数据加密功能"
            test_type:   auto/funtion/class/api/security

        返回:
            {
                "test_code": "生成的测试代码",
                "test_count": 3,
                "mode": "ai/template",
                "description": "功能描述",
            }
        """
        if self.ai_available and test_type != "template":
            return self._generate_with_ai(description)
        else:
            return self._generate_with_template(description, test_type)

    def _generate_with_ai(self, description: str) -> Dict:
        """使用AI生成测试用例（调用DeepSeek API）"""
        prompt = (
            "请为以下功能描述生成Python测试用例代码（使用unittest风格）：\n"
            f"功能描述: {description}\n\n"
            "要求：\n"
            "1. 生成3-5个测试函数\n"
            "2. 覆盖正常流程、边界情况、异常输入\n"
            "3. 使用assert断言\n"
            "4. 函数名以test_开头\n\n"
            "请只返回代码，不要解释。"
        )

        try:
            from core.ai_service import chat_with_ai
            response = chat_with_ai(prompt)
            test_code = response.get("content", "")

            # 提取代码块
            if "```python" in test_code:
                test_code = test_code.split("```python")[1]
                if "```" in test_code:
                    test_code = test_code.split("```")[0]
            elif "```" in test_code:
                test_code = test_code.split("```")[1]
                if "```" in test_code:
                    test_code = test_code.split("```")[0]

            test_count = test_code.count("def test_")
            return {
                "test_code": test_code.strip(),
                "test_count": max(test_count, 1),
                "mode": "ai",
                "description": description,
            }
        except Exception as e:
            logger.error("AI生成测试失败: %s", e)
            return self._generate_with_template(description, "auto")

    def _generate_with_template(self, description: str, test_type: str) -> Dict:
        """使用模板生成测试用例（离线模式）"""
        desc_lower = description.lower()

        # 自动识别测试类型
        if test_type == "auto":
            if any(kw in desc_lower for kw in ["加密", "安全", "脱敏", "权限"]):
                test_type = "security"
            elif any(kw in desc_lower for kw in ["api", "接口", "路由"]):
                test_type = "api"
            elif any(kw in desc_lower for kw in ["类", "对象", "方法"]):
                test_type = "class"
            else:
                test_type = "function"

        template = self.TEST_TEMPLATES.get(test_type, self.TEST_TEMPLATES["function"])

        # 从描述中提取关键信息
        name = self._extract_name(description)
        test_code = template["template"].format(
            name=name,
            func_call=f"{name}()",
            func_call_empty=f"{name}('')",
            func_call_error=f"{name}(None)",
            return_type="(str, int, float, dict, list)",
            empty_expected="None",
            error_type="(ValueError, TypeError)",
            class_name=name.title().replace("_", ""),
            method="process",
            method_args="test_data",
            edge_args="None",
            request_data='{"key": "value"}',
            api_call=name,
            invalid_data="{}",
            sensitive="test_sensitive_data",
            encrypt_func="encrypt",
            decrypt_func="decrypt",
            private_file='"fund_private.json"',
        )

        test_count = test_code.count("def test_")
        return {
            "test_code": test_code.strip(),
            "test_count": max(test_count, 1),
            "mode": "template",
            "description": description,
        }

    def _extract_name(self, description: str) -> str:
        """从描述中提取测试名称"""
        # 移除常见前缀
        for prefix in ["测试", "检查", "验证", "实现"]:
            if description.startswith(prefix):
                description = description[len(prefix):]
        # 取前10个字符作为名称
        name = ""
        for ch in description[:15]:
            if ch.isalnum() or ch == "_":
                name += ch
            else:
                name += "_"
        return name.strip("_").lower() or "default"

    def generate_from_file(self, file_path: str) -> Dict:
        """根据Python文件生成测试用例"""
        if not os.path.isfile(file_path):
            return {"error": f"文件不存在: {file_path}"}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return {"error": f"读取文件失败: {e}"}

        # 解析文件中的函数和类
        functions = []
        classes = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("def ") and "(" in line:
                func_name = line.split("def ")[1].split("(")[0]
                functions.append(func_name)
            elif line.startswith("class ") and ":" in line:
                class_name = line.split("class ")[1].split(":")[0].split("(")[0]
                classes.append(class_name)

        # 为每个函数/类生成测试
        all_tests = []
        for func_name in functions[:5]:
            result = self.generate(f"测试函数 {func_name}", "function")
            all_tests.append(result["test_code"])

        for class_name in classes[:3]:
            result = self.generate(f"测试类 {class_name}", "class")
            all_tests.append(result["test_code"])

        test_code = "\n\n".join(all_tests)
        test_count = test_code.count("def test_")

        return {
            "test_code": test_code,
            "test_count": test_count,
            "functions_found": functions[:10],
            "classes_found": classes[:5],
            "mode": "template",
        }


def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description="AI测试用例生成器")
    parser.add_argument("description", nargs="?", help="功能描述")
    parser.add_argument("--file", "-f", help="从文件生成测试")
    parser.add_argument("--type", "-t", default="auto",
                        choices=["auto", "function", "class", "api", "security"],
                        help="测试类型")

    args = parser.parse_args()

    generator = AITestGenerator()

    if args.file:
        result = generator.generate_from_file(args.file)
    elif args.description:
        result = generator.generate(args.description, args.type)
    else:
        print("请输入功能描述")
        return

    print("=" * 60)
    print("  AI测试生成结果")
    print(f"  - 模式: {result.get('mode', 'template')}")
    print(f"  - 测试数量: {result.get('test_count', 0)}")
    print("=" * 60)
    print()

    if "error" in result:
        print(f"错误: {result['error']}")
        return

    print(result.get("test_code", ""))


if __name__ == "__main__":
    main()
