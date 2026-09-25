# -*- coding: utf-8 -*-
"""JS-20260925-10 收工门禁第 10/11 闸 + 一致性第 ⑫ 项 单元测试

背景（同一条元规则缺了三次）：
  - JS-20260925-05：`tools/staleness_check.py` 抓到过真问题，但从没人调用 → 潜伏 46 天
  - JS-20260925-08：提示「详见 selfcheck.log」，但全仓没有代码在写它 → 告警指向空气
  - JS-20260925-09：新建目录被 `git status` 折叠成一行 → 20 个 .py 从未入库

三件事的根因是同一条：**坑写进了 MEMORY，却没变成检查**。本文件锁住新闸的核心语义：

  1. **能变红**：造出违规必须 FAIL（绿不算数，能红才算数）
  2. **不可用 ≠ 干净**：git 不可用 / 扫描异常一律 FAIL，绝不退化成放行
  3. **不假警**：散文提及不算执行引用；常量传播要能找到真正的写入者
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools import closeout_gate as cg  # noqa: E402
from tools import check_consistency as cc  # noqa: E402
import git_commit_gate as gcg  # noqa: E402


# ---------- _is_exec_reference：散文提及 ≠ 会被执行 ----------

def test_import_counts_as_exec_reference():
    """`from staleness_check import ASSETS` 是真实调用"""
    assert cg._is_exec_reference(
        "from staleness_check import ASSETS, _mtime  # noqa: E402",
        "staleness_check", "staleness_check.py", ".py")


def test_comment_is_not_exec_reference():
    """注释里的提及不算（这正是当年 staleness_check 的假象来源）"""
    assert not cg._is_exec_reference(
        "# 教训：staleness_check.py 早在 2026-08-02 就抓到过问题",
        "staleness_check", "staleness_check.py", ".py")


def test_prose_mention_is_not_exec_reference():
    """docstring 里的散文提及不算 —— 只出现名字不代表会被执行"""
    assert not cg._is_exec_reference(
        "项目里其实早就写好了 `tools/staleness_check.py`（2026-08-02），它首跑就抓到过",
        "staleness_check", "staleness_check.py", ".py")


def test_subprocess_call_counts_as_exec_reference():
    assert cg._is_exec_reference(
        '[sys.executable, "scripts/quality_gate.py", "--verify"],',
        "quality_gate", "quality_gate.py", ".py")


def test_ps1_line_counts_as_exec_reference():
    assert cg._is_exec_reference(
        'python.exe "tools\\health_watch.py"',
        "health_watch", "health_watch.py", ".ps1")


# ---------- 第 10 闸：未跟踪源码 ----------

def test_untracked_gate_blocks_when_untracked_exists(monkeypatch):
    monkeypatch.setattr(cg, "_git_exe", lambda: "git")
    monkeypatch.setattr(gcg, "untracked_sources", lambda porcelain=None: ["tools/新目录/a.py"])
    assert cg._check_untracked_sources() is False


def test_untracked_gate_passes_when_clean(monkeypatch):
    monkeypatch.setattr(cg, "_git_exe", lambda: "git")
    monkeypatch.setattr(gcg, "untracked_sources", lambda porcelain=None: [])
    assert cg._check_untracked_sources() is True


def test_untracked_gate_fails_when_git_unavailable(monkeypatch):
    """核心：git 不可用必须 FAIL。

    "拿不到状态"绝不能退化成"看起来干净"而放行，否则本闸是永远不响的警报器。
    """
    monkeypatch.setattr(cg, "_git_exe", lambda: None)
    assert cg._check_untracked_sources() is False


def test_untracked_gate_fails_when_check_raises(monkeypatch):
    def boom(porcelain=None):
        raise RuntimeError("git 炸了")

    monkeypatch.setattr(cg, "_git_exe", lambda: "git")
    monkeypatch.setattr(gcg, "untracked_sources", boom)
    assert cg._check_untracked_sources() is False


def test_untracked_sources_expands_directories():
    """`?? dir/` 折叠必须被展开 —— 这是第 10 闸存在的理由。

    同一棵目录树：折叠时只看到一行 `?? audio_toolkit/`，里面 5 个 .py 完全
    看不出来（历史上就这样漏掉 20 个源码文件）；展开后才抓得到。
    """
    folded = "?? audio_toolkit/\n?? data/run.log\n"
    expanded = "?? audio_toolkit/a.py\n?? audio_toolkit/b.py\n?? data/run.log\n"
    assert gcg.untracked_sources(folded) == []
    assert gcg.untracked_sources(expanded) == ["audio_toolkit/a.py", "audio_toolkit/b.py"]


def test_untracked_sources_ignores_non_source_and_pycache():
    """运行时产物与 __pycache__ 不算源码（告警只报能变绿的，噪音比没告警更糟）"""
    porcelain = "?? data/run.log\n?? notes.md\n?? __pycache__/x.py\n?? core/a.py\n"
    assert gcg.untracked_sources(porcelain) == ["core/a.py"]


# ---------- 第 11 闸：孤儿检查器 ----------

def test_orphan_gate_blocks_when_orphan_found(monkeypatch):
    monkeypatch.setattr(cg, "_scan_orphan_checkers",
                        lambda root=None: {"total": 3, "orphans": ["tools/x_check.py"], "failed": []})
    assert cg._check_orphan_checkers() is False


def test_orphan_gate_passes_when_all_wired(monkeypatch):
    monkeypatch.setattr(cg, "_scan_orphan_checkers",
                        lambda root=None: {"total": 3, "orphans": [], "failed": []})
    assert cg._check_orphan_checkers() is True


def test_orphan_gate_fails_when_scan_raises(monkeypatch):
    def boom(root=None):
        raise RuntimeError("扫描炸了")

    monkeypatch.setattr(cg, "_scan_orphan_checkers", boom)
    assert cg._check_orphan_checkers() is False


def test_scan_orphan_checkers_on_tmp_tree(tmp_path):
    """真·目录树扫描：被调用的不报，没人调用的报出来"""
    (tmp_path / "tools").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "core").mkdir()
    (tmp_path / "tools" / "wired_check.py").write_text("def run():\n    pass\n", encoding="utf-8")
    (tmp_path / "scripts" / "lonely_guard.py").write_text("def run():\n    pass\n", encoding="utf-8")
    (tmp_path / "core" / "biz.py").write_text(
        "from wired_check import run\n", encoding="utf-8")

    res = cg._scan_orphan_checkers(root=str(tmp_path))
    assert res["total"] == 2
    assert res["orphans"] == ["scripts/lonely_guard.py"]


def test_scan_orphan_checkers_ignores_prose_only_reference(tmp_path):
    """只有散文提及的检查器仍算孤儿（staleness_check 当年的形态）"""
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "stale_check.py").write_text("def run():\n    pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "背景：tools/stale_check.py 早就写好，但没人调用。\n", encoding="utf-8")

    res = cg._scan_orphan_checkers(root=str(tmp_path))
    assert res["orphans"] == ["tools/stale_check.py"]


# ---------- 第 ⑫ 项：告警落盘契约 ----------

def test_alert_sink_flags_air_alert(tmp_path, monkeypatch):
    """提示看一个没人写的文件 → 必须报出来"""
    src = tmp_path / "src"
    src.mkdir()
    (src / "alerter.py").write_text(
        'log("!!! 有异常，详见 金水谣数据/log/nobody_writes.log")\n', encoding="utf-8")
    monkeypatch.setattr(cc, "BASE_DIR", str(tmp_path))

    errors = cc.check_alert_sink_writers()
    assert any("nobody_writes.log" in e for e in errors)


def test_alert_sink_const_propagation_avoids_false_alarm(tmp_path, monkeypatch):
    """核心防假警：路径先赋给常量、再 open(常量,'a') 两段式，必须识别为有写入者。

    只比"同一行"会把已经修好的落盘逻辑判成没人写（假警比没告警更坏）。
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "alerter.py").write_text(
        'log("!!! 有异常，详见 金水谣数据/log/selfcheck.log")\n', encoding="utf-8")
    (src / "writer.py").write_text(
        'SELFCHECK_LOG = os.path.join(BASE_DIR, "金水谣数据", "log", "selfcheck.log")\n'
        '\n'
        'def _append(report):\n'
        '    with open(SELFCHECK_LOG, "a", encoding="utf-8") as f:\n'
        '        f.write(report)\n', encoding="utf-8")
    monkeypatch.setattr(cc, "BASE_DIR", str(tmp_path))

    errors = cc.check_alert_sink_writers()
    assert not [e for e in errors if "selfcheck.log" in e]


def test_alert_sink_ignores_prose_hints(tmp_path, monkeypatch):
    """「详见交接中心§六」这类散文提示不能当成文件路径"""
    src = tmp_path / "src"
    src.mkdir()
    (src / "x.py").write_text(
        "详见上方；详见交接中心§六-H\n", encoding="utf-8")
    monkeypatch.setattr(cc, "BASE_DIR", str(tmp_path))

    assert cc.check_alert_sink_writers() == []


def test_find_writers_direct_open(tmp_path):
    files = [("a.py", ['open("x.log", "a")'])]
    assert cc._find_writers("x.log", files) == {"a.py"}
    assert cc._find_writers("y.log", files) == set()
