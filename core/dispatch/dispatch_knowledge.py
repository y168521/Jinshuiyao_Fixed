# -*- coding: utf-8 -*-
"""金水谣引擎 - 知识库调度模块

从 ai_agent.py 的 _dispatch_knowledge 方法拆出。
接收 agent 实例以复用其 _get_knowledge_db / _get_content_refiner / _last_extracted 等属性。
"""

import logging

logger = logging.getLogger(__name__)


_CAT_NAMES = {"inspiration": "灵感", "project": "项目", "area": "领域",
              "resource": "资源", "skill": "技能", "archive": "归档"}


def _kb_stats(db) -> str:
    stats = db.stats()
    lines = ["【知识库统计】\n", f"  总卡片数: {stats.get('total_cards', 0)} 张"]
    by_domain = stats.get("by_domain", {})
    if by_domain:
        lines.append("\n  按领域分布:")
        for dom, cnt in sorted(by_domain.items(), key=lambda x: x[1], reverse=True)[:8]:
            lines.append(f"    {dom}: {cnt}张")
    by_category = stats.get("by_category", {})
    if by_category:
        lines.append("\n  按分类分布:")
        for cat, cnt in sorted(by_category.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"    {_CAT_NAMES.get(cat, cat)}: {cnt}张")
    recent = db.search(limit=5)
    if recent:
        lines.append("\n  最近添加的5张卡片:")
        for card in recent:
            lines.append(f"    [{card.get('domain', 'general')}] "
                         f"{card.get('title', '无标题')[:30]} - {card.get('created', '')}")
    return "\n".join(lines)


def _kb_search(db, user_input) -> str:
    query = user_input.replace("搜索知识", "").replace("知识搜索", "").replace("查找知识", "").strip()
    if not query:
        return "【搜索知识】\n请告诉我要搜索的关键词，例如：\n  '搜索知识 双色球'"
    results = db.search(query=query, limit=10)
    if not results:
        return f"【搜索知识】\n未找到与 '{query}' 相关的知识卡片。"
    lines = [f"【搜索知识】共找到 {len(results)} 张相关卡片\n"]
    for i, card in enumerate(results[:10], 1):
        lines.append(f"  {i}. [{card.get('domain', 'general')}] "
                     f"{card.get('title', '无标题')} (有效性:{card.get('effectiveness', 50)})")
        content = card.get("content", "")[:100]
        if content:
            lines.append(f"     {content}...")
    return "\n".join(lines)


def _kb_archive(agent, db, user_input) -> str:
    content = user_input.replace("归档", "").replace("存入知识库", "").replace("保存知识", "").strip()
    if agent._last_extracted:
        try:
            refiner = agent._get_content_refiner()
            if refiner:
                refined = refiner.refine(agent._last_extracted)
                card_id = agent._archive_refined_to_knowledge(refined)
                if card_id:
                    return f"【归档成功】\n已将提取的内容归档到知识库。\n卡片ID: {card_id}\n标题: {refined.get('title', '无标题')}"
        except Exception as e:
            logger.error("[dispatch_knowledge] 归档最近提取结果失败: %s", e)
    if not content or len(content) < 5:
        return ("【归档知识】\n请提供要归档的内容，例如：\n"
                "  '归档 今天学到的双色球杀号技巧...'\n或者先提取视频内容，然后说'归档'")
    try:
        from knowledge.mirofish_db import MiroFishDB
        cr = MiroFishDB.smart_classify(content)
        domain, category, tags = cr.get("domain", "general"), cr.get("category", "inspiration"), cr.get("tags", [])
        title = content[:30].replace("\n", " ")
        card_id = db.add_card(title=title, content=content, category=category,
                              domain=domain, tags=tags, source="用户手动归档", priority=5)
        return (f"【归档成功】\n  卡片ID: {card_id}\n  标题: {title}\n  领域: {domain}\n"
                f"  分类: {category}\n  标签: {', '.join(tags) if tags else '无'}")
    except Exception as e:
        return f"归档失败：{e}"


def _kb_value_tiers(db) -> str:
    all_cards = db.search(limit=9999)
    tiers = {"高价值(80-100分)": 0, "较高价值(60-79分)": 0, "中等价值(40-59分)": 0,
             "较低价值(20-39分)": 0, "低价值(0-19分)": 0}
    for card in all_cards:
        eff = card.get("effectiveness", 50)
        if eff >= 80:
            tiers["高价值(80-100分)"] += 1
        elif eff >= 60:
            tiers["较高价值(60-79分)"] += 1
        elif eff >= 40:
            tiers["中等价值(40-59分)"] += 1
        elif eff >= 20:
            tiers["较低价值(20-39分)"] += 1
        else:
            tiers["低价值(0-19分)"] += 1
    total = len(all_cards)
    lines = ["【价值分层统计】\n", f"  总卡片数: {total} 张\n"]
    for tier_name, count in tiers.items():
        pct = (count / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        lines.append(f"  {tier_name}: {count}张 ({pct:.1f}%) {bar}")
    high = [c for c in all_cards if c.get("effectiveness", 50) >= 80]
    if high:
        lines.append("\n  高价值卡片TOP5:")
        for card in high[:5]:
            lines.append(f"    [{card.get('effectiveness', 0)}分] {card.get('title', '无标题')[:30]}")
    return "\n".join(lines)


def dispatch_knowledge(agent, action: str, target: str, user_input: str = "") -> str:
    """调度知识库子系统（stats/search/archive/value_tiers/project_memory 等）"""
    try:
        db = agent._get_knowledge_db()
        if not db:
            return "知识库未就绪，请稍后再试。"
        if action == "stats":
            return _kb_stats(db)
        if action == "search":
            return _kb_search(db, user_input)
        if action == "archive":
            return _kb_archive(agent, db, user_input)
        if action == "value_tiers":
            return _kb_value_tiers(db)
        if action == "project_memory":
            try:
                from core.ai.agent_project_memory import query_project_memory
                return query_project_memory(user_input)
            except Exception as e:
                logger.error("[dispatch_knowledge] 项目记忆查询异常: %s", e)
                return f"项目记忆查询失败：{e}"
        if action == "risk_register":
            try:
                from core.ai.agent_project_memory import query_risk_register
                kw = (user_input.replace("风险", "").replace("登记册", "").replace("隐患", "")
                      .replace("雷", "").replace("清单", "").replace("有什么", "")
                      .replace("现在", "").replace("当前", "").strip())
                return query_risk_register(kw)
            except Exception as e:
                logger.error("[dispatch_knowledge] 风险登记册查询异常: %s", e)
                return f"风险登记册查询失败：{e}"
        if action == "total_index":
            try:
                from core.ai.agent_project_memory import query_total_index
                kw = (user_input.replace("总索引", "").replace("留痕", "").replace("工作留痕", "")
                      .replace("搜索", "").replace("查一下", "").strip())
                return query_total_index(kw, limit=5)
            except Exception as e:
                logger.error("[dispatch_knowledge] 总索引查询异常: %s", e)
                return f"总索引查询失败：{e}"
        return ("【知识库功能】\n  知识库 / 我的知识 → 查看知识库统计\n"
                "  搜索知识 xxx → 搜索知识卡片\n  归档 xxx → 手动归档内容\n  价值分层 → 查看价值分布")
    except Exception as e:
        logger.error("[dispatch_knowledge] 知识库调度异常: %s", e)
        return f"知识库系统异常：{e}"
