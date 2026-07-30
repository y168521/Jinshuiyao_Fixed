# -*- coding: utf-8 -*-
"""金水谣系统 - MiroFish 万物知识库

知识记忆层，为预测引擎提供经验与灵感：
- MiroFishDB: 知识库管理器（PARA分类、领域标签、引擎钩子、有效性评分）
- AITestKnowledge: AI测试知识库（行业最佳实践、学习路径、Prompt模板）
"""

from .mirofish_db import MiroFishDB
from .ai_test_knowledge import AITestKnowledge

__all__ = ["MiroFishDB", "AITestKnowledge"]
