# -*- coding: utf-8 -*-
"""金水谣系统 - 核心内核模块

提供跨子系统的基础设施与核心能力：
- AIService: 统一AI服务层（DeepSeek等多供应商）
- JinshuiyaoAgent: 智能AI体（自然语言交互、子系统调度）
- Theme: 公共GUI主题配置
- registry: 子系统域注册表
- context: 子系统上下文隔离
- 运行模式管理: get_mode/set_mode/get_mode_info (online/offline)
"""

from .ai_service import AIService, get_mode, set_mode, get_mode_info, auto_detect_mode
from .theme import Theme

# 延迟导入：避免循环依赖（AI Agent 可能引用各子系统）


def get_agent():
    """延迟获取 JinshuiyaoAgent 实例，避免导入时循环依赖。"""
    from .ai_agent import JinshuiyaoAgent
    return JinshuiyaoAgent()


__all__ = ["AIService", "Theme", "get_agent", "get_mode", "set_mode", "get_mode_info", "auto_detect_mode"]
