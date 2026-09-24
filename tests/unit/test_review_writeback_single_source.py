# -*- coding: utf-8 -*-
"""复盘回写单一真源回归测试（JS-20260924-32）

背景（真实缺陷，实测取证）：predictions.json 共 3228 条，其中 **30 条 reviewed=True
但没有 actual（开奖号）**，且这 30 条全部生成于 2026-09-23 —— 即「每天新增一批」。

根因：彩票复盘共有 **三条** 代码路径，各自手写回写：
  1. domains/lottery/domain.py  LotteryDomain.review()   —— 写了 actual ✅
  2. core/infra/scheduler.py    _task_auto_review()       —— **漏写 actual** ❌
  3. gui/main_window.py         _review_job()             —— **漏写 actual** ❌
JS-20260921-03 当时只修了第 1 条（domains 路径），漏了另外两条同类项 →
自动复盘每天跑，就每天新增约 30 条「已复盘但无开奖号、事后无法重算」的记录。

修复：抽出单一真源 utils/review_writeback.stamp_review()，三条路径统一调用，
并用 AST 扫描禁止任何地方再直接写 pred["reviewed"]（同类项全量为零）。

本文件的价值：把「回写字段漏项」这个静默错误钉死——它不报错，页面显示"已复盘"，
但开奖号永远查不到，正是「命中率对不上」类问题最难查的那一类。
"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

# 允许直接写 ["reviewed"] 的白名单：单一真源模块 + 历史数据修补脚本
REVIEWED_WRITE_ALLOWLIST = {
    os.path.join("utils", "review_writeback.py"),
    os.path.join("scripts", "backfill_prediction_actual.py"),
}


class _FakeData:
    """桩：只提供自动复盘需要的 has_period / result"""

    RESULT = "01,02,03,04,05,06+07"

    @staticmethod
    def has_period(lot, per):
        return True

    @staticmethod
    def result(lot, per):
        return _FakeData.RESULT, "2026-09-23"


class TestStampReviewSingleSource(unittest.TestCase):
    """stamp_review 是复盘字段回写的唯一落点"""

    def test_stamp_writes_all_fields(self):
        from utils.review_writeback import stamp_review
        p = {}
        stamp_review(p, actual="01,02,03,04,05,06+07", draw_date="2026-09-23",
                     hits=3, hit_type="组选", coverage=0.5)
        self.assertEqual(p["actual"], "01,02,03,04,05,06+07")
        self.assertEqual(p["draw_date"], "2026-09-23")
        self.assertEqual(p["reviewed"], True)
        self.assertEqual(p["hits"], 3)
        self.assertEqual(p["hit_type"], "组选")
        self.assertEqual(p["coverage"], 0.5)

    def test_stamp_skips_none_instead_of_overwriting(self):
        """None 表示调用方未提供，必须跳过——不能用 None 覆盖已有值"""
        from utils.review_writeback import stamp_review
        p = {"actual": "OLD"}
        stamp_review(p, actual=None, hits=1)
        self.assertEqual(p["actual"], "OLD", "None 覆盖了已有开奖号")

    def test_stamp_always_marks_reviewed_and_hits(self):
        from utils.review_writeback import stamp_review
        p = {}
        stamp_review(p, actual="1,2,3")
        self.assertEqual(p["reviewed"], True)
        self.assertIn("hits", p)


class TestAutoReviewPersistsActual(unittest.TestCase):
    """调度器自动复盘必须回存开奖号（缺陷实测点）"""

    def _run(self, store):
        import utils.safe_json as sj
        import models.lottery_data as ld
        import core.infra.scheduler as sched

        written = {}
        old_write = sj.safe_write_json
        old_data = ld.Data
        old_load = sched._load_pred_cache_cached

        def _write(path, data):
            # 自动复盘之后 SmartBrain 学习也会落盘（写的是 dict），
            # 只取「预测列表」那次写入，避免被后续写入覆盖（实测踩过）
            written.setdefault("calls", []).append((path, data))
            if isinstance(data, list) and "data" not in written:
                written["data"] = data
            return True

        sj.safe_write_json = _write
        ld.Data = _FakeData
        sched._load_pred_cache_cached = lambda: list(store)
        try:
            sched.JinshuiyaoScheduler._task_auto_review()
        finally:
            sj.safe_write_json = old_write
            ld.Data = old_data
            sched._load_pred_cache_cached = old_load
        return written.get("data")

    def test_auto_review_writes_actual(self):
        data = self._run([{"lot": "双色球", "period": 2026109,
                           "nums": "01,02,03,04,05,06+07", "type": "单注"}])
        self.assertIsNotNone(data, "自动复盘应发生回写")
        row = data[0]
        self.assertEqual(row.get("reviewed"), True)
        self.assertEqual(row.get("actual"), _FakeData.RESULT,
                         "自动复盘未回存开奖号 → 历史命中事后无法重算")

    def test_auto_review_keeps_hit_type_and_coverage(self):
        """修 actual 的同时不许把 hit_type/coverage 修丢"""
        data = self._run([{"lot": "大乐透", "period": 2026109,
                           "nums": "01,18,21,31,32+04,08", "type": "单注"}])
        row = data[0]
        self.assertIn("hit_type", row)
        self.assertIn("coverage", row)
        self.assertIn("draw_date", row)


class TestNoDirectReviewedWrite(unittest.TestCase):
    """AST 扫描：仓库内禁止绕过 stamp_review 直接写 pred['reviewed']（同类项为零）"""

    def _iter_py(self):
        skip_dirs = {".git", "__pycache__", "venv", ".venv", "node_modules",
                     "archive", "90_归档文档", "obsidian-vault"}
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fn in filenames:
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)

    def test_no_direct_reviewed_assignment(self):
        offenders = []
        for path in self._iter_py():
            rel = os.path.relpath(path, ROOT)
            if rel in REVIEWED_WRITE_ALLOWLIST:
                continue
            if rel.startswith("tests" + os.sep):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    tree = ast.parse(f.read())
            except Exception:
                continue  # 语法/编码问题不属本闸职责
            for node in ast.walk(tree):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, ast.AnnAssign):
                    targets = [node.target]
                for t in targets:
                    if not isinstance(t, ast.Subscript):
                        continue
                    sl = t.slice
                    if isinstance(sl, ast.Constant) and sl.value == "reviewed":
                        offenders.append("%s:%d" % (rel, node.lineno))
        self.assertEqual(offenders, [],
                         "发现绕过 stamp_review 的直接回写（同类项未清零）: %s" % offenders)


if __name__ == "__main__":
    unittest.main()
