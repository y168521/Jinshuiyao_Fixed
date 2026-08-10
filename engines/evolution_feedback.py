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

class AdaptiveFeedback:

    """自适应反馈闭环 - 增强复盘学习效果

    在基础SmartBrain复盘学习之上，增加:

    1. 命中率的CUSUM统计 - 累积和控制图检测命中率偏移

    2. 命中率异常偏低时触发策略调整建议

    3. 将结果反馈给Watchdog更新监控指标

    4. 发现新模式时通过ExperienceMiner沉淀知识

    """

    def __init__(self, brain=None, watchdog=None, experience_miner=None):

        """初始化自适应反馈

        Args:

            brain: SmartBrain实例（可选）

            watchdog: SystemWatchdog实例（可选）

            experience_miner: ExperienceMiner实例（可选）

        """

        self.brain = brain

        self.watchdog = watchdog

        self.experience_miner = experience_miner

        self._lock = threading.Lock()

        # CUSUM统计: 每个彩种的累积和

        # cusum_high: 检测命中率偏高，cusum_low: 检测命中率偏低

        self._cusum_data = defaultdict(lambda: {

            "cusum_high": 0.0,

            "cusum_low": 0.0,

            "history": [],          # 近期命中率记录

            "drift": 0.0,          # 允许的偏移量

            "threshold": 4.0,      # CUSUM告警阈值（h参数）

        })

        # 策略调整建议缓存

        self._suggestions_cache = defaultdict(list)

    # ------------------------------------------------------------------

    # 公开接口

    # ------------------------------------------------------------------

    def on_review_complete(self, lot, predictions, actual_nums, hits):

        """复盘完成后的增强回调

        比基础 learn_from_review 多做:

        1. 记录命中率的CUSUM统计

        2. 如果命中率异常偏低，触发策略调整建议

        3. 将结果反馈给Watchdog更新监控指标

        4. 如果发现新模式，通过ExperienceMiner沉淀知识

        Args:

            lot: 彩种名

            predictions: 本期所有预测 [{nums, type, scheme, hits}]

            actual_nums: 实际开奖号码列表

            hits: 总命中数

        """

        with self._lock:

            # 1. 调用SmartBrain的基础学习

            if self.brain and hasattr(self.brain, "learn_from_review"):

                try:

                    self.brain.learn_from_review(lot, predictions, actual_nums)

                except Exception as e:

                    logger.error("SmartBrain学习更新失败 [%s]: %s", lot, e)

            # 策略卡提炼: 复盘统计 → 引擎挂钩知识卡（幂等, 失败降级不影响学习）

            try:

                from engines.strategy_cards import refresh_strategy_cards

                refresh_strategy_cards()

            except Exception as e:

                logger.warning("策略卡提炼失败(降级跳过): %s", e)

            # 2. CUSUM统计

            hit_rate = self._calc_hit_rate(predictions, hits)

            cusum_result = self._update_cusum(lot, hit_rate)

            # 3. 命中率异常偏低时触发策略调整

            if cusum_result.get("alert_low"):

                suggestions = self.suggest_strategy_adjustments(lot)

                self._suggestions_cache[lot] = suggestions.get("suggestions", [])

                logger.warning(

                    "[%s] CUSUM检测命中率偏低 (hit_rate=%.2f%%, cusum_low=%.2f)，"

                    "已生成%d条策略建议",

                    lot, hit_rate * 100,

                    cusum_result["cusum_low"],

                    len(self._suggestions_cache[lot])

                )

            elif cusum_result.get("alert_high"):

                logger.info(

                    "[%s] CUSUM检测命中率偏高 (hit_rate=%.2f%%)，当前策略表现良好",

                    lot, hit_rate * 100

                )

            # 4. 反馈给Watchdog

            if self.watchdog and hasattr(self.watchdog, "update_metric"):

                try:

                    self.watchdog.update_metric(

                        "evolution.hit_rate." + lot, hit_rate

                    )

                    self.watchdog.update_metric(

                        "evolution.cusum_high." + lot,

                        cusum_result.get("cusum_high", 0.0)

                    )

                    self.watchdog.update_metric(

                        "evolution.cusum_low." + lot,

                        cusum_result.get("cusum_low", 0.0)

                    )

                except Exception as e:

                    logger.debug("Watchdog反馈失败: %s", e)

    def suggest_strategy_adjustments(self, lot):

        """基于近期表现建议策略调整

        分析近期CUSUM统计和命中率趋势，给出具体调整建议。

        Args:

            lot: 彩种名

        Returns:

            dict: {

                "lot": "福彩3D",

                "suggestions": [

                    {"type": "weight_adjust", "detail": "...", "confidence": 0.8},

                    {"type": "engine_toggle", "detail": "...", "confidence": 0.6}

                ]

            }

        """

        suggestions = []

        cusum = self._cusum_data.get(lot, {})

        history = cusum.get("history", [])

        if len(history) < 3:

            return {"lot": lot, "suggestions": suggestions}

        # 计算近期平均命中率

        recent_avg = sum(history[-5:]) / len(history[-5:])

        older_avg = sum(history[:-5]) / len(history[:-5]) if len(history) > 5 else recent_avg

        # 策略1: 权重调整建议

        if recent_avg < older_avg * 0.6:

            confidence = min(0.95, 0.5 + (older_avg - recent_avg))

            suggestions.append({

                "type": "weight_adjust",

                "detail": "近期命中率显著下降 ({:.1f}% -> {:.1f}%)，"

                          "建议降低表现最差的引擎权重10-20%".format(

                              older_avg * 100, recent_avg * 100

                          ),

                "confidence": round(confidence, 2),

            })

        # 策略2: 引擎开关建议

        cusum_low = cusum.get("cusum_low", 0.0)

        if cusum_low > 3.0:

            suggestions.append({

                "type": "engine_toggle",

                "detail": "CUSUM低位告警 ({:.1f})，建议暂时降低高风险引擎的使用频率".format(

                    cusum_low

                ),

                "confidence": min(0.9, 0.4 + cusum_low * 0.1),

            })

        # 策略3: 号码范围建议

        if recent_avg < 0.15 and len(history) >= 5:

            suggestions.append({

                "type": "range_narrow",

                "detail": "命中率持续偏低，建议缩小选号范围或增加过滤条件",

                "confidence": 0.5,

            })

        # 策略4: 热号窗口调整

        if len(history) >= 10:

            # 检查最近3期 vs 前7期的差异

            if len(history) >= 10:

                very_recent = sum(history[-3:]) / 3

                mid_recent = sum(history[-10:-3]) / 7

                if very_recent > mid_recent * 1.5:

                    suggestions.append({

                        "type": "hot_window_adjust",

                        "detail": "近期命中率上升明显，可扩大热号窗口获取更多信号",

                        "confidence": min(0.7, (very_recent - mid_recent) * 5),

                    })

        # 按置信度排序

        suggestions.sort(key=lambda s: s["confidence"], reverse=True)

        return {"lot": lot, "suggestions": suggestions}

    def get_cusum_status(self, lot):

        """获取指定彩种的CUSUM统计状态

        Args:

            lot: 彩种名

        Returns:

            dict: {cusum_high, cusum_low, history, alert_high, alert_low}

        """

        with self._lock:

            cusum = self._cusum_data.get(lot, {})

            threshold = cusum.get("threshold", 4.0)

            return {

                "cusum_high": round(cusum.get("cusum_high", 0.0), 3),

                "cusum_low": round(cusum.get("cusum_low", 0.0), 3),

                "history": list(cusum.get("history", [])),

                "alert_high": cusum.get("cusum_high", 0.0) > threshold,

                "alert_low": cusum.get("cusum_low", 0.0) > threshold,

                "threshold": threshold,

            }

    def get_suggestions(self, lot):

        """获取缓存的策略调整建议

        Args:

            lot: 彩种名

        Returns:

            list[dict]: 建议列表

        """

        with self._lock:

            return list(self._suggestions_cache.get(lot, []))

    # ------------------------------------------------------------------

    # 内部方法

    # ------------------------------------------------------------------

    @staticmethod

    def _calc_hit_rate(predictions, total_hits):

        """计算命中率

        Args:

            predictions: 预测列表

            total_hits: 总命中数

        Returns:

            float: 命中率 (0.0-1.0)

        """

        if not predictions:

            return 0.0

        # 统计总预测号码数

        total_nums = 0

        for p in predictions:

            nums_str = p.get("nums", "")

            # 估算号码数

            parts = nums_str.replace("+", ",").replace("[", ",").replace("]", ",").split(",")

            count = sum(1 for part in parts if part.strip().isdigit())

            total_nums += max(1, count)

        if total_nums == 0:

            return 0.0

        return total_hits / total_nums

    def _update_cusum(self, lot, hit_rate):

        """更新CUSUM累积和

        CUSUM (累积和控制图) 算法:

        - S_hi = max(0, S_hi_prev + (hit_rate - target - drift))

        - S_lo = max(0, S_lo_prev + (target - drift - hit_rate))

        - 当 S_hi > h 或 S_lo > h 时触发告警

        Args:

            lot: 彩种名

            hit_rate: 当前命中率

        Returns:

            dict: 更新后的CUSUM状态

        """

        cusum = self._cusum_data[lot]

        # 目标命中率（根据历史自适应）

        history = cusum["history"]

        if len(history) >= 5:

            target = sum(history[-5:]) / 5  # 近5期均值作为目标

        else:

            target = 0.2  # 默认目标20%

        # 允许偏移量（k参数）

        drift = target * 0.05  # 5%的允许偏移

        # 更新累积和

        old_high = cusum["cusum_high"]

        old_low = cusum["cusum_low"]

        cusum["cusum_high"] = max(0.0, old_high + (hit_rate - target - drift))

        cusum["cusum_low"] = max(0.0, old_low + (target - drift - hit_rate))

        cusum["drift"] = drift

        # 记录历史

        history.append(hit_rate)

        # 只保留最近50条

        if len(history) > 50:

            cusum["history"] = history[-50:]

        threshold = cusum["threshold"]

        return {

            "cusum_high": round(cusum["cusum_high"], 3),

            "cusum_low": round(cusum["cusum_low"], 3),

            "target": round(target, 3),

            "drift": round(drift, 3),

            "alert_high": cusum["cusum_high"] > threshold,

            "alert_low": cusum["cusum_low"] > threshold,

        }

    def get_state(self):

        """获取自适应反馈的完整状态（用于持久化）

        Returns:

            dict: 包含cusum和suggestions的状态字典

        """

        with self._lock:

            state = {

                "cusum_data": {},

                "suggestions_cache": {},

            }

            for lot, data in self._cusum_data.items():

                state["cusum_data"][lot] = {

                    "cusum_high": data["cusum_high"],

                    "cusum_low": data["cusum_low"],

                    "history": data["history"][-20:],  # 只保存最近20条

                    "drift": data["drift"],

                    "threshold": data["threshold"],

                }

            for lot, suggs in self._suggestions_cache.items():

                state["suggestions_cache"][lot] = suggs[-5:]  # 只保存最近5条

        return state

    def load_state(self, state):

        """从状态字典恢复（用于从文件加载）

        Args:

            state: 状态字典（来自get_state的输出）

        """

        with self._lock:

            if not state:

                return

            cusum_data = state.get("cusum_data", {})

            for lot, data in cusum_data.items():

                if lot in self._cusum_data:

                    self._cusum_data[lot]["cusum_high"] = data.get("cusum_high", 0.0)

                    self._cusum_data[lot]["cusum_low"] = data.get("cusum_low", 0.0)

                    self._cusum_data[lot]["history"] = data.get("history", [])

                    self._cusum_data[lot]["drift"] = data.get("drift", 0.0)

                    self._cusum_data[lot]["threshold"] = data.get("threshold", 4.0)

            suggs = state.get("suggestions_cache", {})

            for lot, items in suggs.items():

                self._suggestions_cache[lot] = items

# ===================================================================

# 4. 进化管理器 (EvolutionManager)

# ===================================================================
