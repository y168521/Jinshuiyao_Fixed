# -*- coding: utf-8 -*-
"""导入副作用闸：import 任何模块都不得替换全局 sys.stdout / sys.stderr

背景（本轮实测定位）
------------------
全量 `pytest tests/unit` 崩在 `ValueError: I/O operation on closed file`，
且报 `no tests ran` —— 表面看像 pytest 自身故障，实际是一条**导入副作用链**：

    测试 from tools import health_watch
      → tools/health_watch.py:48  from staleness_check import ASSETS, _mtime
        → tools/staleness_check.py:17（模块级）
              sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

在 pytest 的 global capturing 环境下，`sys.stdout` 是 pytest 自己的捕获对象
（内部 EncodedFile 包 BytesIO）。模块级这行会：
  1. 用 pytest 捕获对象的 `.buffer` 新建一个 TextIOWrapper，替换全局 sys.stdout；
  2. 该包装器被 GC / 关闭时，**连带关掉底层 buffer**；
  3. pytest teardown `stop_global_capturing` → `pop_outerr_to_orig` → `readouterr`
     → `snap` → `self.tmpfile.seek(0)` ⇒ ValueError: I/O operation on closed file。

后果不只是崩溃：`no tests ran` 让**整个回归门静默失效** —— 一个测试都没跑，
却返回 EXIT=1，看上去像"测试挂了"，实际是"测试根本没跑"。

本文件把这些语义锁成常驻单测（跑在 pytest 里，天然进调用链，不触发孤儿闸）。
"""
import ast
import glob
import importlib
import io
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 这些模块会被其他模块 import（生产链路），是危害的直接载体
IMPORTED_BY_OTHERS = [
    "tools.staleness_check",
    "tools.health_watch",
]


def _fresh_import(mod_name):
    """强制干净导入，确保真的执行到模块级代码。"""
    sys.modules.pop(mod_name, None)
    return importlib.import_module(mod_name)


def test_import_does_not_replace_global_streams():
    """import 业务模块后，sys.stdout / sys.stderr 必须是同一个对象。"""
    before_out, before_err = sys.stdout, sys.stderr
    for mod_name in IMPORTED_BY_OTHERS:
        _fresh_import(mod_name)
        assert sys.stdout is before_out, (
            "%s 在 import 时替换了 sys.stdout —— 会关闭调用方（如 pytest capture）"
            "的底层 buffer，导致 teardown 崩在 ValueError: I/O operation on closed file"
            % mod_name
        )
        assert sys.stderr is before_err, "%s 在 import 时替换了 sys.stderr" % mod_name


def test_stdout_still_writable_after_import():
    """import 之后 stdout 必须还能正常写入（防止被替换成已关闭的流）。"""
    _fresh_import("tools.health_watch")
    sys.stdout.write("")
    sys.stdout.flush()


def _module_level_stream_assignments(path):
    """返回文件中「模块级」对 sys.stdout / sys.stderr 的赋值行号列表。

    只扫 tree.body（模块顶层），天然排除函数内与 `if __name__ == '__main__':` 块内 ——
    后者是安全的，因为只有直接运行脚本时才会执行。
    """
    with io.open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    hits = []
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for t in targets:
            if (
                isinstance(t, ast.Attribute)
                and isinstance(t.value, ast.Name)
                and t.value.id == "sys"
                and t.attr in ("stdout", "stderr")
            ):
                hits.append(node.lineno)
    return hits


def test_no_module_level_stream_reassignment_in_tools_and_scripts():
    """闸门：tools/ 与 scripts/ 下不得有模块级 sys.stdout/stderr 赋值。

    同类隐患一共 7 处（Windows 控制台 GBK 乱码的老 hack），其中
    tools/staleness_check.py 已被生产代码 import 并造成本次全量回归崩溃；
    其余 6 处虽暂未被 import，但只要有人 import 就会复现同一故障，
    因此一并禁掉，而不是等下一次踩坑。
    """
    offenders = []
    for pattern in ("tools/*.py", "scripts/*.py"):
        for path in sorted(glob.glob(os.path.join(REPO_ROOT, pattern))):
            for lineno in _module_level_stream_assignments(path):
                rel = os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
                offenders.append("%s:%d" % (rel, lineno))
    assert not offenders, (
        "以下位置在模块级替换了 sys.stdout/stderr，import 即污染调用方全局流"
        "（并可能关闭其底层 buffer）：\n  " + "\n  ".join(offenders)
    )
