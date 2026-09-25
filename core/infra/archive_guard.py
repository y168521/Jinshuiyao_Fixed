# -*- coding: utf-8 -*-
"""
金水谣 — 历史档案清理统一守卫（JS-20260925-06）

背景（真实事故，不要重演）:
    1. 金水谣数据/predictions.json 是「彩票预测历史复盘档案」，每条含
       actual / prize_tier / prize_status 等开奖回填字段，是长期资产。
       但 core/infra/scheduler.py::_task_data_maintenance 把它当缓存，
       写了 preds_data[-200:] 硬截 —— 3258 条一夜变成 200 条，丢 3058 条。
    2. 金水谣数据/agent_memory/vector_index.json 同样被 _save_entries 里的
       entries[-200:] 硬截，长期只留 200 条，加一条就丢一条。

根因三连：
    把档案当缓存 + 硬编码魔数 200 + 没有「条数骤降」保护。

本模块是「档案清理」的唯一真源。任何清理历史档案的调用点都必须走 trim_archive()，
禁止在任何地方再写一份 [:-N] / [-N:] 尾部截断。

Usage:
    from core.infra.archive_guard import trim_archive

    kept, before, after, blocked = trim_archive(
        records, keep_days=1095, max_records=50000, label="预测档案")
    if blocked:
        # 触发骤降保护：必须放弃写入，保留原文件
        ...
    elif after != before:
        safe_write_json(path, kept)
"""

import logging
import time
from datetime import datetime
from typing import List, Optional, Tuple

logger = logging.getLogger("jinshuiyao.archive_guard")

# 单次清理后条数不得低于清理前的该比例；否则视为异常骤降，放弃写入并告警。
# 理由：正常的档案清理是渐进的（每天淘汰最旧的一批），不可能一次砍掉一半以上。
ARCHIVE_SHRINK_GUARD_RATIO = 0.5

# 默认按时间保留 3 年。历史档案优先按「时间」淘汰，而不是按「条数」。
DEFAULT_ARCHIVE_KEEP_DAYS = 1095

_TS_KEYS = ("timestamp", "time", "date", "draw_date", "created_at")


def extract_record_ts(item) -> Optional[float]:
    """从一条记录里提取时间戳（秒）。

    取不到返回 None —— 调用方视为「必须保留」：
    日期缺失不能成为删除历史的理由，宁可留不可删。
    """
    if not isinstance(item, dict):
        return None
    for key in _TS_KEYS:
        val = item.get(key)
        if val is None or val == "":
            continue
        try:
            if isinstance(val, bool):
                continue
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, str):
                return datetime.fromisoformat(val.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError, OverflowError):
            continue
    return None


def trim_archive(
    records: List[dict],
    keep_days: int = DEFAULT_ARCHIVE_KEEP_DAYS,
    max_records: Optional[int] = None,
    now: Optional[float] = None,
    label: str = "档案",
) -> Tuple[List[dict], int, int, bool]:
    """按时间保留历史档案，并保证条数不骤降。

    Args:
        records:     待清理的记录列表（元素应为 dict；非 dict 一律保留）
        keep_days:   按时间保留多少天；超出部分淘汰
        max_records: 条数兜底上限（防文件无限膨胀）。None 表示不限条数
        now:         当前时间戳（秒），便于测试注入
        label:       档案名，仅用于日志

    Returns:
        (kept, before, after, blocked)
        blocked=True 表示触发骤降保护：调用方必须放弃写入、保留原文件，
        而不是写入截断后的结果。此时 kept == records（原样返回）。
    """
    before = len(records)
    if before == 0:
        return records, 0, 0, False
    if now is None:
        now = time.time()

    cutoff = now - keep_days * 86400 if keep_days is not None else None

    kept = records
    if cutoff is not None:
        kept = [it for it in records
                if (ts := extract_record_ts(it)) is None or ts >= cutoff]

    if max_records is not None and len(kept) > max_records:
        kept = kept[-max_records:]

    after = len(kept)
    floor = before * ARCHIVE_SHRINK_GUARD_RATIO
    if after < floor:
        logger.error(
            "[档案守卫] %s 条数骤降保护触发：%d -> %d（低于 %d），放弃本次写入",
            label, before, after, int(floor),
        )
        return records, before, before, True
    return kept, before, after, False
