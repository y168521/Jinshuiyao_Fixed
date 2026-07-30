# -*- coding: utf-8 -*-
"""
金水谣知识库 · 向量检索（离线 VSM）
================================

背景
----
知识库主检索目前是「关键词命中」（MiroFishDB.search）+「图谱三元组」（search_graph_triples），
两者都是字面匹配，无法召回"同义/近义但字面不同"的知识。本模块补齐第三路：**向量召回**

设计
----
纯标准库实现（不依赖 numpy/scipy/sentence-transformers），离线、无网络调用、fail-safe：
- 中文：2~3 字 n-gram（字符级，无需分词器，天然适配中文语义重叠）
- 英文/数字：连续词（长度>1）
- 权重：TF-IDF（标题×3 加权，提升核心语义比重）
- 相似度：余弦（稀疏点积，O(命中维度) 而非 O(词表)）
- 索引持久化：knowledge/vector_index.json，按 mirofish_db.json 的 mtime 自动失效重建
  （为 P3-4「定时 reindex」预留统一入口 build_index_from_kb()）

并发
----
构建/重建由 _BUILD_LOCK(RLock，可重入)串行化；查询只读，无锁。
get_vector_index 持锁时内部会调用 build_index_from_kb（同样抢这把锁），
故必须用 RLock 而非 Lock，否则同线程重入将死锁（请求永久挂起）。
"""
import os
import re
import json
import math
import threading
import logging
from collections import Counter

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
MIROFISH_DB_PATH = os.path.join(KNOWLEDGE_DIR, "mirofish_db.json")
VECTOR_INDEX_PATH = os.path.join(KNOWLEDGE_DIR, "vector_index.json")

# 构建/重建串行锁，防止多线程并发重建导致重复 IO / 半写
_BUILD_LOCK = threading.RLock()

# 单字停用表（中文单字区分度低，2~3 gram 才保留，单字在此剔除）
_STOP_SINGLE = set("的了在是与及或等我你他她它们这那有其个为以被把从对就也又还都更最可可能应该必须需要")


def _tokenize(text):
    """把文本切成 token 多重集（Counter）。

    - 英文/数字：连续字母数字串（长度>1，过滤单字母噪声）
    - 中文：2~3 字 n-gram（字符级，无需分词器）
    """
    if not text:
        return Counter()
    text = text.lower()
    tokens = Counter()
    # 英文 / 数字词
    for w in re.findall(r"[a-z0-9]+", text):
        if len(w) > 1:
            tokens[w] += 1
    # 中文 n-gram（2,3）
    for seg in re.findall(r"[一-鿿]+", text):
        L = len(seg)
        for n in (2, 3):
            for i in range(L - n + 1):
                tok = seg[i:i + n]
                tokens[tok] += 1
    # 单字中文停用剔除（n-gram 已覆盖语义，单字噪声大）
    for s in _STOP_SINGLE:
        if s in tokens:
            del tokens[s]
    return tokens


def _card_text(card):
    """组合一张卡片的可检索文本（标题加权、标签中等加权）。"""
    title = card.get("title", "") or ""
    tags = " ".join(card.get("tags", []) or [])
    content = (card.get("content", "") or card.get("content_preview", "") or "")
    # 标题重复 3 次 → TF-IDF 自然给标题更高权重
    return " ".join([title, title, title, tags, content])


class VectorIndex:
    """TF-IDF 向量空间模型索引（稀疏向量 + 余弦）。"""

    def __init__(self):
        self.idf = {}                 # token -> idf
        self.docs = {}                # doc_id -> {"vec": {tok: w}, "norm": float, "meta": {...}}
        self.doc_count = 0
        self.built_at = ""
        self.source_mtime = 0.0

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def build(self, cards):
        """从卡片列表构建索引。cards: list[dict]，需含 id/title/tags/content。"""
        doc_tokens = {}
        metas = {}
        for c in cards:
            cid = c.get("id")
            if not cid:
                continue
            doc_tokens[cid] = _tokenize(_card_text(c))
            metas[cid] = {
                "title": c.get("title", ""),
                "domain": c.get("domain", "general"),
                "tags": c.get("tags", []) or [],
                "snippet": (c.get("content", "") or c.get("content_preview", ""))[:200],
            }

        # df 统计
        df = Counter()
        for toks in doc_tokens.values():
            for t in toks:
                df[t] += 1

        n = max(len(doc_tokens), 1)
        # 平滑 idf：log((N+1)/(df+1)) + 1
        self.idf = {t: math.log((n + 1) / (d + 1)) + 1.0 for t, d in df.items()}

        # tf-idf 向量 + L2 范数
        self.docs = {}
        for cid, toks in doc_tokens.items():
            vec = {}
            norm_sq = 0.0
            for t, tf in toks.items():
                w = (1.0 + math.log(tf)) * self.idf.get(t, 1.0)
                vec[t] = w
                norm_sq += w * w
            self.docs[cid] = {
                "vec": vec,
                "norm": math.sqrt(norm_sq),
                "meta": metas[cid],
            }
        self.doc_count = n
        self.built_at = _now()
        return self

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def search(self, query, top_k=10, min_score=0.01):
        """余弦相似度检索，返回 [(doc_id, score), ...] 降序。"""
        q_toks = _tokenize(query)
        if not q_toks:
            return []
        # query tf-idf 向量
        qvec = {}
        qnorm_sq = 0.0
        for t, tf in q_toks.items():
            w = (1.0 + math.log(tf)) * self.idf.get(t, 1.0)
            qvec[t] = w
            qnorm_sq += w * w
        qnorm = math.sqrt(qnorm_sq)
        if qnorm == 0:
            return []

        results = []
        for cid, d in self.docs.items():
            dnorm = d["norm"]
            if dnorm == 0:
                continue
            # 稀疏点积：只遍历 query 中存在的维度
            dot = 0.0
            dvec = d["vec"]
            for t, qw in qvec.items():
                dw = dvec.get(t)
                if dw:
                    dot += qw * dw
            if dot == 0:
                continue
            score = dot / (qnorm * dnorm)
            if score >= min_score:
                results.append((cid, round(score, 4)))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def to_dict(self):
        return {
            "version": "1.0",
            "built_at": self.built_at,
            "source_mtime": self.source_mtime,
            "doc_count": self.doc_count,
            "idf": self.idf,
            "docs": {
                cid: {"vec": d["vec"], "norm": d["norm"], "meta": d["meta"]}
                for cid, d in self.docs.items()
            },
        }

    @classmethod
    def from_dict(cls, data):
        idx = cls()
        idx.idf = data.get("idf", {})
        idx.doc_count = data.get("doc_count", 0)
        idx.built_at = data.get("built_at", "")
        idx.source_mtime = data.get("source_mtime", 0.0)
        idx.docs = data.get("docs", {})
        return idx

    def save(self, path=VECTOR_INDEX_PATH):
        """原子写入索引文件。"""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, path)
            return True
        except (IOError, OSError) as e:
            logger.warning("[向量索引] 保存失败: %s", e)
            return False


def _now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_cards_from_kb():
    """从 MiroFishDB 加载全部卡片（fail-safe）。"""
    try:
        from knowledge.mirofish_db import MiroFishDB
        db = MiroFishDB()
        return db._data.get("cards", [])
    except Exception as e:
        logger.warning("[向量索引] 加载知识库卡片失败: %s", e)
        return []


def build_index_from_kb(path=VECTOR_INDEX_PATH):
    """从知识库构建索引并持久化（P3-4 定时 reindex 的统一定时入口）。

    Returns:
        VectorIndex
    """
    with _BUILD_LOCK:
        cards = _load_cards_from_kb()
        idx = VectorIndex()
        idx.source_mtime = _safe_mtime(MIROFISH_DB_PATH)
        idx.build(cards)
        idx.save(path)
        logger.info("[向量索引] 已构建 %d 张卡片向量索引", idx.doc_count)
        return idx


def rebuild_vector_index(path=VECTOR_INDEX_PATH):
    """构建索引、持久化、并刷新进程内缓存单例（供定时 reindex / 手动触发调用）。

    与 get_vector_index 的 mtime 失效机制互补：
    - 主动重建使磁盘索引保持新鲜，首个语义检索无需临时构建
    - 全局 _INDEX 直接指向最新索引，避免「磁盘新 / 内存旧」的窗口期

    注意：build_index_from_kb 内部已持有 _BUILD_LOCK，故此处**不在锁内**赋值全局，
    仅做引用原子赋值（CPython GIL 下安全），避免与 _BUILD_LOCK 重入死锁。
    """
    idx = build_index_from_kb(path)
    global _INDEX
    _INDEX = idx
    return idx


def _safe_mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _index_fresh(index, path=VECTOR_INDEX_PATH):
    """检查内存索引是否仍匹配知识库最新状态。"""
    if index is None:
        return False
    # 文件不存在 → 内存索引若刚构建则可用，否则需重建
    if not os.path.isfile(path):
        return index.doc_count > 0
    # 知识库 mtime 变化 → 失效
    if abs(index.source_mtime - _safe_mtime(MIROFISH_DB_PATH)) > 1e-6:
        return False
    return True


_INDEX = None  # 进程内缓存


def get_vector_index(force=False, path=VECTOR_INDEX_PATH):
    """获取（懒构建/缓存）向量索引单例。

    - 命中内存缓存且知识库 mtime 未变 → 直接返回
    - 否则尝试从磁盘索引文件载入（mtime 匹配）
    - 仍无 → 从知识库重建并持久化
    """
    global _INDEX
    with _BUILD_LOCK:
        if not force and _index_fresh(_INDEX, path):
            return _INDEX
        # 尝试磁盘加载
        if not force and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                idx = VectorIndex.from_dict(data)
                if _index_fresh(idx, path):
                    _INDEX = idx
                    return _INDEX
            except (IOError, json.JSONDecodeError) as e:
                logger.debug("[向量索引] 磁盘索引读取失败，重建: %s", e)
        # 重建
        _INDEX = build_index_from_kb(path)
        return _INDEX


def search_knowledge_vector(query, limit=10, min_score=0.01):
    """高层语义向量检索：返回带 score 的卡片 dict 列表（离线 fail-safe）。

    Args:
        query: 查询文本（中文/英文/混合均可）
        limit: 最多返回条数
        min_score: 最低余弦相似度阈值
    Returns:
        list[dict]: [{id, title, snippet, score, domain, tags}, ...]
    """
    q = (query or "").strip()
    if not q:
        return []
    try:
        idx = get_vector_index()
        hits = idx.search(q, top_k=limit, min_score=min_score)
        out = []
        for cid, score in hits:
            meta = idx.docs.get(cid, {}).get("meta", {})
            out.append({
                "id": cid,
                "title": meta.get("title", ""),
                "snippet": meta.get("snippet", ""),
                "score": score,
                "domain": meta.get("domain", "general"),
                "tags": meta.get("tags", []),
            })
        return out
    except Exception as e:
        logger.debug("[向量检索] 检索失败（降级返回空）: %s", e)
        return []


# 便捷入口（供 handler 直接调用）
def get_vector_retriever():
    """返回当前向量索引（懒加载）。"""
    return get_vector_index()
