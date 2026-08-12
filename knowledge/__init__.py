# -*- coding: utf-8 -*-
"""金水谣系统 - MiroFish 万物知识库

知识记忆层，为预测引擎提供经验与灵感：
- MiroFishDB: 知识库管理器（PARA分类、领域标签、引擎钩子、有效性评分）
（AITestKnowledge 于 2026-08-12 批次B 移除包级导出：0 业务消费，仅测试引用，见 W63补71）
"""

from .mirofish_db import MiroFishDB

__all__ = ["MiroFishDB"]
