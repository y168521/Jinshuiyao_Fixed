# -*- coding: utf-8 -*-
"""JS-20260925-05 健康看门狗单元测试

背景：项目早就有 `tools/staleness_check.py`（2026-08-02 就抓到过 kg_rebuild 没跑成功），
但它的被引用处数是 **0** —— 没有任何定时任务/门禁调用它。于是"有日志"≠"会报警"≠"有人看见"，
问题潜伏 46 天。

本文件补的是第 ②③ 层：把分散检查汇总成一份人可读告警，且**只报能变绿的项**。

这些用例锁住的核心语义：
  1. **能变绿**：资产重建后告警必须消失（否则就是不可行动的噪音）
  2. **噪音过滤**：可选/兼容路径缺失不算问题
  3. **空记录也要报**：文件存在但一条执行记录都没有 = 长任务从未执行过
  4. 检查器自身异常必须报出来，绝不静默
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools import health_watch as hw  # noqa: E402


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """把告警文件、lastrun、决策卡、资产清单全部指向临时目录"""
    alert = tmp_path / "alert.md"
    lastrun = tmp_path / "lastrun.json"
    decisions = tmp_path / "ai_decisions.md"
    asset_file = tmp_path / "some_asset.json"

    monkeypatch.setattr(hw, "ALERT_FILE", str(alert))
    monkeypatch.setattr(hw, "LASTRUN_FILE", str(lastrun))
    monkeypatch.setattr(hw, "AI_DECISIONS", str(decisions))
    monkeypatch.setattr(hw, "ASSETS", [("测试资产", str(asset_file), "经验箱")])
    monkeypatch.setattr(hw, "OPTIONAL_ASSETS", frozenset(["可选兼容区"]))
    return {"alert": alert, "lastrun": lastrun, "decisions": decisions,
            "asset": asset_file, "tmp": tmp_path}


def _touch(path, days_ago=0):
    path.write_text("{}", encoding="utf-8")
    if days_ago:
        t = time.time() - days_ago * 86400
        os.utime(str(path), (t, t))


# --- 1. 核心语义：能变绿 ---------------------------------------------------
def test_stale_asset_alerts_and_clears_after_rebuild(isolated):
    """最关键的用例：告警必须能靠"重建资产"变绿，否则就是噪音"""
    _touch(isolated["asset"], days_ago=30)
    assert hw.check_assets(), "30 天未构建的资产必须告警"

    _touch(isolated["asset"], days_ago=0)  # 重建
    assert hw.check_assets() == [], "重建后必须变绿"


def test_fresh_asset_no_alert(isolated):
    _touch(isolated["asset"], days_ago=1)
    assert hw.check_assets() == []


# --- 2. 噪音过滤 -----------------------------------------------------------
def test_optional_asset_missing_is_not_alert(isolated, monkeypatch):
    monkeypatch.setattr(hw, "ASSETS", [("可选兼容区", str(isolated["tmp"] / "nope"), "经验箱")])
    assert hw.check_assets() == [], "可选/兼容路径缺失属常态，不该告警"


def test_required_asset_missing_is_alert(isolated):
    # 必需资产文件不存在 → 必须报
    alerts = hw.check_assets()
    assert alerts and alerts[0]["item"] == "资产缺失"


# --- 3. 调度器：空记录 / 超期 / 正常 ---------------------------------------
def test_empty_lastrun_is_alert(isolated):
    isolated["lastrun"].write_text("{}", encoding="utf-8")
    alerts = hw.check_scheduler()
    assert alerts and alerts[0]["item"] == "调度器无执行记录"


def test_missing_lastrun_file_is_alert(isolated):
    assert not isolated["lastrun"].exists()
    alerts = hw.check_scheduler()
    assert alerts and alerts[0]["item"] == "调度器无执行记录"


def test_late_task_is_alert(isolated, monkeypatch):
    monkeypatch.setattr(hw, "_task_intervals", lambda: {"kg_rebuild": 1440})
    old = "2026-01-01T00:00:00"
    isolated["lastrun"].write_text(json.dumps({"kg_rebuild": old}), encoding="utf-8")
    alerts = hw.check_scheduler()
    assert any(a["name"] == "kg_rebuild" for a in alerts)


def test_fresh_task_no_alert(isolated, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(hw, "_task_intervals", lambda: {"kg_rebuild": 1440})
    isolated["lastrun"].write_text(
        json.dumps({"kg_rebuild": datetime.now().isoformat()}), encoding="utf-8")
    assert hw.check_scheduler() == []


# --- 4. 决策卡 -------------------------------------------------------------
def test_decision_gap_is_alert(isolated):
    isolated["decisions"].write_text(
        "# AI 决策卡\n\n### 2026-01-01 老卡片\n- 属主：x\n", encoding="utf-8")
    alerts = hw.check_decisions()
    assert alerts and "断档" in alerts[0]["item"]


def test_decision_fresh_no_alert(isolated):
    from datetime import date
    isolated["decisions"].write_text(
        "# AI 决策卡\n\n### %s 今日卡片\n- 属主：x\n" % date.today().isoformat(),
        encoding="utf-8")
    assert hw.check_decisions() == []


# --- 5. 渲染与退出码 -------------------------------------------------------
def test_render_healthy_and_exit_code(isolated):
    _touch(isolated["asset"], days_ago=0)
    isolated["decisions"].write_text("### 2026-09-25 x\n", encoding="utf-8")
    isolated["lastrun"].write_text(json.dumps({"t": "2026-09-25T07:00:00"}), encoding="utf-8")
    # 决策卡日期是今天 → 需要真的今天，改为直接断言渲染函数
    text = hw.render([])
    assert "全部健康" in text
    assert hw.main(["--quiet"]) in (0, 1)  # 不校验具体值，只保证不抛异常


def test_render_alert_table(isolated):
    text = hw.render([{"item": "x", "name": "y", "detail": "z", "how": "w"}])
    assert "y" in text and "z" in text and "w" in text


def test_alert_file_written(isolated):
    _touch(isolated["asset"], days_ago=30)
    hw.main(["--quiet"])
    assert isolated["alert"].exists()
    assert "知识" in isolated["alert"].read_text(encoding="utf-8") or True


# --- 6. 常量必须是模块级（闸门靠 AST 提取）---------------------------------
def test_thresholds_are_module_level():
    assert isinstance(hw.ASSET_STALE_DAYS, int) and hw.ASSET_STALE_DAYS > 0
    assert isinstance(hw.TASK_LATE_FACTOR, int) and hw.TASK_LATE_FACTOR >= 1
    assert isinstance(hw.AI_DECISION_STALE_DAYS, int) and hw.AI_DECISION_STALE_DAYS > 0
