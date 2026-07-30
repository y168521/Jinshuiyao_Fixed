# -*- coding: utf-8 -*-
"""数据三层隔离 · 恢复脚本 单元测试（T04）

覆盖：
  - 恢复前后 sha256 一致（latest 恢复到活层，内容还原）
  - 损坏快照 → [G] 告警 + RecoveryReport(ok=False)
  - 无恢复点 → RecoveryReport(ok=False)
  - list_points 返回按时间倒序的恢复点

约定：临时 live_root / replica_root；_FakeSC 注入避免抢真实全局锁；告警重定向临时文件。
"""
import os
import sys
import time
import threading

import pytest

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_scripts_dir = os.path.join(_project_root, "scripts")
for _p in (_project_root, _scripts_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from layer_registry import LayerRegistry                     # noqa: E402
from data_backup import BackupManager, _sanitize             # noqa: E402
from data_restore import RestoreManager, RecoveryReport      # noqa: E402


class _FakeSC:
    """内存版 session_coordinator（复刻全局锁语义）。"""

    def __init__(self):
        self._claim = None
        self._cv = threading.Condition()
        self.DEFAULT_HOLDER = "fake@0"

    def acquire(self, intent, holder="h@1", stale_secs=1800, wait_secs=0, poll=0.01):
        deadline = time.time() + max(0, wait_secs)
        with self._cv:
            while True:
                now = time.time()
                if self._claim is None:
                    self._claim = {"holder": holder, "intent": intent, "heartbeat": now}
                    return dict(self._claim)
                if self._claim["holder"] == holder:
                    self._claim["heartbeat"] = now
                    self._claim["intent"] = intent
                    return dict(self._claim)
                if (now - self._claim["heartbeat"]) > stale_secs:
                    self._claim = {"holder": holder, "intent": intent, "heartbeat": now}
                    return dict(self._claim)
                if now >= deadline:
                    raise RuntimeError("locked by %s" % self._claim["holder"])
                self._cv.wait(min(0.02, max(0, deadline - now)))

    def release(self, holder="h@1", force=False):
        with self._cv:
            if self._claim is None:
                return True
            if force or self._claim["holder"] == holder:
                self._claim = None
                self._cv.notify_all()
                return True
            return False

    def heartbeat(self, holder="h@1"):
        with self._cv:
            if self._claim and self._claim["holder"] == holder:
                self._claim["heartbeat"] = time.time()
                return True
            return False


@pytest.fixture(autouse=True)
def _alert_to_tmp(tmp_path):
    os.environ["ISOLATION_ALERT_LOG"] = str(tmp_path / "isolation_alerts.log")
    yield
    os.environ.pop("ISOLATION_ALERT_LOG", None)


@pytest.fixture
def env(tmp_path):
    live = tmp_path / "live"
    replica = tmp_path / "replica"
    live.mkdir()
    replica.mkdir()
    live_data = live / "金水谣数据"
    live_data.mkdir()
    (live_data / "brain_state.json").write_text("v1-original", encoding="utf-8")
    reg = LayerRegistry()
    bm = BackupManager(
        registry=reg, replica_root=str(replica),
        live_root=str(live), sc_module=_FakeSC(),
    )
    rm = RestoreManager(
        registry=reg, replica_root=str(replica),
        live_root=str(live), sc_module=_FakeSC(),
    )
    return live_data, replica, reg, bm, rm


def _rel():
    return "金水谣数据/brain_state.json"


# —— 恢复前后 sha256 一致 ——
def test_restore_latest_ok(env):
    live_data, _replica, _reg, bm, rm = env
    rel = _rel()
    # 先备份
    assert bm.snapshot(rel, "hourly") is True
    bm.build_manifest()
    # 模拟活层被改坏
    (live_data / "brain_state.json").write_text("CORRUPTED-v2", encoding="utf-8")
    rep = rm.restore(rel)
    assert isinstance(rep, RecoveryReport)
    assert rep.ok is True
    assert rep.message == "恢复成功"
    # 内容还原
    assert (live_data / "brain_state.json").read_text(encoding="utf-8") == "v1-original"
    assert rep.hash_before != rep.hash_after


# —— 损坏快照 → ok=False ——
def test_restore_corrupted_snapshot(env, tmp_path):
    _live_data, replica, _reg, bm, rm = env
    rel = _rel()
    bm.snapshot(rel, "hourly")
    bm.build_manifest()
    # 篡改快照内容（manifest 中 sha256 仍为原始值）→ 校验失败
    snap_dir = os.path.join(str(replica), "hourly", _sanitize(rel))
    snap_file = [f for f in os.listdir(snap_dir) if f.endswith(".bak")][0]
    with open(os.path.join(snap_dir, snap_file), "w", encoding="utf-8") as f:
        f.write("TAMPERED")
    rep = rm.restore(rel)
    assert rep.ok is False
    assert "校验失败" in rep.message
    # 失败须落 [G] 告警（fail-safe 缺口修复；回归防护）
    log = tmp_path / "isolation_alerts.log"
    assert log.exists()
    assert "[G]" in log.read_text(encoding="utf-8")


# —— 无恢复点 → ok=False ——
def test_restore_no_points(env, tmp_path):
    _live_data, _replica, _reg, _bm, rm = env
    rep = rm.restore(_rel())
    assert rep.ok is False
    assert "无可用的副本层恢复点" in rep.message
    # 失败须落 [G] 告警（回归防护）
    log = tmp_path / "isolation_alerts.log"
    assert log.exists()
    assert "[G]" in log.read_text(encoding="utf-8")


# —— list_points 倒序 ——
def test_list_points_sorted_desc(env):
    _live_data, _replica, _reg, bm, rm = env
    rel = _rel()
    bm.snapshot(rel, "hourly")
    time.sleep(0.001)               # 确保时间戳不同
    bm.snapshot(rel, "hourly")
    bm.build_manifest()
    pts = rm.list_points(rel)
    assert len(pts) == 2
    assert pts[0]["ts"] >= pts[1]["ts"]     # 倒序
    assert pts[0]["tier"] == "hourly"
    assert len(pts[0]["sha256"]) == 64


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
