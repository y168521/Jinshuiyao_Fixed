# -*- coding: utf-8 -*-
"""视频文案提取领域调度器

从 core/ai_agent.py 拆出，负责视频URL检测/文案提取/内容提炼等功能的调度。
"""

import logging

logger = logging.getLogger(__name__)

from core.agent_video_handler import detect_urls, handle_video_url
from core.agent_formatters import (
    format_extracted_result as _fmt_extracted,
    format_refined_result as _fmt_refined,
)


def dispatch_video(agent, action: str, target: str, user_input: str = "") -> str:
    """调度视频文案提取子系统"""
    try:
        urls = detect_urls(user_input)
        auto_archive = ("存入知识库" in user_input or "归档" in user_input or
                       "保存" in user_input)

        if urls:
            url = urls[0]
            return handle_video_url(agent, url, auto_archive=auto_archive)

        if action == "extract":
            if agent._last_extracted:
                return _fmt_extracted(agent._last_extracted)
            return (
                "【视频文案提取】\n"
                "请提供视频链接，支持以下平台：\n"
                "  - 抖音 / TikTok\n"
                "  - B站 (bilibili)\n"
                "  - 快手\n"
                "  - 小红书\n"
                "  - 微信视频号\n"
                "  - YouTube（需安装yt-dlp）\n\n"
                "示例：发送 '提取视频 https://www.douyin.com/video/xxx'\n"
                "也可以通过总控台的「视频文案提取」功能直接粘贴链接���"
            )

        elif action == "refine":
            if agent._last_extracted:
                try:
                    refiner = agent._get_content_refiner()
                    if refiner:
                        refined = refiner.refine(agent._last_extracted)
                        return _fmt_refined(refined)
                except Exception as e:
                    logger.error("[agent] 内容提炼失败: %s", e)
                    return f"内容提炼失败：{e}"
            return (
                "【内容提炼】\n"
                "请先提取视频文案，然后我可以帮你：\n"
                "  - 提取核心观点和关键信息\n"
                "  - 生成知识摘要\n"
                "  - 识别文案技巧\n"
                "  - 提取数据和事实\n"
                "  - 自动分类标签\n\n"
                "请先发送视频链接进行提取。"
            )

        else:
            return (
                "【视频文案提取功能】\n"
                "发送视频链接即可自动提取文案内容。\n"
                "支持：抖音、B站、快手、小红书、微信视频号等平台。\n\n"
                "提取后可以说'存入知识库'或'归档'来保存内容。"
            )
    except Exception as e:
        logger.error("[agent] 视频提取调度异常: %s", e)
        return f"视频提取系统异常：{e}"
