"""本轮事项闸 · 申报新鲜度交叉校验（JS-20261012-03）

背景（真实缺陷，由收工门禁日志暴露）：
    tools/item_register.py::check_items() 只检查「清单里的项有没有闭环」，
    **从不检查「这轮干的事申报了没有」**。于是清单 22 项全部 done 就打 [OK]，
    但那些项全停在 2026-09-25，而 10-06 / 10-07 / 10-12 的工作一条都没申报——
    闸门看起来全绿，实际对当期工作**零覆盖**。这是典型的假绿。

    修法：把清单最新申报日期与**工作留痕总索引的最新 JS 编号日期**交叉比对。
    只要总索引有更新的留痕而清单没人申报 ⇒ 确定是漏申报 ⇒ FAIL。
    这样既不会「没干活却报警」，也不需要补历史欠账（只比对最新日期，只锁增量）。

覆盖：
  1. 总索引更新 → FAIL（核心，抓假绿）
  2. 日期一致 → OK；清单更新 → OK（别把正常态打红）
  3. 清单空但总索引有留痕 → FAIL
  4. 总索引解析不出编号 → FAIL（闸门无法工作必须显形，不能静默放行）
  5. 日期解析辅助函数的取值优先级与兜底
  6. 回归：open / 缺编号 仍优先 FAIL
  7. AST 接线闸：check_items 必须真的调用新鲜度校验
"""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MOD_PATH = os.path.join(ROOT, "tools", "item_register.py")


def _load():
    import importlib.util
    spec = importlib.util.spec_from_file_location("item_register_under_test", MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _with_index(tmp_dir, dates):
    """造一个只含指定 JS 日期的总索引，并把模块的候选路径指过去。"""
    mod = _load()
    path = os.path.join(tmp_dir, "工作留痕总索引.md")
    body = "\n".join("| JS-%s-%02d | 2026-01-01 | 主题 | AI | 改动 | 验证 |" % (d, i + 1)
                     for i, d in enumerate(dates))
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 索引\n\n" + body + "\n")
    mod.INDEX_CANDIDATES = (path,)
    return mod


def _items(pairs):
    """pairs: [(js_or_None, created_at)]"""
    out = []
    for i, (js, created) in enumerate(pairs, 1):
        out.append({"id": i, "title": "t%d" % i, "status": "done",
                    "js": js, "created_at": created, "closed_at": None})
    return out


class TestFreshnessCatchesStaleDeclaration(unittest.TestCase):
    """核心：总索引比清单新 ⇒ 这段工作没申报 ⇒ 必须 FAIL。"""

    def test_index_newer_is_fail(self):
        mod = _load()
        items = _items([("JS-20260925-10", "2026-09-25 09:00:00")])
        ok, msg, _, _ = _patched_check(mod, "20261012", items)
        self.assertFalse(ok, "总索引有更新的留痕却没申报，必须 FAIL")
        self.assertIn("2026-10-12", msg)
        self.assertIn("2026-09-25", msg)

    def test_message_mentions_zero_coverage(self):
        mod = _load()
        items = _items([("JS-20260925-10", "2026-09-25 09:00:00")])
        ok, msg, _, _ = _patched_check(mod, "20261012", items)
        self.assertIn("零覆盖", msg)


class TestFreshnessNoFalseRed(unittest.TestCase):
    """回归锁：正常态不许被打红。"""

    def test_same_day_is_ok(self):
        mod = _load()
        items = _items([("JS-20261012-01", "2026-10-12 05:00:00")])
        ok, msg, _, _ = _patched_check(mod, "20261012", items)
        self.assertTrue(ok, "同日申报不应报红: %s" % msg)

    def test_list_newer_than_index_is_ok(self):
        mod = _load()
        items = _items([("JS-20261012-01", "2026-10-12 05:00:00")])
        ok, msg, _, _ = _patched_check(mod, "20261011", items)
        self.assertTrue(ok, "清单比总索引新（已申报待登记）不应报红: %s" % msg)

    def test_all_closed_and_fresh_reports_count(self):
        mod = _load()
        items = _items([("JS-20261012-01", "2026-10-12 05:00:00"),
                        ("JS-20261012-02", "2026-10-12 05:00:00")])
        ok, msg, _, _ = _patched_check(mod, "20261012", items)
        self.assertTrue(ok)
        self.assertIn("全部闭环", msg)


class TestEmptyListAndUnparsableIndex(unittest.TestCase):
    """边界：清单空 / 总索引读不出 ⇒ 都不能静默放行。"""

    def test_empty_list_with_index_is_fail(self):
        mod = _load()
        ok, msg, _, _ = _patched_check(mod, "20261012", [])
        self.assertFalse(ok, "清单空但总索引已有留痕，必须 FAIL")
        self.assertIn("未申报", msg)

    def test_unparsable_index_is_fail(self):
        mod = _load()
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "工作留痕总索引.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# 索引\n\n没有任何编号\n")
            ok, msg, _, _ = _check_with(mod, path, [])
        self.assertFalse(ok, "总索引解析不出编号 ⇒ 闸门无法工作，必须 FAIL 而非静默")
        self.assertIn("无法校验", msg)


class TestDateHelpers(unittest.TestCase):
    """辅助函数的取值优先级与兜底。"""

    def test_latest_item_date_prefers_js(self):
        mod = _load()
        items = _items([("JS-20261012-01", "2026-09-01 00:00:00")])
        self.assertEqual(mod._latest_item_date(items), "2026-10-12")

    def test_latest_item_date_falls_back_to_created_at(self):
        mod = _load()
        items = _items([(None, "2026-10-07 06:00:00")])
        self.assertEqual(mod._latest_item_date(items), "2026-10-07")

    def test_latest_item_date_empty(self):
        mod = _load()
        self.assertIsNone(mod._latest_item_date([]))
        self.assertIsNone(mod._latest_item_date([{"id": 1, "js": None, "created_at": None}]))

    def test_date_diff_days(self):
        mod = _load()
        self.assertEqual(mod._date_diff_days("2026-10-12", "2026-09-25"), 17)
        self.assertIsNone(mod._date_diff_days("坏日期", "2026-09-25"))


class TestOpenAndNoJsStillWin(unittest.TestCase):
    """回归：未闭环 / 缺编号的判定优先于新鲜度，别被新逻辑盖掉。"""

    def test_open_item_is_fail(self):
        mod = _load()
        items = [{"id": 1, "title": "干了没留痕", "status": "open", "js": None,
                  "created_at": "2026-10-12 05:00:00"}]
        ok, msg, _, _ = _patched_check(mod, "20261012", items)
        self.assertFalse(ok)
        self.assertIn("未闭环", msg)

    def test_done_without_js_is_fail(self):
        mod = _load()
        items = [{"id": 1, "title": "留痕没编号", "status": "done", "js": None,
                  "created_at": "2026-10-12 05:00:00"}]
        ok, msg, _, _ = _patched_check(mod, "20261012", items)
        self.assertFalse(ok)
        self.assertIn("缺编号", msg)


class TestWiredIntoCheckItems(unittest.TestCase):
    """AST 接线闸：check_items 必须真的调用新鲜度校验。"""

    def test_check_items_calls_freshness_helpers(self):
        with open(MOD_PATH, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "check_items":
                fn = node
                break
        self.assertIsNotNone(fn)
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("_latest_index_js_date", called,
                      "check_items 未调用 _latest_index_js_date（新鲜度校验被绕过）")
        self.assertIn("_latest_item_date", called,
                      "check_items 未调用 _latest_item_date（新鲜度校验被绕过）")


def _patched_check(mod, index_date, items):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "工作留痕总索引.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("| JS-%s-01 | 2026-01-01 | 主题 | AI | 改动 | 验证 |\n" % index_date)
        return _check_with(mod, path, items)


def _check_with(mod, index_path, items):
    mod.INDEX_CANDIDATES = (index_path,)
    mod.load_items = lambda: items
    return mod.check_items()


if __name__ == "__main__":
    unittest.main()
