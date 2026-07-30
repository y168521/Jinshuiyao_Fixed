# -*- coding: utf-8 -*-
"""自动系统管理模块单元测试

测试4个自动管理模块的核心功能：
  - DataMaintainer (core.data_maintenance)
  - FileOrganizer  (core.file_organizer)
  - AutoKnowledgeExtractor (core.auto_knowledge)
  - TaskScheduler  (core.scheduler)

使用 tempfile 和 mock，不依赖真实数据。
"""

import os
import sys
import json
import time
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ================================================================
# TestDataMaintainer - 数据维护模块测试
# ================================================================

class TestDataMaintainer(unittest.TestCase):
    """core.data_maintenance.DataMaintainer 核心功能测试"""

    def test_cleanup_temp_files(self):
        """创建临时文件，验证清理"""
        from core.data_maintenance import DataMaintainer

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "金水谣数据")
            os.makedirs(data_dir)

            # 创建 .tmp 文件
            tmp_file = os.path.join(data_dir, "test_temp.tmp")
            with open(tmp_file, "w") as f:
                f.write("x" * 100)

            # 创建 .safe_json_ 残留文件
            safe_tmp = os.path.join(data_dir, ".safe_json_abc123")
            with open(safe_tmp, "w") as f:
                f.write("y" * 50)

            # 创建 test_*_tmp_* 文件
            test_tmp = os.path.join(data_dir, "test_run_tmp_data.txt")
            with open(test_tmp, "w") as f:
                f.write("z" * 80)

            # 创建普通文件（不应被清理）
            normal_file = os.path.join(data_dir, "normal.json")
            with open(normal_file, "w") as f:
                f.write('{"key": "value"}')

            maintainer = DataMaintainer(data_dir=data_dir)
            result = maintainer.cleanup_temp_files()

            self.assertEqual(result["cleaned"], 3)
            self.assertGreater(result["freed_kb"], 0)
            self.assertFalse(os.path.exists(tmp_file))
            self.assertFalse(os.path.exists(safe_tmp))
            self.assertFalse(os.path.exists(test_tmp))
            self.assertTrue(os.path.exists(normal_file))

    def test_get_data_stats(self):
        """验证返回结构"""
        from core.data_maintenance import DataMaintainer

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "金水谣数据")
            os.makedirs(data_dir)

            # 创建一些测试文件
            sub_dir = os.path.join(data_dir, "stock")
            os.makedirs(sub_dir)
            with open(os.path.join(data_dir, "test.json"), "w") as f:
                f.write('{"a": 1}')
            with open(os.path.join(sub_dir, "data.json"), "w") as f:
                f.write('{"b": 2}')

            maintainer = DataMaintainer(data_dir=data_dir)
            stats = maintainer.get_data_stats()

            # 验证返回结构
            self.assertIn("total_size_kb", stats)
            self.assertIn("total_files", stats)
            self.assertIn("sub_systems", stats)
            self.assertIn("trend", stats)
            self.assertIn("last_maintenance", stats)
            self.assertIsInstance(stats["total_files"], int)
            self.assertIsInstance(stats["total_size_kb"], float)
            self.assertGreaterEqual(stats["total_files"], 2)

            # 验证 trend 子结构
            self.assertIn("size_change_kb", stats["trend"])
            self.assertIn("file_change", stats["trend"])
            self.assertIn("growth_percent", stats["trend"])

    def test_cleanup_expired_cache(self):
        """用 tempfile 模拟过期缓存"""
        from core.data_maintenance import DataMaintainer

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "金水谣数据")
            stock_cache = os.path.join(data_dir, "stock", "cache")
            os.makedirs(stock_cache)

            # 创建过期缓存文件（修改时间设为10天前）
            old_cache = os.path.join(stock_cache, "old_data.json")
            with open(old_cache, "w") as f:
                f.write('{"old": true}')
            old_time = time.time() - 10 * 24 * 3600
            os.utime(old_cache, (old_time, old_time))

            # 创建新缓存文件
            new_cache = os.path.join(stock_cache, "new_data.json")
            with open(new_cache, "w") as f:
                f.write('{"new": true}')

            maintainer = DataMaintainer(data_dir=data_dir)
            result = maintainer.cleanup_expired_cache(max_age_days=7)

            self.assertEqual(result["cleaned"], 1)
            self.assertGreater(result["freed_kb"], 0)
            self.assertFalse(os.path.exists(old_cache))
            self.assertTrue(os.path.exists(new_cache))

    def test_vacuum_all_structure(self):
        """验证 vacuum_all 返回结构"""
        from core.data_maintenance import DataMaintainer

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "金水谣数据")
            os.makedirs(data_dir)

            maintainer = DataMaintainer(data_dir=data_dir)
            report = maintainer.vacuum_all()

            self.assertIn("timestamp", report)
            self.assertIn("data_dir", report)
            self.assertIn("steps", report)
            self.assertIn("summary", report)
            self.assertIn("total_freed_kb", report["summary"])
            self.assertIn("total_files_cleaned", report["summary"])
            self.assertIn("total_records_removed", report["summary"])
            self.assertIn("files_compressed", report["summary"])
            self.assertIn("indices_repaired", report["summary"])
            self.assertIn("errors", report["summary"])
            self.assertIn("cleanup_expired_cache", report["steps"])
            self.assertIn("cleanup_old_predictions", report["steps"])
            self.assertIn("cleanup_temp_files", report["steps"])
            self.assertIn("compress_data_files", report["steps"])
            self.assertIn("rebuild_indices", report["steps"])

    def test_rebuild_indices_structure(self):
        """验证 rebuild_indices 返回结构"""
        from core.data_maintenance import DataMaintainer

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "金水谣数据")
            os.makedirs(data_dir)

            # 创建一个健康的索引文件
            with open(os.path.join(data_dir, "brain_state.json"), "w") as f:
                json.dump({"mood": "happy"}, f)

            maintainer = DataMaintainer(data_dir=data_dir)
            result = maintainer.rebuild_indices()

            self.assertIn("checked", result)
            self.assertIn("repaired", result)
            self.assertIn("details", result)
            self.assertEqual(result["checked"], 3)
            self.assertIsInstance(result["details"], list)
            self.assertEqual(len(result["details"]), 3)


# ================================================================
# TestFileOrganizer - 文件整理模块测试
# ================================================================

class TestFileOrganizer(unittest.TestCase):
    """core.file_organizer.FileOrganizer 核心功能测试"""

    def test_clean_pycache(self):
        """验证返回结构"""
        from core.file_organizer import FileOrganizer

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 __pycache__ 目录
            pycache_dir = os.path.join(tmpdir, "__pycache__")
            os.makedirs(pycache_dir)
            pyc_file = os.path.join(pycache_dir, "module.cpython-310.pyc")
            with open(pyc_file, "wb") as f:
                f.write(b"\x00" * 200)

            organizer = FileOrganizer(project_dir=tmpdir)
            result = organizer.clean_pycache()

            # 验证返回结构
            self.assertIn("removed", result)
            self.assertIn("freed_kb", result)
            self.assertIsInstance(result["removed"], int)
            self.assertIsInstance(result["freed_kb"], float)
            self.assertEqual(result["removed"], 1)
            self.assertGreater(result["freed_kb"], 0)
            self.assertFalse(os.path.exists(pycache_dir))

    def test_verify_structure(self):
        """验证返回结构"""
        from core.file_organizer import FileOrganizer

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建完整目录结构
            os.makedirs(os.path.join(tmpdir, "core"))
            os.makedirs(os.path.join(tmpdir, "utils"))
            os.makedirs(os.path.join(tmpdir, "金水谣数据"))

            organizer = FileOrganizer(project_dir=tmpdir)
            result = organizer.verify_structure()

            # 验证返回结构
            self.assertIn("valid", result)
            self.assertIn("missing", result)
            self.assertIn("extra", result)
            self.assertIn("details", result)
            self.assertIsInstance(result["valid"], bool)
            self.assertIsInstance(result["missing"], list)
            self.assertIsInstance(result["extra"], list)
            self.assertIsInstance(result["details"], list)
            self.assertTrue(result["valid"])
            self.assertEqual(result["missing"], [])

    def test_full_organize(self):
        """验证返回结构"""
        from core.file_organizer import FileOrganizer

        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "core"))
            os.makedirs(os.path.join(tmpdir, "utils"))
            os.makedirs(os.path.join(tmpdir, "金水谣数据"))

            organizer = FileOrganizer(project_dir=tmpdir)
            report = organizer.full_organize()

            # 验证返回结构
            self.assertIn("timestamp", report)
            self.assertIn("project_dir", report)
            self.assertIn("steps", report)
            self.assertIn("summary", report)
            self.assertIn("pycache_removed", report["summary"])
            self.assertIn("pycache_freed_kb", report["summary"])
            self.assertIn("logs_archived", report["summary"])
            self.assertIn("logs_kept", report["summary"])
            self.assertIn("orphan_files", report["summary"])
            self.assertIn("structure_valid", report["summary"])
            self.assertIn("root_files_moved", report["summary"])
            self.assertIn("root_files_kept", report["summary"])
            self.assertIn("errors", report["summary"])

    def test_organize_logs(self):
        """验证日志归档返回结构"""
        from core.file_organizer import FileOrganizer

        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = os.path.join(tmpdir, "金水谣数据", "log")
            os.makedirs(log_dir)

            # 创建超过10个日志文件
            for i in range(15):
                log_file = os.path.join(log_dir, f"app_{i:03d}.log")
                with open(log_file, "w") as f:
                    f.write(f"log {i}\n")
                mtime = datetime(2026, 7, 1, i % 24, i % 60, 0).timestamp()
                os.utime(log_file, (mtime, mtime))

            organizer = FileOrganizer(project_dir=tmpdir)
            result = organizer.organize_logs(max_log_files=10)

            self.assertIn("archived", result)
            self.assertIn("kept", result)
            self.assertEqual(result["archived"], 5)
            self.assertEqual(result["kept"], 10)

    def test_check_orphan_files(self):
        """验证孤立文件检测返回结构"""
        from core.file_organizer import FileOrganizer

        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "core"))
            with open(os.path.join(tmpdir, "core", "__init__.py"), "w") as f:
                f.write("")

            organizer = FileOrganizer(project_dir=tmpdir)
            result = organizer.check_orphan_files()

            self.assertIsInstance(result, list)
            for item in result:
                self.assertIn("file", item)
                self.assertIn("reason", item)


# ================================================================
# TestAutoKnowledge - 自动知识积累模块测试
# ================================================================

class TestAutoKnowledge(unittest.TestCase):
    """core.auto_knowledge.AutoKnowledgeExtractor 核心功能测试"""

    def _make_extractor(self):
        """创建知识提取器（mock掉知识库依赖）"""
        with mock.patch("core.auto_knowledge.AutoKnowledgeExtractor.__init__", lambda self: None):
            from core.auto_knowledge import AutoKnowledgeExtractor
            extractor = AutoKnowledgeExtractor()
            extractor._db = None
            extractor._available = False
            return extractor

    def test_extract_from_review_high_hit(self):
        """高命中率提取策略卡片"""
        extractor = self._make_extractor()

        predictions = [
            {"scheme": "趋势策略A", "hits": 8, "total": 10},
            {"scheme": "趋势策略A", "hits": 7, "total": 10},
            {"scheme": "趋势策略A", "hits": 9, "total": 10},
        ]

        cards = extractor.extract_from_review(
            "lottery", predictions, actual="01,02,03", results={}
        )

        # 应提取到"有效策略"卡片
        self.assertGreater(len(cards), 0)
        skill_card = cards[0]
        self.assertIn("有效策略", skill_card["title"])
        self.assertEqual(skill_card["category"], "skill")
        self.assertEqual(skill_card["effectiveness"], 75)

    def test_extract_from_review_low_hit(self):
        """低命中率提取待优化卡片"""
        extractor = self._make_extractor()

        # 4条预测，仅1条命中，命中率 1/4 = 0.25 < 0.30
        predictions = [
            {"scheme": "冷号策略B", "hits": 0, "total": 5},
            {"scheme": "冷号策略B", "hits": 0, "total": 5},
            {"scheme": "冷号策略B", "hits": 1, "total": 5},
            {"scheme": "冷号策略B", "hits": 0, "total": 5},
        ]

        cards = extractor.extract_from_review(
            "lottery", predictions, actual="01,02,03", results={}
        )

        # 应提取到"待优化"卡片
        self.assertGreater(len(cards), 0)
        area_card = cards[0]
        self.assertIn("待优化", area_card["title"])
        self.assertEqual(area_card["category"], "area")
        self.assertEqual(area_card["effectiveness"], 30)

    def test_extract_from_review_consecutive_miss(self):
        """连续未命中提取预警"""
        extractor = self._make_extractor()

        # 所有预测命中数为0，且数量 >= 3
        predictions = [
            {"scheme": "方案A", "hits": 0, "total": 6},
            {"scheme": "方案A", "hits": 0, "total": 6},
            {"scheme": "方案A", "hits": 0, "total": 6},
            {"scheme": "方案A", "hits": 0, "total": 6},
        ]

        cards = extractor.extract_from_review(
            "lottery", predictions, actual="01,02,03", results={}
        )

        # 应提取到"异常预警"卡片
        warn_cards = [c for c in cards if "异常预警" in c["title"]]
        self.assertEqual(len(warn_cards), 1)
        self.assertEqual(warn_cards[0]["category"], "inspiration")

    def test_extract_from_review_consecutive_miss_from_results(self):
        """从 results 字段中检测连续未命中"""
        extractor = self._make_extractor()

        predictions = [
            {"scheme": "方案C", "hits": 0, "total": 6},
        ]
        results = {
            "consecutive_miss": 5,
            "miss_schemes": ["方案C", "方案D"],
        }

        cards = extractor.extract_from_review(
            "lottery", predictions, actual=None, results=results
        )

        warn_cards = [c for c in cards if "异常预警" in c["title"]]
        self.assertEqual(len(warn_cards), 1)
        self.assertIn("5", warn_cards[0]["content"])

    def test_extract_from_conversation(self):
        """对话提取知识"""
        extractor = self._make_extractor()

        user_msg = "双色球今天预测是什么"
        ai_reply = (
            "根据我的分析，双色球本期预测推荐号码为 03, 12, 18, 25, 31, 33 + 08。\n"
            "预测分析：红球走势偏热，蓝球建议关注冷号。\n"
            "建议：可以考虑用小复式扩大号码覆盖范围。"
        )

        cards = extractor.extract_from_conversation("lottery", user_msg, ai_reply)

        # AI 回复包含预测关键词和分析关键词，应至少提取1张卡片
        self.assertGreaterEqual(len(cards), 1)
        # 验证卡片结构
        for card in cards:
            self.assertIn("title", card)
            self.assertIn("content", card)
            self.assertIn("subsystem", card)
            self.assertIn("category", card)
            self.assertIn("tags", card)
            self.assertIn("effectiveness", card)

    def test_extract_from_conversation_empty(self):
        """空回复不提取知识"""
        extractor = self._make_extractor()

        cards = extractor.extract_from_conversation("lottery", "hello", "")
        self.assertEqual(len(cards), 0)

        cards = extractor.extract_from_conversation("lottery", "hello", None)
        self.assertEqual(len(cards), 0)

    def test_extract_from_trend_direction_change(self):
        """趋势方向变化提取知识"""
        extractor = self._make_extractor()

        trend_data = {
            "direction": "up",
            "prev_direction": "down",
            "period": "2026-07-14",
            "details": "从下跌转为上涨趋势",
        }

        cards = extractor.extract_from_trend("stock", trend_data)
        self.assertGreater(len(cards), 0)
        self.assertIn("趋势转折", cards[0]["title"])

    def test_extract_from_trend_abnormal_volatility(self):
        """异常波动提取知识"""
        extractor = self._make_extractor()

        trend_data = {
            "direction": "up",
            "prev_direction": "up",
            "amplitude": 0.10,
            "avg_amplitude": 0.03,
            "period": "2026-07-14",
            "details": "振幅异常放大",
        }

        cards = extractor.extract_from_trend("stock", trend_data)
        self.assertGreater(len(cards), 0)
        self.assertIn("异常信号", cards[0]["title"])

    def test_run_auto_extraction(self):
        """run_auto_extraction 便捷函数测试"""
        with mock.patch("core.auto_knowledge.AutoKnowledgeExtractor") as MockExtractor:
            mock_instance = MockExtractor.return_value
            mock_instance.extract_from_review.return_value = [{"title": "test"}]
            mock_instance.save_cards.return_value = 1

            from core.auto_knowledge import run_auto_extraction
            result = run_auto_extraction("lottery")

            self.assertIn("subsystem", result)
            self.assertEqual(result["subsystem"], "lottery")
            self.assertIn("total_extracted", result)
            self.assertIn("total_saved", result)
            self.assertIn("timestamp", result)

    def test_build_strategy_card_structure(self):
        """验证知识卡片构建结构"""
        from core.auto_knowledge import AutoKnowledgeExtractor

        card = AutoKnowledgeExtractor._build_strategy_card(
            title="测试标题",
            content="测试内容",
            subsystem="lottery",
            category="skill",
            tags=["tag1", "tag2"],
            effectiveness=80,
            engine_hook="test_hook",
        )

        self.assertEqual(card["title"], "测试标题")
        self.assertEqual(card["content"], "测试内容")
        self.assertEqual(card["subsystem"], "lottery")
        self.assertEqual(card["category"], "skill")
        self.assertEqual(card["tags"], ["tag1", "tag2"])
        self.assertEqual(card["effectiveness"], 80)
        self.assertEqual(card["engine_hook"], "test_hook")

    def test_save_cards_unavailable(self):
        """知识库不可用时降级返回0"""
        extractor = self._make_extractor()

        cards = [{"title": "test", "content": "test", "subsystem": "lottery",
                   "category": "skill", "tags": [], "effectiveness": 50}]
        saved = extractor.save_cards(cards)
        self.assertEqual(saved, 0)

    def test_group_by_scheme(self):
        """验证按策略分组统计"""
        from core.auto_knowledge import AutoKnowledgeExtractor

        predictions = [
            {"scheme": "A", "hits": 3, "total": 5},
            {"scheme": "A", "hits": 2, "total": 5},
            {"scheme": "B", "hits": 0, "total": 4},
        ]

        result = AutoKnowledgeExtractor._group_by_scheme(predictions)

        self.assertIn("A", result)
        self.assertIn("B", result)
        self.assertEqual(result["A"]["total"], 2)
        self.assertEqual(result["A"]["hits"], 5)
        self.assertAlmostEqual(result["A"]["hit_rate"], 2.5)  # 5/2
        self.assertEqual(result["B"]["total"], 1)
        self.assertEqual(result["B"]["hits"], 0)
        self.assertEqual(result["B"]["hit_rate"], 0.0)


# ================================================================
# TestScheduler - 调度器模块测试
# ================================================================

class TestScheduler(unittest.TestCase):
    """core.scheduler.TaskScheduler 核心功能测试"""

    def test_register_and_status(self):
        """注册任务并检查状态"""
        from core.scheduler import TaskScheduler

        scheduler = TaskScheduler()

        # 注册任务
        executed = []
        scheduler.register("test_task", lambda: executed.append(1), interval_minutes=60, enabled=True)

        # 检查状态
        status = scheduler.status()
        self.assertEqual(len(status), 1)
        task_status = status[0]
        self.assertEqual(task_status["name"], "test_task")
        self.assertTrue(task_status["enabled"])
        self.assertEqual(task_status["interval_minutes"], 60)
        self.assertEqual(task_status["run_count"], 0)
        self.assertIsNone(task_status["last_run"])
        self.assertIsNone(task_status["last_error"])

    def test_unregister(self):
        """注销任务"""
        from core.scheduler import TaskScheduler

        scheduler = TaskScheduler()
        scheduler.register("to_remove", lambda: None, interval_minutes=10)

        self.assertEqual(len(scheduler.status()), 1)
        scheduler.unregister("to_remove")
        self.assertEqual(len(scheduler.status()), 0)

    def test_start_stop(self):
        """启动和停止"""
        from core.scheduler import TaskScheduler

        scheduler = TaskScheduler()
        counter = {"count": 0}

        def task_func():
            counter["count"] += 1

        # 用较长间隔避免实际执行
        scheduler.register("slow_task", task_func, interval_minutes=9999)
        scheduler.start()

        # 启动后可以停止
        scheduler.stop()

        # 不应执行过
        self.assertEqual(counter["count"], 0)

        # 停止后再次停止（可重入）
        scheduler.stop()  # 不应抛异常

    def test_run_once(self):
        """手动触发一次"""
        from core.scheduler import TaskScheduler
        import threading

        scheduler = TaskScheduler()
        executed = []

        def task_func():
            executed.append("done")

        scheduler.register("manual_task", task_func, interval_minutes=60)
        result = scheduler.run_once("manual_task")

        self.assertTrue(result)

        # 等待线程执行完成
        time.sleep(0.5)

        self.assertEqual(len(executed), 1)

    def test_run_once_nonexistent(self):
        """手动触发不存在的任务"""
        from core.scheduler import TaskScheduler

        scheduler = TaskScheduler()
        result = scheduler.run_once("no_such_task")
        self.assertFalse(result)

    def test_register_duplicate(self):
        """注册同名任务应更新配置"""
        from core.scheduler import TaskScheduler

        scheduler = TaskScheduler()
        scheduler.register("dup_task", lambda: None, interval_minutes=10)
        scheduler.register("dup_task", lambda: None, interval_minutes=20)

        status = scheduler.status()
        self.assertEqual(len(status), 1)
        self.assertEqual(status[0]["interval_minutes"], 20)

    def test_unregister_nonexistent(self):
        """注销不存在的任务不抛异常"""
        from core.scheduler import TaskScheduler

        scheduler = TaskScheduler()
        scheduler.unregister("ghost_task")  # 不应抛异常

    def test_start_reentrant(self):
        """多次启动不创建重复定时器"""
        from core.scheduler import TaskScheduler

        scheduler = TaskScheduler()
        scheduler.register("reentrant_task", lambda: None, interval_minutes=60)

        scheduler.start()
        scheduler.start()  # 第二次应被忽略
        scheduler.stop()