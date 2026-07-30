# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 评估层

增强要点：
- 三分类完整 Brier 分数（不是只看预测类别）
- 命中率、平均概率、按模型分组统计
- 支持多模型对比
"""

from typing import Dict, List
import pandas as pd
from .logger import get_logger

logger = get_logger(__name__)


class JinshuiyaoEvaluator:
    """金水谣评估器"""

    def __init__(self):
        self.results: List[dict] = []
        self._bets: List[dict] = []  # v2.3: 投注盈亏记录

    def add_prediction(
        self,
        match_id: str,
        model_name: str,
        pred_win: float,
        pred_draw: float,
        pred_lose: float,
        actual: str,
        odds: Dict[str, float] = None,
        recommendation: str = None,
    ):
        """
        添加一条预测记录

        Args:
            match_id: 比赛ID
            model_name: 模型名称
            pred_win/draw/lose: 预测概率
            actual: 实际赛果 ('win'/'draw'/'lose')
            odds: 赔率数据
            recommendation: 推荐结果
        """
        self.results.append({
            'match_id': match_id,
            'model': model_name,
            'pred_win': pred_win,
            'pred_draw': pred_draw,
            'pred_lose': pred_lose,
            'actual': actual,
            'odds_home': odds.get('home_win') if odds else None,
            'odds_draw': odds.get('draw') if odds else None,
            'odds_away': odds.get('lose') if odds else None,
            'recommendation': recommendation,
            'correct': (recommendation == self._actual_to_label(actual)) if recommendation else None,
        })

    @staticmethod
    def _actual_to_label(actual: str) -> str:
        mapping = {'win': '主胜', 'draw': '平局', 'lose': '客胜'}
        return mapping.get(actual, actual)

    def compute_model_brier(self, model_name: str) -> float:
        """
        三分类完整 Brier 分数

        Brier = (1/N) * Σ Σ (p_ij - y_ij)²

        其中 y_ij 是 one-hot 编码的实际结果。
        分数越低越好，0 表示完美预测。
        """
        df = pd.DataFrame([r for r in self.results if r['model'] == model_name])
        if df.empty:
            return 1.0

        score = 0.0
        for _, row in df.iterrows():
            if row['actual'] == 'win':
                target = [1, 0, 0]
            elif row['actual'] == 'draw':
                target = [0, 1, 0]
            else:
                target = [0, 0, 1]

            pred = [row['pred_win'], row['pred_draw'], row['pred_lose']]
            score += sum((p - y) ** 2 for p, y in zip(pred, target))

        return score / len(df)

    def compute_accuracy(self, model_name: str = None) -> float:
        """计算准确率（最高概率类别是否命中）"""
        df = pd.DataFrame(self.results)
        if model_name:
            df = df[df['model'] == model_name]
        if df.empty:
            return 0.0

        correct = 0
        for _, row in df.iterrows():
            pred_map = {'win': row['pred_win'], 'draw': row['pred_draw'], 'lose': row['pred_lose']}
            predicted = max(pred_map, key=pred_map.get)
            if predicted == row['actual']:
                correct += 1

        return correct / len(df)

    def compute_log_loss(self, model_name: str = None) -> float:
        """计算对数损失 (Log Loss)"""
        df = pd.DataFrame(self.results)
        if model_name:
            df = df[df['model'] == model_name]
        if df.empty:
            return float('inf')

        import math
        total_loss = 0.0
        for _, row in df.iterrows():
            if row['actual'] == 'win':
                p = max(row['pred_win'], 1e-15)
            elif row['actual'] == 'draw':
                p = max(row['pred_draw'], 1e-15)
            else:
                p = max(row['pred_lose'], 1e-15)
            total_loss += -math.log(p)

        return total_loss / len(df)

    def summary(self, model_name: str = None) -> Dict:
        """生成评估汇总"""
        df = pd.DataFrame(self.results)
        if model_name:
            df = df[df['model'] == model_name]

        if df.empty:
            return {'total': 0, 'error': '无数据'}

        return {
            'total_predictions': len(df),
            'accuracy': round(self.compute_accuracy(model_name), 4),
            'brier_score': round(self.compute_model_brier(model_name or 'all'), 4),
            'log_loss': round(self.compute_log_loss(model_name), 4),
            'avg_pred_win': round(df['pred_win'].mean(), 4),
            'avg_pred_draw': round(df['pred_draw'].mean(), 4),
            'avg_pred_lose': round(df['pred_lose'].mean(), 4),
            'actual_win_pct': round((df['actual'] == 'win').mean(), 4),
            'actual_draw_pct': round((df['actual'] == 'draw').mean(), 4),
            'actual_lose_pct': round((df['actual'] == 'lose').mean(), 4),
        }

    def compare_models(self) -> pd.DataFrame:
        """多模型对比"""
        df = pd.DataFrame(self.results)
        if df.empty:
            return pd.DataFrame()

        models = df['model'].unique()
        rows = []
        for m in models:
            mdf = df[df['model'] == m]
            rows.append({
                'model': m,
                'count': len(mdf),
                'accuracy': round(self.compute_accuracy(m), 4),
                'brier': round(self.compute_model_brier(m), 4),
                'log_loss': round(self.compute_log_loss(m), 4),
            })
        return pd.DataFrame(rows)

    # ================================================================
    # v2.3 新增：ROI 计算 + 策略有效性判定
    # ================================================================

    def record_bet(
        self,
        match_id: str,
        strategy: str,
        recommendation: str,
        stake: float,
        odds: float,
        profit: float,
        won: bool,
        ev: float = 0.0,
        tier: str = "",
    ):
        """
        记录一笔投注的盈亏（v2.3）

        Args:
            match_id: 比赛ID
            strategy: 策略名称 (如 'poisson', 'ensemble')
            recommendation: 推荐方向 ('主胜'/'平局'/'客胜')
            stake: 投注金额
            odds: 投注赔率
            profit: 实际盈亏（正=盈利，负=亏损）
            won: 是否命中
            ev: 期望价值
            tier: 推荐分级
        """
        self._bets.append({
            'match_id': match_id,
            'strategy': strategy,
            'recommendation': recommendation,
            'stake': stake,
            'odds': odds,
            'profit': profit,
            'won': won,
            'ev': ev,
            'tier': tier,
        })
        logger.debug(f"记录投注: {match_id} {recommendation} stake={stake:.2f} profit={profit:.2f}")

    def compute_roi(self, strategy: str = None) -> float:
        """
        计算 ROI（投资回报率）

        ROI = 总盈利 / 总投注额

        Args:
            strategy: 策略名称，None 表示全部

        Returns:
            ROI 值，如 0.05 表示 +5%
        """
        bets = self._bets
        if strategy:
            bets = [b for b in bets if b['strategy'] == strategy]

        if not bets:
            return 0.0

        total_stake = sum(b['stake'] for b in bets)
        total_profit = sum(b['profit'] for b in bets)
        if total_stake == 0:
            return 0.0
        return total_profit / total_stake

    def strategy_effectiveness(
        self,
        strategy: str,
        threshold_roi: float = -0.05,
        min_bets: int = 20,
    ) -> str:
        """
        策略有效性判定（v2.3）

        根据 ROI 和历史投注数对策略分级：
        - 'effective': ROI > +2%，有正期望
        - 'general':   ROI 在 -5% ~ +2% 之间，效果一般
        - 'invalid':   ROI < -5% 或样本不足，策略无效
        - 'insufficient_data': 投注数不足

        Args:
            strategy: 策略名称
            threshold_roi: 无效策略的 ROI 下限
            min_bets: 最少投注数才可判定

        Returns:
            'effective' / 'general' / 'invalid' / 'insufficient_data'
        """
        bets = [b for b in self._bets if b['strategy'] == strategy]
        if len(bets) < min_bets:
            logger.info(f"策略 '{strategy}' 投注数 {len(bets)} < {min_bets}，数据不足")
            return "insufficient_data"

        roi = self.compute_roi(strategy)
        hit_rate = sum(1 for b in bets if b['won']) / len(bets) if bets else 0

        if roi > 0.02:
            logger.info(f"策略 '{strategy}' 有效: ROI={roi:.2%} 胜率={hit_rate:.2%}")
            return "effective"
        elif roi > threshold_roi:
            logger.info(f"策略 '{strategy}' 一般: ROI={roi:.2%} 胜率={hit_rate:.2%}")
            return "general"
        else:
            logger.warning(f"策略 '{strategy}' 无效: ROI={roi:.2%} 胜率={hit_rate:.2%}，建议淘汰或调整")
            return "invalid"

    def strategy_report(self, strategy: str = None) -> Dict:
        """
        策略完整报告（v2.3）

        Returns:
            {
                'total_bets': 50,
                'won_bets': 28,
                'hit_rate': 0.56,
                'total_stake': 5000.0,
                'total_profit': 320.0,
                'roi': 0.064,
                'avg_odds': 2.15,
                'effectiveness': 'effective',
                'tier_breakdown': {'high': 5, 'medium': 15, 'low': 30},
            }
        """
        bets = self._bets
        if strategy:
            bets = [b for b in bets if b['strategy'] == strategy]

        if not bets:
            return {'total_bets': 0, 'error': '无投注记录'}

        total_bets = len(bets)
        won_bets = sum(1 for b in bets if b['won'])
        total_stake = sum(b['stake'] for b in bets)
        total_profit = sum(b['profit'] for b in bets)
        roi = total_profit / total_stake if total_stake > 0 else 0
        avg_odds = sum(b['odds'] for b in bets) / total_bets if total_bets > 0 else 0
        effectiveness = self.strategy_effectiveness(strategy or 'all', min_bets=1) if strategy else 'N/A'

        tier_count = {'high': 0, 'medium': 0, 'low': 0}
        for b in bets:
            t = b.get('tier', 'low')
            if t in tier_count:
                tier_count[t] += 1

        return {
            'total_bets': total_bets,
            'won_bets': won_bets,
            'hit_rate': round(won_bets / total_bets, 4) if total_bets > 0 else 0,
            'total_stake': round(total_stake, 2),
            'total_profit': round(total_profit, 2),
            'roi': round(roi, 4),
            'avg_odds': round(avg_odds, 2),
            'effectiveness': effectiveness,
            'tier_breakdown': tier_count,
        }