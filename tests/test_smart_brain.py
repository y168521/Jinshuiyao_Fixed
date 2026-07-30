# -*- coding: utf-8 -*-
"""
金水谣系统 - 智能大脑测试

测试 engines/smart_brain.py 的核心功能：
默认状态、置信度范围、策略权重格式
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


def test_default_state():
    """测试默认状态结构正确：包含所有必要字段"""
    try:
        from engines.smart_brain import SmartBrain
    except ImportError as e:
        raise AssertionError("无法导入 SmartBrain: %s" % e)

    # 使用临时目录，避免影响真实数据
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_brain_test_")
    try:
        brain = SmartBrain(data_dir=tmpdir)

        # 验证默认状态结构
        state = brain.state
        assert isinstance(state, dict), "状态应为字典"
        assert "version" in state, "状态应包含 version"
        assert "strategy_weights" in state, "状态应包含 strategy_weights"
        assert "digit_bias" in state, "状态应包含 digit_bias"
        assert "confidence_history" in state, "状态应包含 confidence_history"
        assert "total_reviews" in state, "状态应包含 total_reviews"

        # 验证默认值
        assert state["version"] == 1, "version 默认应为 1"
        assert state["total_reviews"] == 0, "total_reviews 默认应为 0"
        assert isinstance(state["strategy_weights"], dict), "strategy_weights 应为字典"
        assert isinstance(state["digit_bias"], dict), "digit_bias 应为字典"
        assert isinstance(state["confidence_history"], list), "confidence_history 应为列表"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_confidence_range():
    """测试置信度在 0-1 范围内"""
    try:
        from engines.smart_brain import SmartBrain
    except ImportError as e:
        raise AssertionError("无法导入 SmartBrain: %s" % e)

    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_brain_test_")
    try:
        brain = SmartBrain(data_dir=tmpdir)

        # 评估置信度
        confidence = brain.assess_confidence("福彩3D")
        assert 0.0 <= confidence <= 1.0, "置信度应在 0.0-1.0 范围内，实际: %.4f" % confidence

        # 测试多个彩种
        for lot in ["福彩3D", "排列三", "快乐8"]:
            conf = brain.assess_confidence(lot)
            assert 0.0 <= conf <= 1.0, "[%s] 置信度应在 0.0-1.0 范围内，实际: %.4f" % (lot, conf)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_strategy_weights():
    """测试策略权重返回正确格式"""
    try:
        from engines.smart_brain import SmartBrain
    except ImportError as e:
        raise AssertionError("无法导入 SmartBrain: %s" % e)

    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_brain_test_")
    try:
        brain = SmartBrain(data_dir=tmpdir)

        # 获取策略权重
        weights = brain.get_strategy_weights("福彩3D")

        # 验证格式
        assert isinstance(weights, dict), "策略权重应为字典"
        assert len(weights) > 0, "策略权重不应为空"

        # 验证权重值范围
        total = 0.0
        for key, value in weights.items():
            assert isinstance(key, str), "策略名应为字符串"
            assert 0.0 < value <= 1.0, "权重值应在 (0, 1] 范围内，实际: %.4f" % value
            total += value

        # 权重总和应接近 1.0（允许浮点误差）
        assert abs(total - 1.0) < 0.01, "权重总和应接近 1.0，实际: %.4f" % total
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_status_report():
    """测试状态报告结构"""
    try:
        from engines.smart_brain import SmartBrain
    except ImportError as e:
        raise AssertionError("无法导入 SmartBrain: %s" % e)

    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_brain_test_")
    try:
        brain = SmartBrain(data_dir=tmpdir)
        report = brain.get_status_report()

        assert isinstance(report, dict), "状态报告应为字典"
        assert "total_reviews" in report, "报告应包含 total_reviews"
        assert "history_size" in report, "报告应包含 history_size"
        assert "saved_strategy_weights" in report, "报告应包含 saved_strategy_weights"
        assert "digit_bias_lots" in report, "报告应包含 digit_bias_lots"
        assert "confidence_records" in report, "报告应包含 confidence_records"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
