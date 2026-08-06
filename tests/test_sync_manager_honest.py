"""刀④（JS-20260806-10）契约欺骗修复测试。

验证 4 个「预留接口」不再对外谎称同步成功：
- 记录层：_record_sync 支持 reserved 标记；预留接口 success=False + reserved=True
- 调用层：4 个方法在线分支返回 True（仅表队列 ack，非同步成功），且 sync_history 中对应
  记录诚实标记为 reserved，绝不谎报 success=True
"""
import os
import tempfile

import pytest

from engines.sync_manager import SyncManager

# 方法名 -> 记录 operation 名
STUB_METHODS = [
    ("sync_analytics", "report_analytics", {}),
    ("sync_engine_params", "sync_engine_params", {"k": 1}),
    ("sync_model_updates", "sync_model_updates", None),
    ("report_health", "report_health", {"cpu": 1}),
]


@pytest.fixture
def sm():
    d = tempfile.mkdtemp()
    m = SyncManager(data_dir=d)
    # 强制在线，使方法走到「诚实标记」分支（否则会走离线入队 return False）
    m.is_online = True
    return m


def _last_for(history, op):
    for r in reversed(history):
        if r["operation"] == op:
            return r
    return None


def test_record_sync_reserved_field(sm):
    sm._record_sync("manual_op", False, "x", reserved=True)
    r = sm.sync_history[-1]
    assert r["operation"] == "manual_op"
    assert r["success"] is False
    assert r["reserved"] is True
    assert r["detail"] == "x"


def test_record_sync_default_not_reserved(sm):
    sm._record_sync("real_op", True, "ok")
    r = sm.sync_history[-1]
    assert r["reserved"] is False
    assert r["success"] is True


@pytest.mark.parametrize("meth,op,arg", STUB_METHODS)
def test_stub_returns_true_and_records_reserved(sm, meth, op, arg):
    ret = getattr(sm, meth)(arg) if arg is not None else getattr(sm, meth)()
    # 返回 True 仅表「队列已 ack / 已处理」，不是「同步成功」
    assert ret is True
    r = _last_for(sm.sync_history, op)
    assert r is not None, f"{op} 未写入 sync_history"
    # 诚实标记：绝不谎报成功
    assert r["success"] is False
    assert r["reserved"] is True
    assert "reserved" in r["detail"]


def test_no_false_success_across_stubs(sm):
    for meth, op, arg in STUB_METHODS:
        getattr(sm, meth)(arg) if arg is not None else getattr(sm, meth)()
    for _, op, _ in STUB_METHODS:
        r = _last_for(sm.sync_history, op)
        assert r["success"] is False, f"{op} 不应谎报 success=True"
        assert r["reserved"] is True
