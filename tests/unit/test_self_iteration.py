# -*- coding: utf-8 -*-
"""智能大脑「自迭代核心逻辑」单元测试（先红后绿）

覆盖：
  1. get_digit_adjustments 决策阶段复用复盘学到的精确偏差（而非从头重算覆盖）
     —— 这是「旧数据空转」的根因修复点
  2. SmartBrain._ensure_fresh 在 predictions.json 变化后自动重载历史/状态
     —— 保证长生命周期大脑实例「越用越聪明」
  3. probe_linkage 检测感知↔推理↔决策链路失配与学习滞后（知识/数据陈旧）
  4. run_self_iteration 编排「采集→学习→刷新→知识更新→闭环验证」
"""
import os
import sys
import json
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engines.smart_brain import SmartBrain


def _seed_preds(path, n, lot="大乐透", reviewed=True, hits=1):
    preds = []
    for i in range(n):
        preds.append({
            "lot": lot,
            "period": 26000 + i,
            "nums": "01,02,03,04,05+06,07",
            "reviewed": reviewed,
            "hits": hits if reviewed else None,
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(preds, f, ensure_ascii=False)


def _mk_brain(tmp_dir):
    return SmartBrain(str(tmp_dir))


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()


class TestDigitAdjustmentReuse(_Base):
    def test_get_digit_adjustments_prefers_persisted_bias(self):
        """决策阶段应复用复盘学到的精确偏差，而非重算后覆盖（修复空转）。"""
        brain = _mk_brain(self._tmp)
        _seed_preds(brain.pred_file, 25, hits=1)
        brain.history = brain._load_history()

        # 学一次：用真实开奖号，得到精确偏差
        actual = [1, 2, 3, 4, 5, 6, 7]
        brain.learn_from_review(
            "大乐透",
            [{"nums": "01,02,03,04,05+06,07", "hits": 2}],
            actual,
        )
        persisted = {int(k): float(v)
                     for k, v in brain.state["digit_bias"]["大乐透"].items()}

        # 决策阶段再取修正：应复用学习到的偏差
        adj = brain.get_digit_adjustments("大乐透")
        self.assertEqual(len(adj), 35)  # 大乐透 1..35 全覆盖
        for k, v in persisted.items():
            self.assertEqual(adj.get(k), v,
                             "学习到的偏差 %s 未被决策阶段复用" % k)


class TestEnsureFresh(_Base):
    def test_ensure_fresh_reloads_history_after_pred_file_change(self):
        brain = _mk_brain(self._tmp)
        self.assertEqual(len(brain.history), 0)
        _seed_preds(brain.pred_file, 3, reviewed=True, hits=1)
        brain._ensure_fresh()
        self.assertEqual(len(brain.history), 3)


class TestProbeLinkage(_Base):
    def test_probe_linkage_detects_learning_lag(self):
        from engines.self_iteration import probe_linkage
        brain = _mk_brain(self._tmp)
        _seed_preds(brain.pred_file, 5, reviewed=True, hits=1)
        status = probe_linkage(brain, self._tmp)
        self.assertEqual(status.learning_lag, 5)
        self.assertTrue(status.mismatch_detected)
        self.assertTrue(status.decision_stale)
        self.assertIn("学习滞后", "".join(status.notes))

    def test_probe_linkage_clean_when_in_sync(self):
        from engines.self_iteration import probe_linkage
        brain = _mk_brain(self._tmp)
        _seed_preds(brain.pred_file, 4, reviewed=True, hits=1)
        brain.state["learned_review_count"] = 4
        brain._save_state()
        status = probe_linkage(brain, self._tmp)
        self.assertEqual(status.learning_lag, 0)
        self.assertFalse(status.mismatch_detected)
        self.assertFalse(status.spin_risk)


class TestNoStateClobber(_Base):
    """类2 隐患：同一持久化文件被多个实例写，最后写入者可能抹掉别人的学习成果。

    brain_state.json 有多个写入方（smart_brain.learn_from_review /
    prediction_service.generate / watchdog）。若某个长生命周期实例的
    内存 state 是陈旧的，它一落盘就会把别的实例刚学到的 digit_bias 抹掉。
    _ensure_fresh() 必须在写之前自愈，本测试把这个不变量锁死。
    """

    def test_stale_instance_does_not_clobber_fresh_learning(self):
        # 实例 B：先加载（此时还没有任何学习成果），模拟常驻单例
        b = _mk_brain(self._tmp)
        _seed_preds(b.pred_file, 25, hits=1)
        b.history = b._load_history()
        self.assertEqual(b.state.get("digit_bias", {}).get("大乐透"), None)

        # 实例 A：学习并落盘（另一条链路，如调度器自动复盘）
        a = _mk_brain(self._tmp)
        a.history = a._load_history()
        a.learn_from_review(
            "大乐透",
            [{"nums": "01,02,03,04,05+06,07", "hits": 2}],
            [1, 2, 3, 4, 5, 6, 7],
        )
        learned = dict(a.state["digit_bias"]["大乐透"])
        self.assertTrue(learned, "学习成果未产生")

        # 实例 B 走一次决策（assess_confidence 内部会 _ensure_fresh 自愈）后再落盘
        b.assess_confidence("大乐透")
        b._save_state()

        # 关键断言：B 的落盘不得抹掉 A 学到的偏差
        after = _mk_brain(self._tmp)
        self.assertEqual(
            dict(after.state["digit_bias"].get("大乐透", {})), learned,
            "陈旧实例落盘抹掉了刚学到的 digit_bias（_ensure_fresh 未生效）")


class TestRunSelfIteration(_Base):
    def test_run_self_iteration_closes_loop(self):
        from engines.self_iteration import run_self_iteration
        brain = _mk_brain(self._tmp)
        _seed_preds(brain.pred_file, 3, reviewed=True, hits=1)

        def review_fn():
            # 模拟：把 3 条已复盘记录标记为「大脑已学」并落盘
            b = _mk_brain(self._tmp)
            b.state["learned_review_count"] = 3
            b._save_state()
            return {"reviews": 3}

        report = run_self_iteration(self._tmp, review_fn=review_fn)
        after = report["after"]
        self.assertEqual(after["learning_lag"], 0)
        self.assertFalse(after["mismatch_detected"])
        self.assertTrue(report.get("learned"))


if __name__ == "__main__":
    unittest.main()
