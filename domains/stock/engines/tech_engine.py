# -*- coding: utf-8 -*-
"""技术指标引擎

计算常见技术指标：MA、MACD、KDJ、RSI、布林带、成交量分析。
纯Python实现，无pandas依赖时降级为基础计算。
"""
import logging
import math

logger = logging.getLogger(__name__)


class TechnicalEngine:
    """技术指标计算引擎"""

    def calculate(self, df):
        """计算全套技术指标

        Args:
            df: DataFrame with columns [date, open, close, high, low, volume]

        Returns:
            dict: 指标结果
        """
        if df is None or df.empty:
            return {"error": "空数据"}

        # 提取序列
        closes = self._extract_series(df, "close")
        highs = self._extract_series(df, "high")
        lows = self._extract_series(df, "low")
        volumes = self._extract_series(df, "volume")
        opens = self._extract_series(df, "open")

        if len(closes) < 60:
            return {"error": f"数据不足60条，当前{len(closes)}条"}

        result = {
            "latest_price": closes[-1],
            "data_length": len(closes),
        }

        # 移动平均线
        result["ma"] = self._calc_ma(closes)

        # MACD
        result["macd"] = self._calc_macd(closes)

        # KDJ
        result["kdj"] = self._calc_kdj(highs, lows, closes)

        # RSI
        result["rsi"] = self._calc_rsi(closes)

        # 布林带
        result["bollinger"] = self._calc_bollinger(closes)

        # 成交量分析
        if volumes:
            result["volume"] = self._calc_volume(volumes)

        # 综合评价
        result["composite"] = self._composite_score(result)

        return result

    # ------------------------------------------------------------------
    # 指标计算
    # ------------------------------------------------------------------

    def _extract_series(self, df, col):
        """从DataFrame或dict提取序列"""
        if hasattr(df, col):
            return df[col].tolist()
        if hasattr(df, "columns") and col in df.columns:
            return df[col].tolist()
        if isinstance(df, dict) and col in df:
            return list(df[col])
        if isinstance(df, list):
            return [row.get(col) for row in df if isinstance(row, dict)]
        return []

    def _calc_ma(self, closes):
        """计算移动平均线"""
        def sma(values, n):
            if len(values) < n:
                return []
            return [sum(values[i - n + 1:i + 1]) / n for i in range(n - 1, len(values))]

        def ema(values, n):
            if len(values) < n:
                return []
            k = 2 / (n + 1)
            ema_vals = [sum(values[:n]) / n]
            for price in values[n:]:
                ema_vals.append(price * k + ema_vals[-1] * (1 - k))
            return ema_vals

        ma5 = sma(closes, 5)
        ma10 = sma(closes, 10)
        ma20 = sma(closes, 20)
        ma60 = sma(closes, 60)
        ema12 = ema(closes, 12)
        ema26 = ema(closes, 26)

        latest = closes[-1]
        return {
            "ma5": ma5[-1] if ma5 else None,
            "ma10": ma10[-1] if ma10 else None,
            "ma20": ma20[-1] if ma20 else None,
            "ma60": ma60[-1] if ma60 else None,
            "ema12": ema12[-1] if ema12 else None,
            "ema26": ema26[-1] if ema26 else None,
            "trend_short": "up" if ma5 and ma5[-1] > (ma5[-2] if len(ma5) > 1 else ma5[-1]) else "down",
            "trend_medium": "up" if ma20 and latest > ma20[-1] else "down",
            "trend_long": "up" if ma60 and latest > ma60[-1] else "down",
            "golden_cross": ma5 and ma20 and ma5[-1] > ma20[-1] and (len(ma5) < 2 or ma5[-2] <= ma20[-1]),
            "death_cross": ma5 and ma20 and ma5[-1] < ma20[-1] and (len(ma5) < 2 or ma5[-2] >= ma20[-1]),
        }

    def _calc_macd(self, closes):
        """计算MACD指标"""
        def ema(values, n):
            if len(values) < n:
                return []
            k = 2 / (n + 1)
            ema_vals = [sum(values[:n]) / n]
            for price in values[n:]:
                ema_vals.append(price * k + ema_vals[-1] * (1 - k))
            return ema_vals

        ema12 = ema(closes, 12)
        ema26 = ema(closes, 26)
        if len(ema12) < len(ema26):
            ema12 = ema12[-len(ema26):]

        dif = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
        dea = ema(dif, 9)
        macd = [(d - d_e) * 2 for d, d_e in zip(dif[-len(dea):], dea)] if dea else []

        if not dif or not dea or not macd:
            return {"error": "数据不足计算MACD"}

        return {
            "dif": dif[-1],
            "dea": dea[-1],
            "macd": macd[-1],
            "signal": "buy" if macd[-1] > 0 and (len(macd) < 2 or macd[-2] <= 0) else
                     "sell" if macd[-1] < 0 and (len(macd) < 2 or macd[-2] >= 0) else "hold",
            "trend": "bull" if dif[-1] > dea[-1] else "bear",
        }

    def _calc_kdj(self, highs, lows, closes):
        """计算KDJ指标（9,3,3）"""
        n = 9
        if len(closes) < n:
            return {"error": "数据不足计算KDJ"}

        k_vals, d_vals, j_vals = [], [], []
        k, d = 50.0, 50.0

        for i in range(n - 1, len(closes)):
            period_highs = highs[i - n + 1:i + 1] if highs else []
            period_lows = lows[i - n + 1:i + 1] if lows else []
            if not period_highs or not period_lows:
                continue
            hn = max(period_highs)
            ln = min(period_lows)
            cn = closes[i]
            rsv = 100 * (cn - ln) / (hn - ln) if hn != ln else 50
            k = (2 / 3) * k + (1 / 3) * rsv
            d = (2 / 3) * d + (1 / 3) * k
            j = 3 * k - 2 * d
            k_vals.append(k)
            d_vals.append(d)
            j_vals.append(j)

        if not k_vals:
            return {"error": "KDJ计算失败"}

        return {
            "k": round(k_vals[-1], 2),
            "d": round(d_vals[-1], 2),
            "j": round(j_vals[-1], 2),
            "signal": "overbought" if j_vals[-1] > 80 else
                     "oversold" if j_vals[-1] < 20 else "neutral",
            "golden_cross": k_vals[-1] > d_vals[-1] and (len(k_vals) < 2 or k_vals[-2] <= d_vals[-1]),
        }

    def _calc_rsi(self, closes, period=14):
        """计算RSI指标"""
        if len(closes) < period + 1:
            return {"error": "数据不足计算RSI"}

        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(abs(min(diff, 0)))

        if len(gains) < period:
            return {"error": "数据不足"}

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        return {
            "rsi": round(rsi, 2),
            "signal": "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral",
        }

    def _calc_bollinger(self, closes, period=20, num_std=2):
        """计算布林带"""
        if len(closes) < period:
            return {"error": "数据不足计算布林带"}

        mb = sum(closes[-period:]) / period
        variance = sum((x - mb) ** 2 for x in closes[-period:]) / period
        std = math.sqrt(variance)
        upper = mb + num_std * std
        lower = mb - num_std * std
        latest = closes[-1]

        position = (latest - lower) / (upper - lower) if upper != lower else 0.5

        return {
            "upper": round(upper, 2),
            "middle": round(mb, 2),
            "lower": round(lower, 2),
            "bandwidth": round((upper - lower) / mb * 100, 2) if mb else 0,
            "position": round(position, 3),
            "signal": "upper_touch" if latest >= upper * 0.99 else
                     "lower_touch" if latest <= lower * 1.01 else "mid",
        }

    def _calc_volume(self, volumes):
        """成交量分析"""
        if len(volumes) < 20:
            return {"error": "数据不足"}

        latest_vol = volumes[-1]
        avg5 = sum(volumes[-5:]) / 5
        avg20 = sum(volumes[-20:]) / 20

        return {
            "latest": latest_vol,
            "avg5": avg5,
            "avg20": avg20,
            "ratio_5": round(latest_vol / avg5, 2) if avg5 else 0,
            "ratio_20": round(latest_vol / avg20, 2) if avg20 else 0,
            "signal": "volume_spike" if latest_vol > avg5 * 2 else
                     "volume_shrink" if latest_vol < avg5 * 0.5 else "normal",
        }

    def _composite_score(self, indicators):
        """综合评分 0-100"""
        score = 50
        ma = indicators.get("ma", {})
        macd = indicators.get("macd", {})
        kdj = indicators.get("kdj", {})
        rsi = indicators.get("rsi", {})
        bb = indicators.get("bollinger", {})
        vol = indicators.get("volume", {})

        # MA趋势加分
        if ma.get("trend_short") == "up":
            score += 10
        if ma.get("trend_medium") == "up":
            score += 10
        if ma.get("golden_cross"):
            score += 15

        # MACD信号
        if macd.get("trend") == "bull":
            score += 10
        if macd.get("signal") == "buy":
            score += 15

        # KDJ
        if kdj.get("signal") == "oversold" and kdj.get("golden_cross"):
            score += 10
        elif kdj.get("signal") == "overbought":
            score -= 10

        # RSI
        rsi_val = rsi.get("rsi", 50)
        if 30 < rsi_val < 70:
            score += 5  # 健康区间
        elif rsi_val < 30:
            score += 10  # 超卖反弹预期
        elif rsi_val > 70:
            score -= 10  # 超买回调风险

        # 布林带
        if bb.get("signal") == "lower_touch":
            score += 10
        elif bb.get("signal") == "upper_touch":
            score -= 10

        # 成交量
        if vol.get("signal") == "volume_spike":
            score += 5

        return {
            "score": min(100, max(0, score)),
            "level": "strong_buy" if score >= 80 else
                     "buy" if score >= 65 else
                     "neutral" if score >= 45 else
                     "sell" if score >= 30 else "strong_sell",
        }
