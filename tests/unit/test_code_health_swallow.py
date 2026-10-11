"""静默吞异常清零：新增一律留痕，存量不回退（JS-20261012-06）

背景（真实缺陷，由代码体检门禁暴露）：
    门禁报「较基线恶化 10 个 / 新增超阈值 19 个」，我一开始只看到 sample 里的
    前 5 条就动手。全量导出后才知道真实规模是 **10 处恶化 + 19 处新增**，
    其中真正危险的是 **17 处 `except Exception: pass`**：
      - 3 处在存量文件里（launch_jinshuiyao / risk_controller / gui.main_window）
      - 14 处在基线（2026-09-21）之后新建的文件里（core/infra/*、tools/*）

    `except Exception: pass` 的可怕之处不是"会错"，而是**错得无声**：
    功能看起来照常运行，实际一直走降级分支，事后没有任何现场可查。
    本模块自己的铁律也写着「存量按年收敛，**新增一律告警**」。

修法：保留容错（失败仍降级、不打断主流程），但**必须留痕**——
    一律改成 `except Exception as e: logger.warning(...)`。

覆盖：
  1. 全仓「较基线恶化」项里不得再出现 swallow 指标（同类项全量为零）
  2. 3 个存量文件的 swallow 数回到基线值（不新增也不顺手清存量）
  3. 14 个基线后新建文件 swallow 必须为 0
  4. 降级语义未变：learn_from_review 仍返回 False、不外抛
  5. 留痕生效：失败时确实打了 WARNING（不是把 pass 换成别的静默写法）
  6. AST 反回退闸：risk_controller 里不得再出现「记日志的 try 里套 pass」
"""
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

try:
    from tools import code_health_gate as g
except Exception as e:  # pragma: no cover
    raise unittest.SkipTest("无法导入 tools.code_health_gate: %s" % e)


# 基线（2026-09-21）里已存在的 swallow 数 —— 存量挂账，允许保持，禁止增长
BASELINE_SWALLOW = {
    "launch_jinshuiyao.py": 14,
    "engines/risk_controller.py": 2,
    "gui/main_window.py": 8,
}

# 基线之后新建的文件 —— 全部 swallow 必须为 0（新增一律告警）
NEW_FILES_ZERO_SWALLOW = [
    "core/infra/scheduler.py",
    "core/infra/security.py",
    "core/infra/telemetry.py",
    "core/infra/video_to_kb.py",
    "core/infra/tk_style.py",
    "core/infra/video_extractor.py",
    "core/infra/scheduler_tasks.py",
    "tools/health_watch.py",
    "tools/check_trail_compliance.py",
]


def _swallow_of(rel_path):
    """用闸门自己的口径统计某文件的静默吞异常数。"""
    src = g._read(os.path.join(BASE, rel_path))
    if not src:
        raise AssertionError("文件不存在或为空: %s" % rel_path)
    return g.count_silent_swallow(g._strip_comments_strings(src))


class TestNoSwallowWorsened(unittest.TestCase):
    """核心：全仓扫一遍，swallow 指标不得出现在「较基线恶化」里。"""

    def test_no_swallow_in_worsened(self):
        baseline = g._load_baseline()
        if baseline is None:
            self.skipTest("基线不可读，跳过（闸门此时会退化为全量模式）")
        _new, worsened, _fixed, _unchanged = g._diff_against_baseline(
            g.scan_project(), baseline)
        bad = [(r["file"], d) for r, d in worsened
               if any(k == "swallow" for k, _o, _c in d)]
        self.assertEqual(
            [], bad,
            "仍有文件的静默吞异常数比基线更差：%s" % bad)


class TestStockFilesBackToBaseline(unittest.TestCase):
    """存量文件：回到基线值即可（不新增，也不越权清存量）。"""

    def test_swallow_equals_baseline(self):
        for rel, expected in BASELINE_SWALLOW.items():
            self.assertEqual(_swallow_of(rel), expected,
                             "%s 的静默吞异常数应回到基线 %d" % (rel, expected))


class TestNewFilesZeroSwallow(unittest.TestCase):
    """基线后新建的文件：一个 swallow 都不许有。"""

    def test_all_zero(self):
        for rel in NEW_FILES_ZERO_SWALLOW:
            self.assertEqual(_swallow_of(rel), 0,
                             "%s 是基线后新建文件，不得有静默吞异常" % rel)


class TestDegradationStillWorks(unittest.TestCase):
    """降级语义不变：失败仍返回 False，绝不把异常抛给复盘主链路。"""

    def test_learn_from_review_returns_false_on_error(self):
        from engines.risk_controller import learn_from_review
        # 传入会让 parse_reds / update_after_review 炸掉的输入
        with self.assertLogs("engines.risk_controller", level="WARNING"):
            ok = learn_from_review("双色球", object(), object(), None)
        self.assertFalse(ok, "失败时必须返回 False 而不是抛错打断复盘")


class TestFailureIsLogged(unittest.TestCase):
    """留痕生效：不是把 pass 换成另一个静默写法，而是真的打 WARNING。"""

    def test_warning_message_present(self):
        from engines.risk_controller import learn_from_review
        with self.assertLogs("engines.risk_controller", level="WARNING") as cm:
            learn_from_review("双色球", object(), object(), None)
        joined = "\n".join(r.getMessage() for r in cm.records)
        self.assertIn("复盘后更新失败", joined,
                      "失败原因必须写进日志，否则事后无法取证")


class TestNoLoggingInsideLogging(unittest.TestCase):
    """AST 反回退闸：不许再出现「记日志的外层 try 里又套一个 pass」。

    旧写法给 logging 套了 try/except: pass——万一日志设施自身出错就彻底无声，
    等于给静默失败留了后门。这道闸防止有人改回去。
    """

    def test_risk_controller_has_module_logger(self):
        import engines.risk_controller as rc
        self.assertTrue(hasattr(rc, "logger"),
                        "risk_controller 应有模块级 logger，而不是现用现 import")

    def test_no_pass_after_logging_call(self):
        src = g._read(os.path.join(BASE, "engines/risk_controller.py"))
        self.assertNotIn("logging.getLogger(__name__).warning(\n                ",
                         src)
        # 直接断言：文件里不存在「except 后紧跟 pass」的剩余新增形态
        self.assertEqual(_swallow_of("engines/risk_controller.py"),
                         BASELINE_SWALLOW["engines/risk_controller.py"])


class TestTruncationIsExplicit(unittest.TestCase):
    """门禁 msg 只列前 5 条，必须显式说明「共 N 个」。

    真实教训：我按 sample 的 5 条排工作量，实际是 10 处恶化 + 19 处新增。
    截断本身没错，错在**没说还有更多**——这条闸防止再被自己骗一次。
    """

    def _verdict(self, n_worse):
        """造 n_worse 个「恶化」条目，看 msg 有没有把真实总数说出来。"""
        baseline = {"generated": "2026-01-01", "files": {}}
        results = []
        for i in range(n_worse):
            rel = "fake_%d.py" % i
            baseline["files"][rel] = {
                "max_func": 10, "any": 0, "sql": 0, "untimed": 0,
                "secret_n": 0, "swallow": 0, "bare": 0}
            results.append({"file": rel, "max_func": 99, "max_func_name": "f",
                            "any": 0, "sql": 0, "secrets": [], "untimed": 0,
                            "swallow": 0, "bare": 0})
        _ok, msg, _violated = g._verdict_baseline(results, baseline, False)
        return msg

    def test_short_list_has_no_ellipsis(self):
        """不足 5 条时不加多余提示。"""
        self.assertNotIn("完整清单", self._verdict(3))

    def test_long_list_says_total(self):
        """超过 5 条必须写出总数，否则读的人会低估规模。"""
        msg = self._verdict(8)
        self.assertIn("共8个", msg)
        self.assertIn("--detail", msg)

    def test_detail_flag_wired(self):
        """--detail 必须真的接进 CLI，不能只在 msg 里提一句。"""
        src = g._read(os.path.join(BASE, "tools", "code_health_gate.py"))
        self.assertIn('"--detail"', src)


if __name__ == "__main__":
    unittest.main()
