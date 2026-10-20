# -*- coding: utf-8 -*-
"""留痕「新鲜度」检查测试（JS-20261020-06）

背景（本轮要治的坑）：
    2026-10-20 07:23，自动同步把第一批改动直接打包提交（`d188cb0`），
    而留痕三件套一条没写——因为 `check_trail_compliance.py` 只检查
    「**当日**有没有任意登记」，当天已有 01/02 两条登记，所以它认为没问题。

    这就是「旧登记冒充新留痕」：改动是新的，记录是旧的，闸门看不出来。

修复思路：
    在原有「内容检查」之上加一道「新鲜度检查」——
    留痕文件的修改时间必须**不早于**本次改动文件的最新修改时间（允许 60s 宽限）。
    改了代码却不写留痕 ⇒ 留痕时间停在旧登记那一刻 ⇒ 被抓住。

reversal（撤销验证）见 TestReverseVerification：拆掉新鲜度判断后本文件必须转红。
"""
from __future__ import annotations

import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools import check_trail_compliance as ctc  # noqa: E402


def _write(path, text, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


TODAY = ctc.today_str()
TRAIL_TODAY = f"| JS-{TODAY.replace('-', '')}-01 | {TODAY} | 旧登记 |"


# ---------------------------------------------------------------------------
# 一、新鲜度关口：旧登记不许冒充新留痕
# ---------------------------------------------------------------------------
class TestTrailFreshness:
    def test_stale_trail_blocked(self, tmp_path, monkeypatch):
        """改动很新、留痕很旧 ⇒ 必须判 MISS（本轮要抓的核心场景）。"""
        monkeypatch.setattr(ctc, "BASE_DIR", str(tmp_path))
        now = time.time()
        # 留痕：两小时前写的当日登记
        _write(tmp_path / "AI协作交接中心.md", TRAIL_TODAY, mtime=now - 7200)
        # 源码：刚刚改的
        src = _write(tmp_path / "core" / "x.py", "print(1)\n", mtime=now)
        ok, msg = ctc.check_trail_file("交接中心", "AI协作交接中心.md",
                                       min_mtime=os.path.getmtime(src))
        assert ok is False, "旧登记冒充新留痕居然通过了（新鲜度关口没生效）"
        assert "早于本次改动" in msg

    def test_fresh_trail_passes(self, tmp_path, monkeypatch):
        """留痕比改动新 ⇒ 通过。"""
        monkeypatch.setattr(ctc, "BASE_DIR", str(tmp_path))
        now = time.time()
        src = _write(tmp_path / "core" / "x.py", "print(1)\n", mtime=now - 60)
        _write(tmp_path / "AI协作交接中心.md", TRAIL_TODAY, mtime=now)
        ok, msg = ctc.check_trail_file("交接中心", "AI协作交接中心.md",
                                       min_mtime=os.path.getmtime(src))
        assert ok is True, msg

    def test_grace_window(self, tmp_path, monkeypatch):
        """留痕比改动早 30 秒（宽限 60s 内）⇒ 仍算通过，避免文件系统抖动误报。"""
        monkeypatch.setattr(ctc, "BASE_DIR", str(tmp_path))
        now = time.time()
        src = _write(tmp_path / "core" / "x.py", "print(1)\n", mtime=now)
        _write(tmp_path / "AI协作交接中心.md", TRAIL_TODAY, mtime=now - 30)
        ok, msg = ctc.check_trail_file("交接中心", "AI协作交接中心.md",
                                       min_mtime=os.path.getmtime(src))
        assert ok is True, msg

    def test_beyond_grace_blocked(self, tmp_path, monkeypatch):
        """超出宽限（早 5 分钟）⇒ 拦住。"""
        monkeypatch.setattr(ctc, "BASE_DIR", str(tmp_path))
        now = time.time()
        src = _write(tmp_path / "core" / "x.py", "print(1)\n", mtime=now)
        _write(tmp_path / "AI协作交接中心.md", TRAIL_TODAY, mtime=now - 300)
        ok, msg = ctc.check_trail_file("交接中心", "AI协作交接中心.md",
                                       min_mtime=os.path.getmtime(src))
        assert ok is False
        assert "早于本次改动" in msg

    def test_missing_content_still_blocked(self, tmp_path, monkeypatch):
        """内容侧行为不变：没有当日登记照样 MISS（不能靠时间过关）。"""
        monkeypatch.setattr(ctc, "BASE_DIR", str(tmp_path))
        now = time.time()
        _write(tmp_path / "AI协作交接中心.md", "没有任何登记\n", mtime=now)
        ok, msg = ctc.check_trail_file("交接中心", "AI协作交接中心.md",
                                       min_mtime=now - 3600)
        assert ok is False
        assert "未找到" in msg

    def test_no_min_mtime_keeps_legacy(self, tmp_path, monkeypatch):
        """不传 min_mtime（旧调用方式）⇒ 只做内容检查，行为不变。"""
        monkeypatch.setattr(ctc, "BASE_DIR", str(tmp_path))
        now = time.time()
        _write(tmp_path / "AI协作交接中心.md", TRAIL_TODAY, mtime=now - 99999)
        ok, msg = ctc.check_trail_file("交接中心", "AI协作交接中心.md")
        assert ok is True, msg


# ---------------------------------------------------------------------------
# 二、接进主流程：源码改动要能推出 min_mtime
# ---------------------------------------------------------------------------
class TestMainWiring:
    def _setup_repo(self, tmp_path, monkeypatch, src_mtime, trail_mtime):
        monkeypatch.setattr(ctc, "BASE_DIR", str(tmp_path))
        for rel in ctc.TRAIL_FILES.values():
            _write(tmp_path / rel, TRAIL_TODAY, mtime=trail_mtime)
        _write(tmp_path / "core" / "x.py", "print(1)\n", mtime=src_mtime)
        monkeypatch.setattr(ctc, "get_staged_files", lambda: ["core/x.py"])

    def test_main_blocks_stale(self, tmp_path, monkeypatch, capsys):
        now = time.time()
        self._setup_repo(tmp_path, monkeypatch, src_mtime=now, trail_mtime=now - 7200)
        rc = ctc.main()
        out = capsys.readouterr().out
        assert rc == 1, f"应判缺留痕，实际 rc={rc}\n{out}"
        assert "早于本次改动" in out

    def test_main_passes_fresh(self, tmp_path, monkeypatch, capsys):
        now = time.time()
        self._setup_repo(tmp_path, monkeypatch, src_mtime=now - 60, trail_mtime=now)
        rc = ctc.main()
        out = capsys.readouterr().out
        assert rc == 0, f"应通过，实际 rc={rc}\n{out}"

    def test_main_ignores_missing_source_mtime(self, tmp_path, monkeypatch, capsys):
        """源码文件不存在（已被删）时不应崩，退回内容检查。"""
        monkeypatch.setattr(ctc, "BASE_DIR", str(tmp_path))
        now = time.time()
        for rel in ctc.TRAIL_FILES.values():
            _write(tmp_path / rel, TRAIL_TODAY, mtime=now)
        monkeypatch.setattr(ctc, "get_staged_files", lambda: ["core/gone.py"])
        rc = ctc.main()
        assert rc == 0


# ---------------------------------------------------------------------------
# 三、撤销验证：拆掉新鲜度判断 ⇒ 本文件必须转红
# ---------------------------------------------------------------------------
class TestReverseVerification:
    def test_removing_freshness_must_go_red(self, tmp_path, monkeypatch):
        """把 TRAIL_FRESHNESS_GRACE 置为无限大（等于关掉新鲜度关口）后，
        「旧登记冒充」这条断言必须变红——否则说明关口是假的。"""
        monkeypatch.setattr(ctc, "BASE_DIR", str(tmp_path))
        now = time.time()
        _write(tmp_path / "AI协作交接中心.md", TRAIL_TODAY, mtime=now - 7200)
        src = _write(tmp_path / "core" / "x.py", "print(1)\n", mtime=now)
        monkeypatch.setattr(ctc, "TRAIL_FRESHNESS_GRACE", 10 ** 9)
        ok, msg = ctc.check_trail_file("交接中心", "AI协作交接中心.md",
                                       min_mtime=os.path.getmtime(src))
        with pytest.raises(AssertionError):
            assert ok is False, "撤销验证失败：关口被拆了却依然拦得住（逻辑没走时间分支）"
