# -*- coding: utf-8 -*-
"""调度器「任务产出回传」链路测试（JS-20261002-20）

背景（真实缺陷，由启动日志「复盘-1条 / 失配=True」暴露）：
    开机自迭代调用 run_once("auto_review") 触发复盘，但该函数：
      ① 是**异步**的——开个线程就返回 True，自迭代随后立刻探测链路，
         读到的仍是「复盘没跑完」的旧状态 → 失配恒为 True 的**假警**；
      ② 拿不到任务产出——`_execute_task` 里 `result = func()` 取到返回值
         却直接丢弃，而 `_task_auto_review` **无任何带值 return**；
      ③ 于是调用方只能硬编码 `{"reviews": -1}` 占位，日志打出「复盘-1条」
         这种误导性数字。

本测试锁死修好后的不变量，防止回退：
    1. _task_auto_review 必须有带值 return（调用方能拿到真实条数）
    2. run_once(wait=True) 必须**同步**等待并回传任务返回值
    3. run_once() 默认仍异步返回 True（向后兼容，不破坏既有调用方）
    4. status() 必须暴露 last_result（"跑了"之外还能看"跑出什么"）
    5. 全仓不得再出现 reviews=-1 之类的哨兵魔数
"""
import ast
import io
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

SCHEDULER_PY = os.path.join(BASE, "core", "infra", "scheduler.py")
TASKS_PY = os.path.join(BASE, "core", "infra", "scheduler_tasks.py")
LAUNCH_PY = os.path.join(BASE, "launch_jinshuiyao.py")


def _read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def _func_node(src, name):
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    return None


class TestAutoReviewReturnsCount(unittest.TestCase):
    """① 自动复盘任务必须回传真实条数，否则调用方只能靠猜。"""

    def test_has_value_return(self):
        node = _func_node(_read(SCHEDULER_PY), "_task_auto_review")
        self.assertIsNotNone(node, "找不到 _task_auto_review")
        valued = [n for n in ast.walk(node)
                  if isinstance(n, ast.Return) and n.value is not None]
        self.assertGreaterEqual(
            len(valued), 1,
            "_task_auto_review 必须至少有一个带值 return，"
            "否则调用方永远拿不到复盘条数（JS-20261002-20）")

    def test_returns_reviews_key(self):
        """至少一条 return 的结果里含 reviews 键（AST 层面确认口径）。"""
        node = _func_node(_read(SCHEDULER_PY), "_task_auto_review")
        found = False
        for n in ast.walk(node):
            if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
                keys = [k.value for k in n.value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)]
                if "reviews" in keys:
                    found = True
        self.assertTrue(found, "_task_auto_review 应返回含 reviews 键的 dict")


class TestRunOnceWait(unittest.TestCase):
    """②③ run_once 的同步等待与向后兼容。"""

    def setUp(self):
        from core.infra.scheduler_tasks import TaskScheduler
        self.sched = TaskScheduler()
        self.sched.register("__test_probe__", lambda: {"reviews": 7, "skipped": 2},
                            interval_minutes=99999, enabled=False)

    def test_run_once_default_is_async_bool(self):
        """默认行为必须保持：异步触发、返回 True（不破坏既有调用方）。"""
        self.assertIs(self.sched.run_once("__test_probe__"), True)

    def test_run_once_wait_returns_task_result(self):
        """wait=True 必须同步等待并回传任务真实返回值。"""
        res = self.sched.run_once("__test_probe__", wait=True, timeout=10)
        self.assertEqual(res, {"reviews": 7, "skipped": 2})

    def test_run_once_wait_unknown_task(self):
        self.assertIsNone(self.sched.run_once("__不存在__", wait=True))

    def test_status_exposes_last_result(self):
        """④ 状态查询要能看到任务产出。"""
        self.sched.run_once("__test_probe__", wait=True, timeout=10)
        rows = [r for r in self.sched.status() if r["name"] == "__test_probe__"]
        self.assertEqual(len(rows), 1)
        self.assertIn("last_result", rows[0])
        self.assertEqual(rows[0]["last_result"], {"reviews": 7, "skipped": 2})


class TestNoSentinelNumbers(unittest.TestCase):
    """⑤ 不得再用 -1 之类哨兵数字冒充条数。"""

    def test_launch_has_no_minus_one_reviews(self):
        src = _read(LAUNCH_PY)
        self.assertNotIn('"reviews": -1', src,
                         "不得再硬编码 reviews=-1 哨兵（会打成「复盘-1条」）")
        self.assertNotIn("'reviews': -1", src)

    def test_run_once_supports_wait(self):
        node = _func_node(_read(TASKS_PY), "run_once")
        args = [a.arg for a in node.args.args]
        self.assertIn("wait", args, "run_once 必须支持 wait 参数")
        self.assertIn("timeout", args, "run_once 必须支持 timeout 参数")


if __name__ == "__main__":
    unittest.main()
