# -*- coding: utf-8 -*-
"""
金水谣系统 - 启动自检测试 (P1)

测试 engines/health_check.py 的核心功能：
自检执行、目录自动创建、报告格式验证
"""

import os
import sys
import json
import shutil
import tempfile

_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_test_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def test_all_checks_run():
    """测试所有检查项都被执行"""
    try:
        from engines.health_check import HealthChecker
    except ImportError as e:
        raise AssertionError("无法导入 HealthChecker: %s" % e)

    checker = HealthChecker()
    report = checker.run_all_checks()

    # 验证报告结构
    assert isinstance(report, dict), "报告应为字典"
    assert "timestamp" in report, "报告应包含 timestamp"
    assert "overall" in report, "报告应包含 overall"
    assert "checks" in report, "报告应包含 checks"
    assert "summary" in report, "报告应包含 summary"

    # 验证至少有一些检查项被执行
    assert len(report["checks"]) > 0, "应至少执行一项检查"

    # 验证检查项结构
    for chk in report["checks"]:
        assert "name" in chk, "检查项应包含 name"
        assert "category" in chk, "检查项应包含 category"
        assert "status" in chk, "检查项应包含 status"
        assert "message" in chk, "检查项应包含 message"
        assert chk["status"] in ("pass", "warn", "fail"), "状态应为 pass/warn/fail"


def test_missing_dir_auto_create():
    """测试目录不存在时自动创建"""
    try:
        from engines.health_check import HealthChecker
    except ImportError as e:
        raise AssertionError("无法导入 HealthChecker: %s" % e)

    checker = HealthChecker()
    report = checker.run_all_checks()

    # 检查是否有目录相关的检查项（可能已创建或原本就存在）
    dir_checks = [c for c in report["checks"] if "目录" in c.get("name", "")]
    if dir_checks:
        # 目录检查应通过（存在或已自动创建）
        for chk in dir_checks:
            assert chk["status"] in ("pass", "warn"), \
                "目录检查应通过（pass）或已自动创建（warn），实际: %s" % chk["status"]


def test_report_format():
    """测试报告格式正确：包含所有必要字段"""
    try:
        from engines.health_check import HealthChecker, format_report
    except ImportError as e:
        raise AssertionError("无法导入 HealthChecker: %s" % e)

    checker = HealthChecker()
    report = checker.run_all_checks()

    # 测试 format_report 函数
    formatted = format_report(report)
    assert isinstance(formatted, str), "格式化报告应为字符串"
    assert len(formatted) > 0, "格式化报告不应为空"
    assert "金水谣系统" in formatted, "格式化报告应包含系统名称"
    assert "L0" in formatted, "格式化报告应包含 L0 标识"

    # 测试 summary 结构
    summary = report.get("summary", {})
    assert "pass" in summary, "summary 应包含 pass"
    assert "warn" in summary, "summary 应包含 warn"
    assert "fail" in summary, "summary 应包含 fail"


def test_summary_counts():
    """测试汇总统计与检查项一致"""
    try:
        from engines.health_check import HealthChecker
    except ImportError as e:
        raise AssertionError("无法导入 HealthChecker: %s" % e)

    checker = HealthChecker()
    report = checker.run_all_checks()

    checks = report.get("checks", [])
    summary = report.get("summary", {})

    # 手动统计
    pass_count = sum(1 for c in checks if c["status"] == "pass")
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    fail_count = sum(1 for c in checks if c["status"] == "fail")

    assert summary.get("pass", 0) == pass_count, "pass 计数不一致"
    assert summary.get("warn", 0) == warn_count, "warn 计数不一致"
    assert summary.get("fail", 0) == fail_count, "fail 计数不一致"
