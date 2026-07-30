# -*- coding: utf-8 -*-
"""
金水谣系统 - 审计模块测试

测试 engines/audit.py 的号码校验功能：
双色球、快乐8、福彩3D等彩种的号码范围和格式检查
"""

import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_test_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def test_ssq_normal():
    """测试正常双色球号码通过审核"""
    try:
        from engines.audit import Audit
    except ImportError as e:
        raise AssertionError("无法导入 Audit: %s" % e)

    # 正常双色球投注
    tks = {
        "单注": ["01,05,12,18,25,33+08", "03,07,15,22,28,31+12"]
    }
    audit = Audit("双色球", tks)
    assert audit.ok() is True, "正常双色球号码应通过审核"


def test_kl8_range():
    """测试快乐8号码范围检查"""
    try:
        from engines.audit import Audit
    except ImportError as e:
        raise AssertionError("无法导入 Audit: %s" % e)

    # 正常快乐8（10-12个号码，范围1-80）
    tks = {
        "单注": ["01,05,12,18,25,33,40,45,50,60"]
    }
    audit = Audit("快乐8", tks)
    assert audit.ok() is True, "正常快乐8号码应通过审核"


def test_3d_fushi():
    """测试福彩3D复式检查"""
    try:
        from engines.audit import Audit
    except ImportError as e:
        raise AssertionError("无法导入 Audit: %s" % e)

    # 福彩3D单注
    tks = {
        "单注": ["1,5,8"]
    }
    audit = Audit("福彩3D", tks)
    assert audit.ok() is True, "正常3D号码应通过审核"


def test_invalid_range():
    """测试超范围号码不通过审核"""
    try:
        from engines.audit import Audit
    except ImportError as e:
        raise AssertionError("无法导入 Audit: %s" % e)

    # 双色球红球超出范围（最大33，传入40）
    tks = {
        "单注": ["01,05,12,18,25,40+08"]
    }
    audit = Audit("双色球", tks)
    assert audit.ok() is False, "超范围号码不应通过审核"


def test_empty_tickets():
    """测试空投注不通过审核"""
    try:
        from engines.audit import Audit
    except ImportError as e:
        raise AssertionError("无法导入 Audit: %s" % e)

    tks = {"单注": []}
    audit = Audit("双色球", tks)
    assert audit.ok() is True, "空投注应通过（无号码可审核）"


def test_kl8_too_few():
    """测试快乐8号码数量不足不通过"""
    try:
        from engines.audit import Audit
    except ImportError as e:
        raise AssertionError("无法导入 Audit: %s" % e)

    # 快乐8至少需要10个号码
    tks = {
        "单注": ["01,05,12,18,25"]
    }
    audit = Audit("快乐8", tks)
    assert audit.ok() is False, "快乐8号码不足10个不应通过审核"
