# -*- coding: utf-8 -*-
"""经验收集箱知识提取模块

从经验收集箱（跨AI共享经验文件）中提取知识卡片和 GraphRAG 三元组，
支持文件监听近实时同步。

拆分自 core/infra/auto_knowledge.py，保持向后兼容。

核心能力：
  1. extract_from_experience_box — 内容哈希增量提取知识卡片
  2. extract_triples_from_experience_box — GraphRAG 三元组抽取
  3. start/stop_experience_box_watcher — 文件监听线程
"""

import os
import re
import time
import hashlib
import threading
import logging
import json
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 经验类关键词（比预测/分析更广泛）
_EXPERIENCE_KEYWORDS = [
    "解决", "修复", "方法", "步骤", "配置", "设置", "安装",
    "原因", "因为", "导致", "关键是", "注意", "避免", "推荐",
    "最佳", "优化", "改进", "技巧", "经验", "教训",
]

# 已处理标记文件（记录上次处理到第几行）
_PROCESSED_MARKER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "金水谣数据", "log", ".kb_last_processed_line"
)

_EXPERIENCE_BOX_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "金水谣数据", "log", "经验收集箱.md"
)
_EXPERIENCE_BOX_MARKER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "金水谣数据", "log", ".expbox_hash"
)

# 三元组"未解析"重试冷却（防止 DeepSeek 临时抽空/异常时高频空转烧钱，
# 同时保证该批经验不会被标记吞掉——冷却期内 watcher 重入直接跳过）
_TRIPLE_RETRY_MARKER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "金水谣数据", "log", ".triple_retry_cooldown"
)
_TRIPLE_RETRY_COOLDOWN_SEC = 600


def _triple_retry_ready() -> bool:
    """距上次"未解析"尝试超过冷却期则允许重试。"""
    if not os.path.isfile(_TRIPLE_RETRY_MARKER):
        return True
    try:
        return time.time() - os.path.getmtime(_TRIPLE_RETRY_MARKER) > _TRIPLE_RETRY_COOLDOWN_SEC
    except OSError:
        return True


def _touch_triple_retry() -> None:
    """记录一次"未解析"尝试时间（原子写）。"""
    try:
        os.makedirs(os.path.dirname(_TRIPLE_RETRY_MARKER), exist_ok=True)
        tmp = _TRIPLE_RETRY_MARKER + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        os.replace(tmp, _TRIPLE_RETRY_MARKER)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# GraphRAG 三元组基础设施（从 knowledge/triple_store.py 导入）
# ---------------------------------------------------------------------------
from knowledge.triple_store import (
    _TRIPLE_STORE_LOCK,
    _TRIPLE_MARKER,
    _TRIPLE_BATCH,
    _TRIPLE_MAX_CHUNKS,
    _TRIPLE_SYSTEM_PROMPT,
    load_triple_store as _load_triple_store,
    save_triple_store as _save_triple_store,
    write_triple_marker as _write_triple_marker,
    parse_triples as _parse_triples,
)


# ---------------------------------------------------------------------------
# 经验收集箱知识提取（跨AI共享经验 → 知识库）
# ---------------------------------------------------------------------------

def _write_expbox_marker(hash_str: str) -> None:
    """原子写入经验收集箱内容哈希标记（增量检测用）。

    用 sha256 全文哈希代替旧的字节大小：无论文件变长/变短/编辑，
    哈希变化即触发同步，根治"字节数变小后 current_size<=last_size 永不触发"的卡死。
    """
    try:
        os.makedirs(os.path.dirname(_EXPERIENCE_BOX_MARKER), exist_ok=True)
        tmp = _EXPERIENCE_BOX_MARKER + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(hash_str)
        os.replace(tmp, _EXPERIENCE_BOX_MARKER)
    except OSError:
        pass


_expbox_extract_lock = threading.Lock()

_ENTRY_KEYWORDS = ("做了什么", "有效方法", "问题", "根因", "方案", "教训")
_ENTRY_PATTERN = re.compile(r"(?m)^#{2,3} \d{4}-\d{2}-\d{2}.*$")


def _read_expbox_content() -> str:
    """读取经验收集箱全文，文件不存在或读取失败返回空串。"""
    if not os.path.isfile(_EXPERIENCE_BOX_PATH):
        return ""
    try:
        with open(_EXPERIENCE_BOX_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _check_hash_changed(content: str, marker_path: str) -> tuple:
    """计算当前哈希并与标记文件比对。返回 (changed: bool, current_hash: str)。"""
    current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    last_hash = ""
    if os.path.isfile(marker_path):
        try:
            with open(marker_path, "r", encoding="utf-8") as f:
                last_hash = f.read().strip()
        except (OSError, ValueError):
            last_hash = ""
    return current_hash != last_hash, current_hash


def _split_exp_entries(content: str) -> List[str]:
    """按带日期的经验标题切分条目，返回有效条目列表。"""
    positions = [m.start() for m in _ENTRY_PATTERN.finditer(content)]
    entries = []
    for idx, pos in enumerate(positions):
        end = positions[idx + 1] if idx + 1 < len(positions) else len(content)
        entry = content[pos:end].strip()
        if any(k in entry for k in _ENTRY_KEYWORDS):
            entries.append(entry)
    return entries


def _build_card_from_entry(entry: str) -> dict:
    """从单条经验文本构建知识卡片 dict。"""
    heading = entry.split("\n", 1)[0].replace("###", "", 1).replace("##", "", 1).strip()
    title = heading[:40]
    return {
        "title": f"[跨AI经验] {title}",
        "content": entry[:800],
        "subsystem": "global",
        "category": "skill",
        "tags": ["跨AI经验", "经验收集箱", "自动提取"],
        "effectiveness": 60,
        "engine_hook": "",
        "source": f"经验收集箱.md#{title}",
    }


def extract_from_experience_box() -> dict:
    """从经验收集箱中提取知识卡片。

    经验收集箱是所有外部AI工具（Qoder/豆包/TRAE/WorkBuddy等）
    写入的共享经验文件。本函数检测新增内容并转化为知识卡片。

    Returns
    -------
    dict
        提取统计: new_entries, extracted, saved
    """
    with _expbox_extract_lock:
        return _extract_from_experience_box_inner()


def _extract_from_experience_box_inner() -> dict:
    content = _read_expbox_content()
    if not content:
        if not os.path.isfile(_EXPERIENCE_BOX_PATH):
            return {"new_entries": 0, "extracted": 0, "saved": 0, "info": "经验收集箱不存在"}
        return {"new_entries": 0, "extracted": 0, "saved": 0, "info": "读取失败"}

    changed, current_hash = _check_hash_changed(content, _EXPERIENCE_BOX_MARKER)
    if not changed:
        return {"new_entries": 0, "extracted": 0, "saved": 0, "info": "无新内容"}

    new_entries = _split_exp_entries(content)
    if not new_entries:
        _write_expbox_marker(current_hash)
        return {"new_entries": 0, "extracted": 0, "saved": 0, "info": "无有效新条目"}

    from core.infra.auto_knowledge import AutoKnowledgeExtractor
    extractor = AutoKnowledgeExtractor()
    all_cards = [_build_card_from_entry(e) for e in new_entries]
    saved = extractor.save_cards(all_cards) if all_cards else 0
    _write_expbox_marker(current_hash)

    result = {
        "new_entries": len(new_entries),
        "extracted": len(all_cards),
        "saved": saved,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if all_cards:
        logger.info("经验收集箱提取: %d 条新经验, 保存 %d 张知识卡片", len(new_entries), saved)
    return result


# ---------------------------------------------------------------------------
# 经验收集箱文件监听（B：近实时触发同步，替代纯轮询）
# ---------------------------------------------------------------------------
# 零依赖实现：用 mtime 轮询近似文件监听（watchdog 需第三方包，本项目严守零依赖）。
# 间隔默认 15 秒，配合 A 的 sha256 内容哈希做真实增量判定，避免同秒多次改写抖动。
# scheduler 的 knowledge_extract(120分钟) 仍保留作三层兜底，二者互补不冲突。

_watcher_thread = None
_watcher_lock = threading.Lock()
_watcher_stop = threading.Event()


def start_experience_box_watcher(interval: int = 15) -> bool:
    """启动经验收集箱文件监听线程（轻量 mtime 轮询，零依赖）。

    监听 经验收集箱.md 的 mtime 变化，变化即触发 extract_from_experience_box()，
    实现"写完即同步"的近实时效果。比纯 120 分钟轮询更及时。

    Args:
        interval: 轮询间隔（秒），默认 15。

    Returns:
        bool: 是否成功启动（已在运行则返回 False）。
    """
    global _watcher_thread
    if not os.path.isfile(_EXPERIENCE_BOX_PATH):
        logger.warning("[经验监听] 目标文件不存在，跳过启动: %s", _EXPERIENCE_BOX_PATH)
        return False
    with _watcher_lock:
        if _watcher_thread is not None and _watcher_thread.is_alive():
            logger.debug("[经验监听] 监听线程已在运行")
            return False
        _watcher_stop.clear()
        _watcher_thread = threading.Thread(
            target=_experience_box_watch_loop,
            args=(interval,),
            name="expbox_watcher",
            daemon=True,
        )
        _watcher_thread.start()
        logger.info("[经验监听] 已启动经验收集箱监听线程（间隔 %d 秒）", interval)
        return True


def stop_experience_box_watcher() -> None:
    """停止经验收集箱监听线程。"""
    global _watcher_thread
    with _watcher_lock:
        if _watcher_thread is not None and _watcher_thread.is_alive():
            _watcher_stop.set()
            # join 确保旧线程真正退出，防止 stop→start 快速调用时
            # 新 start() 的 clear() 让旧线程误以为未停止而继续运行
            # 但不能 join 当前线程自身（会 RuntimeError）
            if _watcher_thread is not threading.current_thread():
                _watcher_thread.join(timeout=5)
            logger.info("[经验监听] 已停止监听线程")
        _watcher_thread = None


def _experience_box_watch_loop(interval: int) -> None:
    """监听主循环：检测 mtime 变化即触发同步（A 的哈希做真实增量判定）。"""
    logger.info("[经验监听] 监听循环启动，监控: %s", _EXPERIENCE_BOX_PATH)
    last_mtime = 0.0
    while not _watcher_stop.is_set():
        try:
            if os.path.isfile(_EXPERIENCE_BOX_PATH):
                mtime = os.path.getmtime(_EXPERIENCE_BOX_PATH)
                if mtime != last_mtime:
                    last_mtime = mtime
                    try:
                        result = extract_from_experience_box()
                        saved = result.get("saved", 0)
                        if saved > 0:
                            logger.info(
                                "[经验监听] 检测到更新，提取 %d 条新经验，保存 %d 张卡片",
                                result.get("new_entries", 0), saved,
                            )
                        # D：同步抽取 GraphRAG 三元组（独立标记，无 key/离线自动降级）
                        try:
                            triple_result = extract_triples_from_experience_box()
                            tsaved = triple_result.get("saved", 0)
                            if tsaved > 0:
                                logger.info(
                                    "[经验监听] GraphRAG 新增 %d 个三元组（解析 %d）",
                                    tsaved, triple_result.get("triples", 0),
                                )
                        except Exception as e:
                            logger.error("[经验监听] 三元组抽取异常: %s", e, exc_info=True)
                    except Exception as e:
                        logger.error("[经验监听] 同步异常: %s", e, exc_info=True)
        except OSError as e:
            logger.debug("[经验监听] 读取文件状态失败: %s", e)
        # 等待 interval 秒，或被停止信号立即唤醒
        _watcher_stop.wait(interval)
    logger.info("[经验监听] 监听循环已退出")


# ---------------------------------------------------------------------------
# GraphRAG 三元组抽取
# ---------------------------------------------------------------------------

def _check_ai_available():
    """检查 AIService 是否可用（有 key 且非离线）。返回 (ai, error_msg)。ai 可用时 error_msg 为 None。"""
    try:
        from core.ai.ai_service import AIService
        _ai = AIService()
        if not getattr(_ai, "api_key", None) or getattr(_ai, "_mode", "online") == "offline":
            logger.info("[GraphRAG] 无 API Key 或离线模式，跳过三元组抽取（降级，标记保留待 key 恢复后重提）")
            return None, "降级：无key/离线，标记未更新待重试"
        return _ai, None
    except Exception as e:
        logger.warning("[GraphRAG] AIService 初始化失败，跳过（标记保留待重试）: %s", e)
        return None, "AIService异常，标记未更新待重试"


def _call_triple_chunks(ai, new_entries: List[str], batch: int) -> tuple:
    """分块调 AI 抽取三元组。返回 (triples_all, chunks, early_return_info)。
    early_return_info 非 None 时表示需提前返回（冷却中/异常）。"""
    triples_all: List[Dict[str, str]] = []
    chunks = 0
    for ci in range(0, len(new_entries), batch):
        if chunks >= _TRIPLE_MAX_CHUNKS:
            break
        if not _triple_retry_ready():
            return triples_all, chunks, "三元组冷却中，标记保留待重试"
        chunk = new_entries[ci:ci + batch]
        chunks += 1
        try:
            user_prompt = "请为以下经验条目抽取三元组（JSON数组）：\n\n" + "\n\n---\n\n".join(chunk)
            reply = ai.chat(_TRIPLE_SYSTEM_PROMPT, user_prompt, temperature=0.2, max_tokens=1500)
            triples_all.extend(_parse_triples(reply))
        except Exception as e:
            logger.error("[GraphRAG] DeepSeek 调用异常(块%d): %s", chunks, e)
            _touch_triple_retry()
            break
    return triples_all, chunks, None


def _dedup_save_triples(triples_all: list, current_hash: str) -> int:
    """去重 + 写入三元组库（整段临界区加锁）。返回新增数。"""
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
                "subject": t["subject"],
                "predicate": t["predicate"],
                "object": t["object"],
                "source": "经验收集箱.md",
                "extracted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            added += 1
        if added > 0:
            store["built_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _save_triple_store(store)
        _write_triple_marker(current_hash)
    return added


def extract_triples_from_experience_box(batch: int = _TRIPLE_BATCH) -> dict:
    """从经验收集箱抽取 GraphRAG 三元组（D）。

    复用 A 的内容哈希标记判断是否已有新内容；仅对新条目分块调 DeepSeek 抽取三元组，
    写入 knowledge/graph_triples.json（去重置信）。无 key / 离线 / 熔断 时降级返回。

    Returns:
        dict: processed（处理经验条数）, triples（解析到的三元组数）, saved（新增落库数）
    """
    content = _read_expbox_content()
    if not content:
        if not os.path.isfile(_EXPERIENCE_BOX_PATH):
            return {"processed": 0, "triples": 0, "saved": 0, "info": "经验收集箱不存在"}
        return {"processed": 0, "triples": 0, "saved": 0, "info": "读取失败"}

    changed, current_hash = _check_hash_changed(content, _TRIPLE_MARKER)
    if not changed:
        return {"processed": 0, "triples": 0, "saved": 0, "info": "无新内容"}

    new_entries = _split_exp_entries(content)
    if not new_entries:
        _write_triple_marker(current_hash)
        return {"processed": 0, "triples": 0, "saved": 0, "info": "无有效新条目"}

    # 检查 AIService 可用性（无 key/离线 直接降级跳过，控成本）
    # ⚠ 降级时**不更新哈希标记**：否则 key 恢复后该批经验永远进不了图谱（真断链）。
    ai, err_msg = _check_ai_available()
    if ai is None:
        return {"processed": len(new_entries), "triples": 0, "saved": 0, "info": err_msg}

    triples_all, chunks, early_info = _call_triple_chunks(ai, new_entries, batch)
    if early_info:
        return {"processed": len(new_entries), "triples": 0, "saved": 0, "info": early_info}

    if not triples_all:
        _touch_triple_retry()
        return {"processed": len(new_entries), "triples": 0,
                "saved": 0, "info": "未解析到三元组（标记保留，冷却后重试）"}

    added = _dedup_save_triples(triples_all, current_hash)
    logger.info("[GraphRAG] 抽取三元组: 处理 %d 条经验(%d块), 解析 %d 个, 新增落库 %d 个",
                len(new_entries), chunks, len(triples_all), added)
    return {
        "processed": len(new_entries),
        "triples": len(triples_all),
        "saved": added,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
