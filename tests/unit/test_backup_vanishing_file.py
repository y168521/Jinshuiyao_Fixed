# -*- coding: utf-8 -*-
"""JS-20260925-07：备份的 TOCTOU 容错（单个文件消失不该让整个备份报废）

事故背景：2026-09-25 07:16:12 日志
    [健康备份] 全量备份失败: 创建备份失败: [WinError 2] 系统找不到指定的文件。
    ...predictions.json.bak.1
真因不是"备份功能坏了"，而是**并发竞态**：backup_all 先遍历收集文件列表，
再逐个写 zip；期间 data_maintenance 做 .bak 轮转让文件瞬间消失 →
`zf.write` 抛 OSError → 整个备份崩溃，且已打包的部分被删除（等于当天没有备份）。

跑法：
    python -m pytest tests/unit/test_backup_vanishing_file.py -q --capture=no
"""
import os
import sys
import zipfile

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.data_backup import backup_all, BACKUP_SKIP_WARN_COUNT  # noqa: E402


def _make_data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "keep.json").write_text('{"a": 1}', encoding="utf-8")
    (d / "keep2.json").write_text('{"b": 2}', encoding="utf-8")
    # 这个文件会在打包时被"并发轮转"掉
    (d / "ghost.json.bak.1").write_text('{"c": 3}', encoding="utf-8")
    return d


def test_backup_survives_vanishing_file(tmp_path, monkeypatch):
    """核心：列表里有、打包时消失 → 跳过它，备份本身必须成功"""
    d = _make_data_dir(tmp_path)

    real_write = zipfile.ZipFile.write

    def flaky_write(self, filename, arcname=None, *a, **kw):
        if str(filename).endswith("ghost.json.bak.1"):
            raise FileNotFoundError(2, "系统找不到指定的文件。", str(filename))
        return real_write(self, filename, arcname, *a, **kw)

    monkeypatch.setattr(zipfile.ZipFile, "write", flaky_write)

    out = backup_all(data_dir=str(d), output_dir=str(tmp_path / "out"))
    assert out and os.path.isfile(out)

    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert any(n.endswith("keep.json") for n in names), "好文件必须进包"
    assert any(n.endswith("keep2.json") for n in names), "好文件必须进包"
    assert not any("ghost" in n for n in names), "消失的文件不应在包里"


def test_backup_all_ok_when_nothing_vanishes(tmp_path):
    """正常场景回归：没有文件消失时行为不变"""
    d = _make_data_dir(tmp_path)
    out = backup_all(data_dir=str(d), output_dir=str(tmp_path / "out"))
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert any(n.endswith("ghost.json.bak.1") for n in names)


def test_skip_threshold_constant_is_positive():
    """跳过阈值必须为正——为 0 会让"全跳过还假装成功"变成静默失败"""
    assert BACKUP_SKIP_WARN_COUNT > 0


def test_missing_data_dir_still_raises(tmp_path):
    """容错不能过头：数据目录不存在仍必须报错（路径类失败禁静默）"""
    with pytest.raises(FileNotFoundError):
        backup_all(data_dir=str(tmp_path / "nope"), output_dir=str(tmp_path / "out"))
