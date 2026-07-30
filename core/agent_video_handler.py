# -*- coding: utf-8 -*-
"""金水谣引擎 - 视频文案提取与URL处理模块

从 ai_agent.py 的 URL检测/视频提取/归档方法拆出。
纯函数或接收 agent 实例的模块级函数。
"""

import logging
import re

from core.intent_rules import VIDEO_PLATFORM_KEYWORDS
from core.agent_formatters import format_extracted_result as _fmt_extracted, format_refined_result as _fmt_refined

logger = logging.getLogger(__name__)


def detect_urls(text: str) -> list:
    """检测文本中的URL

    Args:
        text: 用户输入文本

    Returns:
        URL列表
    """
    url_pattern = r'https?://[^\s\u4e00-\u9fa5，。！？；：""''（）【】、]+'
    urls = re.findall(url_pattern, text, re.IGNORECASE)
    return urls


def detect_video_platform_keywords(text: str) -> bool:
    """检测是否包含视频平台关键词

    Args:
        text: 用户输入文本

    Returns:
        是否包含视频平台关键词
    """
    text_lower = text.lower()
    for kw in VIDEO_PLATFORM_KEYWORDS:
        if kw.lower() in text_lower:
            return True
    return False


def extract_and_archive_url(agent, url: str, auto_archive: bool = True) -> dict:
    """提取URL内容并归档到知识库

    Args:
        agent: JinshuiyaoAgent 实例
        url: 视频/网页链接
        auto_archive: 是否自动归档到知识库

    Returns:
        处理结果字典
    """
    result = {
        "url": url,
        "extracted": None,
        "refined": None,
        "archived": False,
        "card_id": None,
        "error": None,
    }

    try:
        extractor = agent._get_video_extractor()
        if not extractor:
            result["error"] = "视频提取器未就绪"
            return result

        extracted = extractor.extract(url)
        result["extracted"] = extracted
        agent._last_extracted = extracted

        refiner = agent._get_content_refiner()
        if refiner:
            refined = refiner.refine(extracted)
            result["refined"] = refined

            if auto_archive:
                from core.agent_knowledge_archiver import archive_refined_to_knowledge
                card_id = archive_refined_to_knowledge(agent, refined)
                if card_id:
                    result["archived"] = True
                    result["card_id"] = card_id

    except Exception as e:
        logger.error("[video_handler] URL提取归档异常: %s", e)
        result["error"] = str(e)

    return result


def handle_video_url(agent, url: str, auto_archive: bool = False) -> str:
    """处理视频URL，提取内容并可选归档

    Args:
        agent: JinshuiyaoAgent 实例
        url: 视频链接
        auto_archive: 是否自动归档

    Returns:
        格式化的结果文本
    """
    try:
        result = extract_and_archive_url(agent, url, auto_archive=auto_archive)

        if result.get("error"):
            return f"【视频提取失败】\n{result['error']}"

        extracted = result.get("extracted", {})
        refined = result.get("refined", {})
        archived = result.get("archived", False)
        card_id = result.get("card_id", "")

        lines = ["【视频提取成功】\n"]

        platform = extracted.get("platform_name", extracted.get("platform", "未知平台"))
        title = extracted.get("title", "无标题")
        lines.append(f"  平台: {platform}")
        lines.append(f"  标题: {title}")

        if extracted.get("author"):
            lines.append(f"  作者: {extracted['author']}")

        if refined:
            lines.append(f"\n【内容提炼】")
            summary = refined.get("summary", "")
            if summary:
                lines.append(f"  摘要: {summary[:200]}")

            key_points = refined.get("key_points", [])
            if key_points:
                lines.append(f"\n  核心要点:")
                for i, point in enumerate(key_points[:5], 1):
                    lines.append(f"    {i}. {point}")

            tags = refined.get("tags", [])
            if tags:
                lines.append(f"\n  标签: {', '.join(tags[:8])}")

        if archived:
            lines.append(f"\n【已归档到知识库】")
            lines.append(f"  卡片ID: {card_id}")
        else:
            lines.append(f"\n  💡 说'存入知识库'或'归档'可将内容保存到知识库")

        return "\n".join(lines)

    except Exception as e:
        logger.error("[video_handler] 处理视频URL异常: %s", e)
        return f"处理视频链接失败：{e}"
