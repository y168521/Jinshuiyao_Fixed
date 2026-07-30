# -*- coding: utf-8 -*-
"""自动知识积累模块

从预测复盘和AI对话中自动提取有价值的信息，写入MiroFish知识库。
系统运行过程中持续积累经验，形成闭环学习。

核心能力：
  1. AutoKnowledgeExtractor — 从复盘/趋势/对话中提取知识卡片
  2. KnowledgeStats — 知识库统计与低效卡片归档
  3. run_auto_extraction() — 一键运行自动提取流程

使用方式：
    from core.auto_knowledge import AutoKnowledgeExtractor, run_auto_extraction

    # 方式1: 手动调用各提取方法
    extractor = AutoKnowledgeExtractor()
    cards = extractor.extract_from_review("lottery", predictions, actual, results)
    extractor.save_cards(cards)

    # 方式2: 一键运行
    result = run_auto_extraction("lottery", review_result=review_data)
"""

import json
import logging
import os
import re
import hashlib
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class AutoKnowledgeExtractor:
    """自动知识提取器

    从复盘结果、趋势分析和AI对话中自动识别有价值的知识，
    生成标准化的知识卡片并写入MiroFish知识库。
    """

    # 提取规则阈值
    HIGH_HIT_RATE = 0.60       # 命中率 > 60% → 有效策略
    LOW_HIT_RATE = 0.30        # 命中率 < 30% → 待优化
    CONSECUTIVE_MISS = 3       # 连续未命中期数阈值
    EFFECTIVENESS_HIGH = 75    # 高效卡片初始评分
    EFFECTIVENESS_MID = 50     # 中效卡片初始评分
    EFFECTIVENESS_LOW = 30     # 低效卡片初始评分

    # 对话提取关键词（预测类）
    _PREDICTION_KEYWORDS = [
        "预测", "推荐", "建议", "可能性", "概率", "预计",
        "预期", "看好", "不看好", "风险", "机会",
    ]

    # 对话提取关键词（分析类）
    _ANALYSIS_KEYWORDS = [
        "分析", "趋势", "规律", "特征", "异常", "波动",
        "结论", "发现", "指标", "信号", "原因",
    ]

    def __init__(self):
        """初始化知识库连接。

        如果知识库不可用（如缺少依赖或文件损坏），
        降级为纯日志模式，不中断业务流程。
        """
        self._db = None
        self._available = False

        try:
            from knowledge.mirofish_db import MiroFishDB
            self._db = MiroFishDB()
            self._available = True
            logger.info("自动知识提取器就绪，知识库已连接")
        except Exception as e:
            logger.warning("知识库不可用，自动提取将降级为日志记录: %s", e)

    # ------------------------------------------------------------------
    # 复盘知识提取
    # ------------------------------------------------------------------

    def extract_from_review(
        self,
        subsystem: str,
        predictions: List[Dict[str, Any]],
        actual: Any,
        results: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """从复盘结果中自动提取知识卡片。

        提取规则：
          - 命中率 > 60% 的策略 → "有效策略" 卡片
          - 命中率 < 30% 的策略 → "待优化" 卡片
          - 连续3期未命中 → "异常预警" 卡片

        Parameters
        ----------
        subsystem : str
            子系统标识 (lottery/football/stock/music)
        predictions : list[dict]
            本期预测列表，每项包含 nums, scheme, hits 等字段
        actual : Any
            实际结果（号码、比分等）
        results : dict
            复盘统计结果，包含各策略命中率等

        Returns
        -------
        list[dict]
            提取的知识卡片列表，每张卡片包含:
            title, content, subsystem, category, tags, effectiveness
        """
        cards = []

        # --- 规则1: 高命中率策略 → 有效策略卡片 ---
        if predictions:
            scheme_stats = self._group_by_scheme(predictions)
            for scheme, stats in scheme_stats.items():
                hit_rate = stats["hit_rate"]
                if hit_rate > self.HIGH_HIT_RATE:
                    cards.append(self._build_strategy_card(
                        title=f"[{subsystem}] 有效策略: {scheme}",
                        content=(
                            f"策略 '{scheme}' 在近期复盘命中率为 {hit_rate:.1%}，"
                            f"共预测 {stats['total']} 次，命中 {stats['hits']} 次。"
                            f"\n建议继续使用此策略，可适当增加权重。"
                        ),
                        subsystem=subsystem,
                        category="skill",
                        tags=["有效策略", scheme, subsystem],
                        effectiveness=self.EFFECTIVENESS_HIGH,
                        engine_hook="smart_brain",
                    ))

                elif hit_rate < self.LOW_HIT_RATE and stats["total"] >= 3:
                    cards.append(self._build_strategy_card(
                        title=f"[{subsystem}] 待优化: {scheme}",
                        content=(
                            f"策略 '{scheme}' 近期命中率为 {hit_rate:.1%}，"
                            f"共预测 {stats['total']} 次，仅命中 {stats['hits']} 次。"
                            f"\n建议减少权重或调整策略参数。"
                        ),
                        subsystem=subsystem,
                        category="area",
                        tags=["待优化", scheme, subsystem],
                        effectiveness=self.EFFECTIVENESS_LOW,
                        engine_hook="smart_brain",
                    ))

        # --- 规则3: 连续未命中检测 → 异常预警卡片 ---
        consecutive_miss_info = self._detect_consecutive_miss(predictions, results)
        if consecutive_miss_info:
            cards.append(self._build_strategy_card(
                title=f"[{subsystem}] 异常预警: 连续未命中",
                content=(
                    f"检测到连续 {consecutive_miss_info['count']} 期未命中。"
                    f"\n涉及方案: {consecutive_miss_info.get('schemes', '未知')}。"
                    f"\n建议暂停当前策略组合，等待信号变化后重新调整。"
                ),
                subsystem=subsystem,
                category="inspiration",
                tags=["异常预警", "连续未命中", subsystem],
                effectiveness=self.EFFECTIVENESS_LOW,
                engine_hook="smart_brain",
            ))

        if cards:
            logger.info(
                "[%s] 从复盘中提取了 %d 张知识卡片", subsystem, len(cards)
            )
        else:
            logger.debug("[%s] 复盘数据未触发知识提取规则", subsystem)

        return cards

    # ------------------------------------------------------------------
    # 趋势知识提取
    # ------------------------------------------------------------------

    def extract_from_trend(
        self,
        subsystem: str,
        trend_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """从趋势分析数据中提取知识卡片。

        提取规则：
          - 检测到大趋势方向变化（涨→跌或跌→涨）→ "趋势转折" 卡片
          - 检测到异常波动（振幅超过均值2倍）→ "异常信号" 卡片

        Parameters
        ----------
        subsystem : str
            子系统标识
        trend_data : dict
            趋势分析数据，建议包含:
            - direction: 当前方向 (up/down/sideways)
            - prev_direction: 上一期方向
            - amplitude: 当前振幅
            - avg_amplitude: 平均振幅
            - period: 期号/时间标记
            - details: 详细描述文本

        Returns
        -------
        list[dict]
            提取的知识卡片列表
        """
        cards = []

        if not trend_data:
            return cards

        direction = trend_data.get("direction", "")
        prev_direction = trend_data.get("prev_direction", "")
        period = trend_data.get("period", "未知周期")
        details = trend_data.get("details", "")

        # --- 规则1: 趋势方向变化 → 趋势转折卡片 ---
        if direction and prev_direction and direction != prev_direction:
            if (direction in ("up", "上涨") and prev_direction in ("down", "下跌")) or \
               (direction in ("down", "下跌") and prev_direction in ("up", "上涨")):
                direction_map = {"up": "上涨", "down": "下跌", "sideways": "震荡",
                                "上涨": "上涨", "下跌": "下跌", "震荡": "震荡"}
                from_dir = direction_map.get(prev_direction, prev_direction)
                to_dir = direction_map.get(direction, direction)

                cards.append(self._build_strategy_card(
                    title=f"[{subsystem}] 趋势转折: {from_dir}→{to_dir} ({period})",
                    content=(
                        f"在 {period} 检测到趋势方向发生显著变化：{from_dir} → {to_dir}。"
                        f"\n{details}"
                        f"\n建议重新评估策略方向，关注转折确认信号。"
                    ),
                    subsystem=subsystem,
                    category="inspiration",
                    tags=["趋势转折", from_dir, to_dir, subsystem],
                    effectiveness=self.EFFECTIVENESS_MID,
                    engine_hook="miss_breakthrough",
                ))

        # --- 规则2: 异常波动 → 异常信号卡片 ---
        amplitude = trend_data.get("amplitude", 0)
        avg_amplitude = trend_data.get("avg_amplitude", 0)
        if amplitude and avg_amplitude and avg_amplitude > 0:
            ratio = amplitude / avg_amplitude
            if ratio > 2.0:
                cards.append(self._build_strategy_card(
                    title=f"[{subsystem}] 异常信号: 波动放大 {ratio:.1f}倍 ({period})",
                    content=(
                        f"在 {period} 检测到异常波动，当前振幅 {amplitude:.4f}，"
                        f"为平均振幅 {avg_amplitude:.4f} 的 {ratio:.1f} 倍。"
                        f"\n{details}"
                        f"\n可能存在突发事件或数据异常，建议谨慎决策。"
                    ),
                    subsystem=subsystem,
                    category="resource",
                    tags=["异常信号", "异常波动", subsystem],
                    effectiveness=self.EFFECTIVENESS_LOW,
                    engine_hook="weight_calibration",
                ))

        if cards:
            logger.info(
                "[%s] 从趋势分析中提取了 %d 张知识卡片", subsystem, len(cards)
            )

        return cards

    # ------------------------------------------------------------------
    # 对话知识提取
    # ------------------------------------------------------------------

    def extract_from_conversation(
        self,
        subsystem: str,
        user_msg: str,
        ai_reply: str,
    ) -> List[Dict[str, Any]]:
        """从AI对话中提取知识卡片。

        提取规则：
          - AI回复包含预测结果 → 提取预测摘要
          - AI回复包含分析结论 → 提取分析要点
          - 通过关键词匹配判断是否值得提取

        Parameters
        ----------
        subsystem : str
            子系统标识
        user_msg : str
            用户消息
        ai_reply : str
            AI回复内容

        Returns
        -------
        list[dict]
            提取的知识卡片列表
        """
        cards = []

        if not ai_reply or not ai_reply.strip():
            return cards

        # --- 规则1: 包含预测相关内容 → 预测摘要卡片 ---
        if self._text_contains_keywords(ai_reply, self._PREDICTION_KEYWORDS):
            summary = self._extract_prediction_summary(ai_reply)
            if summary:
                cards.append(self._build_strategy_card(
                    title=f"[{subsystem}] 预测摘要: {self._truncate(user_msg, 20)}",
                    content=(
                        f"用户提问: {user_msg[:200]}"
                        f"\n\n预测摘要: {summary}"
                        f"\n\n来源: AI对话自动提取"
                    ),
                    subsystem=subsystem,
                    category="project",
                    tags=["预测摘要", subsystem, "自动提取"],
                    effectiveness=self.EFFECTIVENESS_MID,
                    engine_hook="",
                ))

        # --- 规则2: 包含分析相关内容 → 分析要点卡片 ---
        if self._text_contains_keywords(ai_reply, self._ANALYSIS_KEYWORDS):
            analysis_points = self._extract_analysis_points(ai_reply)
            if analysis_points:
                cards.append(self._build_strategy_card(
                    title=f"[{subsystem}] 分析要点: {self._truncate(user_msg, 20)}",
                    content=(
                        f"用户提问: {user_msg[:200]}"
                        f"\n\n分析要点:\n{analysis_points}"
                        f"\n\n来源: AI对话自动提取"
                    ),
                    subsystem=subsystem,
                    category="resource",
                    tags=["分析要点", subsystem, "自动提取"],
                    effectiveness=self.EFFECTIVENESS_MID,
                    engine_hook="",
                ))

        # 去重：如果同一轮对话同时提取了预测和分析，保留两张（title不同）
        if cards:
            logger.info(
                "[%s] 从对话中提取了 %d 张知识卡片", subsystem, len(cards)
            )

        return cards

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------

    def save_cards(self, cards: List[Dict[str, Any]]) -> int:
        """批量保存知识卡片到MiroFish知识库。

        自动按 title + subsystem 去重（MiroFishDB内部按title去重）。
        知识库不可用时降级为日志记录。

        Parameters
        ----------
        cards : list[dict]
            知识卡片列表，每项包含:
            title, content, subsystem, category, tags, effectiveness

        Returns
        -------
        int
            实际新增的卡片数量
        """
        if not cards:
            return 0

        if not self._available or self._db is None:
            # 降级为日志记录
            for card in cards:
                logger.info(
                    "[降级] 知识卡片未保存（知识库不可用）: [%s] %s",
                    card.get("category", "?"),
                    card.get("title", "?"),
                )
            return 0

        added = 0
        for card in cards:
            try:
                card_id = self._db.add_card(
                    title=card["title"],
                    content=card["content"],
                    category=card.get("category", "inspiration"),
                    domain=self._subsystem_to_domain(card.get("subsystem", "global")),
                    tags=card.get("tags", []),
                    source=card.get("source", "自动知识积累"),
                    engine_hook=card.get("engine_hook", ""),
                    priority=6,
                    subsystem=card.get("subsystem"),
                )
                # add_card 返回已有卡片的id时，不计入新增
                if card_id:
                    added += 1
            except Exception as e:
                logger.warning("保存知识卡片失败: %s - %s", card.get("title", "?"), e)

        if added > 0:
            logger.info("成功保存 %d 张知识卡片（总计 %d 张待保存）", added, len(cards))

        return added

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _build_strategy_card(
        title: str,
        content: str,
        subsystem: str,
        category: str,
        tags: List[str],
        effectiveness: int,
        engine_hook: str = "",
    ) -> Dict[str, Any]:
        """构建标准知识卡片字典。

        Parameters
        ----------
        title : str
            卡片标题
        content : str
            卡片内容
        subsystem : str
            子系统标识
        category : str
            PARA分类
        tags : list[str]
            标签列表
        effectiveness : int
            有效性评分 0-100
        engine_hook : str
            引擎钩子

        Returns
        -------
        dict
            标准知识卡片字典
        """
        return {
            "title": title,
            "content": content,
            "subsystem": subsystem,
            "category": category,
            "tags": tags,
            "effectiveness": min(100, max(0, effectiveness)),
            "engine_hook": engine_hook,
        }

    @staticmethod
    def _group_by_scheme(predictions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """按策略方案分组统计命中率。

        Parameters
        ----------
        predictions : list[dict]
            预测列表，每项包含 scheme 和 hits 字段

        Returns
        -------
        dict
            {方案名: {"total": int, "hits": int, "hit_rate": float}}
        """
        from collections import defaultdict

        scheme_data = defaultdict(lambda: {"total": 0, "hits": 0})
        for p in predictions:
            scheme = p.get("scheme", "默认方案")
            hits = p.get("hits", 0)
            scheme_data[scheme]["total"] += 1
            scheme_data[scheme]["hits"] += hits

        result = {}
        for scheme, data in scheme_data.items():
            total = data["total"]
            hit_rate = data["hits"] / total if total > 0 else 0.0
            result[scheme] = {
                "total": total,
                "hits": data["hits"],
                "hit_rate": hit_rate,
            }

        return result

    @staticmethod
    def _detect_consecutive_miss(
        predictions: List[Dict[str, Any]],
        results: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """检测连续未命中情况。

        Parameters
        ----------
        predictions : list[dict]
            预测列表
        results : dict
            复盘结果，可能包含 consecutive_miss 等字段

        Returns
        -------
        dict | None
            如果检测到连续未命中，返回详情；否则返回 None
        """
        # 优先从 results 中获取已计算的连续未命中数据
        if results:
            if results.get("consecutive_miss", 0) >= AutoKnowledgeExtractor.CONSECUTIVE_MISS:
                return {
                    "count": results["consecutive_miss"],
                    "schemes": ", ".join(results.get("miss_schemes", [])),
                }

        # 从 predictions 中自行检测
        if not predictions:
            return None

        schemes = set()
        all_zero = all(p.get("hits", 0) == 0 for p in predictions)
        if all_zero and len(predictions) >= AutoKnowledgeExtractor.CONSECUTIVE_MISS:
            for p in predictions:
                schemes.add(p.get("scheme", "默认方案"))
            return {
                "count": len(predictions),
                "schemes": ", ".join(schemes),
            }

        return None

    @staticmethod
    def _text_contains_keywords(text: str, keywords: List[str]) -> bool:
        """检查文本是否包含指定关键词列表中的任意一个。

        Parameters
        ----------
        text : str
            待检查的文本
        keywords : list[str]
            关键词列表

        Returns
        -------
        bool
            是否包含至少一个关键词
        """
        for kw in keywords:
            if kw in text:
                return True
        return False

    @staticmethod
    def _extract_prediction_summary(text: str) -> str:
        """从AI回复中提取预测相关摘要。

        提取策略：
          - 按换行分割，选取包含预测关键词的句子
          - 限制摘要长度不超过300字

        Parameters
        ----------
        text : str
            AI回复文本

        Returns
        -------
        str
            预测摘要文本，为空表示未提取到有效内容
        """
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        relevant = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 选取包含预测关键词的行，且长度>10（排除纯标号行）
            if len(line) > 10 and any(
                kw in line for kw in [
                    "预测", "推荐", "建议", "可能", "预计",
                    "概率", "看好", "机会", "号码", "方案",
                ]
            ):
                relevant.append(line)

        if not relevant:
            # 如果没有匹配行，取前3行作为摘要
            relevant = [l.strip() for l in lines if l.strip()][:3]

        summary = "\n".join(relevant)
        return summary[:300] if summary else ""

    @staticmethod
    def _extract_analysis_points(text: str) -> str:
        """从AI回复中提取分析要点。

        提取策略：
          - 按换行分割，选取包含分析关键词的句子
          - 限制要点长度不超过300字

        Parameters
        ----------
        text : str
            AI回复文本

        Returns
        -------
        str
            分析要点文本，为空表示未提取到有效内容
        """
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        relevant = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if len(line) > 10 and any(
                kw in line for kw in [
                    "分析", "趋势", "规律", "特征", "异常",
                    "波动", "结论", "发现", "指标", "信号",
                    "原因", "因此", "所以", "表明", "说明",
                ]
            ):
                relevant.append(line)

        if not relevant:
            # 如果没有匹配行，取前3行作为要点
            relevant = [l.strip() for l in lines if l.strip()][:3]

        points = "\n".join(relevant)
        return points[:300] if points else ""

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        """截断文本到指定长度，超出部分用省略号替代。

        Parameters
        ----------
        text : str
            原始文本
        max_len : int
            最大长度

        Returns
        -------
        str
            截断后的文本
        """
        if len(text) <= max_len:
            return text
        return text[:max_len - 1] + "..."

    @staticmethod
    def _subsystem_to_domain(subsystem: str) -> str:
        """将子系统标识映射为知识库领域标签。

        Parameters
        ----------
        subsystem : str
            子系统标识

        Returns
        -------
        str
            知识库领域标签
        """
        mapping = {
            "lottery": "lottery",
            "football": "football",
            "stock": "general",
            "music": "music",
        }
        return mapping.get(subsystem, "general")


# KnowledgeStats 已拆出到 core/knowledge_stats.py，保持向后兼容
from core.knowledge_stats import KnowledgeStats  # noqa: F401 — re-export


# ------------------------------------------------------------------
# 模块级便捷函数
# ------------------------------------------------------------------

def run_auto_extraction(
    subsystem: str,
    review_result: Optional[Dict[str, Any]] = None,
    trend_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """一键运行：从复盘和趋势数据中自动提取知识并保存到知识库。

    这是自动知识积累的主入口，适合在复盘流程结束后自动调用。

    Parameters
    ----------
    subsystem : str
        子系统标识 (lottery/football/stock/music)
    review_result : dict | None
        复盘结果字典，包含:
        - predictions: 预测列表 [{nums, scheme, hits}, ...]
        - actual: 实际结果
        - results: 统计结果
    trend_data : dict | None
        趋势分析数据，参见 extract_from_trend()

    Returns
    -------
    dict
        提取和保存的统计信息:
        - review_cards_extracted: 从复盘提取的卡片数
        - trend_cards_extracted: 从趋势提取的卡片数
        - total_extracted: 总提取数
        - total_saved: 实际保存数
        - details: 各提取步骤的详情
    """
    extractor = AutoKnowledgeExtractor()
    all_cards = []
    review_count = 0
    trend_count = 0

    # 1. 从复盘中提取
    if review_result:
        predictions = review_result.get("predictions", [])
        actual = review_result.get("actual")
        results = review_result.get("results", {})

        review_cards = extractor.extract_from_review(
            subsystem, predictions, actual, results
        )
        all_cards.extend(review_cards)
        review_count = len(review_cards)

    # 2. 从趋势中提取
    if trend_data:
        trend_cards = extractor.extract_from_trend(subsystem, trend_data)
        all_cards.extend(trend_cards)
        trend_count = len(trend_cards)

    # 3. 批量保存
    saved = extractor.save_cards(all_cards)

    result = {
        "subsystem": subsystem,
        "review_cards_extracted": review_count,
        "trend_cards_extracted": trend_count,
        "total_extracted": len(all_cards),
        "total_saved": saved,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    logger.info(
        "自动知识积累完成 [%s]: 提取 %d 张, 保存 %d 张",
        subsystem, len(all_cards), saved,
    )

    return result


# ---------------------------------------------------------------------------
# 对话日志知识提取（扩展：覆盖所有AI对话，不限于预测域）
# ---------------------------------------------------------------------------

# _EXPERIENCE_KEYWORDS / _PROCESSED_MARKER 已拆出到 core/exp_box_extractor.py
from core.exp_box_extractor import (  # noqa: F401 — re-export
    _EXPERIENCE_KEYWORDS as _EXPERIENCE_KEYWORDS,
    _PROCESSED_MARKER as _PROCESSED_MARKER,
)


def extract_from_conversation_log(max_new: int = 50) -> Dict[str, Any]:
    """从AI对话日志中提取通用经验知识。

    读取 ai_conversations.jsonl 中尚未处理的新对话，
    识别包含有价值经验的对话并生成知识卡片。

    与 extract_from_conversation() 的区别：
      - 本函数处理所有域的对话（不限于预测/分析）
      - 从持久化日志文件批量读取（适合定时任务）
      - 提取更广泛的经验：问题解决方法、配置技巧、有效模式等

    Parameters
    ----------
    max_new : int
        每次最多处理的新对话条数（防止一次处理太多）

    Returns
    -------
    dict
        提取统计: processed, extracted, saved
    """
    import os as _os

    log_file = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "金水谣数据", "log", "ai_conversations.jsonl"
    )

    if not _os.path.isfile(log_file):
        return {"processed": 0, "extracted": 0, "saved": 0, "info": "对话日志文件不存在"}

    # 读取上次处理位置
    last_line = 0
    if _os.path.isfile(_PROCESSED_MARKER):
        try:
            with open(_PROCESSED_MARKER, "r") as f:
                last_line = int(f.read().strip())
        except (ValueError, OSError):
            last_line = 0

    # 读取新行
    new_records = []
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < last_line:
                    continue
                if len(new_records) >= max_new:
                    break
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        if rec.get("success") and rec.get("reply_brief"):
                            new_records.append(rec)
                    except (json.JSONDecodeError, ValueError):
                        continue
    except OSError:
        return {"processed": 0, "extracted": 0, "saved": 0, "info": "读取日志失败"}

    if not new_records:
        return {"processed": 0, "extracted": 0, "saved": 0, "info": "无新对话"}

    # 提取知识
    extractor = AutoKnowledgeExtractor()
    all_cards = []

    for rec in new_records:
        reply = rec.get("reply_brief", "")
        user_msg = rec.get("user_brief", "")
        provider = rec.get("provider", "unknown")

        # 检查是否包含经验类关键词
        has_experience = any(kw in reply for kw in _EXPERIENCE_KEYWORDS)
        if not has_experience:
            continue

        # 生成知识卡片
        title_brief = user_msg[:30].replace("\n", " ") if user_msg else "AI对话经验"
        card = {
            "title": f"[经验] {title_brief}",
            "content": (
                f"用户提问: {user_msg[:200]}"
                f"\n\nAI回复要点: {reply[:500]}"
                f"\n\n来源: {provider} 对话自动提取"
                f"\n时间: {rec.get('time', '')}"
            ),
            "subsystem": "global",
            "category": "resource",
            "tags": ["对话经验", provider, "自动提取"],
            "effectiveness": 50,
            "engine_hook": "",
        }
        all_cards.append(card)

    # 保存
    saved = extractor.save_cards(all_cards) if all_cards else 0

    # 更新处理位置标记
    try:
        _os.makedirs(_os.path.dirname(_PROCESSED_MARKER), exist_ok=True)
        with open(_PROCESSED_MARKER, "w") as f:
            f.write(str(last_line + len(new_records)))
    except OSError:
        pass

    result = {
        "processed": len(new_records),
        "extracted": len(all_cards),
        "saved": saved,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    if all_cards:
        logger.info(
            "对话日志知识提取: 处理 %d 条, 提取 %d 张, 保存 %d 张",
            len(new_records), len(all_cards), saved,
        )

    return result


# exp_box_extractor 已拆出到 core/exp_box_extractor.py
from core.exp_box_extractor import (  # noqa: F401 — re-export
    extract_from_experience_box,
    extract_triples_from_experience_box,
    start_experience_box_watcher,
    stop_experience_box_watcher,
)


# ai_decisions_extractor 已拆出到 core/ai_decisions_extractor.py
from core.ai_decisions_extractor import (  # noqa: F401 — re-export
    extract_from_ai_decisions,
    extract_triples_from_ai_decisions,
    start_ai_decisions_watcher,
    stop_ai_decisions_watcher,
)


# knowledge_search 已拆出到 knowledge/knowledge_search.py，保持向后兼容
from knowledge.knowledge_search import (  # noqa: F401 — re-export
    search_ai_knowledge,
    search_graph_triples,
    search_knowledge_vector,

)

