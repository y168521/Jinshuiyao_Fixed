# -*- coding: utf-8 -*-
"""GUI 预测列表必须走统一查询层（P0 / S-01 + S-02，JS-20261015-04）。

为什么要有这个闸
----------------
评审 §勘误 已实证：3636 条彩票预测**只有 GUI 能看**，而 GUI 的实现是
`for idx, p in enumerate(self.preds)` 一次性全量 insert Treeview
（gui/main_window.py:836）。数据量还在涨，这条路径会持续恶化。

本轮在 `utils/list_query.py` 建了统一查询层，并给 web 端补了
`GET /api/lottery/predictions`。若 GUI 仍各写一套筛选/分页逻辑，就会出现
「网页搜得到、桌面搜不到」的口径分裂 —— 这正是本闸要锁死的事。

锁死三条：
  1. GUI 刷新必须调用统一层的 apply_query（不得自己写筛选/分页）
  2. GUI 刷新不得再全量遍历 self.preds
  3. GUI 不得自带一份检索字段口径（必须复用 prediction 模块那一份）
"""
import ast
import io
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

MAIN_WINDOW = os.path.join(BASE, "gui", "main_window.py")


def _read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def _find_func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                return node
    return None


def _iter_calls(node):
    """产出 node 子树里所有 Call 的名字（Name 或 Attribute 的 attr）。"""
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        fn = sub.func
        if isinstance(fn, ast.Name):
            yield fn.id
        elif isinstance(fn, ast.Attribute):
            yield fn.attr


def _iter_attr_names(node):
    """产出 node 子树里所有 self.xxx 属性访问名。"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
            if sub.value.id == "self":
                yield sub.attr


class TestGuiPredQueryWiring(unittest.TestCase):
    """闸一：刷新函数必须调用统一查询层。"""

    def test_refresh_uses_shared_query_layer(self):
        src = _read(MAIN_WINDOW)
        tree = ast.parse(src)
        func = _find_func(tree, "refresh_pred_panel")
        self.assertIsNotNone(func, "gui/main_window.py 里找不到 refresh_pred_panel")

        calls = set(_iter_calls(func))
        self.assertTrue(
            {"apply_query"} & calls,
            "refresh_pred_panel 必须调用 utils.list_query 的 apply_query，"
            "以保证 GUI 与 web 端筛选/排序/分页口径一致（当前调用：%s）"
            % sorted(calls),
        )


class TestGuiNoFullScan(unittest.TestCase):
    """闸二：不得再把 self.preds 全量灌进 Treeview。"""

    def test_refresh_no_full_scan_of_preds(self):
        src = _read(MAIN_WINDOW)
        tree = ast.parse(src)
        func = _find_func(tree, "refresh_pred_panel")
        self.assertIsNotNone(func, "gui/main_window.py 里找不到 refresh_pred_panel")

        offenders = []
        for sub in ast.walk(func):
            if not isinstance(sub, ast.For):
                continue
            it = sub.iter
            # 命中 for ... in self.preds 或 for ... in enumerate(self.preds)
            if isinstance(it, ast.Attribute) and isinstance(it.value, ast.Name):
                if it.value.id == "self" and it.attr == "preds":
                    offenders.append(sub.lineno)
            elif isinstance(it, ast.Call) and isinstance(it.func, ast.Name):
                if it.func.id == "enumerate":
                    for a in it.args:
                        if (isinstance(a, ast.Attribute)
                                and isinstance(a.value, ast.Name)
                                and a.value.id == "self" and a.attr == "preds"):
                            offenders.append(sub.lineno)
        self.assertEqual(
            [], offenders,
            "refresh_pred_panel 仍在全量遍历 self.preds（行 %s）；"
            "应改为遍历 apply_query 返回的当前页数据" % offenders,
        )


class TestGuiReusesFieldSpec(unittest.TestCase):
    """闸三：检索字段口径只能有一份，GUI 不许自带。"""

    def test_gui_reuses_lottery_field_spec(self):
        src = _read(MAIN_WINDOW)
        self.assertIn(
            "LOTTERY_SEARCH_FIELDS", src,
            "GUI 必须复用 prediction.LOTTERY_SEARCH_FIELDS，"
            "不得自带一份检索字段列表（两套口径必然漂移）",
        )
        # 反向：GUI 里不许出现本地定义的检索字段元组
        self.assertNotIn(
            "GUI_LOTTERY_SEARCH_FIELDS", src,
            "发现 GUI 本地字段口径常量 GUI_LOTTERY_SEARCH_FIELDS；"
            "请改为复用 prediction 模块的唯一真源",
        )

    def test_prediction_module_exports_spec(self):
        """唯一真源本身必须存在，否则 GUI 的复用就是空引用。"""
        from server.handlers import prediction as P
        self.assertTrue(hasattr(P, "LOTTERY_SEARCH_FIELDS"))
        self.assertTrue(hasattr(P, "LOTTERY_NUMBER_FIELDS"))
        self.assertIn("lot", P.LOTTERY_SEARCH_FIELDS)
        self.assertIn("period", P.LOTTERY_NUMBER_FIELDS)
        # 口径守卫：date 绝不能进号码结构化比对，否则搜期号会假命中日期
        self.assertNotIn(
            "date", P.LOTTERY_NUMBER_FIELDS,
            "date 进入 number_fields 会导致搜期号 2026115 假命中日期 2026-10-11",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
