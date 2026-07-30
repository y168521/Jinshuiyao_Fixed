# -*- coding: utf-8 -*-
"""足彩领域调度器

从 core/ai_agent.py 拆出，负责足球赛事/赔率/推荐等功能的调度。
"""

import logging

logger = logging.getLogger(__name__)

from core.agent_formatters import (
    format_football_result as _fmt_football,
    format_football_odds as _fmt_football_odds,
)


def dispatch_football(agent, action: str, target: str) -> str:
    """调度足彩子系统"""
    domain = agent._get_domain("football")
    if not domain or not agent._initialized.get("football"):
        return "足彩子系统未就绪，请稍后再试。"

    try:
        if action in ("matches", "recommend"):
            fetch_result = domain.fetch()
            if fetch_result.get("success"):
                generate_result = domain.generate()
                return _fmt_football(fetch_result, generate_result)
            return f"获取赛事数据失败：{fetch_result.get('message', '')}"

        elif action == "odds":
            fetch_result = domain.fetch()
            if fetch_result.get("success"):
                return _fmt_football_odds(fetch_result)
            return "获取赔率数据失败"

        else:
            fetch_result = domain.fetch()
            if fetch_result.get("success"):
                generate_result = domain.generate()
                return _fmt_football(fetch_result, generate_result)
            return "足彩系统操作失败"
    except Exception as e:
        logger.error("[agent] 足彩调度异常: %s", e)
        return f"足彩系统异常：{e}"
