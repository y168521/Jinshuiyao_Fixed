# -*- coding: utf-8 -*-
"""趋势分析引擎

基于技术指标判断趋势方向和强度。
支持多时间框架（短期/中期/长期）趋势一致性分析。
"""
import logging

logger = logging.getLogger(__name__)


class TrendEngine:
    """趋势方向与强度判断引擎"""

    def judge(self, df, indicators):
        """判断趋势

        Args:
            df: 原始K线数据
            indicators: TechnicalEngine.calculate() 返回的指标字典

        Returns:
            dict: {"direction": "up"/"down"/"sideways", "strength": 0-100, "details": {...}}
        """
        if not indicators or "error" in indicators:
            return {"direction": "unknown", "strength": 0, "details": {}}

        ma = indicators.get("ma", {})
        macd = indicators.get("macd", {})
        kdj = indicators.get("kdj", {})
        rsi = indicators.get("rsi", {})
        bb = indicators.get("bollinger", {})
        composite = indicators.get("composite", {})

        # 1. 方向判断（多因子投票）
        votes = {"up": 0, "down": 0, "sideways": 0}

        # MA投票
        if ma.get("trend_short") == "up":
            votes["up"] += 1
        elif ma.get("trend_short") == "down":
            votes["down"] += 1
        else:
            votes["sideways"] += 1

        if ma.get("trend_medium") == "up":
            votes["up"] += 1
        elif ma.get("trend_medium") == "down":
            votes["down"] += 1

        if ma.get("trend_long") == "up":
            votes["up"] += 1
        elif ma.get("trend_long") == "down":
            votes["down"] += 1

        # MACD投票
        if macd.get("trend") == "bull":
            votes["up"] += 1
        elif macd.get("trend") == "bear":
            votes["down"] += 1

        # KDJ投票
        if kdj.get("signal") == "oversold" and kdj.get("golden_cross"):
            votes["up"] += 1
        elif kdj.get("signal") == "overbought":
            votes["down"] += 1

        # 布林带投票
        if bb.get("signal") == "lower_touch":
            votes["up"] += 1
        elif bb.get("signal") == "upper_touch":
            votes["down"] += 1

        # 确定方向
        direction = max(votes, key=votes.get)
        if votes[direction] <= 1:
            direction = "sideways"

        # 2. 强度计算
        strength = self._calc_strength(direction, votes, indicators)

        # 3. 一致性检查
        consistency = self._check_consistency(ma)

        return {
            "direction": direction,
            "strength": round(strength, 1),
            "consistency": consistency,
            "votes": votes,
            "details": {
                "ma_alignment": self._ma_alignment(ma),
                "macd_signal": macd.get("signal", "none"),
                "kdj_signal": kdj.get("signal", "none"),
                "rsi_value": rsi.get("rsi", 50),
                "composite_score": composite.get("score", 50),
                "composite_level": composite.get("level", "neutral"),
            },
        }

    def _calc_strength(self, direction, votes, indicators):
        """计算趋势强度 0-100"""
        base = votes.get(direction, 0) * 15  # 每个投票15分

        composite = indicators.get("composite", {})
        comp_score = composite.get("score", 50)

        # 综合评分加权
        if direction == "up":
            base += (comp_score - 50) * 0.3
        elif direction == "down":
            base += (50 - comp_score) * 0.3
        else:
            base += 20 - abs(comp_score - 50) * 0.2

        # MACD信号额外加分
        macd = indicators.get("macd", {})
        if macd.get("signal") == "buy" and direction == "up":
            base += 10
        elif macd.get("signal") == "sell" and direction == "down":
            base += 10

        # 金叉/死叉
        ma = indicators.get("ma", {})
        if ma.get("golden_cross") and direction == "up":
            base += 15
        elif ma.get("death_cross") and direction == "down":
            base += 15

        return min(100, max(0, base))

    def _check_consistency(self, ma):
        """检查多周期趋势一致性"""
        short = ma.get("trend_short")
        medium = ma.get("trend_medium")
        long_t = ma.get("trend_long")

        if short == medium == long_t and short is not None:
            return {"aligned": True, "periods": "all", "direction": short}
        if medium == long_t and medium is not None:
            return {"aligned": True, "periods": "medium_long", "direction": medium}
        if short == medium and short is not None:
            return {"aligned": True, "periods": "short_medium", "direction": short}
        return {"aligned": False, "periods": "none", "direction": "mixed"}

    def _ma_alignment(self, ma):
        """MA排列状态"""
        ma5 = ma.get("ma5")
        ma20 = ma.get("ma20")
        ma60 = ma.get("ma60")

        if ma5 is None or ma20 is None or ma60 is None:
            return "unknown"
        if ma5 > ma20 > ma60:
            return "bullish"  # 多头排列
        if ma5 < ma20 < ma60:
            return "bearish"  # 空头排列
        if ma20 > ma5 > ma60:
            return "weak_bull"  # 弱多
        if ma20 < ma5 < ma60:
            return "weak_bear"  # 弱空
        return "mixed"
