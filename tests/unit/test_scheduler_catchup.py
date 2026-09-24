# -*- coding: utf-8 -*-
"""JS-20260925-04 调度器「跨重启补跑」单元测试

问题：所有 24 小时周期的定时任务（kg_rebuild / data_maintenance / memory_decay /
cross_link / kb_lint / vector_index_rebuild / health_backup / file_cleanup）
**从未执行过**。根因是服务实际连续运行时间只有几小时，而这些任务必须等满一个
完整间隔才首跑 —— 永远等不到。调度器每次都正常打印「已注册任务 kg_rebuild」，
看起来一切正常，实际一次都没跑（knowledge_graph.json 因此停在 2026-08-10 达 46 天）。

修法：把各任务「上次成功执行时间」落盘，注册时若距上次已超过一个间隔就按
run_now 处理（开机即补）。

这些用例锁住三个易被改坏的点：
  1. 从未执行过 → 必须补跑（不是"不知道就跳过"）
  2. **只在成功时落盘**（失败必须留待下次补跑，否则失败任务会被永久跳过）
  3. 持久化文件损坏/不可读 → 降级不崩，绝不影响调度器本身
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.infra import scheduler_tasks as st  # noqa: E402
from core.infra.scheduler_tasks import TaskScheduler  # noqa: E402


@pytest.fixture
def tmp_lastrun(tmp_path, monkeypatch):
    """把持久化文件指向临时目录，避免污染真实运行数据"""
    p = tmp_path / "scheduler_lastrun.json"
    monkeypatch.setattr(st, "_LASTRUN_FILE", str(p))
    return p


# --- 1. 从未执行过的任务必须补跑 -------------------------------------------
def test_never_run_task_is_due():
    assert st._due_for_catchup("some_brand_new_task", 1440) is True


def test_register_sets_run_now_when_due(tmp_lastrun):
    s = TaskScheduler()
    s.register("t24h", lambda: None, interval_minutes=1440, enabled=True, run_now=False)
    assert s._tasks["t24h"]["run_now"] is True


# --- 2. 刚执行过不该补跑（否则每次重启都狂跑）-------------------------------
def test_fresh_task_is_not_due(tmp_lastrun):
    tmp_lastrun.write_text(json.dumps({"t24h": st.datetime.now().isoformat()}),
                           encoding="utf-8")
    assert st._due_for_catchup("t24h", 1440) is False

    s = TaskScheduler()
    s.register("t24h", lambda: None, interval_minutes=1440, enabled=True, run_now=False)
    assert s._tasks["t24h"]["run_now"] is False


def test_stale_task_is_due_again(tmp_lastrun):
    """超过一个间隔后重新变成"该补跑" """
    old = st.datetime.fromtimestamp(time.time() - 48 * 3600).isoformat()
    tmp_lastrun.write_text(json.dumps({"t24h": old}), encoding="utf-8")
    assert st._due_for_catchup("t24h", 1440) is True


# --- 3. 成功才落盘，失败不落盘 ---------------------------------------------
def test_persist_on_success(tmp_lastrun):
    s = TaskScheduler()
    s.register("ok_task", lambda: "done", interval_minutes=1440)
    s._execute_task("ok_task")
    data = json.loads(tmp_lastrun.read_text(encoding="utf-8"))
    assert "ok_task" in data
    assert st._due_for_catchup("ok_task", 1440) is False


def test_no_persist_on_failure(tmp_lastrun):
    """失败的任务**不能**记账，否则它会被永久跳过——这是本次修复最关键的语义"""

    def boom():
        raise RuntimeError("模拟任务失败")

    s = TaskScheduler()
    s.register("bad_task", boom, interval_minutes=1440)
    s._execute_task("bad_task")
    assert not tmp_lastrun.exists() or "bad_task" not in json.loads(
        tmp_lastrun.read_text(encoding="utf-8"))
    # 下次仍应判定为"该补跑"
    assert st._due_for_catchup("bad_task", 1440) is True


# --- 4. 持久化损坏 → 降级不崩（绝不影响调度器）------------------------------
def test_corrupted_file_degrades_gracefully(tmp_lastrun):
    tmp_lastrun.write_text("{ this is not json", encoding="utf-8")
    assert st._load_lastrun() == {}
    # 且调度器照样能注册任务
    s = TaskScheduler()
    s.register("t", lambda: None, interval_minutes=60)
    assert "t" in s._tasks


def test_missing_file_degrades_gracefully(tmp_lastrun):
    assert not tmp_lastrun.exists()
    assert st._load_lastrun() == {}


# --- 5. 常量与文件位置 ------------------------------------------------------
def test_lastrun_file_under_log_dir():
    assert st._LASTRUN_FILE.endswith("scheduler_lastrun.json")
    assert "log" in st._LASTRUN_FILE.replace("\\", "/").split("/")
