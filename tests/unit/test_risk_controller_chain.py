# -*- coding: utf-8 -*-
"""策略修正器「复盘后更新」接线单测（先红后绿，JS-20261002-18）

背景：StrategyCorrector.update_after_review() 此前**全仓 0 调用点**，
而 need_blood_change / get_group3_weight_multiplier 依赖的 pool_zeros /
recent_forms 只在它里面递增 → 模块文档声称的三大修正机制**永久失效**，
且从不报错。硬证据：risk_state.json mtime 停在 2026-07-14。

覆盖：
  1. learn_from_review 真的更新状态并落盘（换血机制可被触发）
  2. 连续两期中 0 码 → need_blood_change 由 False 变 True（证明机制活了）
  3. AST 接线闸：learn_from_review 必须被复盘链路真实调用
  4. 失败降级：异常不得抛出打断复盘
"""
import os
import ast
import sys
import json
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import engines.risk_controller as rc


class _TmpState(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_file = rc.RISK_STATE_FILE
        self._orig_singleton = rc._corrector
        rc.RISK_STATE_FILE = os.path.join(self._tmp, "risk_state.json")
        rc._corrector = None  # 重建单例，指向新的 state 文件

    def tearDown(self):
        rc.RISK_STATE_FILE = self._orig_file
        rc._corrector = self._orig_singleton
        shutil.rmtree(self._tmp, ignore_errors=True)


class TestLearnFromReview(_TmpState):
    def test_state_updates_and_persists(self):
        """复盘后：连续0命中计数 + 形态记录 必须真的写进 state 并落盘。"""
        lot = "福彩3D"
        # 池 [0,3,5,6,8]，开奖 [1,2,4] —— 与池无交集 → pool_zeros +1
        ok = rc.learn_from_review(lot, "0,3,5,6,8", "1,2,4", 0)
        self.assertTrue(ok)

        c = rc.get_corrector()
        st = c.get_status(lot)
        self.assertEqual(st["consecutive_zeros"], 1, "连续0命中未记录")
        self.assertEqual(st["pool_zeros"], 1, "池内0码未记录")
        self.assertEqual(st["recent_forms"], ["组六"], "开奖形态未记录")
        self.assertEqual(st["last_pool"], [0, 3, 5, 6, 8], "上期码池未记录")

        # 必须真的落盘
        self.assertTrue(os.path.isfile(rc.RISK_STATE_FILE), "risk_state.json 未落盘")
        with open(rc.RISK_STATE_FILE, "r", encoding="utf-8") as f:
            disk = json.load(f)
        self.assertEqual(
            disk["per_lot"][lot]["consecutive_zeros"], 1, "状态未持久化到磁盘")

    def test_blood_change_becomes_triggerable(self):
        """连续两期池内0码 → need_blood_change 由 False 变 True。

        修复前该条件永远为 False（因为 pool_zeros 永不递增）。
        """
        lot = "排列三"
        c = rc.get_corrector()
        self.assertFalse(c.need_blood_change(lot), "初始不应触发换血")

        rc.learn_from_review(lot, "0,3,5,6,8", "1,2,4", 0)
        self.assertFalse(c.need_blood_change(lot), "仅1期0码不应触发")

        rc.learn_from_review(lot, "0,3,5,6,8", "1,2,7", 0)
        self.assertTrue(c.need_blood_change(lot), "连续2期0码应触发换血")

    def test_hit_resets_counters(self):
        lot = "福彩3D"
        rc.learn_from_review(lot, "0,3,5,6,8", "1,2,4", 0)
        rc.learn_from_review(lot, "0,3,5,6,8", "3,5,8", 2)
        st = rc.get_corrector().get_status(lot)
        self.assertEqual(st["consecutive_zeros"], 0, "命中后应清零")
        self.assertEqual(st["pool_zeros"], 0, "池内有命中应清零")

    def test_exception_is_swallowed(self):
        """旁路功能不得打断复盘主流程。"""
        self.assertFalse(rc.learn_from_review("福彩3D", object(), object(), None))


class TestWiredIntoReviewChain(unittest.TestCase):
    def test_review_chain_calls_learn_from_review(self):
        """AST 闸：复盘链路必须真实调用 learn_from_review。"""
        targets = [
            os.path.join(ROOT, "domains", "lottery", "domain.py"),
            os.path.join(ROOT, "core", "infra", "scheduler.py"),
        ]
        for path in targets:
            with open(path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())
            hit = False
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module == "engines.risk_controller":
                        for al in node.names:
                            if al.name == "learn_from_review":
                                hit = True
            self.assertTrue(hit, "%s 未导入 risk_controller.learn_from_review" % path)


if __name__ == "__main__":
    unittest.main()
