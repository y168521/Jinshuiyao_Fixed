# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 统一数据结构"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class MatchInfo:
    """比赛基本信息"""
    match_id: str
    home_team_id: str
    away_team_id: str
    home_team_name: str
    away_team_name: str
    league: str = ""
    date: str = ""
    kickoff_time: str = ""


@dataclass
class OddsData:
    """赔率数据"""
    home_win: float
    draw: float
    away_win: float
    source: str = ""  # 竞彩/欧赔/交易所


@dataclass
class Recommendation:
    """推荐结果"""
    match_id: str
    recommendation: str       # "主胜" / "平局" / "客胜"
    probability: float
    odds: float
    ev: float
    kelly: float
    suggested_stake: float
    tier: str                  # "high" / "medium" / "low"
    confidence: str            # "高" / "中" / "低"
    candidates: List[dict] = field(default_factory=list)
    value_gap: float = 0.0
    model_prob: Dict[str, float] = field(default_factory=dict)
    market_prob: Dict[str, float] = field(default_factory=dict)


@dataclass
class BacktestRecord:
    """回测单场记录"""
    match_id: str
    recommendation: str
    stake: float
    profit: float
    bankroll: float
    won: bool
    ev: float
    tier: str
    odds_taken: float = 0.0
    closing_odds: float = 0.0


@dataclass
class BacktestSummary:
    """回测汇总"""
    initial_bankroll: float
    final_bankroll: float
    total_profit: float
    roi: float
    max_drawdown: float
    hit_rate: float
    total_bets: int
    won_bets: int
    records: List[BacktestRecord] = field(default_factory=list)