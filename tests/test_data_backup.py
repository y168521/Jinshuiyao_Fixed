# -*- coding: utf-8 -*-
"""数据三层隔离 · 副本层备份 单元测试（T03）

覆盖：
  - 快照：活层文件 → 副本层 <tier>/<sanitized>/<ts>.bak
  - 滚动保留：hourly 保留 24 / daily 保留 7 / weekly 保留 4
  - 旧 *.json.bak.0~2 迁移进副本层且原文件保留兼容期（幂等）
  - manifest 含 sha256 / mtime / size
  - self_check 返回 bool（monkeypatch 守护函数，确定性）

约定：全部用临时 live_root / replica_root，不触碰真实数据；_FakeSC 注入避免抢真实全局锁；
告警重定向到临时文件。
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


class _FakeSC:
    """内存版 session_coordinator（复刻全局锁语义，含等待）。"""

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
    (live / "金水谣数据").mkdir()
    # 造活层文件
    (live / "金水谣数据" / "brain_state.json").write_text("bs", encoding="utf-8")
    (live / "金水谣数据" / "predictions.json").write_text("pd", encoding="utf-8")
    (live / "金水谣数据" / "correlation_matrix.json").write_text("cm", encoding="utf-8")
    reg = LayerRegistry()
    bm = BackupManager(
        registry=reg,
        replica_root=str(replica),
        live_root=str(live),
        sc_module=_FakeSC(),
    )
    return live, replica, reg, bm


def _count_snaps(replica, tier, sanitized):
    d = os.path.join(str(replica), tier, sanitized)
    if not os.path.isdir(d):
        return 0
    return sum(1 for f in os.listdir(d) if f.endswith(".bak"))


# —— 快照落盘 ——
def test_snapshot_creates_file(env):
    _live, replica, _reg, bm = env
    rel = "金水谣数据/brain_state.json"
    assert bm.snapshot(rel, "hourly") is True
    d = os.path.join(str(replica), "hourly", _sanitize(rel))
    assert os.path.isdir(d)
    snaps = [f for f in os.listdir(d) if f.endswith(".bak")]
    assert len(snaps) == 1
    # 内容一致
    with open(os.path.join(d, snaps[0]), "r", encoding="utf-8") as f:
        assert f.read() == "bs"


def test_snapshot_missing_source_returns_false(env):
    _live, _replica, _reg, bm = env
    assert bm.snapshot("金水谣数据/nope.json", "hourly") is False


# —— 滚动保留 ——
def test_hourly_retention_24(env):
    _live, replica, _reg, bm = env
    rel = "金水谣数据/brain_state.json"
    for _ in range(30):
        bm.snapshot(rel, "hourly")
    bm._prune("hourly")
    assert _count_snaps(replica, "hourly", _sanitize(rel)) == 24


def test_daily_retention_7(env):
    _live, replica, _reg, bm = env
    rel = "金水谣数据/predictions.json"
    for _ in range(10):
        bm.snapshot(rel, "daily")
    bm._prune("daily")
    assert _count_snaps(replica, "daily", _sanitize(rel)) == 7


def test_weekly_retention_4(env):
    _live, replica, _reg, bm = env
    rel = "金水谣数据/correlation_matrix.json"
    for _ in range(5):
        bm.snapshot(rel, "weekly")
    bm._prune("weekly")
    assert _count_snaps(replica, "weekly", _sanitize(rel)) == 4


# —— 旧 .bak 迁移（保留原文件，幂等）——
def test_migrate_legacy_bak(env):
    live, replica, _reg, bm = env
    # 造旧三代
    for i in (0, 1, 2):
        (live / "金水谣数据" / ("brain_state.json.bak.%d" % i)).write_text("legacy%d" % i, encoding="utf-8")
    count = bm.migrate_legacy_bak()
    assert count == 3
    # 原文件保留（兼容期）
    for i in (0, 1, 2):
        assert (live / "金水谣数据" / ("brain_state.json.bak.%d" % i)).exists()
    # 副本层 legacy 下存在
    leg = os.path.join(str(replica), "legacy", _sanitize("金水谣数据/brain_state.json"))
    assert os.path.isdir(leg)
    assert set(os.listdir(leg)) == {"brain_state.json.bak.0", "brain_state.json.bak.1", "brain_state.json.bak.2"}
    # 幂等：再跑一次不重复迁移
    assert bm.migrate_legacy_bak() == 0


# —— manifest 含 sha256/mtime/size ——
def test_build_manifest(env):
    _live, replica, _reg, bm = env
    rel = "金水谣数据/brain_state.json"
    bm.snapshot(rel, "hourly")
    bm.build_manifest()
    import json
    data = json.loads(open(bm.manifest_path, "r", encoding="utf-8").read())
    assert len(data["snapshots"]) == 1
    snap = data["snapshots"][0]
    assert snap["rel_path"] == rel
    assert snap["tier"] == "hourly"
    assert len(snap["sha256"]) == 64
    assert isinstance(snap["size"], int)
    assert snap["mtime"] > 0


# —— self_check 返回 bool（monkeypatch 守护）——
def test_self_check_returns_bool(env, monkeypatch):
    _live, _replica, _reg, bm = env
    import data_backup
    monkeypatch.setattr(data_backup, "check_jinshuiyao_data", lambda: True)
    assert bm.self_check() is True
    monkeypatch.setattr(data_backup, "check_jinshuiyao_data", lambda: False)
    assert bm.self_check() is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
