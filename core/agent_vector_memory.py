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


class VectorMemory:
    """轻量向量记忆存储

    用法:
        vm = VectorMemory()
        vm.store("双色球预测方法", "使用冷热号+AC值分析", tag="lottery")
        results = vm.search("怎么预测彩票", top_k=3)
    """

    def __init__(self, mem_dir: str = None):
        if mem_dir is None:
            _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            mem_dir = os.path.join(_root, "金水谣数据", "agent_memory")
        self._mem_dir = mem_dir
        self._index_file = os.path.join(mem_dir, "vector_index.json")
        os.makedirs(mem_dir, exist_ok=True)
        self._entries: List[Dict] = []
        self._load()

    def _load(self):
        if os.path.isfile(self._index_file):
            try:
                with open(self._index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._entries = data.get("entries", [])
            except Exception:
                self._entries = []

    def _save(self):
        safe_write_json(self._index_file, {"entries": self._entries[-200:]})

    def _compute_embedding(self, text: str) -> np.ndarray:
        """基于字词共现的轻量embedding（无需AI模型，纯本地）

        使用字符n-gram + TF风格加权，产出128维向量。
        虽不如深度学习embedding精确，但足够区分"彩票相关"vs"股票相关"。
        """
        dim = 128
        vec = np.zeros(dim, dtype=np.float32)
        text = text.lower()
        # n-gram hash 投射
        for n in (2, 3, 4):
            for i in range(len(text) - n + 1):
                gram = text[i:i + n]
                h = int(hashlib.md5(gram.encode()).hexdigest(), 16)
                idx = h % dim
                vec[idx] += 1.0
        # L2归一化
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def store(self, text: str, summary: str = "", tag: str = "", source: str = ""):
        """存储一条记忆

        Args:
            text: 原始文本
            summary: 简短摘要（可选）
            tag: 标签（lottery/stock/football/general）
            source: 来源（user_history/ai_knowledge）
        """
        embedding = self._compute_embedding(text).tolist()
        entry = {
            "text": text[:500],
            "summary": summary[:200] if summary else text[:100],
            "tag": tag,
            "source": source or "user_history",
            "embedding": embedding,
            "timestamp": datetime.now().isoformat(),
        }
        self._entries.append(entry)
        self._save()

    def search(self, query: str, top_k: int = 5, tag: str = None) -> List[Dict]:
        """按语义搜索记忆

        Args:
            query: 搜索文本
            top_k: 返回条数
            tag: 按标签过滤（可选）

        Returns:
            [{text, summary, tag, score, timestamp}, ...]
        """
        if not self._entries:
            return []

        q_vec = self._compute_embedding(query)
        scored = []

        for entry in self._entries:
            if tag and entry.get("tag") != tag:
                continue
            e_vec = np.array(entry.get("embedding", []), dtype=np.float32)
            if e_vec.size == 0:
                continue
            score = float(np.dot(q_vec, e_vec))
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, entry in scored[:top_k]:
            results.append({
                "text": entry["text"],
                "summary": entry.get("summary", ""),
                "tag": entry.get("tag", ""),
                "score": round(score, 4),
                "timestamp": entry.get("timestamp", ""),
            })
        return results

    def count(self) -> int:
        return len(self._entries)
