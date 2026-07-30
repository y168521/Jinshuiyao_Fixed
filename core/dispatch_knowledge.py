# -*- coding: utf-8 -*-
"""金水谣引擎 - 知识库调度模块

从 ai_agent.py 的 _dispatch_knowledge 方法拆出。
接收 agent 实例以复用其 _get_knowledge_db / _get_content_refiner / _last_extracted 等属性。
"""

import logging

logger = logging.getLogger(__name__)


def dispatch_knowledge(agent, action: str, target: str, user_input: str = "") -> str:
    """调度知识库子系统

    Args:
        agent: JinshuiyaoAgent 实例，用于访问知识库/提炼器等
        action: 操作类型（stats/search/archive/value_tiers）
        target: 目标
        user_input: 用户原始输入
    """
    try:
        db = agent._get_knowledge_db()
        if not db:
            return "知识库未就绪，请稍后再试。"

        if action == "stats":
            stats = db.stats()
            total = stats.get("total_cards", 0)
            by_domain = stats.get("by_domain", {})
            by_category = stats.get("by_category", {})
            by_tag = stats.get("by_tag", {})

            recent_cards = db.search(limit=5)

            lines = ["【知识库统计】\n"]
            lines.append(f"  总卡片数: {total} 张")

            if by_domain:
                lines.append(f"\n  按领域分布:")
                for dom, cnt in sorted(by_domain.items(), key=lambda x: x[1], reverse=True)[:8]:
                    lines.append(f"    {dom}: {cnt}张")

            if by_category:
                lines.append(f"\n  按分类分布:")
                cat_names = {
                    "inspiration": "灵感",
                    "project": "项目",
                    "area": "领域",
                    "resource": "资源",
                    "skill": "技能",
                    "archive": "归档",
                }
                for cat, cnt in sorted(by_category.items(), key=lambda x: x[1], reverse=True):
                    cat_name = cat_names.get(cat, cat)
                    lines.append(f"    {cat_name}: {cnt}张")

            if recent_cards:
                lines.append(f"\n  最近添加的5张卡片:")
                for card in recent_cards:
                    title = card.get("title", "无标题")[:30]
                    domain = card.get("domain", "general")
                    created = card.get("created", "")
                    lines.append(f"    [{domain}] {title} - {created}")

            return "\n".join(lines)

        elif action == "search":
            query = user_input.replace("搜索知识", "").replace("知识搜索", "").replace("查找知识", "").strip()
            if not query:
                return "【搜索知识】\n请告诉我要搜索的关键词，例如：\n  '搜索知识 双色球'"

            results = db.search(query=query, limit=10)
            if not results:
                return f"【搜索知识】\n未找到与 '{query}' 相关的知识卡片。"

            lines = [f"【搜索知识】共找到 {len(results)} 张相关卡片\n"]
            for i, card in enumerate(results[:10], 1):
                title = card.get("title", "无标题")
                domain = card.get("domain", "general")
                effectiveness = card.get("effectiveness", 50)
                lines.append(f"  {i}. [{domain}] {title} (有效性:{effectiveness})")
                content = card.get("content", "")[:100]
                if content:
                    lines.append(f"     {content}...")

            return "\n".join(lines)

        elif action == "archive":
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
                return ("【归档知识】\n"
                        "请提供要归档的内容，例如：\n"
                        "  '归档 今天学到的双色球杀号技巧...'\n"
                        "或者先提取视频内容，然后说'归档'")

            try:
                from knowledge.mirofish_db import MiroFishDB
                classify_result = MiroFishDB.smart_classify(content)
                domain = classify_result.get("domain", "general")
                category = classify_result.get("category", "inspiration")
                tags = classify_result.get("tags", [])

                title = content[:30].replace("\n", " ")
                card_id = db.add_card(
                    title=title,
                    content=content,
                    category=category,
                    domain=domain,
                    tags=tags,
                    source="用户手动归档",
                    priority=5,
                )
                return (f"【归档成功】\n"
                        f"  卡片ID: {card_id}\n"
                        f"  标题: {title}\n"
                        f"  领域: {domain}\n"
                        f"  分类: {category}\n"
                        f"  标签: {', '.join(tags) if tags else '无'}")
            except Exception as e:
                return f"归档失败：{e}"

        elif action == "project_memory":
            try:
                from core.agent_project_memory import query_project_memory
                return query_project_memory(user_input)
            except Exception as e:
                logger.error("[dispatch_knowledge] 项目记忆查询异常: %s", e)
                return f"项目记忆查询失败：{e}"

        elif action == "risk_register":
            try:
                from core.agent_project_memory import query_risk_register
                # 提取可能的关键词：去掉触发词，若为空则返回全部
                kw = (user_input
                      .replace("风险", "").replace("登记册", "").replace("隐患", "")
                      .replace("雷", "").replace("清单", "").replace("有什么", "")
                      .replace("现在", "").replace("当前", "").strip())
                return query_risk_register(kw)
            except Exception as e:
                logger.error("[dispatch_knowledge] 风险登记册查询异常: %s", e)
                return f"风险登记册查询失败：{e}"

        elif action == "total_index":
            try:
                from core.agent_project_memory import query_total_index
                kw = (user_input
                      .replace("总索引", "").replace("留痕", "").replace("工作留痕", "")
                      .replace("搜索", "").replace("查一下", "").strip())
                return query_total_index(kw, limit=5)
            except Exception as e:
                logger.error("[dispatch_knowledge] 总索引查询异常: %s", e)
                return f"总索引查询失败：{e}"

        elif action == "value_tiers":
            all_cards = db.search(limit=9999)

            tiers = {
                "高价值(80-100分)": 0,
                "较高价值(60-79分)": 0,
                "中等价值(40-59分)": 0,
                "较低价值(20-39分)": 0,
                "低价值(0-19分)": 0,
            }

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

            lines = ["【价值分层统计】\n"]
            total = len(all_cards)
            lines.append(f"  总卡片数: {total} 张\n")

            for tier_name, count in tiers.items():
                percentage = (count / total * 100) if total > 0 else 0
                bar = "█" * int(percentage / 5) + "░" * (20 - int(percentage / 5))
                lines.append(f"  {tier_name}: {count}张 ({percentage:.1f}%) {bar}")

            high_value_cards = [c for c in all_cards if c.get("effectiveness", 50) >= 80]
            if high_value_cards:
                lines.append(f"\n  高价值卡片TOP5:")
                for card in high_value_cards[:5]:
                    title = card.get("title", "无标题")[:30]
                    eff = card.get("effectiveness", 0)
                    lines.append(f"    [{eff}分] {title}")

            return "\n".join(lines)

        else:
            return ("【知识库功能】\n"
                    "  知识库 / 我的知识 → 查看知识库统计\n"
                    "  搜索知识 xxx → 搜索知识卡片\n"
                    "  归档 xxx → 手动归档内容\n"
                    "  价值分层 → 查看价值分布")

    except Exception as e:
        logger.error("[dispatch_knowledge] 知识库调度异常: %s", e)
        return f"知识库系统异常：{e}"
