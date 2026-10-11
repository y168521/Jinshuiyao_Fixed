"""收工门禁 · 仓库卫生闸 SKIP 不得伪装成 OK（JS-20261012-02）

背景（真实缺陷，由收工门禁日志暴露）：
    tools/repo_hygiene.py::check() 在「git 不可用 / 仓库为空」时返回
    `(True, "SKIP git 不可用或仓库为空，跳过仓库卫生检查")`。
    closeout_gate._check_repo_hygiene() 只看返回的 ok，于是打成 `[OK]`——
    实测 2026-10-11 06:02、2026-10-12 04:52 连续两天日志里都写着
    `[OK] 仓库卫生: SKIP git 不可用或仓库为空`，而当时仓库有 830 个跟踪文件。

    守卫有两种失败模式：报错和静默，静默才是真敌人。SKIP 就是静默——
    整闸根本没跑，日志却和「检查通过」一模一样。

覆盖:
  1. SKIP 消息 → 标签必须是 SKIP，绝不能是 OK
  2. 正常通过消息 → OK；检出违规 → FAIL（回归锁，别把判定改坏）
  3. AST 接线闸：_check_repo_hygiene 必须调用 _hygiene_tag（防被内联改回去）
"""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GATE = os.path.join(ROOT, "tools", "closeout_gate.py")


def _load_gate():
    import importlib.util
    spec = importlib.util.spec_from_file_location("closeout_gate_under_test", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestHygieneTagSkipsAreNotOk(unittest.TestCase):
    """核心：SKIP 必须显形。"""

    def test_skip_message_is_tagged_skip(self):
        mod = _load_gate()
        tag = mod._hygiene_tag(True, "SKIP git 不可用或仓库为空，跳过仓库卫生检查")
        self.assertEqual(tag, "SKIP", "SKIP 消息必须打 SKIP 标签，不能混进 OK")

    def test_skip_is_case_and_space_tolerant(self):
        mod = _load_gate()
        for msg in ("skip 仓库为空", "  SKIP  ", "Skip git 不可用"):
            self.assertEqual(mod._hygiene_tag(True, msg), "SKIP",
                             "SKIP 判定需容忍大小写与前后空白: %r" % msg)

    def test_skip_wins_even_when_ok_is_true(self):
        """ok=True 且消息是 SKIP → 仍必须是 SKIP（这正是原来的假绿形态）。"""
        mod = _load_gate()
        self.assertEqual(mod._hygiene_tag(True, "SKIP ..."), "SKIP")


class TestHygieneTagBackwardCompat(unittest.TestCase):
    """回归锁：非 SKIP 场景的判定不许被改坏。"""

    def test_clean_repo_is_ok(self):
        mod = _load_gate()
        self.assertEqual(mod._hygiene_tag(True, "无备份/临时类文件入仓（已扫 830 个跟踪文件）"), "OK")

    def test_violation_is_fail(self):
        mod = _load_gate()
        self.assertEqual(mod._hygiene_tag(False, "检出 3 个备份/临时类文件被 git 跟踪"), "FAIL")

    def test_non_string_message_does_not_crash(self):
        """异常防御：消息不是字符串（None/对象）时不得抛异常，按 ok 判定。"""
        mod = _load_gate()
        self.assertEqual(mod._hygiene_tag(True, None), "OK")
        self.assertEqual(mod._hygiene_tag(False, None), "FAIL")


class TestWiredIntoGate(unittest.TestCase):
    """AST 接线闸：标签判定必须真的被 _check_repo_hygiene 调用。"""

    def test_check_repo_hygiene_calls_hygiene_tag(self):
        with open(GATE, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_check_repo_hygiene":
                fn = node
                break
        self.assertIsNotNone(fn, "未找到 _check_repo_hygiene")
        called = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_hygiene_tag"
            for n in ast.walk(fn)
        )
        self.assertTrue(called, "_check_repo_hygiene 未调用 _hygiene_tag（SKIP 又会变回 [OK]）")

    def test_no_direct_ok_false_format_in_hygiene(self):
        """不得再出现 [{'OK' if ok else 'FAIL'}] 这类把 SKIP 吞掉的写法。"""
        with open(GATE, "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
        self.assertNotIn("[{'OK' if ok_rh else 'FAIL'}]", src,
                         "仓库卫生闸不得再用 ok 直接决定标签（会吞掉 SKIP）")


if __name__ == "__main__":
    unittest.main()
