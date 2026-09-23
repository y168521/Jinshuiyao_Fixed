# -*- coding: utf-8 -*-
"""守卫窗口「同日补跑」单元测试（JS-20260924-19）。

背景：daily@HH:MM 原实现只判定 `hour == HH`，窗口仅「整点那一小时」；
若那一小时没开机（例：10:30 才开机），当天该任务被永久跳过
（实测 09-07~09-18 连续 12 天无基金日报）。而模块 docstring 的规格
写的是「每天到 HH:MM **后**触发一次」——规格与实现不符，属真 bug。

本测试用冻结时间验证：错过整点窗口后，**同日**仍应触发一次（补跑）。
"""
import os
import sys
from datetime import datetime as _real_dt

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
from core.infra import automation_mirror as m  # noqa: E402


def _freeze(monkeypatch, hour, minute, day=24, month=9, year=2026):
    """把模块内的 datetime 冻结到指定时刻（子类化保证 isinstance 仍成立）。"""
    class _Frozen(_real_dt):
        @classmethod
        def now(cls, tz=None):
            return cls(year, month, day, hour, minute)
    monkeypatch.setattr(m, "datetime", _Frozen)


def test_daily_catchup_after_missed_hour(monkeypatch):
    """错过整点窗口：10:30 才开机，09:00 的日报仍应在当天补跑。"""
    _freeze(monkeypatch, 10, 30)
    assert m._guard_open("daily@09:00") is True


def test_daily_catchup_late_same_day(monkeypatch):
    """同日很晚（22:00）也应补跑，晚到总比整天没有强。"""
    _freeze(monkeypatch, 22, 0)
    assert m._guard_open("daily@09:00") is True


def test_daily_before_scheduled_not_open(monkeypatch):
    """未到点：08:30 不应触发 09:00 的任务（不能提前跑）。"""
    _freeze(monkeypatch, 8, 30)
    assert m._guard_open("daily@09:00") is False


def test_daily_next_day_not_open(monkeypatch):
    """次日凌晨 00:30 不应补跑昨天的 09:00 任务（跨天不补，避免日期错位）。"""
    _freeze(monkeypatch, 0, 30, day=25)
    assert m._guard_open("daily@09:00") is False


def test_daily_within_hour_still_open(monkeypatch):
    """窗口内（09:30）照旧触发。"""
    _freeze(monkeypatch, 9, 30)
    assert m._guard_open("daily@09:00") is True


def test_daily_minute_boundary(monkeypatch):
    """带分钟的任务：09:20 前不触发，09:20 后触发。"""
    _freeze(monkeypatch, 9, 10)
    assert m._guard_open("daily@09:20") is False
    _freeze(monkeypatch, 9, 25)
    assert m._guard_open("daily@09:20") is True


def test_weekly_guard_unaffected(monkeypatch):
    """周任务行为不变：周一 08:30 触发 weekly@MON@08:00。"""
    _freeze(monkeypatch, 8, 30, day=21)  # 2026-09-21 是周一
    assert m._guard_open("weekly@MON@08:00") is True


def test_weekly_other_weekday_not_open(monkeypatch):
    """周任务不变：周二不触发 Monday 的任务。"""
    _freeze(monkeypatch, 8, 30, day=22)  # 2026-09-22 是周二
    assert m._guard_open("weekly@MON@08:00") is False


def test_end_to_end_catchup_runs_exactly_once(monkeypatch):
    """端到端：走真实 _make_func 链路（守卫判定 + 周期去重），补跑只执行一次。

    脚本故意指向不存在的文件 → 只会走「脚本缺失」分支写日志，不真跑子进程。
    """
    calls = []
    monkeypatch.setattr(m, "_write_log", lambda *a, **k: calls.append(a))
    _freeze(monkeypatch, 10, 30)

    task = {"name": "test_catchup_task", "script": "scripts/__nonexistent__.py",
            "guard": "daily@09:00", "desc": "补跑测试"}
    m._state.pop("test_catchup_task", None)
    run = m._make_func(task)

    run()  # 错过 09:00 那一小时，10:30 补跑 → 应执行
    assert len(calls) == 1, "补跑未触发"

    run()  # 本周期已跑 → 不再重复执行
    assert len(calls) == 1, "同日重复触发了"
