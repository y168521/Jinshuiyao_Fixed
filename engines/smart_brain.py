# -*- coding: utf-8 -*-
"""
金水谣智能大脑 - 自适应学习模块

基于历史复盘数据实现三大核心能力：
1. 置信度评分 - 每次预测前评估信心水平
2. 策略权重自适应 - 根据复盘表现自动调整方案权重
3. 号码级自我修正 - 精确到每个数字的偏态修正

数据来源: 金水谣数据/predictions.json (复盘数据)
持久化:   金水谣数据/brain_state.json (学习状态)
"""

import json
import os
import math
import logging
from collections import defaultdict
from utils.safe_json import safe_load_json, safe_write_json

logger = logging.getLogger(__name__)

class SmartBrain:
    """智能大脑 - 越跑越稳的自适应预测引擎"""

    # 状态文件路径
    STATE_FILE = None  # 初始化时设置

    def __init__(self, data_dir="金水谣数据"):
        self.data_dir = data_dir
        self.STATE_FILE = os.path.join(data_dir, "brain_state.json")
        self.pred_file = os.path.join(data_dir, "predictions.json")

        # 加载持久化状态
        self.state = self._load_state()

        # 加载复盘数据
        self.history = self._load_history()

        logger.info("智能大脑就绪 (学习记录: %d条)", len(self.history))

    def _load_state(self):
        """加载学习状态（持久化）"""
        default = {
            "version": 1,
            "strategy_weights": {},     # {彩种: {方案: 权重}}
            "digit_bias": {},            # {彩种: {数字: 偏差值}}
            "confidence_history": [],    # [{lot, confidence, actual_hits}]
            "total_reviews": 0,
            "last_updated": "",
        }
        loaded = safe_load_json(self.STATE_FILE, default=None)
        if loaded:
            for key, val in default.items():
                if key not in loaded:
                    loaded[key] = val
            return loaded
        return default

    def _save_state(self):
        """保存学习状态（原子写入）"""
        try:
            os.makedirs(os.path.dirname(self.STATE_FILE), exist_ok=True)
            safe_write_json(self.STATE_FILE, self.state)
        except Exception as e:
            logger.warning("保存大脑状态失败: %s", e)

    def _load_history(self):
        """加载复盘数据（兼容 list / dict 两种 predictions.json 格式）"""
        recovered = safe_load_json(self.pred_file, default=None)
        if not recovered:
            return []
        # 兼容 dict 格式（按彩种分组的嵌套结构）
        if isinstance(recovered, dict):
            predictions = []
            if "predictions" in recovered:
                for _lot, items in recovered["predictions"].items():
                    if isinstance(items, list):
                        predictions.extend(items)
            else:
                predictions = list(recovered.values())
        elif isinstance(recovered, list):
            predictions = recovered
        else:
            return []
        return [p for p in predictions
                if isinstance(p, dict) and p.get('reviewed') and p.get('hits') is not None]

    def refresh_history(self):
        """刷新历史数据（复盘回写后调用，确保generate使用最新数据）"""
        self.history = self._load_history()

    # ================================================================
    # 能力1: 置信度评分
    # ================================================================

    def assess_confidence(self, lot, hot_weights=None, final_hot=None):
        """评估当前预测的置信度

        综合三个维度:
        1. 近期命中率趋势 (40%权重) - 最近10期的命中趋势
        2. 热号稳定性 (30%权重) - 热号分布是否集中
        3. 多策略一致性 (30%权重) - 多种策略是否指向相似号码

        Returns:
            float: 0.0-1.0 的置信度分数
        """
        # 维度1: 近期命中率趋势
        trend_score = self._calc_hit_trend(lot)

        # 维度2: 热号稳定性
        stability_score = self._calc_hot_stability(lot, final_hot)

        # 维度3: 多策略一致性
        consistency_score = self._calc_strategy_consistency(lot)

        # 加权综合
        confidence = (trend_score * 0.4 + stability_score * 0.3 + consistency_score * 0.3)
        confidence = max(0.0, min(1.0, confidence))

        # 记录
        self.state["confidence_history"].append({
            "lot": lot,
            "confidence": round(confidence, 3),
            "trend": round(trend_score, 3),
            "stability": round(stability_score, 3),
            "consistency": round(consistency_score, 3),
            "actual_hits": None,
        })
        # 只保留最近100条
        if len(self.state["confidence_history"]) > 100:
            self.state["confidence_history"] = self.state["confidence_history"][-100:]

        logger.info("[%s] 置信度: %.1f%% (趋势%.0f%% + 稳定%.0f%% + 一致%.0f%%)",
                    lot, confidence * 100, trend_score * 100,
                    stability_score * 100, consistency_score * 100)

        return confidence

    def _calc_hit_trend(self, lot, window=10):
        """近期命中率趋势 (0-1)"""
        lot_reviews = [p for p in self.history if p.get('lot') == lot]
        if len(lot_reviews) < 5:
            return 0.5  # 数据不足，中性

        # 按期号分组，取最近window期
        periods = defaultdict(list)
        for p in lot_reviews:
            periods[p.get('period', '')].append(p.get('hits', 0))

        sorted_periods = sorted(periods.keys())[-window:]
        if not sorted_periods:
            return 0.5

        # 每期平均命中
        period_avg = []
        for per in sorted_periods:
            hits_list = periods[per]
            period_avg.append(sum(hits_list) / len(hits_list))

        # 计算趋势：后半段 vs 前半段
        mid = len(period_avg) // 2
        if mid == 0:
            return 0.5

        recent_avg = sum(period_avg[mid:]) / len(period_avg[mid:])
        older_avg = sum(period_avg[:mid]) / len(period_avg[:mid]) if period_avg[:mid] else 0

        if older_avg == 0:
            return 0.8 if recent_avg > 0 else 0.3

        improvement = (recent_avg - older_avg) / max(0.1, older_avg)
        # improvement: -1到+1，映射到0-1
        score = 0.5 + improvement * 0.3
        return max(0.0, min(1.0, score))

    def _calc_hot_stability(self, lot, final_hot):
        """热号稳定性 (0-1) - 热号越集中越稳定"""
        if not final_hot:
            return 0.5

        values = list(final_hot.values())
        if len(values) < 3:
            return 0.5

        # 用变异系数(CV)衡量稳定性：CV越小越稳定
        mean_val = sum(values) / len(values)
        if mean_val == 0:
            return 0.5

        variance = sum((v - mean_val) ** 2 for v in values) / len(values)
        std_val = math.sqrt(variance)
        cv = std_val / mean_val

        # CV范围大约0-3，映射到1-0（越稳定分数越高）
        score = max(0.0, min(1.0, 1.0 - cv * 0.5))
        return score

    def _calc_strategy_consistency(self, lot):
        """多策略一致性 (0-1)"""
        lot_reviews = [p for p in self.history if p.get('lot') == lot]
        if len(lot_reviews) < 10:
            return 0.5

        # 按方案分组的命中率
        scheme_hits = defaultdict(list)
        for p in lot_reviews:
            scheme = p.get('scheme', '默认方案')
            scheme_hits[scheme].append(p.get('hits', 0))

        if len(scheme_hits) < 2:
            return 0.6

        # 如果多种方案的命中率都>0，说明一致性高
        avg_by_scheme = {}
        for scheme, hits in scheme_hits.items():
            avg_by_scheme[scheme] = sum(hits) / len(hits)

        values = list(avg_by_scheme.values())
        # 所有方案都至少有1个命中 = 高一致性
        all_positive = all(v > 0.5 for v in values)
        if all_positive:
            return 0.8 + 0.1 * min(1, len(values) - 2)

        # 部分方案有命中
        positive_ratio = sum(1 for v in values if v > 0.5) / len(values)
        return max(0.2, 0.3 + positive_ratio * 0.5)

    # ================================================================
    # 能力2: 策略权重自适应
    # ================================================================

    def get_strategy_weights(self, lot):
        """获取各方案的推荐权重

        Returns:
            dict: {方案名: 权重(0-1)} 如 {"默认方案": 0.45, "智能融合": 0.30, "参考方案": 0.25}
        """
        lot_reviews = [p for p in self.history if p.get('lot') == lot]

        if len(lot_reviews) < 10:
            # 数据不足，使用均等权重
            return {"默认方案": 0.40, "智能融合": 0.30, "参考方案": 0.30}

        # 按方案统计
        scheme_stats = defaultdict(lambda: {'total': 0, 'hits_sum': 0, 'zero_count': 0})
        for p in lot_reviews:
            scheme = p.get('scheme', '默认方案')
            scheme_stats[scheme]['total'] += 1
            scheme_stats[scheme]['hits_sum'] += p.get('hits', 0)
            if p.get('hits', 0) == 0:
                scheme_stats[scheme]['zero_count'] += 1

        # 计算每个方案的综合得分
        scores = {}
        for scheme, stats in scheme_stats.items():
            if stats['total'] < 3:
                continue
            avg_hits = stats['hits_sum'] / stats['total']
            zero_rate = stats['zero_count'] / stats['total']

            # 得分 = 平均命中 * 2 - 零码率惩罚
            score = avg_hits * 2.0 - zero_rate * 0.5
            scores[scheme] = max(0.05, score)

        # 归一化
        total_score = sum(scores.values())
        if total_score == 0:
            return {"默认方案": 0.40, "智能融合": 0.30, "参考方案": 0.30}

        weights = {s: v / total_score for s, v in scores.items()}

        # 确保三种方案都有权重
        for s in ["默认方案", "智能融合", "参考方案"]:
            if s not in weights:
                weights[s] = 0.15
                total_score += 0.15
        # 重新归一化
        total_score = sum(weights.values())
        weights = {s: v / total_score for s, v in weights.items()}

        # 缓存
        self.state.setdefault("strategy_weights", {})[lot] = weights

        return weights

    def recommend_budget_split(self, lot, total_budget=149):
        """根据策略权重推荐预算分配

        Returns:
            dict: {方案: 预算金额}
        """
        weights = self.get_strategy_weights(lot)

        # 基础预算分配（3个方案）
        split = {}
        remaining = total_budget

        # 默认方案至少占40%预算
        schemes = ["默认方案", "智能融合", "参考方案"]

        for i, scheme in enumerate(schemes):
            if i == len(schemes) - 1:
                split[scheme] = remaining
            else:
                amount = int(remaining * weights.get(scheme, 0.33) / sum(weights.get(s, 0.33) for s in schemes[i:]))
                split[scheme] = max(20, min(amount, remaining - 40))
                remaining -= split[scheme]

        return split

    # ================================================================
    # 能力3: 号码级自我修正
    # ================================================================

    def get_digit_adjustments(self, lot):
        """获取号码级修正权重

        分析历史预测中每个数字的命中偏差:
        - 预测多但命中少 → 降权 (负偏差)
        - 预测少但命中多 → 升权 (正偏差)
        - 遗漏极久的号码 → 升权 (冷号突破)

        Returns:
            dict: {数字: 修正系数(0.5-1.5)}
        """
        lot_reviews = [p for p in self.history if p.get('lot') == lot]

        # 确定号码范围
        ranges = {
            "福彩3D": (0, 9), "排列三": (0, 9),
            "七乐彩": (1, 30), "七星彩": (0, 9),
            "快乐8": (1, 80), "双色球": (1, 33),
            "大乐透": (1, 35),
        }
        rmin, rmax = ranges.get(lot, (1, 35))
        all_digits = list(range(rmin, rmax + 1))

        if len(lot_reviews) < 20:
            return {d: 1.0 for d in all_digits}

        # 统计每个数字的出现次数和命中次数
        digit_pred_count = defaultdict(int)   # 预测中出现的次数
        digit_hit_count = defaultdict(int)    # 命中中出现的次数

        for p in lot_reviews:
            nums_str = p.get('nums', '')
            hits = p.get('hits', 0)

            # 提取预测中的数字
            pred_digits = set()
            for part in nums_str.replace('+', ',').replace(']', ',').replace('[', ',').split(','):
                part = part.strip()
                if part.isdigit():
                    pred_digits.add(int(part))

            for d in pred_digits:
                if rmin <= d <= rmax:
                    digit_pred_count[d] += 1

        # 从复盘记录反推命中数字（简化：用命中率估算）
        # 如果一条记录命中>=1，假设预测中最前面的数字命中
        for p in lot_reviews:
            if p.get('hits', 0) > 0:
                nums_str = p.get('nums', '')
                digits = []
                for part in nums_str.replace('+', ',').replace(']', ',').replace('[', ',').split(','):
                    part = part.strip()
                    if part.isdigit() and rmin <= int(part) <= rmax:
                        digits.append(int(part))

                # 简化：前N个数字有更高命中概率
                hit_estimate = min(p.get('hits', 1), len(digits))
                for d in digits[:max(1, hit_estimate)]:
                    digit_hit_count[d] += 1

        # 计算偏差
        adjustments = {}
        for d in all_digits:
            pred_count = digit_pred_count.get(d, 0)
            hit_count = digit_hit_count.get(d, 0)

            if pred_count == 0:
                # 从未被预测过 → 轻微升权（可能有盲区）
                adjustments[d] = 1.1
            else:
                hit_rate = hit_count / pred_count
                # hit_rate基准约0.2-0.3（对3D）或更低（对大号码池）
                # 偏差 = 实际命中率 / 期望命中率
                # 如果 hit_rate > 期望 → 升权，反之降权
                expected_rate = 0.25 if rmax <= 9 else (3 / max(1, (rmax - rmin + 1)))
                if expected_rate == 0:
                    expected_rate = 0.05

                bias = hit_rate / max(0.01, expected_rate)
                # 映射到 0.5-1.5
                adj = 0.7 + bias * 0.5
                adjustments[d] = max(0.5, min(1.5, adj))

        # 冷号突破修正：遗漏很久的号码额外加权
        cold_bonus = self._get_cold_breakthrough(lot, all_digits)
        for d, bonus in cold_bonus.items():
            adjustments[d] = min(1.5, adjustments.get(d, 1.0) + bonus)

        # 缓存
        self.state.setdefault("digit_bias", {})[lot] = {str(k): round(v, 3) for k, v in adjustments.items()}

        logger.info("[%s] 号码修正: 升权TOP3=%s, 降权TOP3=%s",
                    lot,
                    sorted(adjustments.items(), key=lambda x: -x[1])[:3],
                    sorted(adjustments.items(), key=lambda x: x[1])[:3])

        return adjustments

    def _get_cold_breakthrough(self, lot, all_digits):
        """冷号突破检测：遗漏很久的号码加权"""
        # 从复盘数据中估算遗漏值（简化实现）
        return {d: 0.0 for d in all_digits}  # 基础版不实现，后续可扩展

    # ================================================================
    # 学习更新（复盘后调用）
    # ================================================================

    def learn_from_review(self, lot, predictions, actual_nums):
        """复盘后学习更新

        Args:
            lot: 彩种名
            predictions: 本期所有预测 [{nums, type, scheme, hits}]
            actual_nums: 实际开奖号码列表
        """
        self.state["total_reviews"] = self.state.get("total_reviews", 0) + 1
        self.state["last_updated"] = str(len(self.history))

        # 更新号码偏差
        self._update_digit_bias(lot, predictions, actual_nums)

        # 每次复盘都保存状态（确保重启不丢失学习成果）
        self._save_state()
        logger.info("智能大脑学习状态已保存 (累计%d次复盘)", self.state["total_reviews"])

    def _update_digit_bias(self, lot, predictions, actual_nums):
        """更新号码偏差"""
        if not actual_nums:
            return

        actual_set = set(actual_nums)
        pred_all_digits = defaultdict(int)
        pred_hit_digits = defaultdict(int)

        for p in predictions:
            nums_str = p.get('nums', '')
            hits = p.get('hits', 0)

            digits = []
            for part in nums_str.replace('+', ',').replace(']', ',').replace('[', ',').split(','):
                part = part.strip()
                if part.isdigit():
                    digits.append(int(part))

            for d in digits:
                pred_all_digits[d] += 1
                if d in actual_set:
                    pred_hit_digits[d] += 1

        # 记录偏差
        lot_bias = self.state.setdefault("digit_bias", {}).setdefault(lot, {})
        for d in set(list(pred_all_digits.keys()) + list(actual_nums)):
            pred = pred_all_digits.get(d, 0)
            hit = pred_hit_digits.get(d, 0)
            was_in_actual = 1 if d in actual_set else 0

            # 偏差 = 预测命中率 vs 是否中奖
            # 用滑动平均更新
            old_bias = float(lot_bias.get(str(d), 1.0))
            if pred > 0:
                actual_rate = hit / pred
            else:
                actual_rate = 0.5  # 没预测过

            # 期望中奖率
            rmin, rmax = 0, 9
            for lot_key, (rmin_k, rmax_k) in {
                "福彩3D": (0, 9), "排列三": (0, 9),
                "七乐彩": (1, 30), "七星彩": (0, 9),
                "快乐8": (1, 80), "双色球": (1, 33),
                "大乐透": (1, 35),
            }.items():
                if lot == lot_key:
                    rmin, rmax = rmin_k, rmax_k
                    break

            pool_size = rmax - rmin + 1
            pick_size = len(actual_nums) if actual_nums else 3
            expected = min(1.0, pick_size / max(1, pool_size))

            new_bias = old_bias * 0.8 + (actual_rate / max(0.01, expected)) * 0.2
            new_bias = max(0.5, min(1.5, new_bias))

            lot_bias[str(d)] = round(new_bias, 3)

    # ================================================================
    # 辅助方法
    # ================================================================

    def get_confidence_level(self, lot, hot_weights=None, final_hot=None):
        """获取置信度等级和对应建议"""
        conf = self.assess_confidence(lot, hot_weights, final_hot)

        if conf >= 0.7:
            return "HIGH", conf, "高置信 - 可适当扩大覆盖"
        elif conf >= 0.5:
            return "MEDIUM", conf, "中置信 - 标准策略"
        else:
            return "LOW", conf, "低置信 - 保守策略，缩窄范围"

    def get_status_report(self):
        """获取智能大脑状态报告"""
        return {
            "total_reviews": self.state.get("total_reviews", 0),
            "history_size": len(self.history),
            "saved_strategy_weights": self.state.get("strategy_weights", {}),
            "digit_bias_lots": list(self.state.get("digit_bias", {}).keys()),
            "confidence_records": len(self.state.get("confidence_history", [])),
        }
