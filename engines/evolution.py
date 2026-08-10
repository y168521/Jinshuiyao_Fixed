# -*- coding: utf-8 -*-
"""金水谣系统 - L3自适应进化引擎

让系统从运行经验中学习，持续自我优化。

核心能力:
1. 规则升级管线 (RuleEngine)      - 从重复出现的问题中提炼永久规则
2. 经验知识沉淀 (ExperienceMiner) - 从健康日志中挖掘知识并转化为知识库卡片
3. 自适应反馈闭环 (AdaptiveFeedback) - 增强复盘学习效果，CUSUM统计 + 策略建议
4. 进化管理器 (EvolutionManager)  - 统一管理所有进化子模块的顶层入口

数据文件:
- 金水谣数据/evolution_rules.json   - 规则持久化存储
- 金水谣数据/evolution_state.json   - 进化引擎状态快照
- 金水谣数据/evolution_patterns.json - 已挖掘的经验模式缓存
"""

import os
import re
import json
import uuid
import math
import logging
import threading
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 安全JSON读写（带内回退，以防safe_json模块加载失败）
# ---------------------------------------------------------------------------
try:
    from utils.safe_json import safe_write_json, safe_load_json
except ImportError:
    logger.warning("无法导入utils.safe_json，使用内置安全读写回退")

    def safe_write_json(filepath, data):
        """内置安全写入回退：先写临时文件再原子替换"""
        parent = os.path.dirname(filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)
        import tempfile
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp", dir=parent, prefix=".evolution_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Windows下原子替换：先删再重命名
            if os.path.exists(filepath):
                os.replace(tmp_path, filepath)
            else:
                os.rename(tmp_path, filepath)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def safe_load_json(filepath, default=None):
        """内置安全加载回退：支持损坏文件恢复"""
        if default is None:
            default = {}
        if not os.path.exists(filepath):
            return default
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error("加载文件失败 [%s]: %s，返回默认值", filepath, e)
            return default


# ---------------------------------------------------------------------------
# 辅助常量
# ---------------------------------------------------------------------------
_SEVERITY_LEVELS = {"info": 1, "warn": 2, "critical": 3}

_DEFAULT_RULE_THRESHOLD = 3  # 同一错误出现几次后升级为规则

from engines.evolution_rule import RuleEngine
from engines.evolution_experience import ExperienceMiner
from engines.evolution_feedback import AdaptiveFeedback
from engines.evolution_manager import EvolutionManager
