# -*- coding: utf-8 -*-
"""JS-20260925-02 知识网关相关度门槛（KB_RELEVANCE_RATIO）单元测试

背景：BM25 只要 score>0 就返回，"沾一点边"的弱相关条目会淹没真正有用的结果。
门槛用**相对 top1 的比例**而非绝对分数：四源分数尺度差一个量级
（cards/triples 可达 10+，project_docs 只有 0.x），绝对阈值会静默误杀短文本来源。

这些用例同时锁住两个易被改坏的点：
  1. 门槛必须在 limit 截断**之前**（先截再过滤＝在矮子里拔将军）
  2. top1 恒保留（门槛永不把某来源整片清空）
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.infra import knowledge_gateway as kg  # noqa: E402


def _mk(scores):
    """按给定分数造条目（已降序）"""
    return [{'id': 'd%d' % i, 'text': 'x', 'score': s} for i, s in enumerate(scores)]


# --- 1. 门槛过滤长尾 -------------------------------------------------------
def test_gate_filters_tail():
    """明显低于 top1×ratio 的长尾必须被砍掉"""
    items = _mk([10.0, 9.0, 8.0, 1.0, 0.5, 0.2])
    kept = kg._apply_relevance_gate(items)
    # top1=10.0, ratio=0.35 → floor=3.5 → 保留 10/9/8
    assert [it['score'] for it in kept] == [10.0, 9.0, 8.0]


# --- 2. top1 恒保留（防整源清空）------------------------------------------
def test_gate_keeps_top1_when_all_below_floor():
    """即使没有第二条达标，也必须返回 top1（"一条都没有"会被误读成"没这个知识"）"""
    items = _mk([1.0])
    assert len(kg._apply_relevance_gate(items)) == 1

    # 极端：把绝对下限抬到超过 top1，仍须留 1 条
    orig = kg.KB_MIN_SCORE_ABS
    try:
        kg.KB_MIN_SCORE_ABS = 999.0
        kept = kg._apply_relevance_gate(_mk([1.0, 0.1]))
        assert len(kept) == 1 and kept[0]['score'] == 1.0
    finally:
        kg.KB_MIN_SCORE_ABS = orig


def test_gate_empty_input():
    assert kg._apply_relevance_gate([]) == []


# --- 3. ratio 可调（证明门槛真的在生效，而不是摆设）------------------------
def test_gate_ratio_zero_disables_filter(monkeypatch):
    monkeypatch.setattr(kg, 'KB_RELEVANCE_RATIO', 0.0)
    items = _mk([10.0, 9.0, 8.0, 1.0, 0.5, 0.2])
    assert len(kg._apply_relevance_gate(items)) == 6


def test_gate_ratio_one_keeps_only_top(monkeypatch):
    monkeypatch.setattr(kg, 'KB_RELEVANCE_RATIO', 1.0)
    kept = kg._apply_relevance_gate(_mk([10.0, 9.9, 9.0, 1.0]))
    assert [it['score'] for it in kept] == [10.0]


# --- 4. 绝对下限与相对门槛是 AND ------------------------------------------
def test_gate_abs_floor_is_and(monkeypatch):
    monkeypatch.setattr(kg, 'KB_MIN_SCORE_ABS', 5.0)
    # top1=10 → 相对 floor=3.5，但绝对下限 5.0 更严 → 保留 ≥5.0
    kept = kg._apply_relevance_gate(_mk([10.0, 6.0, 4.0, 3.9]))
    assert [it['score'] for it in kept] == [10.0, 6.0]


# --- 5. _bm25：门槛先于截断（关键顺序）------------------------------------
def test_bm25_applies_gate_and_limit():
    docs = [
        {'id': 'strong', 'text': '彩票命中率 彩票 命中率 彩票命中率'},
        {'id': 'mid', 'text': '彩票 命中率'},
        {'id': 'weak1', 'text': '彩票'},
        {'id': 'weak2', 'text': '命中率'},
        {'id': 'noise', 'text': '基金规模预警阈值'},
    ]
    out = kg._bm25('彩票命中率', docs, limit=5)
    scores = [it['score'] for it in out]
    assert scores == sorted(scores, reverse=True)
    if scores:
        floor = scores[0] * kg.KB_RELEVANCE_RATIO
        assert all(s >= floor for s in scores), "门槛未生效：仍有低于门槛的条目"
    assert len(out) <= 5


def test_bm25_limit_still_works_with_gate():
    """门槛不能破坏 JS-20260925-01 修好的 limit 截断"""
    docs = [{'id': 'd%d' % i, 'text': '彩票命中率%d' % i} for i in range(30)]
    assert len(kg._bm25('彩票命中率', docs, limit=1)) == 1
    assert len(kg._bm25('彩票命中率', docs, limit=3)) <= 3


# --- 6. 常量必须是模块级（闸门靠 AST 提取，默认参数/魔数不算）--------------
def test_constants_are_module_level():
    assert hasattr(kg, 'KB_RELEVANCE_RATIO')
    assert hasattr(kg, 'KB_MIN_SCORE_ABS')
    assert isinstance(kg.KB_RELEVANCE_RATIO, float)
    assert 0.0 < kg.KB_RELEVANCE_RATIO < 1.0


# --- 7. 真实入口端到端：门槛生效且 top1 不受损 ------------------------------
def test_search_end_to_end_gate():
    res = kg.search('彩票命中率', limit=50)
    for key in ('cards', 'triples', 'experiences', 'project_docs'):
        items = res.get(key) or []
        if not items:
            continue
        scores = sorted((it.get('score', 0) for it in items), reverse=True)
        floor = scores[0] * kg.KB_RELEVANCE_RATIO
        assert all(s >= floor for s in scores), "%s 仍有低于门槛的条目" % key
