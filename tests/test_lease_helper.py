# -*- coding: utf-8 -*-
"""数据三层隔离 · 写租约封装 单元测试（T02）

覆盖：
  - 受保护写：acquire → writer 执行 → release（成功路径）
  - fail-safe：writer 抛异常 → 返回 False、不向上抛、锁清理
  - 活层可写性：保险层 / 副本层 / 未授权 → False 并 [G] 告警；活层 → True
  - 占锁失败：被他者占用且超时 → 返回 False（降级告警）
  - 并发串行化：两「会话」（不同 holder）写同一共享文件，后者排队而非覆盖/互删

约定：用内存版 _FakeSC 注入 LeaseManager（复刻全局 CLAIM 语义），
不触碰真实 .workbuddy/session_claim.json，避免与并发 AI 抢锁。
所有告警重定向到临时文件（autouse fixture）。
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
from lease_helper import LeaseManager                      # noqa: E402


class _FakeSC:
    """内存版 session_coordinator，复刻 acquire/release/heartbeat 的全局锁语义（含等待）。"""

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
                is_mine = self._claim["holder"] == holder
                stale = (now - self._claim["heartbeat"]) > stale_secs
                if is_mine:
                    self._claim["heartbeat"] = now
                    self._claim["intent"] = intent
                    return dict(self._claim)
                if stale:                                   # 过期 → 抢锁（自愈）
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
    """所有告警重定向到临时文件，避免污染真实仓库日志。"""
    os.environ["ISOLATION_ALERT_LOG"] = str(tmp_path / "isolation_alerts.log")
    yield
    os.environ.pop("ISOLATION_ALERT_LOG", None)


@pytest.fixture
def reg():
    return LayerRegistry()


# —— 成功路径 ——
def test_write_protected_success(reg):
    sc = _FakeSC()
    lm = LeaseManager(reg, holder="sessA@1", sc_module=sc)
    written = {}

    def writer():
        written["x"] = True

    assert lm.write_protected("金水谣数据/brain_state.json", "写决策", writer) is True
    assert written.get("x") is True
    assert sc._claim is None            # 写后已释放


# —— fail-safe：writer 异常不向上抛 ——
def test_writer_exception_fail_safe(reg):
    sc = _FakeSC()
    lm = LeaseManager(reg, holder="sessA@1", sc_module=sc)

    def bad():
        raise ValueError("boom")

    result = lm.write_protected("金水谣数据/brain_state.json", "写决策", bad)
    assert result is False                 # 降级为 False
    assert sc._claim is None              # finally 中已释放


# —— 活层可写性断言 ——
def test_assert_live_writable(reg):
    lm = LeaseManager(reg)
    # 保险层：insurance/ 与 git 真源（.py）
    assert lm.assert_live_writable("金水谣数据/insurance/decisions.json") is False
    assert lm.assert_live_writable("scripts/layer_registry.py") is False
    # 副本层
    assert lm.assert_live_writable("金水谣数据/backups/hourly/x/y.bak") is False
    # 活层已知文件 / 活层前缀
    assert lm.assert_live_writable("金水谣数据/brain_state.json") is True
    assert lm.assert_live_writable("金水谣数据/lot_data/双色球.json") is True
    assert lm.assert_live_writable("knowledge/用户知识库/foo.md") is True


# —— 保险层写入触发 [G] 告警 ——
def test_insurance_write_alerts(reg, tmp_path):
    lm = LeaseManager(reg)
    assert lm.assert_live_writable("金水谣数据/insurance/x.json") is False
    log = tmp_path / "isolation_alerts.log"
    assert log.exists()
    assert "[G]" in log.read_text(encoding="utf-8")


# —— 占锁失败降级 ——
def test_acquire_failure_returns_false(reg):
    sc = _FakeSC()
    sc._claim = {"holder": "other@9", "intent": "外部占用", "heartbeat": time.time()}
    lm = LeaseManager(reg, holder="me@1", sc_module=sc)
    res = lm.acquire_for_write("金水谣数据/brain_state.json", "写决策", wait_secs=0)
    assert res is False                     # 被他者占用且零等待 → 降级


# —— write_protected 守卫保险层（复用 assert_live_writable）——
def test_write_protected_rejects_insurance(reg, tmp_path):
    sc = _FakeSC()
    lm = LeaseManager(reg, holder="qaB@1", sc_module=sc)
    target = tmp_path / "insurance_x.json"

    def bad_writer():
        target.write_text("x", encoding="utf-8")

    # 误把保险层路径传给 write_protected → 拒绝、不写入、落 [G]
    res = lm.write_protected("金水谣数据/insurance/x.json", "写保险层", bad_writer)
    assert res is False
    assert not target.exists()                 # 不应被真正写入
    log = tmp_path / "isolation_alerts.log"
    assert log.exists()
    assert "[G]" in log.read_text(encoding="utf-8")
    assert sc._claim is None                    # 未占锁


# —— 并发串行化：两会话写同文件，后者排队而非覆盖 ——
def test_two_sessions_serialize(reg):
    sc = _FakeSC()
    barrier = threading.Barrier(2)
    order = []
    lock = threading.Lock()

    def worker(name, holder):
        lm = LeaseManager(reg, holder=holder, sc_module=sc)

        def w():
            with lock:
                order.append(name)        # 临界区内严格先后，无交错
            time.sleep(0.05)

        barrier.wait()                      # 两线程~同时起步（锁外）
        lm.write_protected("金水谣数据/brain_state.json", "写决策", w)

    t1 = threading.Thread(target=worker, args=("A", "sessA@1"))
    t2 = threading.Thread(target=worker, args=("B", "sessB@2"))
    t1.start(); t2.start(); t1.join(); t2.join()

    # 二者最终都成功（B 等 A 释放后写入），且写入顺序严格先后（无并发互删）
    assert len(order) == 2
    assert order in (["A", "B"], ["B", "A"])
    assert sc._claim is None                # 全部释放


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
