# -*- coding: utf-8 -*-
"""
金水谣系统 - 运行监控测试 (P2)

测试 engines/watchdog.py 的核心功能：
心跳机制、异常捕获、CUSUM检测器
"""

import os
import sys
import time

_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_test_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def test_cusum_detector_init():
    """测试 CUSUM 检测器初始化"""
    try:
        from engines.watchdog import CUSUMDetector
    except ImportError as e:
        raise AssertionError("无法导入 CUSUMDetector: %s" % e)

    detector = CUSUMDetector(window=20, threshold_sigma=2.0)
    assert detector is not None, "CUSUMDetector 应成功创建"
    assert detector.window == 20, "窗口大小应为 20"
    assert detector.threshold_sigma == 2.0, "阈值应为 2.0"


def test_cusum_no_alert_initial():
    """测试 CUSUM 初始状态下不触发告警"""
    try:
        from engines.watchdog import CUSUMDetector
    except ImportError as e:
        raise AssertionError("无法导入 CUSUMDetector: %s" % e)

    detector = CUSUMDetector(window=20, threshold_sigma=2.0)

    # 插入少量数据（不足 window），不应告警
    for i in range(10):
        alert = detector.update("福彩3D", 0.2 + i * 0.01)
        assert alert is None, "数据不足时应返回 None"


def test_cusum_reset():
    """测试 CUSUM 状态重置"""
    try:
        from engines.watchdog import CUSUMDetector
    except ImportError as e:
        raise AssertionError("无法导入 CUSUMDetector: %s" % e)

    detector = CUSUMDetector(window=20, threshold_sigma=2.0)

    # 插入一些数据
    for i in range(25):
        detector.update("福彩3D", 0.2)

    # 重置
    detector.reset("福彩3D")

    # 验证状态已重置
    state = detector._state.get("福彩3D", {})
    assert state.get("s_high") == 0.0, "重置后 s_high 应为 0"
    assert state.get("s_low") == 0.0, "重置后 s_low 应为 0"


def test_health_logger_structure():
    """测试健康日志记录器的常量定义"""
    try:
        from engines.watchdog import HealthLogger
    except ImportError as e:
        raise AssertionError("无法导入 HealthLogger: %s" % e)

    # 验证类常量
    assert hasattr(HealthLogger, "LEVEL_INFO"), "应有 LEVEL_INFO 常量"
    assert hasattr(HealthLogger, "LEVEL_WARN"), "应有 LEVEL_WARN 常量"
    assert hasattr(HealthLogger, "LEVEL_CRITICAL"), "应有 LEVEL_CRITICAL 常量"
    assert hasattr(HealthLogger, "CATEGORY_HEARTBEAT"), "应有 CATEGORY_HEARTBEAT 常量"
    assert hasattr(HealthLogger, "CATEGORY_CUSUM"), "应有 CATEGORY_CUSUM 常量"


def test_watchdog_init():
    """测试守护进程初始化"""
    try:
        from engines.watchdog import SystemWatchdog
    except ImportError as e:
        raise AssertionError("无法导入 SystemWatchdog: %s" % e)

    watchdog = SystemWatchdog(app_reference=None, interval=30)
    assert watchdog is not None, "SystemWatchdog 应成功创建"
    assert watchdog.interval == 30, "间隔应为 30"
    assert watchdog._running is False, "初始状态不应运行"
    assert watchdog._heartbeat_fail_count == 0, "心跳失败计数应为 0"
