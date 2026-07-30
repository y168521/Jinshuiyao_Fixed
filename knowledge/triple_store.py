# -*- coding: utf-8 -*-
"""GraphRAG 三元组存储基础设施

从 core/auto_knowledge.py 拆出的独立模块，负责：
  1. 三元组库的加载/保存/原子写入
  2. sources 元数据从 triples 派生（根治 sources 失配）
  3. 哈希标记管理（增量抽取）
  4. DeepSeek 回复解析

使用方式：
    from knowledge.triple_store import (
        _TRIPLE_STORE_LOCK, _TRIPLE_STORE_PATH, _TRIPLE_MARKER,
        _TRIPLE_SYSTEM_PROMPT, _TRIPLE_BATCH, _TRIPLE_MAX_CHUNKS,
        triple_store_path, load_triple_store, save_triple_store,
        write_triple_marker, parse_triples, recompute_sources,
    )
"""

import json
import logging
import os
import threading
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
_TRIPLE_STORE_LOCK = threading.Lock()  # 串行化三元组库的读-改-写临界区
_TRIPLE_STORE_PATH = os.path.join(_BASE_DIR, "knowledge", "graph_triples.json")
_TRIPLE_MARKER = os.path.join(_BASE_DIR, "金水谣数据", "log", ".expbox_triples_hash")
_TRIPLE_BATCH = 8        # 单次 DeepSeek 调用喂入的经验条数
_TRIPLE_MAX_CHUNKS = 6   # 单次 run 最多分块数

_TRIPLE_SYSTEM_PROMPT = (
    "你是知识图谱构建助手。从给定的经验条目中抽取结构化三元组，"
    "格式为 (主体, 谓词, 客体)，谓词用中文动词/关系词"
    "（如：导致、属于、需要、修复、提升、依赖、优于、触发）。"
    "只抽取文本中明确陈述的事实，不要臆测。每条经验可抽 1-4 个三元组。"
    "严格只输出一个 JSON 数组，元素形如 "
    '{"subject":"...","predicate":"...","object":"..."}，'
    "不要输出任何解释文字或 Markdown 代码块标记。"
)


# ---------------------------------------------------------------------------
# 公共函数（去除前缀下划线，让外部直接 import）
# ---------------------------------------------------------------------------
def triple_store_path() -> str:
    """返回三元组库文件路径。"""
    return _TRIPLE_STORE_PATH


def recompute_sources(store: Dict[str, Any]) -> Dict[str, Any]:
    """从 triples 聚合 sources 元数据，保证与 triples 始终一致。

    每个三元组自带 source / extracted_at；按 source 汇总其三元组数量与首尾抽取时间。
    调用方在写库前都会经过此函数，故 sources 永远由权威的 triples 派生。
    """
    agg: Dict[str, Any] = {}
    for t in store.get("triples", []):
        src = (t.get("source") or "未知来源").strip() or "未知来源"
        rec = agg.setdefault(src, {"triples": 0, "first_extracted_at": "", "last_extracted_at": ""})
        rec["triples"] = int(rec.get("triples", 0)) + 1
        ea = t.get("extracted_at", "")
        if ea:
            if not rec["first_extracted_at"] or ea < rec["first_extracted_at"]:
                rec["first_extracted_at"] = ea
            if not rec["last_extracted_at"] or ea > rec["last_extracted_at"]:
                rec["last_extracted_at"] = ea
    store["sources"] = agg
    return store


def load_triple_store() -> Dict[str, Any]:
    """加载三元组库（损坏则回退空库）。"""
    default = {"version": "1.0", "description": "GraphRAG 三元组库",
               "triples": [], "built_at": "", "sources": {}}
    if not os.path.isfile(_TRIPLE_STORE_PATH):
        return default
    try:
        with open(_TRIPLE_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("triples", [])
        return data
    except (OSError, json.JSONDecodeError):
        logger.warning("[GraphRAG] 三元组库损坏，回退空库")
        return default


def save_triple_store(data: Dict[str, Any]) -> None:
    """原子写入三元组库（写前重算 sources，保证与 triples 一致）。"""
    try:
        recompute_sources(data)
        os.makedirs(os.path.dirname(_TRIPLE_STORE_PATH), exist_ok=True)
        tmp = _TRIPLE_STORE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _TRIPLE_STORE_PATH)
    except OSError as e:
        logger.error("[GraphRAG] 三元组库写入失败: %s", e)


def write_triple_marker(hash_str: str) -> None:
    """原子写入三元组抽取标记。"""
    try:
        os.makedirs(os.path.dirname(_TRIPLE_MARKER), exist_ok=True)
        tmp = _TRIPLE_MARKER + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(hash_str)
        os.replace(tmp, _TRIPLE_MARKER)
    except OSError:
        pass


def parse_triples(reply: str) -> List[Dict[str, str]]:
    """从 DeepSeek 回复中解析三元组 JSON 数组，做严格校验。"""
    if not reply:
        return []
    text = reply.strip()
    # 剥离可能的 Markdown 代码块
    if text.startswith("```"):
        text = text.strip("`")
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
    # 截取第一个 [ 到最后一个 ]
    s, e = text.find("["), text.rfind("]")
    if s == -1 or e == -1 or e <= s:
        return []
    try:
        arr = json.loads(text[s:e + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(arr, list):
        return []
    out = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        subj = str(item.get("subject", "")).strip()
        pred = str(item.get("predicate", "")).strip()
        obj = str(item.get("object", "")).strip()
        if subj and pred and obj and len(subj) <= 40 and len(obj) <= 40:
            out.append({"subject": subj, "predicate": pred, "object": obj})
    return out
