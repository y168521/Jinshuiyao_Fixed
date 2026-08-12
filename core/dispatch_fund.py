# -*- coding: utf-8 -*-
"""基金领域调度器

从 core/ai_agent.py 拆出（债务-012 接线），负责基金分析/推荐/行情/回测的调度。
完全遵循 stock/football 的薄委托模式：fetch → analyze → generate 三步流水线。
"""

import logging

logger = logging.getLogger(__name__)

from core.agent_formatters import format_fund_result as _fmt_fund


def dispatch_fund(agent, action: str, target: str) -> str:
    """调度基金子系统"""
    domain = agent._get_domain("fund")
    if not domain or not agent._initialized.get("fund"):
        return "基金子系统未就绪，请稍后再试。"

    try:
        if action == "backtest":
            result = domain.backtest()
            if result.get("success"):
                summary = result.get("report", {}).get("summary", "")
                return f"【基金回测】\n{summary}" if summary else "基金回测完成"
            return f"基金回测失败：{result.get('message', '')}"

        elif action == "quote":
            fetch_result = domain.fetch()
            if fetch_result.get("success"):
                return _fmt_fund(fetch_result, None, None, mode="quote")
            return f"获取基金行情失败：{fetch_result.get('message', '')}"

        else:
            fetch_result = domain.fetch()
            if not fetch_result.get("success"):
                return f"获取基金数据失败：{fetch_result.get('message', '')}"
            analysis = domain.analyze(fetch_result.get("data", {}))
            gen_result = domain.generate(params=analysis, top_n=10)
            return _fmt_fund(fetch_result, analysis, gen_result)
    except Exception as e:
        logger.error("[agent] 基金调度异常: %s", e)
        return f"基金系统异常：{e}"