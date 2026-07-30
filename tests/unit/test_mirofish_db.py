# -*- coding: utf-8 -*-
"""金水谣系统 - MiroFish 万物知识库单元测试

测试 knowledge/mirofish_db.py 的 MiroFishDB 类核心功能。
所有测试使用临时数据库文件，不污染真实知识库。
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestMiroFishDB(unittest.TestCase):
    """测试 MiroFishDB 知识库"""

    def setUp(self):
        """每个测试使用独立的临时数据库文件"""
        try:
            from knowledge.mirofish_db import MiroFishDB
        except Exception as e:
            self.skipTest("无法导入 MiroFishDB: %s" % e)
        self.MiroFishDB = MiroFishDB

        # 创建临时数据库文件
        fd, self.db_path = tempfile.mkstemp(suffix=".json", prefix="mirofish_test_")
        os.close(fd)
        # 写入空库初始化数据
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump({
                "version": "1.0.0",
                "name": "MiroFish 万物知识库",
                "cards": [],
                "stats": {"total_cards": 0, "by_category": {}, "by_domain": {},
                          "by_tag": {}, "by_value_level": {}}
            }, f, ensure_ascii=False)

        self.db = MiroFishDB(db_path=self.db_path)

    def tearDown(self):
        """清理临时文件"""
        try:
            if os.path.isfile(self.db_path):
                os.remove(self.db_path)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 基础添加与去重
    # ------------------------------------------------------------------

    def test_add_card_basic(self):
        """添加卡片应返回非空 card_id，且能在库中找到"""
        card_id = self.db.add_card(
            title="测试卡片1",
            content="这是一个测试知识卡片的内容，包含一些方法说明。",
            category="inspiration",
            domain="general",
        )
        self.assertIsNotNone(card_id)
        self.assertTrue(isinstance(card_id, str))
        self.assertGreater(len(card_id), 0)

        # 卡片应能被搜索到
        results = self.db.search(query="测试卡片1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], card_id)
        self.assertEqual(results[0]["title"], "测试卡片1")

    def test_add_card_duplicate(self):
        """重复标题应自动跳过，返回已有卡片的ID"""
        id1 = self.db.add_card(title="重复标题", content="内容1", domain="general")
        id2 = self.db.add_card(title="重复标题", content="内容2-不同内容", domain="general")
        self.assertEqual(id1, id2, "重复标题应返回同一卡片ID")

        # 库中只有一张
        results = self.db.search(query="重复标题")
        self.assertEqual(len(results), 1)

    # ------------------------------------------------------------------
    # 价值分层与标签
    # ------------------------------------------------------------------

    def test_auto_classify_value(self):
        """auto_classify_value 应能识别 数据/信息/知识/智慧 四个层级"""
        # 数据层：纯数字短文本
        data_content = "1 2 3 5 8 13 21"
        data_level = self.db.auto_classify_value(data_content)
        self.assertIn(data_level, ("数据", "信息"))

        # 信息层：有结论性词汇
        info_content = "根据统计结果得出结论，最近10期号码走势显示偏热。"
        info_level = self.db.auto_classify_value(info_content)
        self.assertIn(info_level, ("信息", "知识"))

        # 知识层：有规律/方法/策略
        knowledge_content = (
            "这是一个重要的规律总结，我们总结出方法：通过遗漏值和频次可以判断号码回补概率。"
            "策略上应该优先选择遗漏突破临界点的号码，方法是结合频次加权计算。"
        )
        knowledge_level = self.db.auto_classify_value(knowledge_content)
        self.assertIn(knowledge_level, ("知识", "智慧"))

        # 智慧层：有方法论/底层逻辑等深度词
        wisdom_content = (
            "从本质上讲，彩票预测的底层逻辑是概率思维与系统思维的结合。"
            "方法论是从根本上认识随机性的核心要义，洞见长期主义与复利思维的辩证关系。"
        )
        wisdom_level = self.db.auto_classify_value(wisdom_content)
        self.assertIn(wisdom_level, ("知识", "智慧"))

        # 空内容默认信息层
        self.assertEqual(self.db.auto_classify_value(""), "信息")
        self.assertEqual(self.db.auto_classify_value("   "), "信息")

    def test_auto_generate_tags(self):
        """auto_generate_tags 应能根据领域和内容生成标签"""
        # 彩票领域应识别彩种关键词
        tags = self.db.auto_generate_tags(
            title="双色球杀号技巧",
            content="通过遗漏和频次分析进行杀号，关注百位和十位的走势规律",
            domain="lottery",
        )
        self.assertIsInstance(tags, list)
        self.assertGreater(len(tags), 0, "彩票领域应能生成标签")
        # 至少应包含部分关键词
        all_tags = set(tags)
        # 至少匹配到1个彩票相关词
        lottery_words = {"双色球", "杀号", "遗漏", "频次", "百位", "十位", "走势", "规律"}
        self.assertTrue(all_tags & lottery_words,
                        "生成的标签应包含至少1个彩票关键词, 实际: %s" % tags)

        # 股票领域
        stock_tags = self.db.auto_generate_tags(
            title="MACD金叉信号",
            content="KDJ指标出现金叉，成交量放大，建议关注突破支撑位后的趋势。",
            domain="stock",
        )
        self.assertIsInstance(stock_tags, list)
        stock_words = {"MACD", "KDJ", "金叉", "成交量", "突破", "支撑位", "趋势"}
        self.assertTrue(set(stock_tags) & stock_words,
                        "股票标签应包含指标关键词, 实际: %s" % stock_tags)

        # 通用领域
        general_tags = self.db.auto_generate_tags(
            title="学习笔记",
            content="今天学到了一些新的知识点，记录下来供以后参考复习。",
            domain="general",
        )
        self.assertIsInstance(general_tags, list)
        # 最多5个标签
        self.assertLessEqual(len(general_tags), 5)

    # ------------------------------------------------------------------
    # 搜索功能
    # ------------------------------------------------------------------

    def test_search_by_keyword(self):
        """关键词搜索应匹配标题、内容或标签"""
        self.db.add_card(title="遗漏分析", content="通过遗漏值判断号码", domain="lottery")
        self.db.add_card(title="走势图", content="分析号码走势", domain="lottery")
        self.db.add_card(title="财经资讯", content="今天股票市场上涨", domain="general")

        # 按标题关键词搜索
        results = self.db.search(query="遗漏")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "遗漏分析")

        # 按内容关键词搜索
        results = self.db.search(query="股票")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "财经资讯")

    def test_search_by_domain(self):
        """按领域搜索应只返回该领域的卡片"""
        self.db.add_card(title="卡片A", content="内容A", domain="lottery")
        self.db.add_card(title="卡片B", content="内容B", domain="football")
        self.db.add_card(title="卡片C", content="内容C", domain="lottery")

        lottery_results = self.db.search(domain="lottery", limit=100)
        self.assertEqual(len(lottery_results), 2)
        for r in lottery_results:
            self.assertEqual(r["domain"], "lottery")

        football_results = self.db.search(domain="football", limit=100)
        self.assertEqual(len(football_results), 1)
        self.assertEqual(football_results[0]["domain"], "football")

    def test_search_by_value_level(self):
        """按价值分层搜索应只返回对应分层的卡片"""
        self.db.add_card(title="数据卡片", content="1 2 3 4 5 6 7",
                         domain="general", value_level="数据")
        self.db.add_card(title="智慧卡片", content="从本质上讲，这是底层逻辑方法论",
                         domain="general", value_level="智慧")
        self.db.add_card(title="信息卡片", content="结论是今天有雨", domain="general",
                         value_level="信息")

        data_results = self.db.search(value_level="数据", limit=100)
        self.assertEqual(len(data_results), 1)
        self.assertEqual(data_results[0]["value_level"], "数据")

        wisdom_results = self.db.search(value_level="智慧", limit=100)
        self.assertEqual(len(wisdom_results), 1)
        self.assertEqual(wisdom_results[0]["value_level"], "智慧")

    # ------------------------------------------------------------------
    # 列表与统计
    # ------------------------------------------------------------------

    def test_list_cards(self):
        """list_cards 应返回卡片列表，按创建时间倒序"""
        import time
        self.db.add_card(title="第一张", content="内容1", domain="lottery")
        # created 时间戳精度为秒，需间隔 >= 1.1 秒才能保证排序顺序
        time.sleep(1.1)
        self.db.add_card(title="第二张", content="内容2", domain="lottery")
        time.sleep(1.1)
        self.db.add_card(title="第三张", content="内容3", domain="football")

        cards = self.db.list_cards(domain="lottery", limit=10)
        self.assertEqual(len(cards), 2)
        # 按创建时间倒序，最新的在前
        self.assertEqual(cards[0]["title"], "第二张")
        self.assertEqual(cards[1]["title"], "第一张")

        # 全部列表
        all_cards = self.db.list_cards(limit=100)
        self.assertEqual(len(all_cards), 3)
        # 全部列表倒序：最新的(第三张)应在前
        self.assertEqual(all_cards[0]["title"], "第三张")

    def test_stats(self):
        """stats 应返回正确的统计信息"""
        self.db.add_card(title="卡片1", content="内容1", category="inspiration",
                         domain="lottery", tags=["遗漏", "杀号"])
        self.db.add_card(title="卡片2", content="内容2", category="resource",
                         domain="football", tags=["遗漏"])
        self.db.add_card(title="卡片3", content="内容3", category="inspiration",
                         domain="lottery", tags=["走势"])

        stats = self.db.stats()
        self.assertIsInstance(stats, dict)
        self.assertEqual(stats["total_cards"], 3)
        self.assertIn("by_category", stats)
        self.assertIn("by_domain", stats)
        self.assertIn("by_tag", stats)
        self.assertIn("by_value_level", stats)

        # by_domain 应反映各领域卡片数
        self.assertEqual(stats["by_domain"].get("lottery", 0), 2)
        self.assertEqual(stats["by_domain"].get("football", 0), 1)

        # by_category 应反映分类
        self.assertEqual(stats["by_category"].get("inspiration", 0), 2)
        self.assertEqual(stats["by_category"].get("resource", 0), 1)

        # by_tag 应反映标签计数
        self.assertEqual(stats["by_tag"].get("遗漏", 0), 2)

    # ------------------------------------------------------------------
    # 有效性更新与引擎钩子
    # ------------------------------------------------------------------

    def test_update_effectiveness(self):
        """update_effectiveness 应更新评分，并限制在 0-100"""
        card_id = self.db.add_card(title="评分测试", content="测试内容", domain="lottery")
        # 初始评分为 50
        results = self.db.search(query="评分测试")
        self.assertEqual(results[0]["effectiveness"], 50)

        # 增加 20 分
        new_score = self.db.update_effectiveness(card_id, 20)
        self.assertEqual(new_score, 70)

        # 减少 200 分（应被截断到 0）
        new_score = self.db.update_effectiveness(card_id, -200)
        self.assertEqual(new_score, 0)

        # 增加超过 100（应被截断到 100）
        new_score = self.db.update_effectiveness(card_id, 200)
        self.assertEqual(new_score, 100)

        # 不存在的 card_id 应返回 None
        self.assertIsNone(self.db.update_effectiveness("nonexistent_id", 10))

    def test_get_for_engine(self):
        """get_for_engine 应根据场景返回相关知识，并更新使用计数"""
        # 添加带 engine_hook 的卡片
        self.db.add_card(
            title="位置分析方法",
            content="通过百位十位个位的位置分布进行分析",
            domain="lottery",
            engine_hook="position_analysis",
        )
        self.db.add_card(
            title="杀号策略",
            content="杀号策略：通过频次和遗漏排除号码",
            domain="lottery",
            engine_hook="kill_strategy",
        )
        self.db.add_card(
            title="通用知识",
            content="这是一般性的彩票分析方法",
            domain="lottery",
            engine_hook="position_analysis",
        )

        # 查询 position_analysis 场景的知识
        results = self.db.get_for_engine("position_analysis", domain="lottery", limit=5)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        # 返回的卡片应都是 position_analysis 钩子
        for r in results:
            self.assertEqual(r["engine_hook"], "position_analysis")

        # 验证 use_count 已更新
        self.assertGreater(results[0]["use_count"], 0)
        self.assertIsNotNone(results[0]["last_used"])

        # 查询不存在的场景
        empty_results = self.db.get_for_engine("nonexistent_scenario", domain="lottery")
        self.assertEqual(len(empty_results), 0)

    # ------------------------------------------------------------------
    # 子系统隔离
    # ------------------------------------------------------------------

    def test_subsystem_isolation(self):
        """子系统隔离：lottery 子系统查询不应返回 football 卡片，但可返回 global 卡片"""
        # 显式指定 subsystem
        self.db.add_card(title="彩票知识", content="彩票分析方法", domain="lottery",
                         subsystem="lottery")
        self.db.add_card(title="足球知识", content="足球分析方法", domain="football",
                         subsystem="football")
        self.db.add_card(title="通用知识", content="跨域通用方法", domain="general",
                         subsystem="global")

        # lottery 子系统查询：应包含 lottery 卡片和 global 卡片，不含 football
        lottery_results = self.db.search(subsystem="lottery", limit=100)
        titles = {r["title"] for r in lottery_results}
        self.assertIn("彩票知识", titles)
        self.assertIn("通用知识", titles)
        self.assertNotIn("足球知识", titles)

        # football 子系统查询：应包含 football 卡片和 global 卡片
        football_results = self.db.search(subsystem="football", limit=100)
        fb_titles = {r["title"] for r in football_results}
        self.assertIn("足球知识", fb_titles)
        self.assertIn("通用知识", fb_titles)
        self.assertNotIn("彩票知识", fb_titles)

    def test_infer_subsystem_auto(self):
        """_infer_subsystem 应根据 domain 自动推断 subsystem"""
        # lottery 系列 domain → lottery
        self.assertEqual(self.MiroFishDB._infer_subsystem("lottery"), "lottery")
        self.assertEqual(self.MiroFishDB._infer_subsystem("3d"), "lottery")
        self.assertEqual(self.MiroFishDB._infer_subsystem("ssq"), "lottery")
        # football 系列 → football
        self.assertEqual(self.MiroFishDB._infer_subsystem("football"), "football")
        # 其他 → global
        self.assertEqual(self.MiroFishDB._infer_subsystem("general"), "global")
        self.assertEqual(self.MiroFishDB._infer_subsystem("stock"), "global")


if __name__ == "__main__":
    unittest.main()
