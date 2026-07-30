# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 模型基类"""

from abc import ABC, abstractmethod
from typing import Dict


class BaseModel(ABC):
    """所有预测模型的抽象基类"""

    def __init__(self, name: str = "base"):
        self.name = name

    @abstractmethod
    def predict_proba(self, features: Dict) -> Dict[str, float]:
        """
        预测胜平负概率

        Args:
            features: 特征字典

        Returns:
            {'win': 0.45, 'draw': 0.28, 'lose': 0.27}
        """
        pass

    def validate_output(self, prob: Dict) -> bool:
        """校验输出格式"""
        required_keys = {'win', 'draw', 'lose'}
        if not required_keys.issubset(prob.keys()):
            return False
        if not all(isinstance(v, (int, float)) for v in prob.values()):
            return False
        total = sum(prob.values())
        if abs(total - 1.0) > 0.15:  # 允许微小误差
            return False
        return True