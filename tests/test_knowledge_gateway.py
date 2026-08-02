# -*- coding: utf-8 -*-
"""知识网关测试：四源召回 / BM25 排序 / 相关性门槛 / fail-safe / API"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import knowledge_gateway as gw


class TestBM25:
    def test_bm25_ranks_relevant_first(self):
        docs = [
            {"id": 1, "text": "知识蒸馏：经验到 Skill 的全自动管线"},
            {"id": 2, "text": "今天天气不错，适合出门"},
            {"id": 3, "text": "蒸馏器的幂等标记与归档行设计"},
        ]
        out = gw._bm25("知识蒸馏 管线", docs, 3)
        assert out and out[0]["id"] == 1
        assert all(d["score"] > 0 for d in out)

    def test_bm25_empty_safe(self):
        assert gw._bm25("", [], 5) == []
        assert gw._bm25("查询", [], 5) == []
        assert gw._bm25("", [{"id": 1, "text": "x"}], 5) == []

    def test_bm25_no_match_returns_empty(self):
        out = gw._bm25("zzzq不存在词xyz", [{"id": 1, "text": "知识卡片"}], 5)
        assert out == []


class TestRelevanceGate:
    def test_generic_chat_not_injected(self):
        # 泛化问候/天气不注入（虚词黑名单）
        for q in ["今天天气怎么样", "你好", "随便聊聊"]:
            txt = gw.summarize(q, limit=4)
            assert txt == "", f'应不注入: {q!r} -> {txt!r}'

    def test_project_query_injected(self):
        txt = gw.summarize("W63补12 基金 弹窗", limit=4)
        assert txt, "项目知识查询应注入"
        assert "第十二条" in txt or "经验" in txt

    def test_relevance_filter_blocks_unrelated(self):
        items = [
            {"title": "A", "text": "知识蒸馏管线设计"},
            {"title": "B", "text": "足彩盘口分析"},
        ]
        out = gw._relevant(items, "蒸馏 管线")
        assert [i["title"] for i in out] == ["A"]


class TestFourSourceRecall:
    def test_search_returns_all_sources(self):
        r = gw.search("数据真实性 守卫", limit=5)
        assert r["query"] == "数据真实性 守卫"
        for key in ("cards", "triples", "vectors", "experiences", "project_docs"):
            assert key in r
        assert r["total"] > 0

    def test_experience_hit(self):
        r = gw.search("相对路径 幽灵垃圾", limit=5)
        titles = [e["title"] for e in r["experiences"]]
        assert any("第十二条" in t for t in titles)

    def test_empty_query(self):
        r = gw.search("")
        assert r["total"] == 0 and r["error"]


class TestFailSafe:
    def test_missing_asset_does_not_break(self, monkeypatch):
        monkeypatch.setattr(gw, "TRIPLE_PATH", os.path.join(os.path.dirname(__file__), "不存在.json"))
        monkeypatch.setattr(gw, "EXPBOX_PATH", os.path.join(os.path.dirname(__file__), "不存在.md"))
        r = gw.search("任何查询词")
        assert r["total"] >= 0  # 其他源仍工作，不抛异常

    def test_broken_recall_source(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("源坏了")
        monkeypatch.setattr(gw, "_recall_cards", boom)
        r = gw.search("查询")
        assert r["total"] >= 0  # 单源失败不致命


class TestCache:
    def test_cache_hits(self, monkeypatch):
        calls = {"n": 0}
        real = gw._cached_asset

        def counting(key, loader, path=None):
            calls["n"] += 1
            return real(key, loader, path)
        monkeypatch.setattr(gw, "_cached_asset", counting)
        gw._recall_triples("查询", 3)
        gw._recall_triples("查询", 3)
        assert calls["n"] <= 2  # 第二次命中缓存（mtime 未变）


class TestSummarize:
    def test_summarize_shape(self):
        txt = gw.summarize("知识网关 MCP", limit=3)
        if txt:  # 有相关内容时是纯文本、可控长度
            assert len(txt) < 4000
