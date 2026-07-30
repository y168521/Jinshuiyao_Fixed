# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 概率校准模块

核心功能：
- 向市场概率收缩 (shrink-to-market)
- 避免模型"过度自信"导致的推荐偏差

真实生产可接入 sklearn CalibratedClassifierCV / isotonic regression
"""

from typing import Dict
from .config import CALIBRATION_ALPHA
from .logger import get_logger

logger = get_logger(__name__)


class ProbabilityCalibrator:
    """
    简化版概率校准器。

    核心思路：市场赔率包含大量有效信息，完全无视市场
    经常会让模型推荐"看似高 EV、实际是模型偏差"的选项。
    """

    @staticmethod
    def shrink_to_market(
        model_prob: Dict[str, float],
        market_prob: Dict[str, float],
        alpha: float = None,
    ) -> Dict[str, float]:
        """
        混合模型概率和市场隐含概率

        blended = alpha * model_prob + (1 - alpha) * market_prob

        alpha 越高越相信模型，越低越贴近市场。

        Args:
            model_prob: 模型输出的 {'win': 0.45, 'draw': 0.28, 'lose': 0.27}
            market_prob: 市场隐含概率
            alpha: 模型置信度 (默认从 config 读取)

        Returns:
            校准后的概率（归一化）
        """
        alpha = alpha if alpha is not None else CALIBRATION_ALPHA

        blended = {}
        for k in ['win', 'draw', 'lose']:
            mp = model_prob.get(k, 0.0)
            mkp = market_prob.get(k, 0.0)
            blended[k] = alpha * mp + (1.0 - alpha) * mkp

        total = sum(blended.values())
        if total == 0:
            return {'win': 1/3, 'draw': 1/3, 'lose': 1/3}

        result = {k: blended[k] / total for k in blended}
        logger.debug(f"概率校准: alpha={alpha:.2f}, model={model_prob}, blended={result}")
        return result

    @staticmethod
    def temperature_scale(
        prob: Dict[str, float],
        temperature: float = 1.0,
    ) -> Dict[str, float]:
        """
        Temperature Scaling 校准

        T > 1: 让概率更平滑（降低置信度）
        T < 1: 让概率更尖锐（提高置信度）
        T = 1: 不变

        适用于神经网络输出的 logits 校准。
        """
        if temperature <= 0:
            temperature = 1.0

        scaled = {
            k: v ** (1.0 / temperature)
            for k, v in prob.items()
        }
        total = sum(scaled.values())
        if total == 0:
            return prob
        return {k: v / total for k, v in scaled.items()}

    @staticmethod
    def compress_high_prob(p_raw: float, lambda_factor: float = 0.6) -> float:
        """
        单概率压缩（v2.3）

        公式: p_cal = 0.5 + (p_raw - 0.5) * lambda_factor (仅当 p_raw > 0.5)

        用于对冲模型系统性高估。lambda_factor 越小压缩越狠。

        示例:
            compress_high_prob(0.80, 0.6) → 0.68  (80% → 68%)
            compress_high_prob(0.60, 0.6) → 0.56  (60% → 56%)
            compress_high_prob(0.45, 0.6) → 0.45  (不变)

        Args:
            p_raw: 原始概率 (0~1)
            lambda_factor: 压缩系数 (0~1), 默认 0.6
        """
        if p_raw <= 0.5:
            return p_raw
        lambda_factor = max(0.0, min(1.0, lambda_factor))
        return 0.5 + (p_raw - 0.5) * lambda_factor