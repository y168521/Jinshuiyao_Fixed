# -*- coding: utf-8 -*-
"""知识库统一检索入口

从 core/auto_knowledge.py 拆出的独立模块，负责：
  1. AI 决策知识离线检索（关键词命中）
  2. GraphRAG 三元组检索（全来源/指定来源）
  3. 语义向量检索（VSM，中文 n-gram + TF-IDF + 余弦相似度）
  4. AI 决策条目计数（供门禁使用）

使用方式：
    from knowledge.knowledge_search import (
        search_ai_knowledge, search_graph_triples,
        search_knowledge_vector, count_ai_decisions_today,
    )
"""

import logging
import os
import re
from typing import Dict, Any, List

from knowledge.triple_store import (
    _TRIPLE_STORE_LOCK,
    load_triple_store,
)

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AI_DECISIONS_PATH = os.path.join(_BASE_DIR, "金水谣数据", "log", "ai_decisions.md")


def _read_decisions_text() -> str:
    """安全读取 ai_decisions.md 全文（检索/计数用）。"""
    try:
        with open(_AI_DECISIONS_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def search_ai_knowledge(query: str, limit: int = 10) -> Dict[str, Any]:
    """检索 AI 决策知识（离线、无网络依赖，fail-safe）。

    直接检索两张可搜索源：① ai_decisions.md 原文决策条目 ② graph_triples.json 三元组。
    返回命中条目/三元组，供下一个 AI 在接手时快速定位"为什么这么改"。

    Args:
        query: 关键词（空格分隔多词，任一命中即返回）
        limit: 每种源最多返回条数
    Returns:
        dict: cards(list) / triples(list) / count
    """
    q = (query or "").strip().lower()
    if not q:
        return {"cards": [], "triples": [], "count": 0}
    tokens = [t for t in re.split(r"\s+", q) if t]

    cards = []
    try:
        text = _read_decisions_text()
        blocks = re.split(r"(?m)^### \d{4}-\d{2}-\d{2}.*$", text)
        heads = re.findall(r"(?m)^### (\d{4}-\d{2}-\d{2}.*)$", text)
        for i, block in enumerate(blocks[1:]):
            head = heads[i] if i < len(heads) else f"块{i}"
            if any(tok in block.lower() or tok in head.lower() for tok in tokens):
                snippet = block.strip()[:300].replace("\n", " ")
                cards.append({"title": head, "snippet": snippet})
                if len(cards) >= limit:
                    break
    except Exception as e:
        logger.debug("[AI决策检索] 读决策原文失败: %s", e)

    triples = []
    try:
        store = load_triple_store()
        for t in store.get("triples", []):
            if t.get("source") != "ai_decisions.md":
                continue
            blob = f"{t.get('subject','')} {t.get('predicate','')} {t.get('object','')}".lower()
            if any(tok in blob for tok in tokens):
                triples.append(t)
                if len(triples) >= limit:
                    break
    except Exception as e:
        logger.debug("[AI决策检索] 读三元组库失败: %s", e)

    return {"cards": cards, "triples": triples, "count": len(cards) + len(triples)}


def search_graph_triples(query: str, limit: int = 10, source: str = None) -> List[Dict[str, Any]]:
    """检索 GraphRAG 三元组库（离线、无网络依赖，fail-safe）。

    与 search_ai_knowledge 不同，本函数检索【全部来源】的三元组（经验箱 + ai_decisions + 未来来源），
    供主检索路径 /api/knowledge/search 并入图谱证据，也可由 /api/knowledge/graph/search 直接调用。

    并发安全：读库在共享 _TRIPLE_STORE_LOCK 临界区内进行。

    Args:
        query: 关键词（空格分隔多词，任一命中即返回）
        limit: 最多返回条数
        source: 可选，限定来源；None 表示全部来源
    Returns:
        list: 命中的三元组 dict
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    tokens = [t for t in re.split(r"\s+", q) if t]
    results: List[Dict[str, Any]] = []
    try:
        with _TRIPLE_STORE_LOCK:
            store = load_triple_store()
            for t in store.get("triples", []):
                if source and t.get("source") != source:
                    continue
                blob = " ".join([
                    str(t.get("subject", "")),
                    str(t.get("predicate", "")),
                    str(t.get("object", "")),
                ]).lower()
                if any(tok in blob for tok in tokens):
                    results.append(t)
                    if len(results) >= limit:
                        break
    except Exception as e:
        logger.debug("[图谱检索] 读三元组库失败: %s", e)
    return results


def search_knowledge_vector(query: str, limit: int = 10, min_score: float = 0.01) -> List[Dict[str, Any]]:
    """语义向量检索（离线 VSM：中文 n-gram + TF-IDF + 余弦相似度，fail-safe）。

    知识库第三路召回：补齐关键词命中 + 图谱三元组之外的语义召回。
    实现见 knowledge.vector_index，本函数为统一入口。

    Args:
        query: 查询文本
        limit: 最多返回条数
        min_score: 最低余弦相似度阈值
    Returns:
        list[dict]: [{id, title, snippet, score, domain, tags}, ...]
    """
    try:
        from knowledge.vector_index import search_knowledge_vector as _vsearch
        return _vsearch(query, limit=limit, min_score=min_score)
    except Exception as e:
        logger.debug("[向量检索] 入口降级: %s", e)
        return []


def count_ai_decisions_today(today_str: str) -> int:
    """统计 ai_decisions.md 中当天的决策条目数（供门禁使用）。"""
    text = _read_decisions_text()
    if not text or today_str not in text:
        return 0
    return len(re.findall(rf"### {re.escape(today_str)}", text))
