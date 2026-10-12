# -*- coding: utf-8 -*-
"""AI 每日简报守卫单测（JS-20261012-16）

背景：预测耗时 336s 中 97.6% 花在 ensure_daily_brief 的 AI 调用，
且该简报失败时 generate 仍 success=True（对出号非必需）。
故加三道守卫：①总开关可关闭 ②硬超时上限 ③失败当天负面缓存不再重试。

守卫两失败模式：报错与静默，**静默才是真敌人**——故每条都断言「AI 被跳过/被限时」，
而不是只看返回值。
"""
import os
import time

import pytest

import config
import engines.brain_daily as bd


@pytest.fixture
def brain_tmp(tmp_path, monkeypatch):
    """把简报缓存目录指到临时目录，避免污染真实 金水谣数据/brain"""
    d = tmp_path / "brain"
    d.mkdir()
    monkeypatch.setattr(bd, "_BRAIN_DIR", str(d))
    monkeypatch.setattr(bd, "_today", lambda: "2026-10-12")
    return d


@pytest.fixture
def spy(monkeypatch):
    """替换 _build_brief，记录调用次数（默认立即返回 None）"""
    calls = {"n": 0}

    def _fake(lot, arr=None):
        calls["n"] += 1
        return calls.get("ret")

    monkeypatch.setattr(bd, "_build_brief", _fake)
    return calls


def _set_cfg(monkeypatch, enabled, timeout):
    monkeypatch.setattr(config, "LOTTERY_AI_BRIEF_ENABLED", enabled, raising=False)
    monkeypatch.setattr(config, "LOTTERY_AI_BRIEF_TIMEOUT_SEC", timeout, raising=False)


# ---------------------------------------------------------------- ① 总开关
def test_disabled_skips_ai_entirely(brain_tmp, spy, monkeypatch):
    """开关关闭：一次都不许调 AI（这是 336s→15s 的收益来源）"""
    _set_cfg(monkeypatch, False, 15)
    t0 = time.time()
    out = bd.ensure_daily_brief("大乐透", [{"period": 1, "nums": "01,02"}])
    assert out is None
    assert spy["n"] == 0, "开关关闭却仍调用了 AI"
    assert time.time() - t0 < 0.5, "开关关闭时不应有任何等待"


def test_enabled_invokes_ai(brain_tmp, spy, monkeypatch):
    """开关打开：应当调用一次 AI（反向验证，防止开关误伤正常路径）"""
    _set_cfg(monkeypatch, True, 15)
    spy["ret"] = {"hot": [1, 2], "kill": [3], "morph": "组六", "reason": "x"}
    out = bd.ensure_daily_brief("大乐透", [{"period": 1, "nums": "01,02"}])
    assert spy["n"] == 1
    assert out is not None and out["hot"] == [1, 2]


# ---------------------------------------------------------------- ② 硬超时
def test_slow_ai_is_capped_by_timeout(brain_tmp, monkeypatch):
    """慢 AI 必须被超时截断：不能无限等（实测曾达 124s）"""
    _set_cfg(monkeypatch, True, 1)

    def _slow(lot, arr=None):
        time.sleep(30)  # 远超超时
        return {"hot": [1]}

    monkeypatch.setattr(bd, "_build_brief", _slow)
    t0 = time.time()
    out = bd.ensure_daily_brief("大乐透", [{"period": 1, "nums": "01,02"}])
    dt = time.time() - t0
    assert out is None, "超时应降级为 None"
    assert dt < 5, f"耗时 {dt:.1f}s 未被 1s 超时截断"


# ---------------------------------------------------------------- ③ 负面缓存
def test_failure_is_negatively_cached(brain_tmp, spy, monkeypatch):
    """失败当天只付一次学费：第二次不得再调 AI（原实现会每次重付 123s）"""
    _set_cfg(monkeypatch, True, 15)
    spy["ret"] = None  # AI 失败
    bd.ensure_daily_brief("大乐透", [{"period": 1, "nums": "01,02"}])
    assert spy["n"] == 1
    out2 = bd.ensure_daily_brief("大乐透", [{"period": 1, "nums": "01,02"}])
    assert spy["n"] == 1, f"第二次仍调用 AI（负面缓存失效），共 {spy['n']} 次"
    assert out2 is None


def test_success_is_cached_and_reused(brain_tmp, spy, monkeypatch):
    """成功简报当天复用，不得重复调用"""
    _set_cfg(monkeypatch, True, 15)
    spy["ret"] = {"hot": [7], "kill": [8], "morph": "组三", "reason": "r"}
    bd.ensure_daily_brief("大乐透", [{"period": 1, "nums": "01,02"}])
    out2 = bd.ensure_daily_brief("大乐透", [{"period": 1, "nums": "01,02"}])
    assert spy["n"] == 1, "成功简报未命中缓存"
    assert out2["hot"] == [7]


def test_no_arr_never_calls_ai(brain_tmp, spy, monkeypatch):
    """arr 为空时不调 AI（保持原语义，防回归）"""
    _set_cfg(monkeypatch, True, 15)
    assert bd.ensure_daily_brief("大乐透", None) is None
    assert spy["n"] == 0
