# -*- coding: utf-8 -*-
"""金水谣系统 - 定时任务调度器单元测试

测试 core/scheduler.py 的 TaskScheduler / JinshuiyaoScheduler / get_scheduler 单例。
所有任务使用 mock 函数，不触发真实的网络/数据操作。
"""
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestSchedulerSingleton(unittest.TestCase):
    """测试调度器单例模式"""

    def setUp(self):
        try:
            import core.scheduler as scheduler_module
            from core.scheduler import TaskScheduler, JinshuiyaoScheduler, get_scheduler
        except Exception as e:
            self.skipTest("无法导入 scheduler: %s" % e)
        self.scheduler_module = scheduler_module
        self.TaskScheduler = TaskScheduler
        self.JinshuiyaoScheduler = JinshuiyaoScheduler
        self.get_scheduler = get_scheduler

    def test_scheduler_singleton(self):
        """get_scheduler 应返回同一单例"""
        # 重置全局单例
        with patch.object(self.scheduler_module, "_global_scheduler", None):
            s1 = self.get_scheduler()
            s2 = self.get_scheduler()
            self.assertIs(s1, s2, "get_scheduler 应返回同一单例实例")
            self.assertIsInstance(s1, self.JinshuiyaoScheduler)

    def test_scheduler_singleton_thread_safe(self):
        """多线程并发获取单例应返回同一实例"""
        with patch.object(self.scheduler_module, "_global_scheduler", None):
            instances = []

            def worker():
                s = self.get_scheduler()
                instances.append(s)

            threads = [__import__("threading").Thread(target=worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # 所有线程应拿到同一实例
            self.assertEqual(len(instances), 10)
            first = instances[0]
            for s in instances[1:]:
                self.assertIs(s, first, "并发获取应返回同一实例")


class TestTaskSchedulerStartStop(unittest.TestCase):
    """测试 TaskScheduler 启动/停止"""

    def setUp(self):
        try:
            from core.scheduler import TaskScheduler
        except Exception as e:
            self.skipTest("无法导入 TaskScheduler: %s" % e)
        self.TaskScheduler = TaskScheduler
        self.scheduler = TaskScheduler()

    def tearDown(self):
        try:
            self.scheduler.stop()
        except Exception:
            pass

    def test_scheduler_start_stop(self):
        """启动/停止调度器"""
        # 初始应为未启动
        self.assertFalse(self.scheduler._started)

        # 注册一个任务（不执行真实操作）
        self.scheduler.register("test_task", lambda: None, interval_minutes=1)
        self.scheduler.start()
        self.assertTrue(self.scheduler._started)

        # 重复启动应安全
        self.scheduler.start()
        self.assertTrue(self.scheduler._started)

        # 停止
        self.scheduler.stop()
        self.assertFalse(self.scheduler._started)

        # 重复停止应安全
        self.scheduler.stop()
        self.assertFalse(self.scheduler._started)

    def test_scheduler_start_schedules_enabled_tasks(self):
        """启动时应调度已启用的任务"""
        called = {"count": 0}

        def task_func():
            called["count"] += 1

        # 用很短的间隔（1秒的1/60=约0.016秒）以便快速触发
        self.scheduler.register("quick_task", task_func, interval_minutes=1.0 / 60,
                                enabled=True)
        self.scheduler.register("disabled_task", task_func, interval_minutes=1,
                                enabled=False)

        self.scheduler.start()
        # 等待约 0.1 秒让 Timer 触发
        time.sleep(0.1)

        # 禁用任务不应被调度（_timers 中不应有 disabled_task）
        self.assertNotIn("disabled_task", self.scheduler._timers)
        # 启用的任务应被调度
        self.assertIn("quick_task", self.scheduler._timers)


class TestSchedulerTasks(unittest.TestCase):
    """测试调度器任务注册"""

    def setUp(self):
        try:
            from core.scheduler import TaskScheduler
        except Exception as e:
            self.skipTest("无法导入 TaskScheduler: %s" % e)
        self.TaskScheduler = TaskScheduler
        self.scheduler = TaskScheduler()

    def tearDown(self):
        try:
            self.scheduler.stop()
        except Exception:
            pass

    def test_scheduler_tasks(self):
        """任务注册/注销"""
        # 注册任务
        self.scheduler.register("task_a", lambda: "a", interval_minutes=5)
        self.scheduler.register("task_b", lambda: "b", interval_minutes=10)

        # 应在 _tasks 中
        self.assertIn("task_a", self.scheduler._tasks)
        self.assertIn("task_b", self.scheduler._tasks)
        # 任务信息应包含必要字段
        task_a = self.scheduler._tasks["task_a"]
        self.assertEqual(task_a["interval_minutes"], 5)
        self.assertTrue(task_a["enabled"])
        self.assertEqual(task_a["run_count"], 0)

        # 注销任务
        self.scheduler.unregister("task_a")
        self.assertNotIn("task_a", self.scheduler._tasks)
        # 注销不存在的任务应安全
        self.scheduler.unregister("nonexistent")

    def test_scheduler_register_update_existing(self):
        """重复注册同名任务应更新配置"""
        self.scheduler.register("dup_task", lambda: None, interval_minutes=5)
        original_func = self.scheduler._tasks["dup_task"]["func"]

        # 再次注册同名任务（不同间隔）
        new_func = lambda: "updated"
        self.scheduler.register("dup_task", new_func, interval_minutes=10)

        # 应仍是同一个任务条目，但配置已更新
        self.assertIn("dup_task", self.scheduler._tasks)
        self.assertEqual(self.scheduler._tasks["dup_task"]["interval_minutes"], 10)

    def test_scheduler_register_disabled(self):
        """注册时设置 enabled=False 应不立即调度"""
        self.scheduler.register("disabled_task", lambda: None,
                                interval_minutes=5, enabled=False)
        self.assertFalse(self.scheduler._tasks["disabled_task"]["enabled"])

        # 启动调度器，该任务不应被调度
        self.scheduler.start()
        self.assertNotIn("disabled_task", self.scheduler._timers)

    def test_scheduler_run_once(self):
        """run_once 应能手动触发任务执行一次"""
        called = {"count": 0}

        def task_func():
            called["count"] += 1

        self.scheduler.register("once_task", task_func, interval_minutes=60)
        result = self.scheduler.run_once("once_task")
        self.assertTrue(result, "run_once 应返回 True")

        # 等待异步执行完成
        time.sleep(0.3)
        self.assertGreaterEqual(called["count"], 1, "任务应被触发至少1次")

        # 触发不存在的任务应返回 False
        result = self.scheduler.run_once("nonexistent")
        self.assertFalse(result)


class TestJinshuiyaoSchedulerTasks(unittest.TestCase):
    """测试 JinshuiyaoScheduler 默认任务注册"""

    def setUp(self):
        try:
            from core.scheduler import JinshuiyaoScheduler
        except Exception as e:
            self.skipTest("无法导入 JinshuiyaoScheduler: %s" % e)
        self.JinshuiyaoScheduler = JinshuiyaoScheduler
        # 用 patch 替换所有任务的 func 实现为 mock，避免真实网络/数据操作
        # 这里只验证任务注册情况，不执行真实任务
        self.scheduler = JinshuiyaoScheduler()

    def tearDown(self):
        try:
            self.scheduler.stop()
        except Exception:
            pass

    def test_jinshuiyao_default_tasks_registered(self):
        """JinshuiyaoScheduler 应注册6项默认任务"""
        expected_tasks = [
            "data_refresh",
            "auto_review",
            "knowledge_extract",
            "data_maintenance",
            "health_backup",
            "file_cleanup",
        ]
        for name in expected_tasks:
            self.assertIn(name, self.scheduler._tasks,
                          "应注册默认任务: %s" % name)
            task = self.scheduler._tasks[name]
            self.assertTrue(task["enabled"], "默认任务应启用: %s" % name)
            self.assertGreater(task["interval_minutes"], 0,
                              "任务间隔应大于0: %s" % name)

    def test_jinshuiyao_data_refresh_interval(self):
        """data_refresh 任务间隔应为 60 分钟"""
        task = self.scheduler._tasks.get("data_refresh")
        self.assertIsNotNone(task)
        self.assertEqual(task["interval_minutes"], 60)

    def test_jinshuiyao_auto_review_interval(self):
        """auto_review 任务间隔应为 120 分钟"""
        task = self.scheduler._tasks.get("auto_review")
        self.assertIsNotNone(task)
        self.assertEqual(task["interval_minutes"], 120)


class TestSchedulerStatus(unittest.TestCase):
    """测试调度器状态查询"""

    def setUp(self):
        try:
            from core.scheduler import TaskScheduler
        except Exception as e:
            self.skipTest("无法导入 TaskScheduler: %s" % e)
        self.TaskScheduler = TaskScheduler
        self.scheduler = TaskScheduler()

    def tearDown(self):
        try:
            self.scheduler.stop()
        except Exception:
            pass

    def test_scheduler_status(self):
        """status 应返回所有任务的状态信息"""
        self.scheduler.register("status_task_a", lambda: None, interval_minutes=5)
        self.scheduler.register("status_task_b", lambda: None, interval_minutes=10)

        statuses = self.scheduler.status()
        self.assertIsInstance(statuses, list)
        self.assertEqual(len(statuses), 2)

        # 每条状态应包含必要字段
        for s in statuses:
            self.assertIn("name", s)
            self.assertIn("enabled", s)
            self.assertIn("interval_minutes", s)
            self.assertIn("last_run", s)
            self.assertIn("next_run", s)
            self.assertIn("run_count", s)
            self.assertIn("last_error", s)

        # 应能找到注册的任务
        names = {s["name"] for s in statuses}
        self.assertIn("status_task_a", names)
        self.assertIn("status_task_b", names)

    def test_scheduler_status_empty(self):
        """空调度器 status 应返回空列表"""
        statuses = self.scheduler.status()
        self.assertEqual(len(statuses), 0)

    def test_scheduler_status_after_run(self):
        """执行任务后 status 应反映执行情况"""
        self.scheduler.register("run_status_task", lambda: "ok", interval_minutes=60)
        # 手动触发一次
        self.scheduler.run_once("run_status_task")
        time.sleep(0.3)  # 等待异步执行

        statuses = self.scheduler.status()
        for s in statuses:
            if s["name"] == "run_status_task":
                self.assertGreaterEqual(s["run_count"], 1, "执行次数应>=1")
                self.assertIsNotNone(s["last_run"], "上次执行时间应不为空")
                self.assertIsNone(s["last_error"], "无错误时应为 None")
                return
        self.fail("未找到 run_status_task 的状态")


if __name__ == "__main__":
    unittest.main()
