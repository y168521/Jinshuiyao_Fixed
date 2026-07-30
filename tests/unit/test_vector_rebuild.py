# -*- coding: utf-8 -*-
"""P3-4 单元测试：定时 reindex 的底层能力（knowledge.vector_index.rebuild_vector_index）
与调度器任务注册（core.scheduler 的 vector_index_rebuild）。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from unittest import mock

import knowledge.vector_index as vi_module
from knowledge.vector_index import rebuild_vector_index, get_vector_index


def _fake_cards():
    return [
        {"id": "c1", "title": "股票价值投资", "content": "长期持有优质资产",
         "tags": ["股票"], "domain": "stock"},
        {"id": "c2", "title": "足球赔率预测", "content": "分析欧赔亚盘",
         "tags": ["足球"], "domain": "football"},
        {"id": "c3", "title": "彩票冷热号分析", "content": "统计遗漏周期",
         "tags": ["彩票"], "domain": "lottery"},
    ]


def test_rebuild_writes_index_and_refreshes_global(tmp_path):
    """rebuild_vector_index 应构建索引、持久化、并刷新进程内缓存单例。"""
    path = os.path.join(str(tmp_path), "vector_index.json")
    saved_global = vi_module._INDEX
    vi_module._INDEX = None
    try:
        with mock.patch.object(vi_module, "_load_cards_from_kb", return_value=_fake_cards()):
            idx = rebuild_vector_index(path=path)
        # 1) 返回正确的 VectorIndex
        assert idx.doc_count == 3
        assert idx.built_at
        # 2) 索引文件已持久化
        assert os.path.isfile(path)
        # 3) 进程内缓存单例指向最新索引（get_vector_index 无需重建即可命中）
        cached = get_vector_index(force=False)
        assert cached is idx
        assert cached.doc_count == 3
    finally:
        vi_module._INDEX = saved_global


def test_rebuild_isolated_from_build_lock_no_deadlock(tmp_path):
    """rebuild_vector_index 调用 build_index_from_kb（内部持 _BUILD_LOCK），
    再在锁外更新全局 _INDEX —— 不应发生重入死锁。
    """
    path = os.path.join(str(tmp_path), "vector_index.json")
    saved_global = vi_module._INDEX
    vi_module._INDEX = None
    try:
        with mock.patch.object(vi_module, "_load_cards_from_kb", return_value=_fake_cards()):
            # 若死锁，这里会无限挂起（测试超时即失败）
            idx = rebuild_vector_index(path=path)
        assert idx is not None
        assert idx.doc_count == 3
    finally:
        vi_module._INDEX = saved_global


def test_scheduler_registers_vector_index_rebuild_task():
    """JinshuiyaoScheduler 应注册 vector_index_rebuild 任务（默认 24h）。"""
    try:
        from core.scheduler import JinshuiyaoScheduler
    except Exception as e:
        raise AssertionError(f"无法导入 JinshuiyaoScheduler: {e}") from e

    sched = JinshuiyaoScheduler()
    try:
        assert "vector_index_rebuild" in sched._tasks, "应注册 vector_index_rebuild 任务"
        task = sched._tasks["vector_index_rebuild"]
        assert task["enabled"] is True
        # 默认间隔 24 小时
        assert task["interval_minutes"] == 24 * 60
        # func 应指向 _task_vector_index_rebuild（无参静态方法）
        assert task["func"] is JinshuiyaoScheduler._task_vector_index_rebuild
    finally:
        sched.stop()


def test_scheduler_task_calls_rebuild_vector_index(tmp_path):
    """调度任务 body 应调用 rebuild_vector_index（无参、异常隔离）。"""
    try:
        from core.scheduler import JinshuiyaoScheduler
    except Exception as e:
        raise AssertionError(f"无法导入 JinshuiyaoScheduler: {e}") from e

    fake_idx = type("FakeIdx", (), {"doc_count": 17, "built_at": "2026-07-24 00:00:00"})()
    sched = JinshuiyaoScheduler()
    try:
        with mock.patch.object(vi_module, "rebuild_vector_index", return_value=fake_idx) as rb:
            # 直接调用静态任务体（异常应被隔离、不抛出）
            JinshuiyaoScheduler._task_vector_index_rebuild()
        rb.assert_called_once()
    finally:
        sched.stop()


def test_scheduler_task_rebuild_exception_isolated(tmp_path):
    """任务体内部异常不应上抛（调度器异常隔离要求）。"""
    try:
        from core.scheduler import JinshuiyaoScheduler
    except Exception as e:
        raise AssertionError(f"无法导入 JinshuiyaoScheduler: {e}") from e

    sched = JinshuiyaoScheduler()
    try:
        with mock.patch.object(vi_module, "rebuild_vector_index", side_effect=RuntimeError("boom")):
            # 不应抛出异常
            JinshuiyaoScheduler._task_vector_index_rebuild()
    finally:
        sched.stop()
