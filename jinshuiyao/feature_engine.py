# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 特征工程

修复要点：
- 新增 aggregate_recent_form() 统一聚合函数，解决字段命名不一致
- build_features() 使用标准化的 _avg 后缀字段
"""

from typing import Dict, Optional
import pandas as pd
from .schemas import MatchInfo
from .config import (
    DEFAULT_GOALS_SCORED_AVG,
    DEFAULT_GOALS_CONCEDED_AVG,
    DEFAULT_XG_AVG,
    DEFAULT_XGA_AVG,
)
from .logger import get_logger

logger = get_logger(__name__)


class JinshuiyaoFeatureEngine:
    """金水谣特征工程引擎"""

    @staticmethod
    def aggregate_recent_form(df: Optional[pd.DataFrame]) -> Dict[str, float]:
        """
        统一聚合近 N 场数据为标准特征字典。

        解决原始代码中 .mean().to_dict() 产生 'goals_scored'
        而 build_features() 期望 'goals_scored_avg' 的问题。

        Returns:
            {
                'goals_scored_avg': 1.5,
                'goals_conceded_avg': 1.2,
                'xg_avg': 1.4,
                'xga_avg': 1.1,
            }
        """
        if df is None or df.empty:
            return {
                'goals_scored_avg': DEFAULT_GOALS_SCORED_AVG,
                'goals_conceded_avg': DEFAULT_GOALS_CONCEDED_AVG,
                'xg_avg': DEFAULT_XG_AVG,
                'xga_avg': DEFAULT_XGA_AVG,
            }

        result = {}

        # 进球
        if 'goals_scored' in df.columns:
            result['goals_scored_avg'] = float(df['goals_scored'].mean())
        elif 'goals_for' in df.columns:
            result['goals_scored_avg'] = float(df['goals_for'].mean())
        else:
            result['goals_scored_avg'] = DEFAULT_GOALS_SCORED_AVG

        # 失球
        if 'goals_conceded' in df.columns:
            result['goals_conceded_avg'] = float(df['goals_conceded'].mean())
        elif 'goals_against' in df.columns:
            result['goals_conceded_avg'] = float(df['goals_against'].mean())
        else:
            result['goals_conceded_avg'] = DEFAULT_GOALS_CONCEDED_AVG

        # xG
        if 'xg' in df.columns:
            result['xg_avg'] = float(df['xg'].mean())
        else:
            result['xg_avg'] = DEFAULT_XG_AVG

        # xGA
        if 'xga' in df.columns:
            result['xga_avg'] = float(df['xga'].mean())
        else:
            result['xga_avg'] = DEFAULT_XGA_AVG

        return result

    @staticmethod
    def build_features(
        match: MatchInfo,
        home_form_agg: Dict[str, float],
        away_form_agg: Dict[str, float],
        injury: Optional[Dict[str, float]] = None,
        h2h: Optional[pd.DataFrame] = None,
    ) -> Dict[str, float]:
        """
        构建模型输入特征

        Args:
            match: 比赛基本信息
            home_form_agg: 主队近期聚合特征（来自 aggregate_recent_form）
            away_form_agg: 客队近期聚合特征
            injury: 伤病影响 {'home_loss': 0, 'away_loss': 0}
            h2h: 历史交锋数据

        Returns:
            标准化特征字典
        """
        injury = injury or {'home_loss': 0.0, 'away_loss': 0.0}

        features = {
            # 主队特征
            'home_goals_avg': home_form_agg.get('goals_scored_avg', DEFAULT_GOALS_SCORED_AVG),
            'home_conceded_avg': home_form_agg.get('goals_conceded_avg', DEFAULT_GOALS_CONCEDED_AVG),
            'home_xg_avg': home_form_agg.get('xg_avg', DEFAULT_XG_AVG),
            'home_xga_avg': home_form_agg.get('xga_avg', DEFAULT_XGA_AVG),

            # 客队特征
            'away_goals_avg': away_form_agg.get('goals_scored_avg', DEFAULT_GOALS_SCORED_AVG),
            'away_conceded_avg': away_form_agg.get('goals_conceded_avg', DEFAULT_GOALS_CONCEDED_AVG),
            'away_xg_avg': away_form_agg.get('xg_avg', DEFAULT_XG_AVG),
            'away_xga_avg': away_form_agg.get('xga_avg', DEFAULT_XGA_AVG),

            # 伤病调整因子 (1.0 = 无影响, < 1.0 = 实力折损)
            'home_injury_factor': max(0.5, 1.0 - injury.get('home_loss', 0.0)),
            'away_injury_factor': max(0.5, 1.0 - injury.get('away_loss', 0.0)),
        }

        # H2H 特征
        if h2h is not None and not h2h.empty:
            features['h2h_home_wins'] = len(h2h[h2h['result'] == 'win'])
            features['h2h_draws'] = len(h2h[h2h['result'] == 'draw'])
            features['h2h_away_wins'] = len(h2h[h2h['result'] == 'lose'])
        else:
            features['h2h_home_wins'] = 0.0
            features['h2h_draws'] = 0.0
            features['h2h_away_wins'] = 0.0

        logger.debug(f"构建特征完成: {len(features)} 维")
        return features