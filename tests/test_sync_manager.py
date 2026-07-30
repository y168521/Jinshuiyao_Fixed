# -*- coding: utf-8 -*-
"""
金水谣系统 - 同步管理测试 (P5)

测试 engines/sync_manager.py 的核心功能：
离线优先、网络检测、离线队列
注意：sync_manager.py 文件可能有格式问题，测试会做导入保护
"""

import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_test_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def test_sync_module_import():
    """测试同步管理模块可以导入"""
    try:
        from engines import sync_manager
        assert sync_manager is not None, "同步管理模块应可导入"
    except SyntaxError as e:
        # sync_manager.py 文件可能有格式问题
        raise AssertionError("sync_manager.py 有语法错误: %s" % e)
    except Exception as e:
        raise AssertionError("导入 sync_manager 异常: %s" % e)


def test_sync_constants():
    """测试同步模块的常量定义"""
    try:
        from engines.sync_manager import (
            _PROBE_URLS,
            _DEFAULT_NETWORK_TIMEOUT,
            _OFFLINE_QUEUE_FILENAME,
            _MAX_SYNC_HISTORY,
        )
    except (ImportError, SyntaxError) as e:
        raise AssertionError("无法导入同步模块常量: %s" % e)

    # 验证常量
    assert isinstance(_PROBE_URLS, list), "探测URL列表应为列表"
    assert len(_PROBE_URLS) > 0, "探测URL列表不应为空"
    assert isinstance(_DEFAULT_NETWORK_TIMEOUT, int), "超时应为整数"
    assert _DEFAULT_NETWORK_TIMEOUT > 0, "超时应大于0"
    assert isinstance(_OFFLINE_QUEUE_FILENAME, str), "队列文件名应为字符串"
    assert isinstance(_MAX_SYNC_HISTORY, int), "最大同步历史应为整数"


def test_offline_queue_filename():
    """测试离线队列文件名格式"""
    try:
        from engines.sync_manager import _OFFLINE_QUEUE_FILENAME
    except (ImportError, SyntaxError):
        raise AssertionError("无法导入 _OFFLINE_QUEUE_FILENAME")

    assert _OFFLINE_QUEUE_FILENAME.endswith(".jsonl"), \
        "离线队列文件应以 .jsonl 结尾"
