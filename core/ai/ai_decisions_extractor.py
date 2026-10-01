# -*- coding: utf-8 -*-
"""AI 决策自动入知识库（Layer A+B）。

从 ai_decisions.md 中提取 AI 改动决策卡，转为：
  1. MiroFish 知识卡片（可被知识库搜索 API 检索）
  2. GraphRAG 三元组（predicate 含 为什么/根因/修复/导致/重启铁律 等语义）

复用经验收集箱全部基础设施（sha256 增量 / 锁 / 原子写 / DeepSeek 降级），零新依赖。
"""

import os
import re
import time
import hashlib
import threading
import logging
from datetime import datetime
from typing import Dict, List

from core.infra.pipeline_mode import get_pipeline_mode, should_skip_triples as _ai_decisions_skip_triples
from knowledge.triple_store import (
    _TRIPLE_STORE_LOCK,
    _TRIPLE_STORE_PATH,  # noqa: F401 — 保留向后兼容
    _TRIPLE_BATCH,
    _TRIPLE_MAX_CHUNKS,
    _TRIPLE_SYSTEM_PROMPT,  # noqa: F401 — 保留向后兼容
    load_triple_store as _load_triple_store,
    save_triple_store as _save_triple_store,
    parse_triples as _parse_triples,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AI 决策自动入知识库（Layer A+B：让每个 AI 的"为什么改"都能被后续 AI 搜到，根治接力失真）
# ---------------------------------------------------------------------------
# 设计动机：经验收集箱承载"人类/跨AI经验"，但 AI 自己改代码时的"为什么根因/坑/属主"
# 只散落在代码注释 + 交接文档，下一个 AI 接手读不到全貌。本模块把 AI 决策卡
# (ai_decisions.md) 同样自动抽取为：① MiroFish 知识卡片（可被知识库搜索 API 检索）
# ② GraphRAG 三元组（predicate 含 为什么/根因/修复/导致/重启铁律 等语义）。
# 复用经验收集箱全部基础设施（sha256 增量 / 锁 / 原子写 / DeepSeek 降级），零新依赖。
#
# 多模式容错（应对突发情况，fail-safe 不 fail-closed）：
#   NORMAL   —— 默认：卡片 + 三元组全量同步
#   DEGRADED —— DeepSeek 限流/不稳：仍写卡片（不依赖 LLM），跳过三元组
#   OFFLINE  —— 无网络/无 key：仅本地卡片；也可完全离线手动跑 sync 脚本
#   OVERRIDE —— 紧急豁免：门禁只警告不阻断（须在交接中心记录原因）
# 任何 IO/网络异常均 try/except 包住，绝不致命。

_AI_DECISIONS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "金水谣数据", "log", "ai_decisions.md"
)
_AI_DECISIONS_MARKER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "金水谣数据", "log", ".ai_decisions_hash"
)
_AI_DECISIONS_TRIPLE_MARKER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "金水谣数据", "log", ".ai_decisions_triples_hash"
)

# 三元组"未解析"重试冷却（防 DeepSeek 临时抽空/异常时高频空转，
# 且该批决策不会被标记吞掉——冷却期内重入直接跳过，冷却后自动重试）
_AI_DECISIONS_RETRY_MARKER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "金水谣数据", "log", ".ai_decisions_triple_retry_cooldown"
)
_AI_DECISIONS_RETRY_COOLDOWN_SEC = 600


def _ai_decisions_retry_ready() -> bool:
    """距上次"未解析"尝试超过冷却期则允许重试。"""
    if not os.path.isfile(_AI_DECISIONS_RETRY_MARKER):
        return True
    try:
        return time.time() - os.path.getmtime(_AI_DECISIONS_RETRY_MARKER) > _AI_DECISIONS_RETRY_COOLDOWN_SEC
    except OSError:
        return True


def _touch_ai_decisions_retry() -> None:
    """记录一次"未解析"尝试时间（原子写）。"""
    try:
        os.makedirs(os.path.dirname(_AI_DECISIONS_RETRY_MARKER), exist_ok=True)
        tmp = _AI_DECISIONS_RETRY_MARKER + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        os.replace(tmp, _AI_DECISIONS_RETRY_MARKER)
    except OSError:
        pass


def _write_ai_decisions_marker(hash_str: str) -> None:
    """原子写入 ai_decisions 内容哈希标记（增量检测用）。"""
    try:
        os.makedirs(os.path.dirname(_AI_DECISIONS_MARKER), exist_ok=True)
        tmp = _AI_DECISIONS_MARKER + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(hash_str)
        os.replace(tmp, _AI_DECISIONS_MARKER)
    except OSError:
        pass


def _write_ai_decisions_triple_marker(hash_str: str) -> None:
    """原子写入 ai_decisions 三元组抽取标记（复用 A 的哈希思路）。"""
    try:
        os.makedirs(os.path.dirname(_AI_DECISIONS_TRIPLE_MARKER), exist_ok=True)
        tmp = _AI_DECISIONS_TRIPLE_MARKER + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(hash_str)
        os.replace(tmp, _AI_DECISIONS_TRIPLE_MARKER)
    except OSError:
        pass


_AI_DECISIONS_LOCK = threading.Lock()


def extract_from_ai_decisions() -> Dict[str, object]:
    """从 ai_decisions.md 提取 AI 决策知识卡片（Layer A）。

    ai_decisions.md 是每个 AI 会话结束自动追加的"为什么改"决策卡。
    本函数检测新增内容并转为 MiroFish 知识卡片（可被知识库搜索 API 检索），
    实现"每个 AI 改写都能被后续 AI 搜到"，根治接力失真。

    Returns:
        dict: new_entries / extracted / saved / timestamp
    """
    with _AI_DECISIONS_LOCK:
        return _extract_from_ai_decisions_inner()


def _build_decision_cards(new_entries):
    """把决策条目转为 MiroFish 知识卡片列表"""
    all_cards = []
    for entry in new_entries:
        heading = entry.split("\n", 1)[0].replace("###", "", 1).strip()
        title = heading[:40]
        owner = "跨AI"
        m_owner = re.search(r"属主[：:]\s*([^\n]+)", entry)
        if m_owner:
            owner = m_owner.group(1).strip().split()[0]
        all_cards.append({
            "title": f"[AI决策] {title}", "content": entry[:800],
            "subsystem": "global", "category": "skill",
            "tags": ["AI决策", owner, "自动提取"],
            "effectiveness": 65, "engine_hook": "",
            "source": f"ai_decisions.md#{title}",
        })
    return all_cards


def _extract_from_ai_decisions_inner() -> Dict[str, object]:
    new_entries, current_hash = _load_new_decision_entries(
        _AI_DECISIONS_MARKER, _write_ai_decisions_marker)
    if new_entries is None:
        return {"new_entries": 0, "extracted": 0, "saved": 0, "info": current_hash}

    # 延迟导入避免循环依赖（auto_knowledge 会反过来 import 本模块）
    from core.infra.auto_knowledge import AutoKnowledgeExtractor
    all_cards = _build_decision_cards(new_entries)
    saved = AutoKnowledgeExtractor().save_cards(all_cards) if all_cards else 0
    _write_ai_decisions_marker(current_hash)

    if all_cards:
        logger.info("[AI决策] 提取 %d 条决策, 保存 %d 张知识卡片", len(new_entries), saved)

    # JS-20261002-11 A3：同步进版本化存储层（决策卡 = 存储层第一个真实写入源）。
    # 为什么必须接在这里：存储层自带 verify/find_expired/骤降守卫并已接进一致性门禁第 ⑬ 项，
    # 但**没有写入源就是空库**，门禁恒绿等于没监控。本函数是现役唯一会被 watcher 与
    # 定时器真正调用的入口，接在这里才算接进调用链（MEMORY：写完必须当场接，否则成孤儿）。
    # 失败不阻断原链路（卡片/三元组同步优先），但**必须留痕**，绝不静默吞掉。
    store_info: Dict[str, object] = {"error": "未执行"}
    try:
        from core.infra.knowledge_ingest import ingest_decision_entries
        store_info = ingest_decision_entries(new_entries)
    except Exception as e:
        logger.warning("[AI决策] 写入知识存储层失败（不阻断卡片同步）: %s: %s",
                       type(e).__name__, e)
        store_info = {"error": "%s: %s" % (type(e).__name__, e)}

    return {
        "new_entries": len(new_entries),
        "extracted": len(all_cards),
        "saved": saved,
        "store": store_info,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


_AI_DECISION_TRIPLE_PROMPT = (
    "你是代码决策图谱构建助手。从给定的 AI 改动决策条目中抽取结构化三元组，"
    "格式为 (主体, 谓词, 客体)，谓词用中文动词/关系词，并尽量覆盖『为什么』类语义："
    "（导致、修复、根因、为什么、需要、依赖、优于、触发、重启铁律、属于、降级、避免）。"
    "主体/客体尽量写『文件.函数』或『文件』或『机制』。若条目说明了『属主(qoder/WorkBuddy)』，"
    "可额外抽一条 (机制/文件, 属主, XXX) 三元组。只抽取文本中明确陈述的事实，不要臆测。"
    "每条可抽 1-5 个三元组。严格只输出一个 JSON 数组，元素形如 "
    '{"subject":"...","predicate":"...","object":"..."}，不要输出任何解释或 Markdown 标记。'
)


def _load_new_decision_entries(marker_path, write_marker_fn):
    """读取 ai_decisions.md，按哈希增量解析新增决策条目。

    Returns:
        (new_entries, current_hash) 或 (None, info_str) 表示无需处理。
    """
    if not os.path.isfile(_AI_DECISIONS_PATH):
        return None, "ai_decisions.md 不存在"
    try:
        with open(_AI_DECISIONS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None, "读取失败"

    current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    last_hash = ""
    if os.path.isfile(marker_path):
        try:
            with open(marker_path, "r", encoding="utf-8") as f:
                last_hash = f.read().strip()
        except (OSError, ValueError):
            last_hash = ""
    if current_hash == last_hash:
        return None, "无新内容"

    pattern = re.compile(r"(?m)^### \d{4}-\d{2}-\d{2}.*$")
    positions = [m.start() for m in pattern.finditer(content)]
    new_entries = []
    for idx, pos in enumerate(positions):
        end = positions[idx + 1] if idx + 1 < len(positions) else len(content)
        entry = content[pos:end].strip()
        if "做了什么" in entry or "为什么根因" in entry or "有效方法" in entry:
            new_entries.append(entry)

    if not new_entries:
        write_marker_fn(current_hash)
        return None, "无有效新条目"
    return new_entries, current_hash


def _persist_unique_triples(triples_all, current_hash):
    """三元组去重后写入共享库（持锁），返回新增数量"""
    with _TRIPLE_STORE_LOCK:
        store = _load_triple_store()
        existing_keys = {
            (t.get("subject", ""), t.get("predicate", ""), t.get("object", ""))
            for t in store.get("triples", [])
        }
        added = 0
        for t in triples_all:
            key = (t["subject"], t["predicate"], t["object"])
            if key in existing_keys:
                continue
            existing_keys.add(key)
            store.setdefault("triples", []).append({
                "subject": t["subject"], "predicate": t["predicate"],
                "object": t["object"], "source": "ai_decisions.md",
                "extracted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            added += 1
        if added > 0:
            store["built_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _save_triple_store(store)
        _write_ai_decisions_triple_marker(current_hash)
    return added


def extract_triples_from_ai_decisions(batch: int = _TRIPLE_BATCH) -> Dict[str, object]:
    """从 ai_decisions.md 抽取 GraphRAG 三元组（Layer B，predicate 含 为什么/根因）。

    复用 A 的内容哈希增量（独立 marker）。无 key/离线/DEGRADED|OFFLINE 模式 时降级跳过。
    写库复用共享 _TRIPLE_STORE_LOCK（与经验箱三元组库同一文件，防并发覆盖丢失）。
    """
    new_entries, current_hash = _load_new_decision_entries(
        _AI_DECISIONS_TRIPLE_MARKER, _write_ai_decisions_triple_marker)
    if new_entries is None:
        return {"processed": 0, "triples": 0, "saved": 0, "info": current_hash}

    # 降级判定：无 key / 离线 / DEGRADED|OFFLINE 模式 → 跳过三元组
    try:
        from core.ai.ai_service import AIService
        _ai = AIService()
        ai_offline = (not getattr(_ai, "api_key", None)) or getattr(_ai, "_mode", "online") == "offline"
    except Exception:
        ai_offline = True
    if ai_offline or _ai_decisions_skip_triples():
        reason = "无key/离线" if ai_offline else f"模式={get_pipeline_mode()}"
        logger.info("[AI决策 GraphRAG] 降级跳过三元组抽取（%s）", reason)
        return {"processed": len(new_entries), "triples": 0, "saved": 0,
                "info": f"降级：{reason}，标记保留待 key 恢复后重提"}

    triples_all = _call_llm_for_triples(new_entries, batch, _ai)
    if not triples_all:
        _touch_ai_decisions_retry()
        return {"processed": len(new_entries), "triples": 0, "saved": 0,
                "info": "未解析到三元组（标记保留，冷却后重试）"}

    added = _persist_unique_triples(triples_all, current_hash)
    logger.info("[AI决策 GraphRAG] 处理 %d 条, 解析 %d 个, 新增 %d 个",
                len(new_entries), len(triples_all), added)
    return {"processed": len(new_entries), "triples": len(triples_all), "saved": added}


def _call_llm_for_triples(new_entries, batch, ai_svc):
    """分批调用 LLM 抽取三元组，返回三元组列表（空列表表示失败/冷却）"""
    triples_all: List[Dict[str, str]] = []
    chunks = 0
    for ci in range(0, len(new_entries), batch):
        if chunks >= _TRIPLE_MAX_CHUNKS:
            break
        if not _ai_decisions_retry_ready():
            return []
        chunk = new_entries[ci:ci + batch]
        chunks += 1
        try:
            user_prompt = ("请为以下 AI 改动决策条目抽取三元组（JSON数组）：\n\n"
                           + "\n\n---\n\n".join(chunk))
            reply = ai_svc.chat(_AI_DECISION_TRIPLE_PROMPT, user_prompt,
                                temperature=0.2, max_tokens=1500)
            triples_all.extend(_parse_triples(reply))
        except Exception as e:
            logger.error("[AI决策 GraphRAG] DeepSeek 调用异常(块%d): %s", chunks, e)
            _touch_ai_decisions_retry()
            break
    return triples_all


# ---------------------------------------------------------------------------
# AI 决策独立文件监听（与经验箱监听并列；零依赖 mtime 轮询，15 秒）
# ---------------------------------------------------------------------------
_ai_decisions_watcher_thread = None
_ai_decisions_watcher_lock = threading.Lock()
_ai_decisions_watcher_stop = threading.Event()


def start_ai_decisions_watcher(interval: int = 15) -> bool:
    """启动 ai_decisions.md 文件监听线程（与经验箱监听并列，互补不冲突）。"""
    global _ai_decisions_watcher_thread
    if not os.path.isfile(_AI_DECISIONS_PATH):
        logger.warning("[AI决策监听] 目标文件不存在，跳过启动: %s", _AI_DECISIONS_PATH)
        return False
    with _ai_decisions_watcher_lock:
        if _ai_decisions_watcher_thread is not None and _ai_decisions_watcher_thread.is_alive():
            logger.debug("[AI决策监听] 监听线程已在运行")
            return False
        _ai_decisions_watcher_stop.clear()
        _ai_decisions_watcher_thread = threading.Thread(
            target=_ai_decisions_watch_loop,
            args=(interval,),
            name="ai_decisions_watcher",
            daemon=True,
        )
        _ai_decisions_watcher_thread.start()
        logger.info("[AI决策监听] 已启动 ai_decisions 监听线程（间隔 %d 秒）", interval)
        return True


def stop_ai_decisions_watcher() -> None:
    """停止 ai_decisions 监听线程。"""
    global _ai_decisions_watcher_thread
    with _ai_decisions_watcher_lock:
        if _ai_decisions_watcher_thread is not None and _ai_decisions_watcher_thread.is_alive():
            _ai_decisions_watcher_stop.set()
            _ai_decisions_watcher_thread.join(timeout=5)
            logger.info("[AI决策监听] 已停止监听线程")
        _ai_decisions_watcher_thread = None


def _ai_decisions_watch_loop(interval: int) -> None:
    """监听主循环：mtime 变化即触发卡片+三元组同步（A 的哈希做真实增量判定）。"""
    logger.info("[AI决策监听] 监听循环启动，监控: %s", _AI_DECISIONS_PATH)
    last_mtime = 0.0
    while not _ai_decisions_watcher_stop.is_set():
        try:
            if os.path.isfile(_AI_DECISIONS_PATH):
                mtime = os.path.getmtime(_AI_DECISIONS_PATH)
                if mtime != last_mtime:
                    last_mtime = mtime
                    try:
                        r = extract_from_ai_decisions()
                        if r.get("saved", 0) > 0:
                            logger.info("[AI决策监听] 提取 %d 条决策, 保存 %d 张卡片",
                                        r.get("new_entries", 0), r.get("saved", 0))
                        try:
                            tr = extract_triples_from_ai_decisions()
                            if tr.get("saved", 0) > 0:
                                logger.info("[AI决策监听] GraphRAG 新增 %d 个三元组", tr.get("saved", 0))
                        except Exception as e:
                            logger.error("[AI决策监听] 三元组抽取异常: %s", e, exc_info=True)
                    except Exception as e:
                        logger.error("[AI决策监听] 同步异常: %s", e, exc_info=True)
        except OSError as e:
            logger.debug("[AI决策监听] 读取文件状态失败: %s", e)
        _ai_decisions_watcher_stop.wait(interval)
    logger.info("[AI决策监听] 监听循环已退出")
