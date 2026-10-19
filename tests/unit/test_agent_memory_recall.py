# -*- coding: utf-8 -*-
"""AI 助手"记事本"接线测试（JS-20261020-05）

背景（第一批：让助手记得住事）：
    助手有个语义记事本（agent_vector_memory），每轮对话结束都会往里写一条，
    但**从来没有人读过**——`_aa_search_memory()` 实现了却零调用，
    `_aa_chat_general()` 只注入了「最近 3 轮 + 用户画像 + 知识库线索」。

    更糟的是实测发现：索引里 236 条记忆中 **235 条是"你好"**、1 条是探针 "probe"。
    每轮对话结束都把最后一轮原样入库，寒暄被反复存了 235 次；
    而 n-gram 短文本会产生虚高相似度（实测查"帮我看看双色球"，top5 全是"你好"）。
    ⇒ 这就是"记事本写了却没人敢翻"的真实原因：翻了只会注入噪声。

    所以本批不只是"接线"，必须同时做两件事：
      入库侧止损：寒暄 / 过短 / 近期重复 不写入
      召回侧过滤：短正文 + 低相似度 不召回
    另：`_aa_chat_general` 的 system prompt 补入【沟通约定】
    （用户不懂技术，只描述现象 ⇒ 先大白话说原因 + 给操作步骤，不抛选项）。

reversal（撤销验证）见 TestReverseVerification：破坏过滤后本文件必须转红。
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.ai import ai_agent  # noqa: E402
from core.ai.agent_vector_memory import (  # noqa: E402
    VECTOR_MEM_DEDUP_WINDOW,
    VECTOR_MEM_MIN_SCORE,
    VECTOR_MEM_MIN_TEXT_LEN,
    VectorMemory,
    _is_low_value,
)


def _mk(tmp_path):
    """造一个只指向临时目录的记事本，绝不碰真实记忆库。"""
    return VectorMemory(str(tmp_path / "agent_memory"))


def _emb(text):
    """真实的 128 维向量（手写的低维假向量会和 128 维查询对不上）。"""
    from core.ai.agent_vector_memory import _compute_embedding
    return _compute_embedding(text).tolist()


def _entry(text, summary="答", emb_text=None):
    return {
        "text": text, "summary": summary, "tag": "", "source": "user_history",
        "embedding": _emb(emb_text or text),
        "timestamp": "2026-10-01T00:00:00",
    }


def _orthogonal_entry(text):
    """128 维里只有第 0 维非零 ⇒ 与绝大多数查询的点积接近 0（模拟"完全不相关"）。"""
    vec = [0.0] * 128
    vec[0] = 1.0
    return {
        "text": text, "summary": "答", "tag": "", "source": "user_history",
        "embedding": vec, "timestamp": "2026-10-01T00:00:00",
    }


class _FakeAgent:
    """只带记事本接口的假助手，避免拉起真实 agent（会联网/读域配置）。"""

    def __init__(self, vm):
        self._vector_memory = vm
        self._history = []

    def _get_vector_memory(self):
        return self._vector_memory


# ---------------------------------------------------------------------------
# 一、入库侧：寒暄/过短/重复 不配进记忆库
# ---------------------------------------------------------------------------
class TestStoreFilter:
    def test_greeting_not_stored(self, tmp_path):
        vm = _mk(tmp_path)
        for g in ("你好", "在吗", "谢谢", "再见", "ok", "测试"):
            assert vm.store(g, summary="…") is False, g
        assert vm.count() == 0

    def test_too_short_not_stored(self, tmp_path):
        vm = _mk(tmp_path)
        assert vm.store("嗯", summary="…") is False
        assert vm.store("好的", summary="…") is False
        assert vm.count() == 0

    def test_real_question_stored(self, tmp_path):
        vm = _mk(tmp_path)
        assert vm.store("我下周三要出差去上海", summary="记下了") is True
        assert vm.count() == 1

    def test_recent_duplicate_not_stored(self, tmp_path):
        vm = _mk(tmp_path)
        q = "我下周三要出差去上海"
        assert vm.store(q, summary="第一次") is True
        assert vm.store(q, summary="第二次") is False
        assert vm.store(q + " ", summary="第三次（带空格也算重复）") is False
        assert vm.count() == 1

    def test_duplicate_window_allows_later_reask(self, tmp_path):
        """窗口外的相同问题允许再存一次（用户可能真的又问了一遍）。"""
        vm = _mk(tmp_path)
        q = "明天要开会记得提醒我"
        assert vm.store(q) is True
        for i in range(VECTOR_MEM_DEDUP_WINDOW):
            vm.store(f"第{i}个不相关的问题，用来把窗口挤过去")
        assert vm.store(q) is True

    def test_low_value_table(self):
        assert _is_low_value("你好") is True
        assert _is_low_value("  在吗  ") is True
        assert _is_low_value("嗯") is True
        assert _is_low_value("") is True
        assert _is_low_value("我下周三要出差去上海") is False


# ---------------------------------------------------------------------------
# 二、召回侧：短正文 + 低相似度 不召回
# ---------------------------------------------------------------------------
class TestSearchFilter:
    def test_short_text_filtered(self, tmp_path):
        """历史遗留的 235 条"你好"必须被挡在门外（相似度满分也要挡）。"""
        vm = _mk(tmp_path)
        vm._entries = [_entry("你好", summary="你好！我是金水谣AI助手")]
        assert vm.search("你好", top_k=5) == []

    def test_low_score_filtered(self, tmp_path):
        vm = _mk(tmp_path)
        vm._entries = [_orthogonal_entry("一个足够长的、与查询无关的问题内容")]
        assert vm.search("基金收益怎么样", top_k=5,
                         min_score=VECTOR_MEM_MIN_SCORE) == []

    def test_min_score_zero_keeps_legacy_behavior(self, tmp_path):
        """显式传 0 = 关掉分数过滤，保证既有调用方行为不变。"""
        vm = _mk(tmp_path)
        vm._entries = [_orthogonal_entry("一个足够长的、与查询无关的问题内容")]
        got = vm.search("基金收益怎么样", top_k=5,
                        min_score=0.0, min_text_len=0)
        assert len(got) == 1

    def test_real_memory_recalled(self, tmp_path):
        vm = _mk(tmp_path)
        q = "我下周三要出差去上海，记得提醒我带充电器"
        vm.store(q, summary="好的，会提醒你带充电器")
        got = vm.search("我出差要带什么", top_k=3)
        assert got and got[0]["text"] == q


# ---------------------------------------------------------------------------
# 三、接线：_aa_search_memory 真的能被调用并产出可用文本
# ---------------------------------------------------------------------------
class TestSearchMemoryWired:
    def test_empty_when_only_greetings(self, tmp_path):
        """库里只有寒暄时必须返回空串——否则等于把噪声注入回答。"""
        vm = _mk(tmp_path)
        vm._entries = [_entry("你好", summary="欢迎语")]
        assert ai_agent._aa_search_memory(_FakeAgent(vm), "你好") == ""

    def test_returns_readable_text(self, tmp_path):
        vm = _mk(tmp_path)
        q = "我下周三要出差去上海"
        vm.store(q, summary="记下了，会提醒你")
        text = ai_agent._aa_search_memory(_FakeAgent(vm), "我要去哪儿出差")
        assert "用户问过" in text
        assert q in text
        assert "记下了" in text

    def test_no_vector_memory_returns_empty(self):
        class _NoMem:
            def _get_vector_memory(self):
                return None
        assert ai_agent._aa_search_memory(_NoMem(), "任意问题") == ""


# ---------------------------------------------------------------------------
# 四、_aa_chat_general：system prompt 必须带上【沟通约定】和历史记忆
# ---------------------------------------------------------------------------
class TestChatGeneralPrompt:
    def _run(self, tmp_path, monkeypatch, vm, user_input):
        captured = {}

        def _fake_free(self, system_prompt, user_prompt, max_tokens=800):
            captured["system"] = system_prompt
            return "（测试回答）"

        monkeypatch.setattr(ai_agent, "_aa_chat_free", _fake_free)
        monkeypatch.setattr(ai_agent, "_aa_get_memories", lambda self, limit=15: [])
        monkeypatch.setattr("core.infra.knowledge_gateway.summarize",
                            lambda *a, **k: "")
        agent = _FakeAgent(vm)
        reply = ai_agent._aa_chat_general(agent, user_input)
        assert reply == "（测试回答）"
        return captured["system"]

    def test_communication_contract_present(self, tmp_path, monkeypatch):
        vm = _mk(tmp_path)
        system = self._run(tmp_path, monkeypatch, vm, "帮我看看双色球")
        assert "【沟通约定】" in system
        assert "大白话" in system
        assert "不要罗列一堆选项" in system

    def test_memory_injected_when_relevant(self, tmp_path, monkeypatch):
        vm = _mk(tmp_path)
        vm.store("我下周三要出差去上海", summary="记下了，会提醒你")
        system = self._run(tmp_path, monkeypatch, vm, "我出差要带什么")
        assert "以前和这个用户聊过" in system
        assert "我下周三要出差去上海" in system

    def test_no_memory_section_when_irrelevant(self, tmp_path, monkeypatch):
        """没有相关记忆时不能硬塞一段空壳，免得模型瞎联想。"""
        vm = _mk(tmp_path)
        vm.store("我下周三要出差去上海", summary="记下了")
        system = self._run(tmp_path, monkeypatch, vm, "今天星期几")
        assert "以前和这个用户聊过" not in system


# ---------------------------------------------------------------------------
# 五、撤销验证：破坏过滤 ⇒ 本文件必须转红
# ---------------------------------------------------------------------------
class TestReverseVerification:
    def _run_with_broken_low_value(self, tmp_path, monkeypatch):
        """把 `_is_low_value` 破坏成"一律不丢弃"，模拟撤销本次改动。"""
        monkeypatch.setattr(
            "core.ai.agent_vector_memory._is_low_value", lambda text: False)
        vm = _mk(tmp_path)
        vm.store("你好", summary="欢迎语")
        return vm

    def test_broken_store_filter_must_go_red(self, tmp_path, monkeypatch):
        """撤销入库过滤后，"寒暄不得入库"这条断言必须转红——否则说明闸门是假的。"""
        vm = self._run_with_broken_low_value(tmp_path, monkeypatch)
        with pytest.raises(AssertionError):
            assert vm.count() == 0, "撤销验证失败：寒暄居然入库了（过滤没生效）"

    def test_broken_search_filter_must_go_red(self, tmp_path, monkeypatch):
        """撤销召回过滤后，短正文条目必须重新被召回（该断言预期为红）。"""
        monkeypatch.setattr(
            "core.ai.agent_vector_memory.VECTOR_MEM_MIN_TEXT_LEN", 0)
        monkeypatch.setattr(
            "core.ai.agent_vector_memory.VECTOR_MEM_MIN_SCORE", 0.0)
        vm = _mk(tmp_path)
        vm._entries = [_entry("你好", summary="欢迎语")]
        got = vm.search("你好", top_k=5)
        with pytest.raises(AssertionError):
            assert got == [], "撤销验证失败：短正文条目被召回了（过滤没生效）"
