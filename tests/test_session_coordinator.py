# -*- coding: utf-8 -*-
"""第二刀 JS-20260806-02 · 会话租约接线 + 非原子写改造 单元测试

覆盖：
  - PROTECTED_REL 补全（6 项：总索引 / ai_decisions / 经验收集箱 / 交接中心 / 契 / MEMORY）
  - session_coordinator 真实 acquire/release/过期接管（STALE_SECS + STALE_TAKEOVER_SECS），
    用临时 CLAIM 文件隔离，不触碰真实 .workbuddy/session_claim.json
  - shared_write 两条路径：
      锁成功 → 受保护写（atomic / safe_write_json embed_checksum=False）
      锁失败 → 降级无锁直写（**不丢数据**）

约定：告警统一重定向到临时文件（autouse fixture）；所有写锁用临时 CLAIM 或注入假 LM，
避免与并发 AI 抢真实全局锁。
"""
import os
import sys
import json
import time

import pytest

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_scripts_dir = os.path.join(_project_root, "scripts")
for _p in (_project_root, _scripts_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import session_coordinator as sc_mod                         # noqa: E402
import utils.shared_write as shared_write                    # noqa: E402


@pytest.fixture(autouse=True)
def _alert_to_tmp(tmp_path):
    """所有告警重定向到临时文件，避免污染真实仓库日志。"""
    os.environ["ISOLATION_ALERT_LOG"] = str(tmp_path / "isolation_alerts.log")
    yield
    os.environ.pop("ISOLATION_ALERT_LOG", None)


# ───────────────────────── PROTECTED_REL 补全 ─────────────────────────
def test_protected_rel_has_six_entries():
    rel = sc_mod.PROTECTED_REL
    assert isinstance(rel, list)
    assert len(rel) == 6


def test_protected_rel_includes_new_docs():
    rel = set(sc_mod.PROTECTED_REL)
    must = {
        "工作留痕总索引.md",
        "Jinshuiyao_Fixed/金水谣数据/log/ai_decisions.md",
        "Jinshuiyao_Fixed/金水谣数据/log/经验收集箱.md",   # 第二刀新增
        "AI协作交接中心.md",                                  # 第二刀新增
        "金水谣_契.md",                                       # 第二刀新增
        ".workbuddy/memory/MEMORY.md",
    }
    assert must <= rel


# ─────────────── 真实 acquire / release / 过期接管（临时 CLAIM）───────────────
@pytest.fixture
def isolated_claim(tmp_path, monkeypatch):
    """把全局 CLAIM 重定向到临时文件，并把 protected_files 做成空，隔离真实仓库。"""
    claim = tmp_path / "session_claim.json"
    monkeypatch.setattr(sc_mod, "CLAIM_PATH", claim)
    monkeypatch.setattr(sc_mod, "protected_files", lambda: [])
    # 清掉可能残留的真实 claim 引用（本进程内）
    if claim.exists():
        claim.unlink()
    yield claim
    if claim.exists():
        claim.unlink()


def test_acquire_release_real(isolated_claim):
    sc_mod._clear_claim()
    c = sc_mod.acquire("编辑总索引", holder="sessA@1", wait_secs=0)
    assert c["holder"] == "sessA@1"
    assert isolated_claim.exists()
    # 自己再 acquire → 续约（同一 holder）
    c2 = sc_mod.acquire("继续编辑", holder="sessA@1", wait_secs=0)
    assert c2["holder"] == "sessA@1"
    # 释放
    assert sc_mod.release(holder="sessA@1") is True
    assert not isolated_claim.exists()


def test_release_by_other_rejected(isolated_claim):
    sc_mod._clear_claim()
    sc_mod.acquire("x", holder="sessA@1", wait_secs=0)
    # 他者释放 → 拒绝（不清除）
    assert sc_mod.release(holder="sessB@2") is False
    assert isolated_claim.exists()


def test_stale_takeover_real(isolated_claim):
    """心跳超过 STALE_SECS（30min）→ 过期接管。"""
    old = {
        "holder": "otherhost@1",
        "pid": 1,
        "intent": "滞留",
        "heartbeat": time.time() - 2000,   # > 1800
    }
    isolated_claim.write_text(json.dumps(old), encoding="utf-8")
    c = sc_mod.acquire("接管", holder="me@1", stale_secs=sc_mod.STALE_SECS, wait_secs=0)
    assert c["holder"] == "me@1"           # 成功抢到


def test_fast_takeover_real(isolated_claim):
    """心跳 > STALE_TAKEOVER_SECS(600) 但 < STALE_SECS → 快速接管（异机 holder，排除死进程误判）。"""
    old = {
        "holder": "remotehost@12345",      # 异机 → 不触发 _pid_alive 死进程接管
        "pid": 1,
        "intent": "异常滞留",
        "heartbeat": time.time() - 700,    # > 600 且 < 1800
    }
    isolated_claim.write_text(json.dumps(old), encoding="utf-8")
    c = sc_mod.acquire("快速接管", holder="me@1", stale_secs=sc_mod.STALE_SECS, wait_secs=0)
    assert c["holder"] == "me@1"


def test_live_holder_blocks(isolated_claim):
    """新鲜持有者（他者、锁龄 < 接管阈值）→ 零等待 acquire 抛错（降级失败）。"""
    fresh = {
        "holder": "remotehost@12345",
        "pid": 1,
        "intent": "正常干活",
        "heartbeat": time.time() - 5,      # 新鲜
    }
    isolated_claim.write_text(json.dumps(fresh), encoding="utf-8")
    with pytest.raises(RuntimeError):
        sc_mod.acquire("抢", holder="me@1", stale_secs=sc_mod.STALE_SECS, wait_secs=0)


# ─────────────── shared_write：锁成功 / 锁失败直写 两条路径 ───────────────
class _FakeLM:
    """可注入的假 LeaseManager：acquired 控制占锁成败。"""

    def __init__(self, acquired):
        self._acquired = acquired
        self.released = False

    def acquire_for_write(self, rel_path, intent, wait_secs=15):
        return self._acquired

    def release(self):
        self.released = True
        return True


@pytest.fixture
def fake_lm_success(monkeypatch):
    monkeypatch.setattr(shared_write, "LeaseManager", lambda *a, **k: _FakeLM(True))


@pytest.fixture
def fake_lm_fail(monkeypatch):
    monkeypatch.setattr(shared_write, "LeaseManager", lambda *a, **k: _FakeLM(False))


def test_shared_write_text_lock_success(fake_lm_success, tmp_path):
    p = tmp_path / "doc.md"
    ok = shared_write.protected_write_text(str(p), "# hi\n", mode="w", intent="测试")
    assert ok is True
    assert p.read_text(encoding="utf-8") == "# hi\n"


def test_shared_write_text_lock_failure_direct_write(fake_lm_fail, tmp_path):
    """锁失败也**绝不丢数据**：降级无锁直写，文件照常落盘。"""
    p = tmp_path / "doc.md"
    ok = shared_write.protected_write_text(str(p), "# hi\n", mode="w", intent="测试")
    assert ok is True                          # 降级直写仍返回成功
    assert p.read_text(encoding="utf-8") == "# hi\n"   # 数据没丢


def test_shared_write_append_lock_success(fake_lm_success, tmp_path):
    p = tmp_path / "log.md"
    p.write_text("a\n", encoding="utf-8")
    shared_write.protected_write_text(str(p), "b\n", mode="a", intent="追加")
    assert p.read_text(encoding="utf-8") == "a\nb\n"


def test_shared_write_rmw_lock_success(fake_lm_success, tmp_path):
    p = tmp_path / "j.md"
    p.write_text("old\n", encoding="utf-8")
    shared_write.protected_rmw_text(str(p), lambda c: c.replace("old", "new"), intent="改写")
    assert p.read_text(encoding="utf-8") == "new\n"


def test_shared_write_rmw_lock_failure_direct(fake_lm_fail, tmp_path):
    p = tmp_path / "j.md"
    p.write_text("old\n", encoding="utf-8")
    ok = shared_write.protected_rmw_text(str(p), lambda c: c.replace("old", "new"), intent="改写")
    assert ok is True
    assert p.read_text(encoding="utf-8") == "new\n"   # 降级 RMW 仍生效


def test_shared_write_json_lock_success_no_checksum(fake_lm_success, tmp_path):
    p = tmp_path / "data.json"
    ok = shared_write.protected_write_json(str(p), {"k": "v"}, intent="写JSON")
    assert ok is True
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data == {"k": "v"}
    assert "_metadata" not in data          # 业务 JSON 不注入 checksum（契约）


def test_shared_write_json_lock_failure_direct(fake_lm_fail, tmp_path):
    p = tmp_path / "data.json"
    ok = shared_write.protected_write_json(str(p), {"k": "v"}, intent="写JSON")
    assert ok is True                       # 降级直写不丢数据
    assert json.loads(p.read_text(encoding="utf-8")) == {"k": "v"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
