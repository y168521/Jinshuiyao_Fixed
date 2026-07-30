# -*- coding: utf-8 -*-
"""股票领域调度器

从 core/ai_agent.py 拆出，负责股票行情/选股/技术分析等功能的调度。
"""

import logging

logger = logging.getLogger(__name__)

from core.agent_formatters import (
    format_stock_result as _fmt_stock,
    format_stock_picks as _fmt_stock_picks,
    format_stock_technical as _fmt_stock_tech,
)


def dispatch_stock(agent, action: str, target: str) -> str:
    """调度股票子系统"""
    domain = agent._get_domain("stock")
    if not domain or not agent._initialized.get("stock"):
        return "股票子系统未就绪，请稍后再试。"

    try:
        if action == "index":
            symbols = ["sh000001", "sz399001", "sh000300"]
            fetch_result = domain.fetch(symbols=symbols)
            if fetch_result.get("success"):
                analysis = domain.analyze(fetch_result["data"], symbols=symbols)
                return _fmt_stock(fetch_result, analysis, target)
            return f"获取行情失败：{fetch_result.get('message', '')}"

        elif action == "pick":
            fetch_result = domain.fetch(symbols=["sh000001"])
            if fetch_result.get("success"):
                analysis = domain.analyze(fetch_result["data"])
                picks = domain.generate(params=analysis, top_n=10)
                return _fmt_stock_picks(picks)
            return "获取数据失败，无法生成选股推荐"

        elif action == "technical":
            fetch_result = domain.fetch(symbols=["sh000001"])
            if fetch_result.get("success"):
                analysis = domain.analyze(fetch_result["data"])
                return _fmt_stock_tech(analysis)
            return "获取数据失败"

        else:
            fetch_result = domain.fetch()
            if fetch_result.get("success"):
                analysis = domain.analyze(fetch_result["data"])
                return _fmt_stock(fetch_result, analysis, "综合")
            return "股票系统操作失败"
    except Exception as e:
        logger.error("[agent] 股票调度异常: %s", e)
        return f"股票系统异常：{e}"
