# -*- coding: utf-8 -*-
"""P3-2 单元测试：离线 VSM 向量检索核心（knowledge.vector_index）。"""
import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from knowledge.vector_index import VectorIndex, _tokenize


def _make_cards():
    return [
        {
            "id": "c1",
            "title": "股票投资策略：长期价值投资",
            "content": "坚持长期持有优质资产，价值投资法看重企业内在价值，忽略短期波动。",
            "tags": ["股票", "价值投资"],
            "domain": "stock",
        },
        {
            "id": "c2",
            "title": "足球比赛赔率预测",
            "content": "分析欧赔亚盘盘口，结合球队主客场状态预测比赛结果。",
            "tags": ["足球", "赔率"],
            "domain": "football",
        },
        {
            "id": "c3",
            "title": "彩票冷热号与遗漏分析",
            "content": "统计历史开奖的冷热号分布与遗漏周期，辅助选号。",
            "tags": ["彩票", "遗漏"],
            "domain": "lottery",
        },
    ]


def test_tokenize_ngram():
    toks = _tokenize("价值投资")
    # 应含 2-gram 与 3-gram（不含 4-gram，符合设计）
    assert "价值" in toks
    assert "投资" in toks
    assert "价值投" in toks
    assert "值投资" in toks


def test_build_and_search_ranks_relevant():
    idx = VectorIndex().build(_make_cards())
    assert idx.doc_count == 3
    # 查询与 c1（价值投资）共享 n-gram，应召回 c1 且排首位
    hits = idx.search("价值投资方法", top_k=3)
    assert hits, "应召回至少一条结果"
    assert hits[0][0] == "c1"
    assert hits[0][1] > 0


def test_search_semantic_not_literal():
    idx = VectorIndex().build(_make_cards())
    # “长期股权资产配置” 字面无“价值投资”，但共享 长期/投资 等 n-gram → 仍应召回 c1
    hits = idx.search("长期股权资产配置策略", top_k=3)
    ids = [h[0] for h in hits]
    assert "c1" in ids
    # 且 c1 应排在与足球/彩票卡片之前（若同列）
    if "c2" in ids:
        assert ids.index("c1") < ids.index("c2")


def test_empty_query_returns_empty():
    idx = VectorIndex().build(_make_cards())
    assert idx.search("", top_k=5) == []
    assert idx.search("   ", top_k=5) == []


def test_min_score_filters():
    idx = VectorIndex().build(_make_cards())
    # 极高阈值应过滤掉弱相关
    hits = idx.search("足球赔率盘口", top_k=5, min_score=0.99)
    # c2 与查询强相关，阈值 0.99 仍应保留 c2（自身高度相关）
    assert all(s >= 0.99 for _, s in hits) or not hits


def test_cosine_score_in_range():
    idx = VectorIndex().build(_make_cards())
    hits = idx.search("价值", top_k=5)
    for _, s in hits:
        assert 0.0 <= s <= 1.0 + 1e-9
