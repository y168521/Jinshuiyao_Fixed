# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 赔率标准化模块

核心功能：
- 隐含概率计算（去水位）
- 庄家返还率/抽水计算
- 模型概率 vs 市场隐含概率价值差
"""

from typing import Dict


class OddsUtils:
    """赔率标准化工具"""

    @staticmethod
    def implied_probs_1x2(odds: Dict[str, float]) -> Dict[str, float]:
        """
        从 1x2 赔率计算市场隐含概率（去水位）

        Args:
            odds: {'home_win': 2.1, 'draw': 3.2, 'lose': 3.5}
                  注意：'lose' 即 'away_win'

        Returns:
            {'win': 0.44, 'draw': 0.29, 'lose': 0.27}  (归一化后)
        """
        raw = {
            'win': 1.0 / odds['home_win'] if odds.get('home_win', 0) > 0 else 0.0,
            'draw': 1.0 / odds['draw'] if odds.get('draw', 0) > 0 else 0.0,
            'lose': 1.0 / odds['lose'] if odds.get('lose', 0) > 0 else 0.0,
        }
        total = sum(raw.values())
        if total == 0:
            return {'win': 1/3, 'draw': 1/3, 'lose': 1/3}
        return {k: v / total for k, v in raw.items()}

    @staticmethod
    def bookmaker_margin(odds: Dict[str, float]) -> float:
        """
        计算庄家抽水比例

        margin = (1/主胜 + 1/平局 + 1/客胜) - 1

        Returns:
            0.06 表示 6% 抽水
        """
        implied_sum = (
            1.0 / odds.get('home_win', 1.0) +
            1.0 / odds.get('draw', 1.0) +
            1.0 / odds.get('lose', 1.0)
        )
        return implied_sum - 1.0

    @staticmethod
    def value_gap(model_prob: Dict[str, float], market_prob: Dict[str, float]) -> Dict[str, float]:
        """
        模型概率 - 市场隐含概率 = 价值差

        正值表示模型比市场更看好该结果。
        用于判断推荐是否有信息优势。
        """
        return {
            k: model_prob.get(k, 0.0) - market_prob.get(k, 0.0)
            for k in ['win', 'draw', 'lose']
        }

    @staticmethod
    def calculate_ev(model_prob: Dict[str, float], odds: Dict[str, float]) -> Dict[str, float]:
        """
        计算三个结果的期望价值

        EV = 模型概率 × 赔率 - 1

        Returns:
            {'win': 0.12, 'draw': -0.10, 'lose': -0.05}
        """
        odds_map = {
            'win': odds.get('home_win', 1.0),
            'draw': odds.get('draw', 1.0),
            'lose': odds.get('lose', 1.0),
        }
        return {
            k: model_prob.get(k, 0.0) * odds_map[k] - 1.0
            for k in ['win', 'draw', 'lose']
        }

    @staticmethod
    def calculate_kelly(prob: float, odds: float, multiplier: float = 0.25) -> float:
        """
        凯利公式（折扣版）

        kelly = (prob * odds - 1) / (odds - 1) * multiplier

        Args:
            prob: 模型预测概率
            odds: 赔率 (十进制)
            multiplier: 凯利折扣系数 (0.25 = 1/4 Kelly)
        """
        if odds <= 1.0 or prob <= 0:
            return 0.0
        full_kelly = (prob * odds - 1.0) / (odds - 1.0)
        return max(0.0, full_kelly * multiplier)