# -*- coding: utf-8 -*-
"""金水谣引擎 - 知识库归档模块

从 ai_agent.py 的 _archive_refined_to_knowledge 和 _infer_domain_from_content 拆出。
接收 agent 实例以访问知识库等。
"""

import logging

logger = logging.getLogger(__name__)


def archive_refined_to_knowledge(agent, refined_card: dict) -> str:
    """将提炼结果归档到知识库

    Args:
        agent: JinshuiyaoAgent 实例，用于访问知识库
        refined_card: ContentRefiner提炼的知识卡片

    Returns:
        卡片ID，失败返回None
    """
    try:
        db = agent._get_knowledge_db()
        if not db:
            return None

        title = refined_card.get("title", "无标题")
        summary = refined_card.get("summary", "")
        key_points = refined_card.get("key_points", [])
        data_points = refined_card.get("data_points", [])
        writing_techniques = refined_card.get("writing_techniques", [])
        tags = refined_card.get("tags", [])
        source_url = refined_card.get("source_url", "")
        source_platform = refined_card.get("source_platform", "")
        full_text = refined_card.get("full_text", "")

        content_parts = []
        if summary:
            content_parts.append(f"【摘要】{summary}")
        if key_points:
            content_parts.append("【核心要点】")
            for i, point in enumerate(key_points[:10], 1):
                content_parts.append(f"  {i}. {point}")
        if data_points:
            content_parts.append("【数据事实】")
            for point in data_points[:5]:
                content_parts.append(f"  - {point}")
        if writing_techniques:
            content_parts.append("【文案技巧】")
            for tech in writing_techniques[:5]:
                content_parts.append(f"  - {tech}")
        if full_text and len(full_text) > 500:
            content_parts.append(f"\n【全文】{full_text[:2000]}")
            if len(full_text) > 2000:
                content_parts.append("...(内容已截断)")

        content = "\n".join(content_parts)

        domain = infer_domain_from_content(full_text + " " + " ".join(tags))
        category = "resource"
        priority = 5

        source_desc = f"{source_platform} - {source_url}" if source_platform else source_url

        card_id = db.add_card(
            title=title[:80] if title else "视频知识卡片",
            content=content,
            category=category,
            domain=domain,
            tags=tags[:10],
            source=source_desc,
            priority=priority,
        )

        logger.info("[knowledge_archiver] 知识卡片已归档: %s", card_id)
        return card_id

    except Exception as e:
        logger.error("[knowledge_archiver] 归档到知识库失败: %s", e)
        return None


def infer_domain_from_content(text: str) -> str:
    """根据内容关键词推断领域

    Args:
        text: 内容文本

    Returns:
        领域标识
    """
    text_lower = text.lower()

    domain_keywords = {
        "lottery": ["双色球", "大乐透", "福彩3d", "排列三", "七乐彩", "七星彩", "快乐8",
                    "彩票", "开奖", "杀号", "遗漏", "冷热", "和值", "跨度"],
        "stock": ["股票", "行情", "大盘", "上证", "深证", "沪深", "选股", "技术指标",
                  "macd", "kdj", "rsi", "均线", "k线", "基金", "投资", "理财"],
        "football": ["足球", "足彩", "比赛", "赔率", "欧赔", "亚盘", "让球", "联赛",
                     "世界杯", "欧冠", "英超", "西甲", "德甲", "意甲", "法甲"],
        "music": ["音乐", "音频", "旋律", "作曲", "编曲", "混音", "采样", "音量", "转码",
                  "mp3", "wav", "lufs"],
        "ai": ["ai", "人工智能", "机器学习", "深度学习", "模型", "训练", "神经网络",
               "chatgpt", "大语言模型", "知识库"],
    }

    best_domain = "general"
    best_score = 0

    for domain, keywords in domain_keywords.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > best_score:
            best_score = score
            best_domain = domain

    return best_domain
