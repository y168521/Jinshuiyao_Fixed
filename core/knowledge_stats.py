# -*- coding: utf-8 -*-
"""知识库统计分析与低效卡片归档

从 auto_knowledge.py 拆出的独立模块，负责：
  1. 知识库各子系统的卡片统计（数量、分类、有效性评分）
  2. 低效卡片识别与归档（effectiveness < threshold → archive 分类）

使用方式：
    from core.knowledge_stats import KnowledgeStats
    stats = KnowledgeStats()
    report = stats.get_stats()
    archived = stats.archive_low_score(threshold=20)
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class KnowledgeStats:
    """知识库统计分析与低效卡片归档。

    功能：
      - 统计各子系统的知识卡数量、分类分布、有效性评分
      - 识别低效知识卡片（effectiveness < 30），建议归档
      - 执行归档操作（将低分卡片移入 archive 分类）
    """

    # 归档阈值：effectiveness 低于此值的卡片将被归档
    DEFAULT_ARCHIVE_THRESHOLD = 20

    def __init__(self):
        """初始化，连接知识库。

        知识库不可用时降级为只读模式。
        """
        self._db = None
        self._available = False

        try:
            from knowledge.mirofish_db import MiroFishDB
            self._db = MiroFishDB()
            self._available = True
            logger.info("知识库统计分析器就绪")
        except Exception as e:
            logger.warning("知识库不可用，统计分析将受限: %s", e)

    def get_stats(self) -> Dict[str, Any]:
        """获取知识库的详细统计信息。

        返回内容：
          - 各 subsystem 的知识卡数量
          - 各 subsystem 的分类分布
          - 各 subsystem 的平均有效性评分
          - 低效知识卡片列表（effectiveness < 30），建议归档

        Returns
        -------
        dict
            统计信息字典，包含:
            - total_cards: 总卡片数
            - by_subsystem: {子系统: {count, categories, avg_effectiveness}}
            - low_score_cards: [{id, title, effectiveness, subsystem, category}]
            """
        if not self._available or self._db is None:
            logger.warning("知识库不可用，返回空统计")
            return {
                "total_cards": 0,
                "by_subsystem": {},
                "low_score_cards": [],
                "message": "知识库不可用",
            }

        all_cards = self._db.get_all_cards()
        total = len(all_cards)

        # 按子系统分组统计
        by_subsystem: Dict[str, Dict[str, Any]] = {}
        low_score_cards: List[Dict[str, Any]] = []

        for card in all_cards:
            sub = card.get("subsystem", "global")
            eff = card.get("effectiveness", 50)
            cat = card.get("category", "unknown")

            if sub not in by_subsystem:
                by_subsystem[sub] = {
                    "count": 0,
                    "categories": {},
                    "effectiveness_sum": 0,
                }

            by_subsystem[sub]["count"] += 1
            by_subsystem[sub]["effectiveness_sum"] += eff
            by_subsystem[sub]["categories"][cat] = (
                by_subsystem[sub]["categories"].get(cat, 0) + 1
            )

            # 收集低效卡片
            if eff < 30:
                low_score_cards.append({
                    "id": card.get("id", ""),
                    "title": card.get("title", ""),
                    "effectiveness": eff,
                    "subsystem": sub,
                    "category": cat,
                })

        # 计算平均有效性
        for sub_data in by_subsystem.values():
            count = sub_data["count"]
            sub_data["avg_effectiveness"] = (
                round(sub_data["effectiveness_sum"] / count, 1) if count > 0 else 0
            )
            del sub_data["effectiveness_sum"]

        # 按effectiveness排序低效卡片
        low_score_cards.sort(key=lambda x: x["effectiveness"])

        result = {
            "total_cards": total,
            "by_subsystem": by_subsystem,
            "low_score_cards": low_score_cards,
            "low_score_count": len(low_score_cards),
        }

        logger.info(
            "知识库统计: 总计 %d 张卡片, %d 个子系统, %d 张低效卡片",
            total, len(by_subsystem), len(low_score_cards),
        )

        return result

    def archive_low_score(self, threshold: int = DEFAULT_ARCHIVE_THRESHOLD) -> int:
        """归档低分知识卡片。

        将 effectiveness < threshold 的卡片分类改为 'archive'。
        归档后的卡片不会被引擎调用（MiroFishDB的search默认排除archive）。

        Parameters
        ----------
        threshold : int
            归档阈值（默认20），effectiveness 低于此值的卡片将被归档

        Returns
        -------
        int
            实际归档的卡片数量
        """
        if not self._available or self._db is None:
            logger.warning("知识库不可用，无法执行归档")
            return 0

        # 获取需要归档的卡片
        all_cards = self._db.get_all_cards()
        to_archive = [
            c for c in all_cards
            if c.get("effectiveness", 50) < threshold
            and c.get("category") != "archive"
        ]

        if not to_archive:
            logger.info("没有需要归档的低分卡片（阈值=%d）", threshold)
            return 0

        archived = 0
        for card in to_archive:
            try:
                # 通过删除旧卡片 + 重新添加为archive分类来实现归档
                card_id = card.get("id", "")
                title = card.get("title", "")
                content = card.get("content", "")
                tags = card.get("tags", [])

                # 删除原卡片
                self._db.remove_card(card_id)

                # 以 archive 分类重新添加
                new_id = self._db.add_card(
                    title=f"[归档] {title}",
                    content=content,
                    category="archive",
                    domain=card.get("domain", "general"),
                    tags=tags + ["已归档"],
                    source=card.get("source", "自动归档"),
                    engine_hook="",  # 归档后不参与引擎调用
                    priority=1,
                    subsystem=card.get("subsystem"),
                )
                if new_id:
                    archived += 1

            except Exception as e:
                logger.warning("归档卡片失败: %s - %s", card.get("title", "?"), e)

        logger.info(
            "归档完成: 共归档 %d 张卡片（阈值=%d，待归档=%d）",
            archived, threshold, len(to_archive),
        )

        return archived
