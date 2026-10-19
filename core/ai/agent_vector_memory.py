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

# --- 入库门槛（JS-20261020-05）----------------------------------------------
# 实测：索引里 236 条记忆中 **235 条是"你好"**，1 条是探针 "probe"——
# 每轮对话结束都把最后一轮原样入库，寒暄被反复存了 235 次，
# 语义召回被寒暄霸榜（实测查"帮我看看双色球"，top5 全是"你好"，分数 0.2582）。
# 这就是"记事本写了却没人敢翻"的真实原因：翻了只会注入噪声。
# 对策：入库侧止损（寒暄/过短/近期重复不存）+ 召回侧过滤（短正文 + 低分不召回）。
#
# ⚠️ 两个门槛的分工（2026-10-20 实测，改前先看这里，别拍脑袋）：
#   相似度实测分布：寒暄虚高 0.26；**真正相关的提问只有 0.10~0.29**
#   （同义改写 0.19/0.24，几乎同句才 0.52）。
#   ⇒ 分数门槛**没有分辨力**：调到 0.30 能挡住废话，但同时把所有
#     "换个说法"的真记忆也挡掉，功能形同虚设。
#   ⇒ 最终分工：**短正文（MIN_TEXT_LEN）负责挡寒暄**（"你好"2字、235 条全灭），
#     **分数（MIN_SCORE）只负责挡"完全不相关"**（实测正交向量≈0，真实相关最低 0.10）。
#     阈值取 0.12：放过实测最低的真实相关 0.1466，挡住 0.10 以下的弱相关。
VECTOR_MEM_MIN_TEXT_LEN = 6       # 问题正文少于此长度视为无信息量（"你好"2字、"在吗"2字）
VECTOR_MEM_MIN_SCORE = 0.12       # 余弦相似度下限；只挡"完全不相关"，别指望它分辨寒暄
VECTOR_MEM_DEDUP_WINDOW = 10      # 最近 N 条内出现相同问题则跳过（防同一句刷屏入库）

# 无信息量问答：整句命中即不入库
_LOW_VALUE_TEXTS = {
    "你好", "您好", "在吗", "在不在", "嗨", "哈喽", "hello", "hi",
    "谢谢", "多谢", "感谢", "再见", "拜拜", "晚安", "早安",
    "好的", "好", "嗯", "哦", "啊", "是", "否", "不", "ok", "okay",
    "测试", "试试", "probe",
}


def _is_low_value(text: str) -> bool:
    """寒暄/过短/纯符号的问答不配进记忆库（返回 True 表示应丢弃）。"""
    t = (text or "").strip()
    if len(t) < VECTOR_MEM_MIN_TEXT_LEN:
        return True
    if t.lower() in _LOW_VALUE_TEXTS:
        return True
    return False



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


def _score_and_rank(entries, q_vec, top_k, tag, min_score=0.0, min_text_len=0):
    """对记忆条目按余弦相似度打分排序，返回 top_k 结果列表

    min_score / min_text_len：召回侧过滤。历史遗留的寒暄条目（短正文）与
    虚高相似度都靠它挡在门外；默认 0 表示不过滤（保持既有调用方行为）。
    """
    scored = []
    for entry in entries:
        if tag and entry.get("tag") != tag:
            continue
        if min_text_len and len(entry.get("text", "")) < min_text_len:
            continue
        e_vec = np.array(entry.get("embedding", []), dtype=np.float32)
        if e_vec.size == 0:
            continue
        score = float(np.dot(q_vec, e_vec))
        if score < min_score:
            continue
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
        """存储一条记忆；寒暄/过短/近期重复的问答不入库（返回是否真的存了）"""
        if _is_low_value(text):
            return False
        t = (text or "").strip()
        if any((e.get("text") or "").strip() == t
               for e in self._entries[-VECTOR_MEM_DEDUP_WINDOW:]):
            return False
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
        return True

    def search(self, query, top_k=5, tag=None,
               min_score=None, min_text_len=None) -> List[Dict]:
        """按语义搜索记忆，返回 top_k 条

        min_score / min_text_len 默认取模块级门槛（见 VECTOR_MEM_MIN_SCORE /
        VECTOR_MEM_MIN_TEXT_LEN）；传 0 可显式关掉对应过滤。
        """
        if not self._entries:
            return []
        ms = VECTOR_MEM_MIN_SCORE if min_score is None else min_score
        ml = VECTOR_MEM_MIN_TEXT_LEN if min_text_len is None else min_text_len
        return _score_and_rank(self._entries, _compute_embedding(query),
                               top_k, tag, min_score=ms, min_text_len=ml)

    def count(self) -> int:
        return len(self._entries)
