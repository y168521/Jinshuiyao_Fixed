# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 泊松模型（已修复：比分矩阵扩大到0-10）"""

from typing import Dict
from .base_model import BaseModel
from ..config import POISSON_MAX_GOALS, POISSON_MIN_LAMBDA


class PoissonModel(BaseModel):
    """
    泊松进球模型

    修复要点：
    - max_goals 从 4 扩大到 10，避免强弱悬殊比赛概率失真
    - lambda 下限设为 0.05，防止 log(0)
    """

    def __init__(self, max_goals: int = None):
        super().__init__(name="poisson")
        self.max_goals = max_goals if max_goals is not None else POISSON_MAX_GOALS

    def predict_proba(self, features: Dict) -> Dict[str, float]:
        from scipy.stats import poisson

        home_lambda = max(features.get('home_goals_avg', 1.3), POISSON_MIN_LAMBDA)
        away_lambda = max(features.get('away_goals_avg', 1.1), POISSON_MIN_LAMBDA)

        prob_home_win = 0.0
        prob_draw = 0.0
        prob_away_win = 0.0

        for i in range(self.max_goals + 1):
            for j in range(self.max_goals + 1):
                p = poisson.pmf(i, home_lambda) * poisson.pmf(j, away_lambda)
                if i > j:
                    prob_home_win += p
                elif i == j:
                    prob_draw += p
                else:
                    prob_away_win += p

        total = prob_home_win + prob_draw + prob_away_win
        if total == 0:
            return {'win': 0.40, 'draw': 0.30, 'lose': 0.30}

        return {
            'win': prob_home_win / total,
            'draw': prob_draw / total,
            'lose': prob_away_win / total,
        }


class SimpleEnsemble(BaseModel):
    """
    简单加权集成模型

    支持混合泊松、XGBoost、神经网络等多模型输出。
    当前在没有其他模型可用时，退化为纯泊松。
    """

    def __init__(self, models: list = None, weights: dict = None):
        super().__init__(name="ensemble")
        self.models = models or [PoissonModel()]
        self.weights = weights or {"poisson": 1.0}

    def predict_proba(self, features: Dict) -> Dict[str, float]:
        weighted = {'win': 0.0, 'draw': 0.0, 'lose': 0.0}
        total_weight = 0.0

        for model in self.models:
            w = self.weights.get(model.name, 0.0)
            if w <= 0:
                continue
            try:
                prob = model.predict_proba(features)
                for k in ['win', 'draw', 'lose']:
                    weighted[k] += w * prob.get(k, 0.0)
                total_weight += w
            except Exception:
                continue

        if total_weight == 0:
            return {'win': 0.40, 'draw': 0.30, 'lose': 0.30}

        return {
            k: weighted[k] / total_weight
            for k in ['win', 'draw', 'lose']
        }