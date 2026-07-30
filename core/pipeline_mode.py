# -*- coding: utf-8 -*-
"""AI 决策同步管线模式控制

从 core/auto_knowledge.py 拆出的独立模块，负责：
  1. 多模式容错状态机（NORMAL/DEGRADED/OFFLINE/OVERRIDE）
  2. 模式切换与查询
  3. 三元组抽取降级判断

模式说明：
  NORMAL   — 默认：卡片 + 三元组全量同步
  DEGRADED — DeepSeek 限流/不稳：仍写卡片，跳过三元组
  OFFLINE  — 无网络/无 key：仅本地卡片
  OVERRIDE — 紧急豁免：门禁只警告不阻断

使用方式：
    from core.pipeline_mode import set_pipeline_mode, get_pipeline_mode
"""

import logging

logger = logging.getLogger(__name__)

_PIPELINE_MODE = "NORMAL"
_PIPELINE_MODES = ("NORMAL", "DEGRADED", "OFFLINE", "OVERRIDE")


def set_pipeline_mode(mode: str) -> str:
    """设置 AI 决策同步管线模式（应对突发情况）。返回实际生效模式。"""
    global _PIPELINE_MODE
    m = str(mode).upper()
    if m not in _PIPELINE_MODES:
        logger.warning("[AI决策] 未知模式 %s，保持 %s", m, _PIPELINE_MODE)
        return _PIPELINE_MODE
    _PIPELINE_MODE = m
    logger.info("[AI决策] 管线模式切换为 %s", m)
    return _PIPELINE_MODE


def get_pipeline_mode() -> str:
    """读取当前管线模式。"""
    return _PIPELINE_MODE


def should_skip_triples() -> bool:
    """当前模式是否应跳过三元组抽取（DEGRADED/OFFLINE 时跳过，卡片仍写）。"""
    return _PIPELINE_MODE in ("DEGRADED", "OFFLINE")
