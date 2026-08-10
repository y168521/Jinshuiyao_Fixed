# -*- coding: utf-8 -*-
"""金水谣系统 - L3自适应进化引擎子模块（JS-20260810-10 由 engines/evolution.py 拆分）"""
import os
import re
import json
import uuid
import math
import logging
import threading
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from utils.safe_json import safe_write_json, safe_load_json
except ImportError:
    def safe_write_json(filepath, data):
        parent = os.path.dirname(filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)
        import tempfile
        fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=parent, prefix=".evolution_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if os.path.exists(filepath):
                os.replace(tmp_path, filepath)
            else:
                os.rename(tmp_path, filepath)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def safe_load_json(filepath, default=None):
        if default is None:
            default = {}
        if not os.path.exists(filepath):
            return default
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error("加载文件失败 [%s]: %s，返回默认值", filepath, e)
            return default

_SEVERITY_LEVELS = {"info": 1, "warn": 2, "critical": 3}
_DEFAULT_RULE_THRESHOLD = 3

from engines.evolution_rule import RuleEngine
from engines.evolution_experience import ExperienceMiner
from engines.evolution_feedback import AdaptiveFeedback
class EvolutionManager:

    """进化管理器 - 统一管理规则引擎+经验挖掘+自适应反馈

    系统的顶层入口，整合RuleEngine、ExperienceMiner和AdaptiveFeedback，

    提供统一的记录、复盘和报告接口。

    使用示例:

        manager = EvolutionManager(data_dir="金水谣数据", brain=brain)

        manager.start()

        # 记录错误事件

        manager.record_and_evolve("连接超时", "network")

        # 复盘完成

        manager.on_review_complete("福彩3D", predictions, actual_nums, hits)

        # 获取报告

        report = manager.get_evolution_report()

    """

    def __init__(self, data_dir="金水谣数据", brain=None, watchdog=None):

        """初始化进化管理器

        Args:

            data_dir: 数据目录路径

            brain: SmartBrain实例（可选，用于自适应反馈）

            watchdog: SystemWatchdog实例（可选，用于监控指标更新）

        """

        self.data_dir = data_dir

        self.rule_file = os.path.join(data_dir, "evolution_rules.json")

        self.state_file = os.path.join(data_dir, "evolution_state.json")

        # 初始化子模块

        self.rule_engine = RuleEngine(rule_file=self.rule_file)

        self.experience_miner = ExperienceMiner(data_dir=data_dir)

        self.adaptive_feedback = AdaptiveFeedback(

            brain=brain,

            watchdog=watchdog,

            experience_miner=self.experience_miner,

        )

        self._started = False

        self._lock = threading.Lock()

        # 统计计数

        self._stats = {

            "total_events": 0,

            "total_reviews": 0,

            "rules_activated": 0,

            "knowledge_cards_created": 0,

            "suggestions_generated": 0,

            "started_at": None,

        }

        logger.info("进化管理器就绪 (data_dir=%s)", data_dir)

    # ------------------------------------------------------------------

    # 生命周期

    # ------------------------------------------------------------------

    def start(self):

        """启动进化引擎

        加载历史状态，准备就绪。后续通过record_and_evolve和on_review_complete

        驱动进化过程。

        """

        with self._lock:

            if self._started:

                logger.info("进化引擎已在运行中")

                return

            # 加载历史状态

            self._load_state()

            self._started = True

            self._stats["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            logger.info(

                "进化引擎已启动 (历史事件: %d, 规则: %d, 知识卡片: %d)",

                self._stats["total_events"],

                len(self.rule_engine.get_active_rules()),

                self._stats["knowledge_cards_created"],

            )

    def stop(self):

        """停止进化引擎，保存状态"""

        with self._lock:

            if not self._started:

                return

            self._started = False

            self.save_state()

            logger.info("进化引擎已停止，状态已保存")

    # ------------------------------------------------------------------

    # 核心接口

    # ------------------------------------------------------------------

    def record_and_evolve(self, error_message, category, data=None):

        """统一入口: 记录事件 + 检查规则 + 挖掘知识

        这是进化引擎的核心驱动方法，每次系统发生事件时调用。

        会自动完成规则匹配、规则激活、修复动作执行。

        Args:

            error_message: 错误信息字符串

            category: 事件分类

            data: 附带数据（可选）

        Returns:

            dict: 进化处理结果 {

                "event_recorded": True,

                "rule_result": {...},

                "stats": {...}

            }

        """

        with self._lock:

            self._stats["total_events"] += 1

        # 1. 规则引擎处理

        rule_result = self.rule_engine.record_event(error_message, category, data)

        with self._lock:

            if rule_result.get("activated"):

                self._stats["rules_activated"] += 1

            if rule_result.get("new_rule_created"):

                logger.info("进化: 自动创建新规则 (%s)", error_message[:50])

        return {

            "event_recorded": True,

            "rule_result": rule_result,

            "stats": {

                "total_events": self._stats["total_events"],

                "rules_activated": self._stats["rules_activated"],

            }

        }

    def on_review_complete(self, lot, predictions, actual_nums, hits):

        """复盘完成后的进化处理

        整合自适应反馈闭环，在SmartBrain基础学习之上提供增强分析。

        Args:

            lot: 彩种名

            predictions: 本期所有预测 [{nums, type, scheme, hits}]

            actual_nums: 实际开奖号码列表

            hits: 总命中数

        Returns:

            dict: {

                "lot": str,

                "brain_learned": bool,

                "cusum_alert": bool,

                "suggestions": list,

            }

        """

        with self._lock:

            self._stats["total_reviews"] += 1

        # 调用自适应反馈

        self.adaptive_feedback.on_review_complete(

            lot, predictions, actual_nums, hits

        )

        # 检查CUSUM状态

        cusum_status = self.adaptive_feedback.get_cusum_status(lot)

        suggestions = self.adaptive_feedback.get_suggestions(lot)

        with self._lock:

            if suggestions:

                self._stats["suggestions_generated"] += len(suggestions)

        return {

            "lot": lot,

            "brain_learned": self.adaptive_feedback.brain is not None,

            "cusum_alert": cusum_status.get("alert_low", False)

                        or cusum_status.get("alert_high", False),

            "cusum_status": cusum_status,

            "suggestions": suggestions,

        }

    # ------------------------------------------------------------------

    # 报告与持久化

    # ------------------------------------------------------------------

    def get_evolution_report(self):

        """获取进化报告（规则数、知识沉淀数、建议数）

        Returns:

            dict: 完整的进化报告

        """

        rule_stats = self.rule_engine.get_stats()

        cusum_summary = {}

        # 汇总所有彩种的CUSUM状态

        for lot in list(self.adaptive_feedback._cusum_data.keys()):

            cusum_summary[lot] = self.adaptive_feedback.get_cusum_status(lot)

        # 汇总建议

        all_suggestions = {}

        for lot in list(self.adaptive_feedback._suggestions_cache.keys()):

            all_suggestions[lot] = self.adaptive_feedback.get_suggestions(lot)

        return {

            "engine": "金水谣L3自适应进化引擎",

            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

            "stats": {

                "total_events": self._stats["total_events"],

                "total_reviews": self._stats["total_reviews"],

                "rules_activated": self._stats["rules_activated"],

                "knowledge_cards_created": self._stats["knowledge_cards_created"],

                "suggestions_generated": self._stats["suggestions_generated"],

                "started_at": self._stats.get("started_at"),

                "running": self._started,

            },

            "rule_engine": rule_stats,

            "experience_patterns": len(self.experience_miner.get_cached_patterns()),

            "cusum_status": cusum_summary,

            "active_suggestions": all_suggestions,

        }

    def save_state(self):

        """保存进化状态到文件

        持久化所有子模块的状态，包括:

        - 统计计数

        - CUSUM数据

        - 策略建议缓存

        """

        state = {

            "version": 1,

            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

            "stats": dict(self._stats),

            "adaptive_feedback": self.adaptive_feedback.get_state(),

        }

        try:

            safe_write_json(self.state_file, state)

            logger.debug("进化状态已保存到 %s", self.state_file)

        except Exception as e:

            logger.error("保存进化状态失败: %s", e, exc_info=True)

            raise

    def _load_state(self):

        """从文件加载进化状态"""

        if not os.path.exists(self.state_file):

            logger.debug("进化状态文件不存在，使用默认状态")

            return

        state = safe_load_json(self.state_file)

        if not state or not isinstance(state, dict):

            return

        # 恢复统计

        saved_stats = state.get("stats", {})

        for key, value in saved_stats.items():

            if key in self._stats:

                self._stats[key] = value

        # 恢复自适应反馈状态

        fb_state = state.get("adaptive_feedback", {})

        if fb_state:

            self.adaptive_feedback.load_state(fb_state)

        logger.debug("进化状态已恢复 (历史事件: %d)", self._stats["total_events"])

    # ------------------------------------------------------------------

    # 便捷方法

    # ------------------------------------------------------------------

    def mine_and_learn(self, log_path=None, min_occurrences=3, auto_card=True):

        """一键挖掘日志并生成知识卡片

        Args:

            log_path: 日志路径（默认使用data_dir下的log目录）

            min_occurrences: 最小出现次数

            auto_card: 是否自动生成知识卡片

        Returns:

            dict: {patterns_found, cards_created}

        """

        if log_path is None:

            log_path = os.path.join(self.data_dir, "log")

        patterns = self.experience_miner.mine_patterns(

            log_path, min_occurrences=min_occurrences

        )

        cards_created = []

        if auto_card and patterns:

            cards_created = self.experience_miner.batch_generate_cards(patterns)

            with self._lock:

                self._stats["knowledge_cards_created"] += len(cards_created)

        return {

            "patterns_found": len(patterns),

            "cards_created": len(cards_created),

            "card_ids": cards_created,

        }

    def apply_all_fixes(self, context=None):

        """应用所有已激活规则的修复动作

        Args:

            context: 上下文数据

        Returns:

            list[dict]: 修复结果列表

        """
