# -*- coding: utf-8 -*-
"""跨子系统信号关联测试

覆盖：
  - Signal 信号创建与过期
  - SignalBus 发布/订阅/查询
  - CrossDomainAnalyzer 规则触发
  - 信号隔离（子系统只收到订阅的类型）
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.cross_domain import Signal, SignalBus, CrossDomainAnalyzer


class TestSignal(unittest.TestCase):
    """测试Signal"""

    def test_create_signal(self):
        sig = Signal("trend_change", "stock", {"direction": "up", "strength": 70})
        self.assertEqual(sig.signal_type, "trend_change")
        self.assertEqual(sig.source_domain, "stock")
        self.assertEqual(sig.data["direction"], "up")
        self.assertFalse(sig.is_expired())

    def test_expired_signal(self):
        sig = Signal("test", "stock", {}, timestamp="2020-01-01 00:00:00", ttl=3600)
        self.assertTrue(sig.is_expired())

    def test_repr(self):
        sig = Signal("test", "stock", {"key": "val"})
        r = repr(sig)
        self.assertIn("test", r)
        self.assertIn("stock", r)

    def test_unique_id(self):
        s1 = Signal("test", "a", {})
        s2 = Signal("test", "a", {})
        self.assertNotEqual(s1.id, s2.id)


class TestSignalBus(unittest.TestCase):
    """测试SignalBus"""

    def setUp(self):
        SignalBus.reset()  # 每个测试用干净的实例

    def tearDown(self):
        SignalBus.reset()

    def test_singleton(self):
        bus1 = SignalBus()
        bus2 = SignalBus()
        self.assertIs(bus1, bus2)

    def test_subscribe_and_publish(self):
        bus = SignalBus()
        received = []

        def handler(sig):
            received.append(sig)

        bus.subscribe("trend_change", "lottery", handler)
        bus.publish(Signal("trend_change", "stock", {"direction": "up"}))

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].source_domain, "stock")
        self.assertEqual(received[0].data["direction"], "up")

    def test_wildcard_subscription(self):
        bus = SignalBus()
        received = []

        def handler(sig):
            received.append(sig)

        bus.subscribe("*", "lottery", handler)
        bus.publish(Signal("any_type", "stock", {}))
        bus.publish(Signal("another_type", "football", {}))

        self.assertEqual(len(received), 2)

    def test_unsubscribe(self):
        bus = SignalBus()
        received = []

        def handler(sig):
            received.append(sig)

        bus.subscribe("test", "lottery", handler)
        bus.unsubscribe("test", "lottery")
        bus.publish(Signal("test", "stock", {}))

        self.assertEqual(len(received), 0)

    def test_expired_signal_not_delivered(self):
        bus = SignalBus()
        received = []

        def handler(sig):
            received.append(sig)

        bus.subscribe("test", "lottery", handler)
        bus.publish(Signal("test", "stock", {}, timestamp="2020-01-01 00:00:00", ttl=3600))

        self.assertEqual(len(received), 0)

    def test_query_by_type(self):
        bus = SignalBus()
        bus.publish(Signal("type_a", "stock", {}))
        bus.publish(Signal("type_b", "stock", {}))
        bus.publish(Signal("type_a", "football", {}))

        results = bus.query(signal_type="type_a")
        self.assertEqual(len(results), 2)

    def test_query_by_domain(self):
        bus = SignalBus()
        bus.publish(Signal("type_a", "stock", {}))
        bus.publish(Signal("type_a", "football", {}))

        results = bus.query(source_domain="stock")
        self.assertEqual(len(results), 1)

    def test_query_limit(self):
        bus = SignalBus()
        for i in range(10):
            bus.publish(Signal("test", "stock", {"i": i}))

        results = bus.query(limit=3)
        self.assertEqual(len(results), 3)

    def test_stats(self):
        bus = SignalBus()
        bus.subscribe("test", "lottery", lambda s: None)
        bus.publish(Signal("test", "stock", {}))

        stats = bus.stats()
        self.assertEqual(stats["total_subscribers"], 1)
        self.assertEqual(stats["history_size"], 1)

    def test_multiple_subscribers(self):
        bus = SignalBus()
        r1, r2 = [], []

        bus.subscribe("test", "lottery", lambda s: r1.append(s))
        bus.subscribe("test", "football", lambda s: r2.append(s))
        bus.publish(Signal("test", "stock", {}))

        self.assertEqual(len(r1), 1)
        self.assertEqual(len(r2), 1)


class TestCrossDomainAnalyzer(unittest.TestCase):
    """测试跨域分析器"""

    def setUp(self):
        SignalBus.reset()

    def tearDown(self):
        SignalBus.reset()

    def test_builtin_rules_exist(self):
        analyzer = CrossDomainAnalyzer()
        status = analyzer.status()
        self.assertGreater(status["active_rules"], 0)

    def test_stock_trend_triggers_budget_adjust(self):
        """A股下跌→彩票预算调整"""
        analyzer = CrossDomainAnalyzer()
        sig = Signal("stock.trend_change", "stock", {
            "direction": "down", "strength": 70
        })
        actions = analyzer.analyze_signal(sig)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "adjust_budget")
        self.assertEqual(actions[0]["target_domain"], "lottery")

    def test_stock_uptrend_no_trigger(self):
        """A股上涨不触发预算调整"""
        analyzer = CrossDomainAnalyzer()
        sig = Signal("stock.trend_change", "stock", {
            "direction": "up", "strength": 70
        })
        actions = analyzer.analyze_signal(sig)
        # up方向不满足 condition
        self.assertEqual(len(actions), 0)

    def test_self_domain_ignored(self):
        """自己发自己的信号不触发"""
        analyzer = CrossDomainAnalyzer()
        sig = Signal("stock.trend_change", "lottery", {
            "direction": "down", "strength": 70
        })
        # source=lottery, target=lottery → 被跳过
        actions = analyzer.analyze_signal(sig)
        self.assertEqual(len(actions), 0)

    def test_custom_rule(self):
        """自定义跨域规则"""
        analyzer = CrossDomainAnalyzer()
        custom_rule = {
            "id": "test_custom",
            "name": "测试规则",
            "description": "测试用",
            "trigger_signal": "test.signal",
            "action_domain": "football",
            "condition": lambda data: data.get("flag") is True,
            "action": "test_action",
            "action_params": {"key": "val"},
        }
        analyzer.register_rule(custom_rule)

        sig = Signal("test.signal", "lottery", {"flag": True})
        actions = analyzer.analyze_signal(sig)

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["rule_id"], "test_custom")
        self.assertEqual(actions[0]["target_domain"], "football")

    def test_action_log(self):
        """动作日志记录"""
        analyzer = CrossDomainAnalyzer()
        sig = Signal("stock.trend_change", "stock", {"direction": "down", "strength": 70})
        analyzer.analyze_signal(sig)

        log = analyzer.get_action_log()
        self.assertEqual(len(log), 1)

    def test_football_upset_triggers_emotion_alert(self):
        """足彩冷门→彩票情绪预警"""
        analyzer = CrossDomainAnalyzer()
        sig = Signal("football.match_result", "football", {"upset": True})
        actions = analyzer.analyze_signal(sig)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "emotion_alert")


if __name__ == "__main__":
    unittest.main(verbosity=2)
