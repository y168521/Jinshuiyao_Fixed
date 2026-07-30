# -*- coding: utf-8 -*-
"""金水谣系统 - 子系统隔离测试

验证不同子系统之间的数据不会互相污染。
核心测试目标：
1. contextvars 上下文正确隔离
2. 知识库按 subsystem 过滤
3. 子系统A的状态变更不影响子系统B
"""
import sys
import os
import unittest

# 确保能找到项目根目录
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.context import (
    get_current_subsystem, set_subsystem_context, reset_subsystem_context,
    run_in_subsystem, current_subsystem_id
)
from core.registry import register, get_domain, list_domains, is_registered
from domains.lottery.domain import LotteryDomain
from domains.football.domain import FootballDomain
from knowledge.mirofish_db import MiroFishDB


class TestContextVarsIsolation(unittest.TestCase):
    """测试 contextvars 子系统上下文隔离"""

    def test_default_subsystem_is_lottery(self):
        """默认子系统应为 lottery"""
        self.assertEqual(get_current_subsystem(), "lottery")

    def test_set_and_reset_context(self):
        """设置和重置上下文正确工作"""
        original = get_current_subsystem()
        token = set_subsystem_context("football")
        self.assertEqual(get_current_subsystem(), "football")
        reset_subsystem_context(token)
        self.assertEqual(get_current_subsystem(), original)

    def test_run_in_subsystem_isolation(self):
        """run_in_subsystem 自动隔离"""
        result = run_in_subsystem("stock", get_current_subsystem)
        self.assertEqual(result, "stock")
        # 函数返回后上下文应恢复
        self.assertEqual(get_current_subsystem(), "lottery")

    def test_context_no_leak_between_calls(self):
        """多次调用之间上下文不泄漏"""
        r1 = run_in_subsystem("a", get_current_subsystem)
        r2 = run_in_subsystem("b", get_current_subsystem)
        self.assertEqual(r1, "a")
        self.assertEqual(r2, "b")
        self.assertEqual(get_current_subsystem(), "lottery")


class TestRegistryIsolation(unittest.TestCase):
    """测试域注册表隔离"""

    def test_register_and_retrieve(self):
        """注册和获取域"""
        register("test_lottery", LotteryDomain, "测试彩票")
        self.assertTrue(is_registered("test_lottery"))
        cls = get_domain("test_lottery")
        self.assertIs(cls, LotteryDomain)

    def test_register_football(self):
        """注册足彩域"""
        register("test_football", FootballDomain, "测试足彩")
        self.assertTrue(is_registered("test_football"))

    def test_list_domains_includes_both(self):
        """列出域包含彩票和足彩"""
        # 在当前测试中重新注册（注册表不跨测试实例共享）
        register("test_lottery2", LotteryDomain, "测试彩票2")
        register("test_football2", FootballDomain, "测试足彩2")
        domains = list_domains()
        ids = [d[0] for d in domains]
        self.assertIn("test_lottery2", ids)
        self.assertIn("test_football2", ids)


class TestKnowledgeBaseIsolation(unittest.TestCase):
    """测试知识库按 subsystem 隔离"""

    def test_search_lottery_only(self):
        """搜索 lottery 子系统只返回彩票相关卡片"""
        db = MiroFishDB()
        cards = db.search(subsystem="lottery")
        for card in cards:
            sub = card.get("subsystem", "")
            self.assertIn(sub, ["lottery", "global"],
                          f"非lottery/global卡片出现在lottery搜索中: {card.get('title')}")

    def test_search_global_accessible(self):
        """global 知识对所有子系统可见"""
        db = MiroFishDB()
        global_cards = db.search(subsystem="global")
        self.assertGreater(len(global_cards), 0, "global知识应存在")

    def test_subsystem_field_exists_on_all_cards(self):
        """所有卡片都有 subsystem 字段"""
        db = MiroFishDB()
        cards = db._data.get("cards", [])
        for card in cards:
            self.assertIn("subsystem", card,
                          f"卡片缺少subsystem字段: {card.get('title')}")

    def test_lottery_cards_not_in_global_search(self):
        """lottery专用卡片不应出现在global搜索中（如果global过滤严格）"""
        db = MiroFishDB()
        global_cards = db.search(subsystem="global")
        for card in global_cards:
            self.assertEqual(card.get("subsystem"), "global",
                          f"非global卡片出现在global搜索中: {card.get('title')}")


class TestDomainStatusIsolation(unittest.TestCase):
    """测试子系统状态互不影响"""

    def test_lottery_football_status_independent(self):
        """彩票和足彩的状态互相独立"""
        lottery = LotteryDomain()
        football = FootballDomain()

        # 各自setup
        lottery.setup()
        football.setup()

        # 检查状态
        ls = lottery.status()
        fs = football.status()
        self.assertEqual(ls["domain_id"], "lottery")
        self.assertEqual(fs["domain_id"], "football")
        self.assertNotEqual(ls["engines"], fs["engines"])

        # teardown不影响对方
        lottery.teardown()
        self.assertFalse(lottery.status()["ready"])
        # football 仍应为 ready
        self.assertTrue(football.status()["ready"])
        football.teardown()


if __name__ == "__main__":
    unittest.main()
