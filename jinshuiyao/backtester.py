# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 回测模块

核心功能：
- 批量跑历史比赛，统计 ROI、命中率、最大回撤
- 记录每场盈亏、CLV（收盘赔率价值）
- 支持按联赛/时间段分组统计
"""

from typing import Dict, List, Optional
import pandas as pd
from .schemas import BacktestRecord, BacktestSummary, MatchInfo
from .feature_engine import JinshuiyaoFeatureEngine
from .logger import get_logger

logger = get_logger(__name__)


class JinshuiyaoBacktester:
    """金水谣回测器"""

    def __init__(
        self,
        provider,
        feature_engine: JinshuiyaoFeatureEngine,
        decision_engine,
        risk_controller=None,
    ):
        self.provider = provider
        self.feature_engine = feature_engine
        self.decision_engine = decision_engine
        self.risk_controller = risk_controller

    def run(
        self,
        match_ids: List[str],
        bankroll: float = 1000.0,
        verbose: bool = False,
    ) -> BacktestSummary:
        """
        执行回测

        Args:
            match_ids: 比赛 ID 列表
            bankroll: 初始资金
            verbose: 是否打印详细信息

        Returns:
            BacktestSummary 回测汇总
        """
        records: List[BacktestRecord] = []
        current_bankroll = bankroll
        peak_bankroll = bankroll
        max_drawdown = 0.0
        total_bets = 0
        won_bets = 0

        for match_id in match_ids:
            try:
                # 1. 获取比赛数据
                match_info = self.provider.get_match_basic(match_id)

                home_form = self.provider.get_recent_form(match_info.home_team_id, n=10)
                away_form = self.provider.get_recent_form(match_info.away_team_id, n=10)

                home_agg = self.feature_engine.aggregate_recent_form(home_form)
                away_agg = self.feature_engine.aggregate_recent_form(away_form)

                features = self.feature_engine.build_features(
                    match_info,
                    home_agg,
                    away_agg,
                    injury={'home_loss': 0.0, 'away_loss': 0.0},
                )

                # 2. 模型预测
                prob = self.decision_engine.ensemble_prob(features)
                odds = self.provider.get_odds(match_id)

                # 3. 生成推荐
                rec = self.decision_engine.recommend(
                    match_id,
                    odds,
                    prob,
                    bankroll=current_bankroll,
                )

                if not rec:
                    if verbose:
                        logger.info(f"[{match_id}] 无推荐，跳过")
                    continue

                # 4. 风控审批
                if self.risk_controller:
                    approved, reason, adjusted_stake = self.risk_controller.approve_recommendation(
                        rec, match_info, current_bankroll,
                        league=match_info.league,
                    )
                    if not approved:
                        if verbose:
                            logger.info(f"[{match_id}] 风控拦截: {reason}")
                        continue
                    stake = adjusted_stake
                else:
                    stake = rec.suggested_stake

                # 5. 获取实际结果
                try:
                    actual = self.provider.get_result(match_id)
                except Exception:
                    if verbose:
                        logger.warning(f"[{match_id}] 无赛果数据，跳过")
                    continue

                # 6. 计算盈亏
                won = rec.recommendation == self._map_actual_to_recommendation(actual)

                if won:
                    odds_key = self._recommendation_to_odds_key(rec.recommendation)
                    profit = stake * (odds[odds_key] - 1.0)
                else:
                    profit = -stake

                current_bankroll += profit
                peak_bankroll = max(peak_bankroll, current_bankroll)
                drawdown = (peak_bankroll - current_bankroll) / peak_bankroll if peak_bankroll > 0 else 0
                max_drawdown = max(max_drawdown, drawdown)

                total_bets += 1
                if won:
                    won_bets += 1

                records.append(BacktestRecord(
                    match_id=match_id,
                    recommendation=rec.recommendation,
                    stake=round(stake, 2),
                    profit=round(profit, 2),
                    bankroll=round(current_bankroll, 2),
                    won=won,
                    ev=rec.ev,
                    tier=rec.tier,
                    odds_taken=rec.odds,
                ))

                if verbose:
                    logger.info(
                        f"[{match_id}] {rec.recommendation} "
                        f"stake={stake:.2f} profit={profit:.2f} "
                        f"bankroll={current_bankroll:.2f}"
                    )

                # 通知风控层记录结果
                if self.risk_controller:
                    self.risk_controller.record_result(match_id, profit)

            except Exception as e:
                if verbose:
                    logger.error(f"[{match_id}] 回测异常: {e}")
                records.append(BacktestRecord(
                    match_id=match_id,
                    recommendation="ERROR",
                    stake=0.0,
                    profit=0.0,
                    bankroll=current_bankroll,
                    won=False,
                    ev=0.0,
                    tier="",
                ))

        total_profit = current_bankroll - bankroll
        hit_rate = won_bets / total_bets if total_bets > 0 else 0.0

        logger.info(
            f"回测完成: 初始={bankroll:.0f} 最终={current_bankroll:.0f} "
            f"ROI={total_profit/bankroll:.2%} 命中率={hit_rate:.2%} "
            f"最大回撤={max_drawdown:.2%}"
        )

        return BacktestSummary(
            initial_bankroll=bankroll,
            final_bankroll=round(current_bankroll, 2),
            total_profit=round(total_profit, 2),
            roi=round(total_profit / bankroll, 4),
            max_drawdown=round(max_drawdown, 4),
            hit_rate=round(hit_rate, 4),
            total_bets=total_bets,
            won_bets=won_bets,
            records=records,
        )

    @staticmethod
    def _map_actual_to_recommendation(actual: str) -> str:
        mapping = {'win': '主胜', 'draw': '平局', 'lose': '客胜'}
        return mapping.get(actual, actual)

    @staticmethod
    def _recommendation_to_odds_key(recommendation: str) -> str:
        mapping = {'主胜': 'home_win', '平局': 'draw', '客胜': 'lose'}
        return mapping.get(recommendation, 'home_win')

    @staticmethod
    def analyze_by_league(records: List[BacktestRecord], matches: List[MatchInfo]) -> pd.DataFrame:
        """按联赛分组分析回测结果"""
        match_map = {m.match_id: m.league for m in matches}

        data = []
        for r in records:
            league = match_map.get(r.match_id, 'unknown')
            data.append({
                'league': league,
                'profit': r.profit,
                'won': r.won,
                'stake': r.stake,
            })

        df = pd.DataFrame(data)
        if df.empty:
            return df

        return df.groupby('league').agg(
            total_bets=('won', 'count'),
            won_bets=('won', 'sum'),
            total_profit=('profit', 'sum'),
            total_stake=('stake', 'sum'),
        ).assign(
            hit_rate=lambda x: round(x['won_bets'] / x['total_bets'], 4),
            roi=lambda x: round(x['total_profit'] / x['total_stake'], 4),
        ).sort_values('total_profit', ascending=False)