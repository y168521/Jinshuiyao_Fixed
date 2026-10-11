"""学习滞后告警 · 存量欠账基线（JS-20261012-04）

背景（真实缺陷，由启动日志暴露）：
    `learning_lag = 已复盘记录数 − 大脑已学习记录数`。当分子分母**同步增长**
    时，差值恒定不变，却仍被判「失配=True + 空转风险=True」，
    于是每天启动都喊「系统已停止进化」。实测该值自 2026-10-03 起恒为 3369
    （2026-09-24 批量回填 3202 条已复盘记录留下的历史欠账），
    同期备份链显示 learned 185→189→198→207 每轮都在涨 —— 学习链路正常，
    是告警口径错了。**这类告警永远变不了绿 = 噪音**，且比没告警更坏。

修法：
    失配/空转只由**相对基线的增量**判定，存量部分照常披露数字但不计失配。
    **基线必须显式创建，绝不自动锁定** —— 自动锁会把「首次出现的真故障」
    当成存量基线吃掉（第一次见到 lag=50 时无法区分历史欠账还是刚断的链路）。
    无基线文件时行为与改造前完全一致（回归安全）。

覆盖：
  1. 无基线 → 行为不变（lag>0 即失配），回归锁
  2. 有基线且 lag == 基线 → 不计失配，notes 明确标注存量
  3. 有基线且 lag > 基线 → 增量部分计失配（真故障仍抓得住）
  4. lag < 基线（欠账被消化）→ 基线降到新水位，不计失配
  5. 空转风险由增量判定，不被 3369 这类存量数字触发
  6. 基线文件损坏 → 按无基线处理（退化方向是继续报警，不是静默放行）
  7. 基线绝不自动创建（无文件跑完后不得凭空生成基线文件）
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engines.self_iteration import (  # noqa: E402
    probe_linkage, _lag_baseline_path, _load_lag_baseline,
    _save_lag_baseline, LEARNING_LAG_SPIN_THRESHOLD,
)
from engines.smart_brain import SmartBrain  # noqa: E402


def _seed_preds(path, n):
    preds = [{"lot": "大乐透", "period": 26000 + i, "nums": "01,02,03,04,05+06,07",
              "reviewed": True, "hits": 1} for i in range(n)]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(preds, f, ensure_ascii=False)


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def _brain(self, n_reviewed, learned=None):
        """造场景：**先**写 predictions、**后**落 brain_state。

        顺序很关键：`decision_stale = predictions.mtime > brain_state.mtime`。
        若先 save 再 seed，predictions 反而更新，decision_stale 恒为 True，
        失配就永远为真，断言便测不到「学习滞后」这一项本身。
        learned=None 时不落 state（state_mt==0 → decision_stale=True），
        用于复现改造前的原始行为。
        """
        b = SmartBrain(str(self._tmp))
        _seed_preds(b.pred_file, n_reviewed)
        if learned is not None:
            b.state["learned_review_count"] = learned
            b._save_state()
        return b


class TestNoBaselineBehavesAsBefore(_Base):
    """回归锁：没有基线文件时，行为必须与改造前完全一致。"""

    def test_lag_positive_is_mismatch(self):
        b = self._brain(5)          # learned=None → 与改造前同场景
        st = probe_linkage(b, self._tmp)
        self.assertEqual(st.learning_lag, 5)
        self.assertTrue(st.mismatch_detected, "无基线时 lag>0 必须判失配")
        self.assertIn("学习滞后", "".join(st.notes))

    def test_in_sync_is_clean(self):
        b = self._brain(4, learned=4)
        st = probe_linkage(b, self._tmp)
        self.assertEqual(st.learning_lag, 0)
        self.assertFalse(st.mismatch_detected)
        self.assertFalse(st.spin_risk)


class TestBaselineSuppressesStaleOnly(_Base):
    """核心：存量部分不报警，增量部分必须报警。"""

    def _write_baseline(self, value):
        path = _lag_baseline_path(os.path.join(self._tmp, "predictions.json"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"baseline": value}, f)
        return path

    def test_lag_equal_baseline_is_not_mismatch(self):
        """3369 == 3369：存量欠账，不该每天喊停摆。"""
        self._write_baseline(3369)
        # 3576 条已复盘、已学 207 条 → lag = 3369
        b = self._brain(3576, learned=207)
        st = probe_linkage(b, self._tmp)
        self.assertEqual(st.learning_lag, 3369)
        self.assertFalse(st.mismatch_detected, "存量欠账不应判失配")
        self.assertFalse(st.spin_risk, "存量欠账不应触发空转风险")
        joined = "".join(st.notes)
        self.assertIn("3369", joined, "数字仍应如实披露")
        self.assertIn("存量基线", joined)

    def test_lag_above_baseline_is_mismatch(self):
        """基线 3369、当前 3380 → 新增 11 条没学，必须抓得住。"""
        self._write_baseline(3369)
        b = self._brain(3576, learned=196)   # lag = 3380，增量 11
        st = probe_linkage(b, self._tmp)
        self.assertEqual(st.learning_lag, 3380)
        self.assertTrue(st.mismatch_detected, "相对基线有新增必须判失配")
        self.assertTrue(st.spin_risk, "增量 11 > 阈值 10 应触发空转风险")
        self.assertIn("新增", "".join(st.notes))

    def test_small_increment_below_threshold_is_mismatch_but_no_spin(self):
        self._write_baseline(3369)
        b = self._brain(3576, learned=204)   # lag = 3372 → 增量 3
        st = probe_linkage(b, self._tmp)
        self.assertTrue(st.mismatch_detected)
        self.assertFalse(st.spin_risk, "增量 3 未过阈值 %d" % LEARNING_LAG_SPIN_THRESHOLD)

    def test_lag_below_baseline_lowers_water_mark(self):
        """欠账被消化 → 基线降到新水位，且不计失配。"""
        self._write_baseline(3369)
        b = self._brain(3576, learned=1000)   # lag = 2576 < 3369
        st = probe_linkage(b, self._tmp)
        self.assertFalse(st.mismatch_detected)
        self.assertEqual(_load_lag_baseline(os.path.join(self._tmp, "predictions.json")), 2576,
                         "水位下降后基线应跟到新低，避免用旧高基线虚报")


class TestBaselineIsNeverAutoCreated(_Base):
    """安全底线：绝不自动锁基线，否则会吞掉首次真故障。"""

    def test_no_baseline_file_created_by_probe(self):
        b = self._brain(50)
        probe_linkage(b, self._tmp)     # lag=50，但没有基线文件
        path = _lag_baseline_path(b.pred_file)
        self.assertFalse(os.path.isfile(path),
                         "探测过程不得凭空创建基线文件（会把首次真故障当存量吃掉）")

    def test_corrupted_baseline_falls_back_to_no_baseline(self):
        """损坏的基线 → 按无基线处理：继续报警，而不是静默放行。"""
        path = _lag_baseline_path(os.path.join(self._tmp, "predictions.json"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ 这不是 json")
        b = self._brain(5)
        st = probe_linkage(b, self._tmp)
        self.assertTrue(st.mismatch_detected, "基线损坏必须退化到「继续报警」而非放行")


class TestFailureIsNeverSilent(_Base):
    """静默才是真敌人：读不出已复盘条数不得伪装成「滞后 0」（假健康）。"""

    def test_count_reviewed_exception_is_logged(self):
        """导入/解析失败必须留 WARNING，不能只 return 0。"""
        import types
        from unittest import mock
        import engines.self_iteration as si

        fake = types.ModuleType("utils.safe_json")

        def boom(*a, **k):
            raise RuntimeError("boom")

        fake.safe_load_json = boom
        with mock.patch.dict(sys.modules, {"utils.safe_json": fake}):
            with self.assertLogs("engines.self_iteration", level="WARNING") as cm:
                self.assertEqual(si._count_reviewed("whatever.json"), 0)
        self.assertTrue(any("按 0 处理" in m for m in cm.output),
                        "失败必须留下可检索的告警文本，不能静默")

    def test_cli_entry_fixes_syspath(self):
        """CLI 直跑时 sys.path[0] 是 engines/，必须显式补项目根。

        否则 `from utils.safe_json import` 失败被吞成 0，
        show-baseline 会报「当前滞后=0」这种彻头彻尾的假健康信号，
        拿它去 lock-baseline 更会把基线锁成 0（之后天天报警）。
        """
        path = os.path.join(ROOT, "engines", "self_iteration.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        i = src.index('if __name__ == "__main__":')
        self.assertIn("sys.path.insert", src[i:],
                      "CLI 入口必须补 sys.path，否则 utils 导入失败会被静默吞成 0")


class TestBaselineHelpers(_Base):
    def test_save_and_load_roundtrip(self):
        p = os.path.join(self._tmp, "predictions.json")
        self.assertIsNone(_load_lag_baseline(p))
        self.assertTrue(_save_lag_baseline(p, 3369))
        self.assertEqual(_load_lag_baseline(p), 3369)

    def test_baseline_path_under_log_dir(self):
        p = os.path.join("金水谣数据", "predictions.json")
        self.assertTrue(_lag_baseline_path(p).replace("\\", "/").endswith(
            "金水谣数据/log/learning_lag_baseline.json"))


if __name__ == "__main__":
    unittest.main()
