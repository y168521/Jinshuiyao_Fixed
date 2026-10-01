# -*- coding: utf-8 -*-
"""彩票领域调度器

从 core/ai/ai_agent.py 拆出，负责彩票预测/历史查询等功能的调度。
"""

import logging

logger = logging.getLogger(__name__)

from core.ai.agent_formatters import (
    format_lottery_result as _fmt_lottery,
    format_lottery_result_detailed as _fmt_lottery_detail,
)


def is_direct_lottery_request(agent, text: str) -> bool:
    """判断是否为直接的彩票预测请求

    例如："今天双色球"、"来一注大乐透"等
    """
    direct_patterns = [
        "今天双色球", "今天大乐透", "今天3d", "今天排列三",
        "来一注", "给我预测", "直接出号", "出号",
        "今天的", "今日", "今晚",
    ]
    text_lower = text.lower()
    for pattern in direct_patterns:
        if pattern.lower() in text_lower:
            return True
    return False


def _try_predict(domain, lots=None):
    """尝试 generate，失败则降级 predict_full，返回格式化结果或 None。"""
    try:
        result = domain.generate(lots=lots)
    except Exception:
        result = None
    if result and result.get("status") == "ok":
        return _fmt_lottery_detail(result)
    try:
        result = domain.predict_full(lots=lots)
    except Exception:
        result = None
    if result and result.get("status") == "ok":
        return _fmt_lottery(result)
    return None


_LOT_MAP = {"双色球": "双色球", "大乐透": "大乐透", "福彩3D": "福彩3D",
            "排列三": "排列三", "七乐彩": "七乐彩", "七星彩": "七星彩", "快乐8": "快乐8"}


def dispatch_lottery(agent, action: str, target: str, user_input: str = "") -> str:
    """调度彩票子系统"""
    domain = agent._get_domain("lottery")
    if not domain or not agent._initialized.get("lottery"):
        return "彩票子系统未就绪，请稍后再试。"
    try:
        if action == "predict" or is_direct_lottery_request(agent, user_input):
            lot_name = _LOT_MAP.get(target, target)
            lots = [lot_name] if target != "全部彩种" and lot_name != "全部彩种" else None
            return _try_predict(domain, lots) or "预测生成失败，请稍后再试。"
        if action == "predict_all":
            return _try_predict(domain) or "预测生成失败，请稍后再试。"
        if action == "history":
            result = domain.fetch()
            if result.get("success"):
                return f"已获取最新开奖数据：{result.get('message', '')}"
            return "获取开奖数据失败"
        return _try_predict(domain) or "操作执行失败"
    except Exception as e:
        logger.error("[agent] 彩票调度异常: %s", e)
        return f"彩票系统异常：{e}"
