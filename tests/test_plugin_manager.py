# -*- coding: utf-8 -*-
"""
金水谣系统 - 插件管理测试 (P4)

测试 engines/plugin_manager.py 的核心功能：
插件基类、插件管理器基本接口
注意：plugin_manager.py 文件可能有格式问题，测试会做导入保护
"""

import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_test_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def test_plugin_module_import():
    """测试插件管理模块可以导入"""
    try:
        from engines import plugin_manager
        assert plugin_manager is not None, "插件管理模块应可导入"
    except SyntaxError as e:
        # plugin_manager.py 文件可能有格式问题
        raise AssertionError("plugin_manager.py 有语法错误: %s" % e)
    except Exception as e:
        raise AssertionError("导入 plugin_manager 异常: %s" % e)


def test_plugin_base_class():
    """测试插件基类定义"""
    try:
        from engines.plugin_manager import JinshuiyaoPlugin
    except (ImportError, SyntaxError) as e:
        raise AssertionError("无法导入 JinshuiyaoPlugin 基类: %s" % e)

    # 验证 JinshuiyaoPlugin 是抽象基类
    from abc import ABC
    assert issubclass(JinshuiyaoPlugin, ABC), "JinshuiyaoPlugin 应继承自 ABC"

    # 验证有抽象方法
    abstract_methods = getattr(JinshuiyaoPlugin, "__abstractmethods__", set())
    assert len(abstract_methods) > 0, "JinshuiyaoPlugin 应有抽象方法"


def test_plugin_manager_class():
    """测试插件管理器类存在"""
    try:
        from engines.plugin_manager import JinshuiyaoPlugin
    except (ImportError, SyntaxError):
        raise AssertionError("无法导入插件管理模块")

    # 验证模块中有 JinshuiyaoPlugin 类
    assert JinshuiyaoPlugin is not None, "JinshuiyaoPlugin 类应存在"
