# -*- coding: utf-8 -*-
"""回测评估指标（按领域拆分的包，MetricsCalculator 为兼容门面）

子模块：
  - returns: 收益指标（日收益率、总收益、年化）
  - risk: 风险指标（最大回撤、波动率、夏普/索提诺/Calmar）
  - trades: 交易指标（胜率、盈亏比）
  - distribution: 收益率分布统计
  - compare: 策略 A/B 对比
"""
from .returns import calc_returns, return_metrics
from .risk import max_drawdown_detail, risk_metrics
from .trades import trade_metrics
from .distribution import return_distribution
from .compare import compare_strategies


class MetricsCalculator:
    """回测指标计算器（门面，委托给子模块）"""

    @staticmethod
    def calculate_all(daily_values, trades, initial_capital, risk_free_rate=0.03):
        """计算全套指标"""
        if not daily_values:
            return {"error": "无数据"}

        returns = calc_returns(daily_values)
        return {
            "returns": return_metrics(daily_values, initial_capital),
            "risk": risk_metrics(daily_values, returns, risk_free_rate),
            "trades": trade_metrics(trades),
            "distribution": return_distribution(returns),
        }

    @staticmethod
    def _calc_returns(daily_values):
        return calc_returns(daily_values)

    @staticmethod
    def return_metrics(daily_values, initial_capital):
        return return_metrics(daily_values, initial_capital)

    @staticmethod
    def risk_metrics(daily_values, returns, risk_free_rate=0.03):
        return risk_metrics(daily_values, returns, risk_free_rate)

    @staticmethod
    def _max_drawdown_detail(daily_values):
        return max_drawdown_detail(daily_values)

    @staticmethod
    def trade_metrics(trades):
        return trade_metrics(trades)

    @staticmethod
    def return_distribution(returns):
        return return_distribution(returns)

    @staticmethod
    def compare_strategies(results_a, results_b):
        return compare_strategies(results_a, results_b)


__all__ = [
    "MetricsCalculator",
    "calc_returns",
    "return_metrics",
    "risk_metrics",
    "max_drawdown_detail",
    "trade_metrics",
    "return_distribution",
    "compare_strategies",
]
