# -*- coding: utf-8 -*-
"""测试自动闭环模块：熔断器 + 审计日志"""
import os
import sys
import time
import json
import unittest
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


class TestCircuitBreaker(unittest.TestCase):
    """测试熔断器"""

    def setUp(self):
        from core.circuit_breaker import CircuitBreaker
        self.cb = CircuitBreaker("test_cb", failure_threshold=3, recovery_timeout=0.1)

    def test_initial_state_closed(self):
        """初始状态应为closed"""
        self.assertEqual(self.cb.state, "closed")
        self.assertTrue(self.cb.can_execute())

    def test_success_does_not_trigger(self):
        """成功调用不会触发熔断"""
        for _ in range(10):
            self.cb.record_success()
        self.assertEqual(self.cb.state, "closed")
        self.assertEqual(self.cb._failure_count, 0)

    def test_failure_threshold_triggers_open(self):
        """连续失败达到阈值后触发熔断"""
        for i in range(2):
            self.cb.record_failure()
            self.assertEqual(self.cb.state, "closed")  # 还没到阈值

        self.cb.record_failure()  # 第3次
        self.assertEqual(self.cb.state, "open")
        self.assertFalse(self.cb.can_execute())

    def test_open_state_blocks_execution(self):
        """熔断状态下不能执行"""
        for _ in range(3):
            self.cb.record_failure()
        self.assertEqual(self.cb.state, "open")
        self.assertFalse(self.cb.can_execute())

    def test_half_open_after_timeout(self):
        """超时后进入半开状态"""
        for _ in range(3):
            self.cb.record_failure()
        self.assertEqual(self.cb.state, "open")

        time.sleep(0.15)  # 超过 recovery_timeout
        self.assertEqual(self.cb.state, "half_open")

    def test_half_open_success_recovers(self):
        """半开状态下成功则恢复"""
        for _ in range(3):
            self.cb.record_failure()
        time.sleep(0.15)

        self.assertEqual(self.cb.state, "half_open")
        self.assertTrue(self.cb.can_execute())  # 允许1次探测
        self.cb.record_success()
        self.assertEqual(self.cb.state, "closed")

    def test_half_open_failure_reopens(self):
        """半开状态下失败则重新熔断"""
        for _ in range(3):
            self.cb.record_failure()
        time.sleep(0.15)

        self.assertEqual(self.cb.state, "half_open")
        self.cb.record_failure()
        self.assertEqual(self.cb.state, "open")

    def test_call_with_fallback(self):
        """call方法带fallback参数时，失败自动降级"""
        def real_func():
            raise ValueError("网络错误")

        def fallback_func():
            return "mock_data"

        # 前2次失败，还是closed状态，会尝试调用
        for i in range(2):
            result = self.cb.call(real_func, fallback=fallback_func)
            self.assertEqual(result, "mock_data")

        # 第3次失败后熔断
        result = self.cb.call(real_func, fallback=fallback_func)
        self.assertEqual(result, "mock_data")
        self.assertEqual(self.cb.state, "open")

        # 熔断后直接走fallback，不再调用real_func
        call_count = [0]
        def real_func2():
            call_count[0] += 1
            raise ValueError("网络错误")

        self.cb.call(real_func2, fallback=fallback_func)
        self.assertEqual(call_count[0], 0)  # 没被调用

    def test_call_without_fallback_raises(self):
        """没有fallback时，失败抛出异常"""
        def real_func():
            raise ValueError("网络错误")

        with self.assertRaises(ValueError):
            self.cb.call(real_func)

    def test_stats(self):
        """统计信息正确"""
        self.cb.record_success()
        self.cb.record_failure()
        stats = self.cb.get_stats()
        self.assertEqual(stats["name"], "test_cb")
        self.assertEqual(stats["total_success"], 1)
        self.assertEqual(stats["total_failure"], 1)
        self.assertEqual(stats["state"], "closed")

    def test_reset(self):
        """重置熔断器"""
        for _ in range(5):
            self.cb.record_failure()
        self.cb.reset()
        self.assertEqual(self.cb.state, "closed")
        self.assertEqual(self.cb._failure_count, 0)


class TestCircuitBreakerRegistry(unittest.TestCase):
    """测试熔断器注册表"""

    def test_singleton(self):
        """注册表是单例"""
        from core.circuit_breaker import CircuitBreakerRegistry
        r1 = CircuitBreakerRegistry()
        r2 = CircuitBreakerRegistry()
        self.assertIs(r1, r2)

    def test_get_creates_and_reuses(self):
        """get方法创建并复用实例"""
        from core.circuit_breaker import CircuitBreakerRegistry
        r = CircuitBreakerRegistry()
        r.reset_all()
        cb1 = r.get("test_reg", failure_threshold=5)
        cb2 = r.get("test_reg")
        self.assertIs(cb1, cb2)
        self.assertEqual(cb1.failure_threshold, 5)

    def test_list_all(self):
        """列出所有熔断器"""
        from core.circuit_breaker import CircuitBreakerRegistry
        r = CircuitBreakerRegistry()
        r.reset_all()
        r.get("cb_a")
        r.get("cb_b")
        all_stats = r.list_all()
        self.assertIn("cb_a", all_stats)
        self.assertIn("cb_b", all_stats)


class TestAuditLog(unittest.TestCase):
    """测试审计日志"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_audit.logl")
        from core import audit_log
        audit_log.set_audit_log_path(self.log_path)
        self.audit_log = audit_log

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_log_event(self):
        """记录一条事件"""
        self.audit_log.log_event(
            event_type="TEST",
            subsystem="test",
            summary="测试事件",
            detail="详细信息",
        )
        records = self.audit_log.read_recent()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["type"], "TEST")
        self.assertEqual(records[0]["subsystem"], "test")
        self.assertEqual(records[0]["summary"], "测试事件")

    def test_log_predict(self):
        """记录预测事件"""
        self.audit_log.log_predict("lottery", "福彩3D", "默认方案", 20, True)
        records = self.audit_log.read_recent()
        self.assertEqual(records[0]["type"], "PREDICT")
        self.assertEqual(records[0]["data"]["lot"], "福彩3D")
        self.assertEqual(records[0]["data"]["ticket_count"], 20)

    def test_log_review(self):
        """记录复盘事件"""
        self.audit_log.log_review("lottery", "福彩3D", 0.35, "2024123")
        records = self.audit_log.read_recent()
        self.assertEqual(records[0]["type"], "REVIEW")
        self.assertAlmostEqual(records[0]["data"]["hit_rate"], 0.35)

    def test_log_fetch(self):
        """记录数据拉取事件"""
        self.audit_log.log_fetch("stock", "akshare_sh000001", True, 8680, False)
        records = self.audit_log.read_recent()
        self.assertEqual(records[0]["type"], "FETCH")
        self.assertTrue(records[0]["data"]["success"])
        self.assertEqual(records[0]["data"]["count"], 8680)

    def test_log_circuit_breaker(self):
        """记录熔断器事件"""
        self.audit_log.log_circuit_breaker("stock_akshare", "closed", "open", "连续失败3次")
        records = self.audit_log.read_recent()
        self.assertEqual(records[0]["type"], "CIRCUIT_BREAKER")
        self.assertEqual(records[0]["data"]["from"], "closed")
        self.assertEqual(records[0]["data"]["to"], "open")

    def test_log_system(self):
        """记录系统事件"""
        self.audit_log.log_system("启动", "版本v2.0")
        records = self.audit_log.read_recent()
        self.assertEqual(records[0]["type"], "SYSTEM")

    def test_read_recent_limit(self):
        """读取最近N条"""
        for i in range(10):
            self.audit_log.log_event("TEST", "test", f"事件{i}")
        records = self.audit_log.read_recent(limit=3)
        self.assertEqual(len(records), 3)
        # 最新的在前
        self.assertIn("事件9", records[0]["summary"])

    def test_read_recent_filter(self):
        """按类型过滤"""
        self.audit_log.log_event("TYPE_A", "test", "A1")
        self.audit_log.log_event("TYPE_B", "test", "B1")
        self.audit_log.log_event("TYPE_A", "test", "A2")
        records = self.audit_log.read_recent(event_type="TYPE_A")
        self.assertEqual(len(records), 2)
        for r in records:
            self.assertEqual(r["type"], "TYPE_A")

    def test_read_empty_file(self):
        """读取不存在的文件返回空列表"""
        self.audit_log.set_audit_log_path(os.path.join(self.tmp_dir, "nonexistent.logl"))
        records = self.audit_log.read_recent()
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
