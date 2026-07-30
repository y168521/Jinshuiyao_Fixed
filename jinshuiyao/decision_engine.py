# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 决策引擎

增强要点：
- 保留所有候选项 (candidates)，不只是最佳推荐
- 加入 value_gap 最低门槛
- 加入赔率范围过滤
- 折扣凯利计算
"""

from typing import Dict, List, Optional
from .schemas import Recommendation
from .odds_utils import OddsUtils
from .calibrator import ProbabilityCalibrator
from .config import (
    EV_THRESHOLD, VALUE_GAP_THRESHOLD,
    MIN_ODDS, MAX_ODDS, KELLY_MULTIPLIER, MAX_STAKE_RATIO,
)
from .logger import get_logger

logger = get_logger(__name__)


class JinshuiyaoDecisionEngine:
    """金水谣决策引擎：模型集成 → 概率校准 → 推荐生成"""

    def __init__(self, models: list = None):
        """
        Args:
            models: 模型列表，默认使用 SimpleEnsemble
        """
        from .models.poisson_model import SimpleEnsemble
        self.ensemble = models if models else SimpleEnsemble()
        if not isinstance(self.ensemble, list) and hasattr(self.ensemble, 'predict_proba'):
            self._use_ensemble = True
        else:
            self._use_ensemble = False

    def ensemble_prob(self, features: Dict) -> Dict[str, float]:
        """多模型集成预测概率"""
        if self._use_ensemble:
            return self.ensemble.predict_proba(features)

        # 多模型加权平均
        from .models.poisson_model import SimpleEnsemble
        ens = SimpleEnsemble(
            models=self.ensemble,
            weights={m.name: 1.0 / len(self.ensemble) for m in self.ensemble}
        )
        return ens.predict_proba(features)

    def recommend(
        self,
        match_id: str,
        odds: Dict[str, float],
        prob: Dict[str, float],
        bankroll: float = 1000.0,
    ) -> Optional[Recommendation]:
        """
        生成推荐

        流程：
        1. 计算市场隐含概率
        2. 校准模型概率
        3. 生成所有候选项
        4. 过滤 + 排序
        5. 返回最佳推荐（含 candidates）

        Returns:
            Recommendation 或 None（无可推荐）
        """
        # 1. 市场隐含概率
        market_prob = OddsUtils.implied_probs_1x2(odds)

        # 2. 概率校准
        calibrated = ProbabilityCalibrator.shrink_to_market(prob, market_prob)

        # 3. 计算各结果指标
        outcomes = {'win': '主胜', 'draw': '平局', 'lose': '客胜'}
        odds_map = {'win': odds['home_win'], 'draw': odds['draw'], 'lose': odds['away_win']}
        ev_map = OddsUtils.calculate_ev(calibrated, odds)
        value_gaps = OddsUtils.value_gap(calibrated, market_prob)
        margin = OddsUtils.bookmaker_margin(odds)

        # 4. 生成所有候选项
        candidates = []
        best_ev = -999
        best_outcome = None

        for key, label in outcomes.items():
            ev = ev_map[key]
            gap = value_gaps[key]
            odd = odds_map[key]

            kelly = OddsUtils.calculate_kelly(calibrated[key], odd, KELLY_MULTIPLIER)

            candidates.append({
                'outcome': label,
                'prob': round(calibrated[key], 4),
                'odds': odd,
                'ev': round(ev, 4),
                'kelly': round(kelly, 4),
                'value_gap': round(gap, 4),
                'market_prob': round(market_prob[key], 4),
            })

            if ev > best_ev:
                best_ev = ev
                best_outcome = key

        candidates.sort(key=lambda x: x['ev'], reverse=True)

        # 5. 过滤条件
        if best_outcome is None:
            logger.info(f"[{match_id}] 无有效候选项")
            return None

        best = {c['outcome']: c for c in candidates}[outcomes[best_outcome]]

        # EV 门槛
        if best['ev'] < EV_THRESHOLD:
            logger.info(f"[{match_id}] EV={best['ev']:.4f} < {EV_THRESHOLD}, 不推荐")
            return None

        # 价值差门槛
        if best['value_gap'] < VALUE_GAP_THRESHOLD:
            logger.info(f"[{match_id}] value_gap={best['value_gap']:.4f} < {VALUE_GAP_THRESHOLD}, 不推荐")
            return None

        # 赔率范围过滤
        if best['odds'] < MIN_ODDS:
            logger.info(f"[{match_id}] 赔率={best['odds']:.2f} < {MIN_ODDS}, 过低不推荐")
            return None
        if best['odds'] > MAX_ODDS:
            logger.info(f"[{match_id}] 赔率={best['odds']:.2f} > {MAX_ODDS}, 过高不推荐")
            return None

        # 6. 计算建议投注额
        suggested_stake = min(
            best['kelly'] * bankroll,
            bankroll * MAX_STAKE_RATIO,
        )

        # 7. 分级
        if best['ev'] > 0.10 and best['value_gap'] > 0.06:
            tier = "high"
            confidence = "高"
        elif best['ev'] > 0.05 and best['value_gap'] > 0.04:
            tier = "medium"
            confidence = "中"
        else:
            tier = "low"
            confidence = "低"

        return Recommendation(
            match_id=match_id,
            recommendation=outcomes[best_outcome],
            probability=best['prob'],
            odds=best['odds'],
            ev=best['ev'],
            kelly=best['kelly'],
            suggested_stake=round(suggested_stake, 2),
            tier=tier,
            confidence=confidence,
            candidates=candidates,
            value_gap=best['value_gap'],
            model_prob=calibrated,
            market_prob=market_prob,
        )

    # ================================================================
    # v2.3 新增：市场/模型加权融合 + 简化推荐（含概率压缩）
    # ================================================================

    @staticmethod
    def ensemble_probability(
        market_probs: Dict[str, float],
        model_probs: Dict[str, float],
        market_weight: float = 0.6,
        model_weight: float = 0.4,
    ) -> Dict[str, float]:
        """
        加权融合市场概率与模型概率（v2.3）

        fused = market_weight * market_prob + model_weight * model_prob
        然后归一化。

        与 shrink_to_market 的区别：
        - shrink_to_market 使用 alpha 控制融合度（1-alpha 给市场）
        - ensemble_probability 分别指定两个权重，更直观

        Args:
            market_probs: 市场隐含概率 {'win': 0.44, 'draw': 0.29, 'lose': 0.27}
            model_probs:  模型预测概率 {'win': 0.51, 'draw': 0.25, 'lose': 0.24}
            market_weight: 市场权重 (0~1)
            model_weight:  模型权重 (0~1)

        Returns:
            融合后归一化概率
        """
        fused = {}
        for key in market_probs:
            fused[key] = market_weight * market_probs.get(key, 0) + model_weight * model_probs.get(key, 0)

        total = sum(fused.values())
        if total == 0:
            return {'win': 1/3, 'draw': 1/3, 'lose': 1/3}
        return {k: v / total for k, v in fused.items()}

    def get_simple_recommendation(
        self,
        odds: Dict[str, float],
        model_probs: Dict[str, float],
        bankroll: float = 1000.0,
        max_single_pct: float = 0.02,
        use_compression: bool = True,
    ) -> Optional[Recommendation]:
        """
        简化推荐（v2.3 风格）—— 适合快速决策

        流程：
        1. 可选：单概率压缩（compress_high_prob）
        2. 逐方向计算 EV
        3. 选最大 EV 方向
        4. 半凯利计算仓位
        5. EV 分层

        与 recommend() 的区别：
        - 不做 shrink_to_market 校准
        - 不做 value_gap 过滤
        - 不做赔率范围过滤
        - 更快更轻量，适合实时/批量场景

        Args:
            odds: 赔率 {'home_win': 1.53, 'draw': 3.50, 'lose': 5.25}
            model_probs: 模型概率 {'win': 0.51, 'draw': 0.25, 'lose': 0.24}
            bankroll: 当前资金
            max_single_pct: 单注最大资金占比
            use_compression: 是否对 >0.5 概率进行压缩

        Returns:
            Recommendation 或 None
        """
        from .calibrator import ProbabilityCalibrator

        direction_map = {'win': '主胜', 'draw': '平局', 'lose': '客胜'}
        odds_key_map = {'win': 'home_win', 'draw': 'draw', 'lose': 'lose'}
        best_ev = -999
        best_direction = None
        best_prob = 0.0
        best_odd = 0.0

        for direction, prob in model_probs.items():
            odd = odds.get(odds_key_map[direction])
            if odd is None or odd <= 1.0:
                continue

            # 单概率压缩
            prob_used = prob
            if use_compression and prob > 0.5:
                prob_used = ProbabilityCalibrator.compress_high_prob(prob)

            ev = prob_used * (odd - 1) - (1 - prob_used)
            if ev > best_ev:
                best_ev = ev
                best_direction = direction
                best_prob = prob_used
                best_odd = odd

        if best_ev <= 0 or best_direction is None:
            logger.info("简化推荐: 无正EV方向")
            return None

        # 半凯利仓位
        b = best_odd - 1
        full_kelly = (b * best_prob - (1 - best_prob)) / b if b > 0 else 0
        half_kelly = full_kelly * 0.6
        stake_pct = min(max(0, half_kelly), max_single_pct)
        stake = bankroll * stake_pct

        # 分级
        if best_ev > 0.05:
            tier, confidence = "high", "高"
        elif best_ev > 0.02:
            tier, confidence = "medium", "中"
        else:
            tier, confidence = "low", "低"

        # 计算凯利
        kelly = OddsUtils.calculate_kelly(best_prob, best_odd, 0.25)

        return Recommendation(
            match_id="simple",
            recommendation=direction_map[best_direction],
            probability=round(best_prob, 4),
            odds=best_odd,
            ev=round(best_ev, 4),
            kelly=round(kelly, 4),
            suggested_stake=round(stake, 2),
            tier=tier,
            confidence=confidence,
            value_gap=0.0,
        )