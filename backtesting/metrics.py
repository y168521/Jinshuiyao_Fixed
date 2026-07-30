# -*- coding: utf-8 -*-
"""回测评估指标

提供全面的策略评估指标计算。
"""
import math
import logging

logger = logging.getLogger(__name__)


class MetricsCalculator:
    """回测指标计算器"""

    @staticmethod
    def calculate_all(daily_values, trades, initial_capital, risk_free_rate=0.03):
        """计算全套指标

        Args:
            daily_values: [{"date": str, "value": float}, ...]
            trades: [{"date": str, "action": str, "price": float, ...}, ...]
            initial_capital: 初始资金
            risk_free_rate: 无风险利率（年化，默认3%）

        Returns:
            dict: 所有指标
        """
        if not daily_values:
            return {"error": "无数据"}

        returns = MetricsCalculator._calc_returns(daily_values)

        return {
            "returns": MetricsCalculator.return_metrics(daily_values, initial_capital),
            "risk": MetricsCalculator.risk_metrics(daily_values, returns, risk_free_rate),
            "trades": MetricsCalculator.trade_metrics(trades),
            "distribution": MetricsCalculator.return_distribution(returns),
        }

    @staticmethod
    def _calc_returns(daily_values):
        """计算日收益率序列"""
        returns = []
        for i in range(1, len(daily_values)):
            prev = daily_values[i - 1]["value"]
            curr = daily_values[i]["value"]
            if prev > 0:
                returns.append((curr - prev) / prev)
        return returns

    @staticmethod
    def return_metrics(daily_values, initial_capital):
        """收益指标"""
        final_value = daily_values[-1]["value"]
        total_return = (final_value - initial_capital) / initial_capital

        # 年化收益率
        days = len(daily_values)
        annual_return = (1 + total_return) ** (252 / days) - 1 if days > 0 else 0

        return {
            "total_return": round(total_return, 4),
            "total_return_pct": f"{total_return*100:.2f}%",
            "annual_return": round(annual_return, 4),
            "annual_return_pct": f"{annual_return*100:.2f}%",
            "initial_capital": initial_capital,
            "final_value": round(final_value, 2),
        }

    @staticmethod
    def risk_metrics(daily_values, returns, risk_free_rate=0.03):
        """风险指标"""
        # 最大回撤
        max_dd, max_dd_start, max_dd_end = MetricsCalculator._max_drawdown_detail(daily_values)

        # 波动率（年化）
        if len(returns) > 1:
            avg_ret = sum(returns) / len(returns)
            variance = sum((r - avg_ret) ** 2 for r in returns) / len(returns)
            volatility = (variance ** 0.5) * (252 ** 0.5)
        else:
            volatility = 0

        # 夏普比率
        daily_rf = risk_free_rate / 252
        if volatility > 0 and len(returns) > 0:
            excess_return = sum(returns) / len(returns) - daily_rf
            sharpe = (excess_return / (volatility / 252 ** 0.5)) * (252 ** 0.5)
        else:
            sharpe = 0

        # 索提诺比率（只考虑下行波动）
        downside_returns = [r for r in returns if r < 0]
        if downside_returns:
            downside_std = (sum(r ** 2 for r in downside_returns) / len(downside_returns)) ** 0.5
            downside_std *= (252 ** 0.5)
            sortino = (sum(returns) / len(returns) * 252 - risk_free_rate) / downside_std if downside_std > 0 else 0
        else:
            sortino = 0

        # Calmar比率
        calmar = (sum(returns) / len(returns) * 252) / max_dd if max_dd > 0 and returns else 0

        return {
            "max_drawdown": round(max_dd, 4),
            "max_drawdown_pct": f"{max_dd*100:.2f}%",
            "max_dd_period": {"start": max_dd_start, "end": max_dd_end},
            "volatility": round(volatility, 4),
            "volatility_pct": f"{volatility*100:.2f}%",
            "sharpe_ratio": round(sharpe, 3),
            "sortino_ratio": round(sortino, 3),
            "calmar_ratio": round(calmar, 3),
        }

    @staticmethod
    def _max_drawdown_detail(daily_values):
        """计算最大回撤及区间"""
        peak = daily_values[0]["value"]
        peak_idx = 0
        max_dd = 0
        dd_start = daily_values[0]["date"]
        dd_end = daily_values[0]["date"]

        for i, dv in enumerate(daily_values):
            val = dv["value"]
            if val > peak:
                peak = val
                peak_idx = i
            dd = (peak - val) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
                dd_start = daily_values[peak_idx]["date"]
                dd_end = dv["date"]

        return max_dd, dd_start, dd_end

    @staticmethod
    def trade_metrics(trades):
        """交易指标"""
        buy_trades = [t for t in trades if t.get("action") == "buy"]
        sell_trades = [t for t in trades if t.get("action") == "sell"]

        # 盈亏统计
        profits = []
        for sell in sell_trades:
            # 找到对应的买入记录（简化：假设FIFO）
            cost = sell.get("cost", 0) or sell.get("shares", 0) * sell.get("price", 0)
            revenue = sell.get("revenue", 0)
            if cost > 0:
                profit_pct = (revenue - cost) / cost
                profits.append(profit_pct)

        if not profits:
            return {"total_trades": len(trades), "profit_trades": 0, "win_rate": 0}

        win_count = sum(1 for p in profits if p > 0)
        avg_profit = sum(profits) / len(profits)
        max_profit = max(profits)
        max_loss = min(profits)

        # 盈亏比
        avg_win = sum(p for p in profits if p > 0) / win_count if win_count > 0 else 0
        avg_loss = sum(p for p in profits if p <= 0) / (len(profits) - win_count) if len(profits) > win_count else 1
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        return {
            "total_trades": len(trades),
            "buy_count": len(buy_trades),
            "sell_count": len(sell_trades),
            "profit_trades": len(profits),
            "win_count": win_count,
            "loss_count": len(profits) - win_count,
            "win_rate": round(win_count / len(profits), 4),
            "avg_return": round(avg_profit, 4),
            "avg_return_pct": f"{avg_profit*100:.2f}%",
            "max_profit": round(max_profit, 4),
            "max_loss": round(max_loss, 4),
            "profit_factor": round(profit_factor, 2),
        }

    @staticmethod
    def return_distribution(returns):
        """收益率分布统计"""
        if not returns:
            return {}

        sorted_returns = sorted(returns)
        n = len(sorted_returns)

        def percentile(p):
            idx = int(n * p / 100)
            return sorted_returns[max(0, min(idx, n - 1))]

        return {
            "count": n,
            "mean": round(sum(returns) / n, 6),
            "median": round(sorted_returns[n // 2], 6),
            "std": round((sum((r - sum(returns)/n)**2 for r in returns) / n) ** 0.5, 6),
            "min": round(sorted_returns[0], 6),
            "max": round(sorted_returns[-1], 6),
            "p5": round(percentile(5), 6),
            "p25": round(percentile(25), 6),
            "p75": round(percentile(75), 6),
            "p95": round(percentile(95), 6),
            "positive_days": sum(1 for r in returns if r > 0),
            "negative_days": sum(1 for r in returns if r < 0),
        }

    @staticmethod
    def compare_strategies(results_a, results_b):
        """A/B测试：对比两个策略的回测结果

        Args:
            results_a: BacktestEngine.run_stock() 返回的报告
            results_b: 同上

        Returns:
            dict: 对比结果
        """
        def _extract(report):
            return {
                "return": report.get("total_return", 0),
                "max_dd": report.get("max_drawdown", 0),
                "sharpe": report.get("sharpe_ratio", 0),
                "win_rate": report.get("win_rate", 0),
                "trades": report.get("trade_count", 0),
            }

        a = _extract(results_a)
        b = _extract(results_b)

        comparisons = {
            "return": {"a": a["return"], "b": b["return"], "winner": "A" if a["return"] > b["return"] else "B"},
            "max_dd": {"a": a["max_dd"], "b": b["max_dd"], "winner": "A" if a["max_dd"] < b["max_dd"] else "B"},
            "sharpe": {"a": a["sharpe"], "b": b["sharpe"], "winner": "A" if a["sharpe"] > b["sharpe"] else "B"},
            "win_rate": {"a": a["win_rate"], "b": b["win_rate"], "winner": "A" if a["win_rate"] > b["win_rate"] else "B"},
        }

        # 综合评分（越低越好，除了return/sharpe/win_rate）
        score_a = (a["return"] + a["sharpe"] * 0.5 + a["win_rate"] - a["max_dd"] * 2)
        score_b = (b["return"] + b["sharpe"] * 0.5 + b["win_rate"] - b["max_dd"] * 2)

        return {
            "comparisons": comparisons,
            "overall_winner": "A" if score_a > score_b else "B",
            "score_a": round(score_a, 4),
            "score_b": round(score_b, 4),
            "recommendation": "策略A更优" if score_a > score_b else "策略B更优",
        }
