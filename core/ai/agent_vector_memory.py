"""向量记忆引擎 — 让AI能按语义搜索过去的对话和知识

基于 numpy 的轻量向量存储，无需外部数据库。
与现有 JSON 文件记忆互补：顺序记忆 + 语义记忆 = 完整记忆系统。
"""

import os
import json
import hashlib
import numpy as np
from datetime import datetime
from typing import List, Dict, Optional
from utils.safe_json import safe_write_json
# JS-20260925-06：档案清理唯一真源，禁止各写一份 [-N:] 截断
from core.infra.archive_guard import trim_archive as _guard_trim_archive

import logging

logger = logging.getLogger("jinshuiyao.agent_vector_memory")

# 向量记忆索引是长期记忆资产，不是缓存。
# 原有的尾部按 200 条硬截 会导致「加一条丢一条」，实测已被截断在 200 条。
VECTOR_MEM_KEEP_DAYS = 1095        # 按时间保留：3 年
VECTOR_MEM_MAX_ENTRIES = 50000    # 条数兜底上限（防文件无限膨胀）


def _default_mem_dir() -> str:
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(_root, "金水谣数据", "agent_memory")


def _compute_embedding(text: str) -> np.ndarray:
    """基于字词共现的轻量embedding（无需AI模型，纯本地）

    使用字符n-gram + TF风格加权，产出128维向量。
    虽不如深度学习embedding精确，但足够区分"彩票相关"vs"股票相关"。
    """
    dim = 128
    vec = np.zeros(dim, dtype=np.float32)
    text = text.lower()
    for n in (2, 3, 4):
        for i in range(len(text) - n + 1):
            gram = text[i:i + n]
            h = int(hashlib.md5(gram.encode()).hexdigest(), 16)
            vec[h % dim] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


def _load_entries(index_file: str) -> List[Dict]:
    if not os.path.isfile(index_file):
        return []
    try:
        with open(index_file, "r", encoding="utf-8") as f:
            return json.load(f).get("entries", [])
    except Exception:
        return []


def _save_entries(index_file: str, entries: List[Dict]):
    """保存记忆条目：按时间保留，条数骤降时放弃写入。"""
    kept, before, after, blocked = _guard_trim_archive(
        entries, keep_days=VECTOR_MEM_KEEP_DAYS,
        max_records=VECTOR_MEM_MAX_ENTRIES, label="向量记忆索引")
    if blocked:
        logger.error("[向量记忆] 条数骤降保护触发，放弃写入 %s", index_file)
        return
    safe_write_json(index_file, {"entries": kept})


def _score_and_rank(entries, q_vec, top_k, tag):
    """对记忆条目按余弦相似度打分排序，返回 top_k 结果列表"""
    scored = []
    for entry in entries:
        if tag and entry.get("tag") != tag:
            continue
        e_vec = np.array(entry.get("embedding", []), dtype=np.float32)
        if e_vec.size == 0:
            continue
        score = float(np.dot(q_vec, e_vec))
        scored.append((score, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{
        "text": e["text"], "summary": e.get("summary", ""),
        "tag": e.get("tag", ""), "score": round(s, 4),
        "timestamp": e.get("timestamp", ""),
    } for s, e in scored[:top_k]]


class VectorMemory:
    """轻量向量记忆存储：store(text, ...) 存记忆，search(query) 按语义召回"""

    def __init__(self, mem_dir: str = None):
        self._mem_dir = mem_dir or _default_mem_dir()
        self._index_file = os.path.join(self._mem_dir, "vector_index.json")
        os.makedirs(self._mem_dir, exist_ok=True)
        self._entries: List[Dict] = _load_entries(self._index_file)

    def _save(self):
        _save_entries(self._index_file, self._entries)

    def store(self, text, summary="", tag="", source=""):
        """存储一条记忆"""
        embedding = _compute_embedding(text).tolist()
        entry = {
            "text": text[:500],
            "summary": summary[:200] if summary else text[:100],
            "tag": tag, "source": source or "user_history",
            "embedding": embedding,
            "timestamp": datetime.now().isoformat(),
        }
        self._entries.append(entry)
        self._save()

    def search(self, query, top_k=5, tag=None) -> List[Dict]:
        """按语义搜索记忆，返回 top_k 条"""
        if not self._entries:
            return []
        return _score_and_rank(self._entries, _compute_embedding(query), top_k, tag)

    def count(self) -> int:
        return len(self._entries)
