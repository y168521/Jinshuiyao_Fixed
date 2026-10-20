# -*- coding: utf-8 -*-
"""复核、总结必须各自独立限时，且「内层之和」必须小于「外层接口总闸」（JS-20261021-02）

【为什么要这条闸】
实测一次基金问答的耗时构成（修复前）：
    取数+分析 ~1.7s  /  总结 ~12~35s  /  复核 ~47s  /  每只基金AI推荐语 124s
而 POST /api/chat 的接口总闸当时只有 60s（server/config.py::_EXT_TIMEOUT["chat"]），
于是整次回复被掐断，前端只显示「请求失败，请稍后重试」。

更深一层的结构性错误：**内层单步超时（总结 90s）竟然比外层总闸（60s）还长**。
这等于内层永远轮不到「放弃 AI 总结、退回原始数据」的优雅降级——
用户失去的是「不完美但有数据」的结果，换来的只有一句「请求失败」。

【闸门含义】
1. 复核 `_AA_REVIEW_TIMEOUT` ≤ 15s（它只值一句话，不值 47s）；
2. 总结 `_AA_SUMMARY_TIMEOUT` ≤ 40s（超时退回原始数据表）；
3. 二者之和必须明显小于外层总闸，且留够余量，保证内层先降级、外层不硬掐。
"""
import core.ai.ai_agent as mod
from server.config import _EXT_TIMEOUT


class _AgentStub:
    """只提供复核函数需要的一个开关，避免拉起重型 Agent。"""

    _enable_review = True


def test_review_timeout_is_short():
    """复核限时必须很短——它只值一句话。"""
    assert mod._AA_REVIEW_TIMEOUT <= 15, (
        "复核限时 %ss 过长：实测复核要 47s，只为加一句「复核补充」，"
        "会连带把正常回复一起顶穿成「请求失败」" % mod._AA_REVIEW_TIMEOUT
    )


def test_summary_timeout_is_short():
    """总结限时必须短于接口总闸，否则轮不到优雅降级。"""
    assert mod._AA_SUMMARY_TIMEOUT <= 40, (
        "总结限时 %ss 过长：原值是 90s，比接口总闸还长，"
        "导致「放弃 AI 总结、退回原始数据」这条降级路径永远走不到"
        % mod._AA_SUMMARY_TIMEOUT
    )


def test_inner_timeouts_fit_outer_gate():
    """内层各步超时之和必须明显小于外层总闸，且留足余量。"""
    gate = _EXT_TIMEOUT["chat"]
    inner = mod._AA_SUMMARY_TIMEOUT + mod._AA_REVIEW_TIMEOUT
    assert inner < gate, (
        "内层超时之和 %ss ≥ 外层总闸 %ss：必然被外层硬掐，用户只能看到「请求失败」"
        % (inner, gate)
    )
    assert gate - inner >= 30, (
        "内层之和 %ss 距外层总闸 %ss 只剩 %ss 余量，网络稍慢就会重现超时"
        % (inner, gate, gate - inner)
    )


def test_review_passes_short_timeout_to_router(monkeypatch):
    """复核必须把短超时真正传给路由，不能沿用默认值。"""
    captured = {}

    def fake_route(task_type, system, user, **kwargs):
        captured["task"] = task_type
        captured["timeout"] = kwargs.get("timeout")
        return "OK", None, {"used": "free"}

    import core.ai.model_router as mr
    monkeypatch.setattr(mr, "route", fake_route)

    mod._aa_review_with_free(_AgentStub(), "fund", "基金要不要调整", "系统数据", "初稿内容")

    assert captured["task"] == "review"
    assert captured["timeout"] == mod._AA_REVIEW_TIMEOUT, (
        "复核没有把 _AA_REVIEW_TIMEOUT 传给路由（实际传了 %r），"
        "等于又退回默认超时" % (captured["timeout"],)
    )


def test_summary_passes_short_timeout_to_router(monkeypatch):
    """总结必须把短超时真正传给路由，不能沿用默认值。"""
    captured = {}

    def fake_route(task_type, system, user, **kwargs):
        captured["task"] = task_type
        captured["timeout"] = kwargs.get("timeout")
        return "总结内容", None, {"used": "free"}

    import core.ai.model_router as mr
    monkeypatch.setattr(mr, "route", fake_route)

    mod._aa_summarize_with_free(_AgentStub(), "fund", "基金要不要调整", "系统数据")

    assert captured["task"] == "data_summary"
    assert captured["timeout"] == mod._AA_SUMMARY_TIMEOUT, (
        "总结没有把 _AA_SUMMARY_TIMEOUT 传给路由（实际传了 %r），"
        "等于又退回默认超时" % (captured["timeout"],)
    )


def test_review_failure_is_silent(monkeypatch):
    """复核超时/失败必须静默跳过，不能影响主回复。"""
    def boom(*args, **kwargs):
        raise TimeoutError("模拟复核超时")

    import core.ai.model_router as mr
    monkeypatch.setattr(mr, "route", boom)

    assert mod._aa_review_with_free(_AgentStub(), "fund", "问题", "数据", "初稿") is None


class _NoPaidAI:
    """付费兜底不可用：模拟密钥失效/超额。"""

    is_available = False


class _AgentNoPaid(_AgentStub):
    _last_model_used = None
    _ai = _NoPaidAI()


def test_summary_gives_up_sooner_than_the_outer_gate(monkeypatch):
    """总结拿不到就返回 None —— 让主流程退回「原始数据表」而不是整单作废。

    这条是「优雅降级」的关键：用户宁可看到一份没有 AI 润色的基金评级表，
    也不要看到「请求失败，请稍后重试」。
    """
    import core.ai.model_router as mr
    monkeypatch.setattr(mr, "route", lambda *a, **k: (None, "TIMEOUT", {}))

    assert mod._aa_chat_summarize(_AgentNoPaid(), "fund", "基金要不要调整", "系统数据") is None, (
        "总结失败时必须返回 None，让 _aa_chat 退回原始数据；"
        "若这里抛异常或返回空串，整次问答就只剩一句「请求失败」"
    )
