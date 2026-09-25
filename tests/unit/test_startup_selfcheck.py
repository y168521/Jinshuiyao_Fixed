# -*- coding: utf-8 -*-
"""JS-20260925-09：启动自检的两个缺陷（假警 + 结果从不落盘）

背景：2026-09-25 服务启动日志「⚠️ 检测到 3 项异常，详见 金水谣数据/log/selfcheck.log」。
两处问题：
  ① 3 项异常全是**假警**——模块早已迁到 core/ai/、core/infra/ 子包，
     自检还按旧路径 core/ 找 → 功能明明可用却报错（假警会淹没真问题）。
  ② selfcheck.log **全仓没有任何代码在写**（只有 health.py 在读）
     → 用户被告知去看一个不存在的文件，异常内容永远看不到。

跑法：
    python -m pytest tests/unit/test_startup_selfcheck.py -q --capture=no
"""
import io
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import startup_selfcheck as SS  # noqa: E402


def test_no_false_alarm_on_all_core_modules():
    """核心模块必须全部通过——模块迁到子包后路径没跟，会造出假警"""
    report = SS.run_startup_check_safe()
    failed = {k: v.get("note") for k, v in report["departments"].items()
              if not v.get("passed", False)}
    assert failed == {}, "启动自检出现失败项（可能是模块路径又过时了）: %s" % failed
    assert report["all_passed"] is True


def test_module_paths_are_importable():
    """逐项确认自检列出的模块路径真的能导入（防止路径再漂移）"""
    for label, mod, path in [
        ("视频提取", "core.infra.video_extractor", None),
        ("内容提炼", "core.ai.content_refiner", None),
        ("AI服务", "core.ai.ai_service", None),
    ]:
        ok, note = SS._check_import(mod, path)
        assert ok, "%s(%s) 导入失败: %s" % (label, mod, note)


def test_report_is_appended_to_log(tmp_path, monkeypatch):
    """核心：自检结果必须落盘，否则「详见 selfcheck.log」指向一个不存在的文件"""
    log = tmp_path / "selfcheck.log"
    monkeypatch.setattr(SS, "SELFCHECK_LOG", str(log))
    SS.run_startup_check_safe()
    assert log.is_file(), "自检结果没有落盘 → 用户永远看不到异常内容"
    text = io.open(str(log), encoding="utf-8").read()
    assert "启动自检" in text
    # 失败项必须以 NG 前缀呈现，便于一眼看出
    assert "OK  视频提取" in text or "OK " in text


def test_log_write_failure_never_breaks_selfcheck(tmp_path, monkeypatch):
    """落盘失败不能让自检本身崩掉（自检在启动链路上，崩了会挡住服务）"""
    bad = tmp_path / "no_such_dir" / "selfcheck.log"
    monkeypatch.setattr(SS, "SELFCHECK_LOG", str(bad))
    # 目录不存在且父目录不可写时，os.makedirs 会抛；这里用文件冒充目录强制失败
    bad.parent.mkdir(parents=True, exist_ok=True)
    (bad.parent / "blocker").write_text("x", encoding="utf-8")
    monkeypatch.setattr(SS, "SELFCHECK_LOG", str(bad.parent / "blocker" / "x.log"))
    report = SS.run_startup_check_safe()
    assert isinstance(report, dict) and "all_passed" in report


def test_log_size_is_capped(tmp_path, monkeypatch):
    """日志必须有体积上限——无上限的追加等于定时炸弹"""
    assert SS.SELFCHECK_LOG_MAX_BYTES > 0
    log = tmp_path / "selfcheck.log"
    monkeypatch.setattr(SS, "SELFCHECK_LOG", str(log))
    monkeypatch.setattr(SS, "SELFCHECK_LOG_MAX_BYTES", 200)
    SS.run_startup_check_safe()
    SS.run_startup_check_safe()
    assert log.stat().st_size <= SS.SELFCHECK_LOG_MAX_BYTES + 4096
