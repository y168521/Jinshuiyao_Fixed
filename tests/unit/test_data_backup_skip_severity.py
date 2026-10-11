"""备份跳过定级：轮转副本降 WARNING，主数据被跳过才 ERROR（JS-20261012-05）

背景（真实缺陷，由启动日志暴露）：
    启动日志每天一条：
    `utils.data_backup ERROR: 跳过文件数 24 超过阈值 20，备份可能严重不完整`
    逐条核对后发现，被跳过的 24 个**全是 `.bak.N` 轮转副本**
    （predictions.json.bak.2、agent_memory/history.json.bak.0/1/2、
    lot_data/七乐彩.json.bak.0/1/2 …），主数据一个没丢。

    这个 ERROR 是常驻假警：并发清理/轮转让次级副本瞬间消失是**设计本意**，
    既修不好也不该修，它却天天喊「严重不完整」——
    常驻假警会让真正危险的那次（主文件被跳过）被习惯性忽略。

修法：按「跳过的是主数据还是轮转副本」定级，而不是只看条数。
    主数据被跳过 → ERROR（真危险）；仅轮转副本 → WARNING（附说明）。

覆盖：
  1. 只有 .bak.N 被跳过（哪怕 >20 个）→ 不得 ERROR
  2. 有主数据文件被跳过 → 必须 ERROR（真危险要响）
  3. 混合场景：只要有 1 个主文件 → ERROR
  4. 没有文件被跳过 → 不定级
  5. _is_rotated_copy 的识别范围
"""
import os
import unittest

try:
    from utils.data_backup import _skip_severity, _is_rotated_copy, BACKUP_SKIP_WARN_COUNT
except Exception as e:  # pragma: no cover
    raise unittest.SkipTest("无法导入 utils.data_backup: %s" % e)


ROTATED = [
    "金水谣数据/predictions.json.bak.2",
    "金水谣数据/agent_memory/history.json.bak.0",
    "金水谣数据/lot_data/七乐彩.json.bak.1",
]


def _many_rotated(n):
    return ["金水谣数据/lot_data/双色球.json.bak.%d" % i for i in range(n)]


class TestRotatedOnlyIsNotError(unittest.TestCase):
    """核心：轮转副本被跳过不得谎报「严重不完整」。"""

    def test_few_rotated_is_warning(self):
        level, msg = _skip_severity(ROTATED)
        self.assertEqual(level, "warning")
        self.assertIn("主数据完整", msg)

    def test_many_rotated_over_threshold_still_not_error(self):
        """超过阈值 20 也只 WARNING —— 这正是原来天天误报的场景。"""
        skipped = _many_rotated(BACKUP_SKIP_WARN_COUNT + 10)
        level, msg = _skip_severity(skipped)
        self.assertNotEqual(level, "error",
                            "被跳过的全是轮转副本，不得报 ERROR（常驻假警）")
        self.assertEqual(level, "warning")
        self.assertIn("轮转副本", msg)


class TestPrimarySkipIsError(unittest.TestCase):
    """真危险：主数据文件被跳过必须 ERROR。"""

    def test_primary_only_is_error(self):
        level, msg = _skip_severity(["金水谣数据/predictions.json"])
        self.assertEqual(level, "error")
        self.assertIn("严重不完整", msg)

    def test_mixed_primary_wins(self):
        """混合场景：只要有 1 个主文件就是 ERROR。"""
        level, msg = _skip_severity(
            ["金水谣数据/predictions.json"] + _many_rotated(30))
        self.assertEqual(level, "error")
        self.assertIn("严重不完整", msg)

    def test_primary_count_in_message(self):
        level, msg = _skip_severity(
            ["金水谣数据/predictions.json", "金水谣数据/brain_state.json"])
        self.assertEqual(level, "error")
        self.assertIn("2", msg)


class TestNoSkips(unittest.TestCase):
    def test_empty_is_none(self):
        level, msg = _skip_severity([])
        self.assertIsNone(level)
        self.assertIsNone(msg)


class TestRotatedCopyDetection(unittest.TestCase):
    def test_detects_various_forms(self):
        for name in ("a.json.bak", "a.json.bak.0", "a.json_bak", "a.orig",
                     "a.rej", "a.BASE.123.py", "a.LOCAL.1"):
            self.assertTrue(_is_rotated_copy(os.path.join("d", name)),
                            "应识别为轮转副本: %s" % name)

    def test_primary_files_not_detected(self):
        for name in ("predictions.json", "brain_state.json",
                     "lot_data/七乐彩.json", "risk_state.json"):
            self.assertFalse(_is_rotated_copy(os.path.join("d", name)),
                             "主数据不应被当成轮转副本: %s" % name)


class TestEndToEndBackupLogging(unittest.TestCase):
    """端到端：真跑一次 backup_all，看日志级别对不对。"""

    def _make_data_dir(self, n_rotated):
        import tempfile
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "predictions.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        for i in range(n_rotated):
            with open(os.path.join(tmp, "x.json.bak.%d" % i), "w", encoding="utf-8") as f:
                f.write("{}")
        return tmp

    def _run_backup(self, data_dir, fail_on):
        import tempfile
        import zipfile
        from unittest import mock
        from utils.data_backup import backup_all

        real_write = zipfile.ZipFile.write

        def fake_write(self, filename, arcname=None, *a, **k):
            if fail_on in str(filename):
                raise OSError(2, "系统找不到指定的文件")
            return None

        out = tempfile.mkdtemp()
        with mock.patch.object(zipfile.ZipFile, "write", fake_write):
            with self.assertLogs("utils.data_backup", level="WARNING") as cm:
                backup_all(data_dir=data_dir, output_dir=out)
        return cm.records

    def test_rotated_skips_log_no_error(self):
        """25 个轮转副本被跳过 → 日志里不得出现 ERROR。"""
        data_dir = self._make_data_dir(BACKUP_SKIP_WARN_COUNT + 5)
        records = self._run_backup(data_dir, fail_on=".bak")
        self.assertTrue(records, "应有跳过的告警记录")
        levels = {r.levelname for r in records}
        self.assertNotIn("ERROR", levels,
                         "轮转副本被跳过不得报 ERROR: %s" % [r.getMessage() for r in records])

    def test_primary_skip_logs_error(self):
        """主数据文件被跳过 → 必须 ERROR。"""
        data_dir = self._make_data_dir(3)
        records = self._run_backup(data_dir, fail_on="predictions.json")
        self.assertIn("ERROR", {r.levelname for r in records},
                      "主数据被跳过必须报 ERROR: %s" % [r.getMessage() for r in records])


if __name__ == "__main__":
    unittest.main()
