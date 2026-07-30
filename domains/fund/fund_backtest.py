# -*- coding: utf-8 -*-
"""基金回测引擎（专属模块）

在 backtesting/engine.py 的 BacktestEngine 基础上提供基金专属增强：
  - 更多策略：网格定投、目标止盈、股债平衡、定投+止盈组合
  - 策略对比模式（同基金多策略并排）
  - 归因指标集成（Alpha/Beta/Tracking Error/Information Ratio）
  - 基准对比（沪深300等）
  - 多基金组合回测

与 FundDomain.backtest() 的关系：本模块是 FundDomain.backtest() 的增强实现，
FundDomain 可选用本模块替代直接调用 BacktestEngine。
"""
import math
import logging
from datetime import datetime

from backtesting.engine import BacktestEngine, FUND_STRATEGIES
from domains.fund.fund_metrics import FundMetrics

logger = logging.getLogger(__name__)


def _as_float(v, default=0.0):
    """统一把任意类型转 float，避免 .get() 结果为字符串/None 时 f-string 数值格式化报错。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ======================================================================
# 增强策略（比 engine.py 中的基础策略更多样）
# ======================================================================

def fund_strategy_grid_dca(ctx, code, row, rows, **_):
    """网格定投：净值越低买越多（倒金字塔加仓）

    每下跌5%翻倍买入金额，锁定低估值区间更多份额。
    上涨时不卖（适合长期定投者），仅调整买入量。
    """
    idx = next((i for i, r in enumerate(rows) if r["date"] == row["date"]), -1)
    if idx < 20:
        return {"action": "hold"}

    state = ctx.setdefault("_grid_state", {}).setdefault(code, {"baseline": None})
    cur = row["close"]
    if state["baseline"] is None:
        state["baseline"] = cur
        return {"action": "buy", "weight": 0.2}

    drop_pct = (state["baseline"] - cur) / state["baseline"]
    if drop_pct > 0.20:
        weight = 1.0
    elif drop_pct > 0.15:
        weight = 0.8
    elif drop_pct > 0.10:
        weight = 0.6
    elif drop_pct > 0.05:
        weight = 0.4
    else:
        weight = 0.15

    buy_signal = weight > 0.19
    if buy_signal:
        state["baseline"] = cur
        return {"action": "buy", "weight": weight}
    return {"action": "hold"}


def fund_strategy_target_profit(ctx, code, row, rows, target=0.20, **_):
    """目标止盈：达到目标收益率则全部赎回，定投重新开始

    适合震荡市和基金定投场景：在目标收益兑现后重置仓位，
    避免坐过山车。目标收益率默认20%。
    """
    idx = next((i for i, r in enumerate(rows) if r["date"] == row["date"]), -1)
    if idx < 10:
        return {"action": "hold"}

    state = ctx.setdefault("_tp_state", {}).setdefault(code, {
        "total_cost": 0.0, "total_shares": 0.0, "active": True
    })
    if not state["active"]:
        return {"action": "hold"}

    cur = row["close"]
    if state["total_shares"] > 0 and state["total_cost"] > 0:
        current_value = state["total_shares"] * cur
        profit_pct = (current_value - state["total_cost"]) / state["total_cost"]
        if profit_pct >= target:
            state["active"] = False
            return {"action": "sell"}

    return {"action": "buy", "weight": 0.2}


def fund_strategy_balanced(ctx, code, row, rows, stock_ratio=0.6, rebalance_days=63, **_):
    """股债平衡策略：固定比例股债配置，每 rebalance_days 天再平衡

    模拟基金持仓中的股票/债券比例动态调整。
    简化实现：以净值位置推断股性强度，触发再平衡。
    """
    idx = next((i for i, r in enumerate(rows) if r["date"] == row["date"]), -1)
    if idx < rebalance_days:
        return {"action": "buy", "weight": stock_ratio}

    state = ctx.setdefault("_bal_state", {}).setdefault(code, {
        "last_rebalance": idx, "drift": 0
    })

    days_since = idx - state["last_rebalance"]
    if days_since >= rebalance_days:
        state["last_rebalance"] = idx
        past = [rows[i]["close"] for i in range(idx - rebalance_days, idx)]
        ret = (past[-1] - past[0]) / past[0] if past[0] else 0
        deviation = ret * 2
        target_weight = max(0.1, min(0.9, stock_ratio + deviation))
        return {"action": "buy", "weight": target_weight}

    return {"action": "hold"}


def fund_strategy_dca_stop_profit(ctx, code, row, rows, every=5, weight=0.2, target=0.20, **_):
    """定投+止盈组合：每隔 every 天定投，达到 target 收益率则全部止盈

    融合微笑曲线与止盈纪律，适合长期定投场景。
    """
    idx = next((i for i, r in enumerate(rows) if r["date"] == row["date"]), -1)
    if idx < 10:
        return {"action": "hold"}

    state = ctx.setdefault("_dca_tp", {}).setdefault(code, {
        "total_cost": 0.0, "total_shares": 0.0, "bought_count": 0
    })
    cur = row["close"]

    if state["total_shares"] > 0 and state["total_cost"] > 0:
        current_value = state["total_shares"] * cur
        profit_pct = (current_value - state["total_cost"]) / state["total_cost"]
        if profit_pct >= target:
            state["total_cost"] = 0.0
            state["total_shares"] = 0.0
            return {"action": "sell"}

    if state["bought_count"] % every == 0:
        state["bought_count"] += 1
        return {"action": "buy", "weight": weight}
    state["bought_count"] += 1
    return {"action": "hold"}


ENHANCED_STRATEGIES = {
    "买入持有": FUND_STRATEGIES["买入持有"],
    "定投": FUND_STRATEGIES["定投"],
    "均线择时": FUND_STRATEGIES["均线择时"],
    "网格定投": fund_strategy_grid_dca,
    "目标止盈": fund_strategy_target_profit,
    "股债平衡": fund_strategy_balanced,
    "定投+止盈": fund_strategy_dca_stop_profit,
}

STRATEGY_DESCRIPTIONS = {
    "买入持有": "首日满仓买入，之后长期持有，适合牛市判断",
    "定投": "每N期定投固定权重，摊薄成本，适合震荡市",
    "均线择时": "净值上穿均线买入、下穿卖出，适合趋势市",
    "网格定投": "净值越低买入越多（倒金字塔），锁定低估值份额",
    "目标止盈": "定投+目标收益率止盈（默认20%），锁定利润",
    "股债平衡": "固定比例配置+定期再平衡，适合稳健型投资者",
    "定投+止盈": "定投积累份额，达到目标收益全部赎回再开始",
}


# ======================================================================
# 基金回测引擎（增强版）
# ======================================================================

class FundBacktestEngine:
    """基金专属回测引擎

    在 BacktestEngine 基础上提供基金专属策略和归因分析。

    用法：
        engine = FundBacktestEngine()
        # 单策略回测
        result = engine.run(code, nav_data, strategy="均线择时")
        # 策略对比
        comparison = engine.compare_strategies(code, nav_data)
        # 基准对比
        benchmarked = engine.with_benchmark(code, nav_data, bench_navs)
    """

    def __init__(self, initial_capital=100000.0, commission_rate=0.0015):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self._be = None
        self._metrics = FundMetrics()

    def _get_engine(self, name="fund"):
        return BacktestEngine(
            name=name,
            initial_capital=self.initial_capital,
            commission_rate=self.commission_rate,
            slippage=0.0,
        )

    def run(self, fund_code, nav_data, strategy="买入持有", **kwargs):
        """对单只基金执行指定策略回测

        Args:
            fund_code: 基金代码
            nav_data: 基金净值 DataFrame 或 list[dict]
            strategy: 策略名称（参见 ENHANCED_STRATEGIES）
            **kwargs: strategy_args（传给策略函数的额外参数）、
                       bench_navs（基准净值，计算 Alpha/Beta 等）

        Returns:
            dict: 回测结果 + 归因指标
        """
        strat_func = ENHANCED_STRATEGIES.get(strategy)
        if not strat_func:
            return {"success": False, "error": f"未知策略: {strategy}", "status": "error"}

        try:
            engine = self._get_engine(f"fund_{fund_code}_{strategy}")
            nav_dict = {fund_code: nav_data}

            strategy_args = kwargs.get("strategy_args", {})

            def wrapped_strategy(ctx, code, row, rows):
                return strat_func(ctx, code, row, rows, **strategy_args)

            report = engine.run_fund(
                nav_dict, wrapped_strategy,
                commission_rate=kwargs.get("commission_rate", self.commission_rate),
                initial_capital=kwargs.get("initial_capital", self.initial_capital),
            )
            if "error" in report:
                return {"success": False, "error": report["error"], "status": "error"}

            result = {
                "success": True,
                "fund_code": fund_code,
                "strategy": strategy,
                "strategy_desc": STRATEGY_DESCRIPTIONS.get(strategy, ""),
                "report": report,
                "status": "ok",
            }

            bench_navs = kwargs.get("bench_navs")
            if bench_navs is not None:
                try:
                    fund_navs = self._extract_nav_values(nav_data)
                    bench_values = self._extract_nav_values(bench_navs)
                    metrics_result = self._metrics.calculate(fund_navs, bench_values)
                    if "error" not in metrics_result:
                        result["metrics"] = metrics_result
                except Exception as e:
                    logger.warning("归因指标计算失败: %s", e)

            summary = (
                f"基金回测（{strategy}）：{fund_code} "
                f"初始{_as_float(self.initial_capital):.0f} → "
                f"最终{_as_float(report.get('final_value', 0)):.2f} "
                f"(收益率{_as_float(report.get('total_return', 0))*100:.2f}%, "
                f"最大回撤{_as_float(report.get('max_drawdown', 0))*100:.2f}%, "
                f"夏普{_as_float(report.get('sharpe_ratio', 0)):.2f})"
            )
            result["summary"] = summary
            return result

        except Exception as e:
            logger.error("基金回测失败 %s/%s: %s", fund_code, strategy, e)
            return {"success": False, "error": str(e), "status": "error"}

    def compare_strategies(self, fund_code, nav_data, strategies=None, **kwargs):
        """多策略对比：同一只基金运行多个策略，并排输出

        Args:
            fund_code: 基金代码
            nav_data: 净值数据
            strategies: 策略名称列表；None 表示运行全部
            **kwargs: 传给 run() 的额外参

        Returns:
            dict: {success, comparisons:[{strategy, report, metrics, summary}],
                   best_by_return, best_by_sharpe, best_by_drawdown}
        """
        if strategies is None:
            strategies = list(ENHANCED_STRATEGIES.keys())

        results = []
        for strat in strategies:
            res = self.run(fund_code, nav_data, strategy=strat, **kwargs)
            if res.get("success"):
                rpt = res.get("report", {})
                results.append({
                    "strategy": strat,
                    "desc": STRATEGY_DESCRIPTIONS.get(strat, ""),
                    "final_value": rpt.get("final_value"),
                    "total_return": rpt.get("total_return"),
                    "total_return_pct": rpt.get("total_return_pct"),
                    "max_drawdown": rpt.get("max_drawdown"),
                    "max_drawdown_pct": rpt.get("max_drawdown_pct"),
                    "sharpe_ratio": rpt.get("sharpe_ratio"),
                    "trade_count": rpt.get("trade_count"),
                    "summary": res.get("summary"),
                    "metrics": res.get("metrics"),
                })

        if not results:
            return {"success": False, "error": "所有策略回测失败", "status": "error"}

        valid = [r for r in results if r.get("total_return") is not None]
        best_return = max(valid, key=lambda x: x["total_return"]) if valid else None
        best_sharpe = max(valid, key=lambda x: x.get("sharpe_ratio") or -999) if valid else None
        best_dd = min(valid, key=lambda x: x.get("max_drawdown") or 999) if valid else None

        return {
            "success": True,
            "fund_code": fund_code,
            "comparisons": results,
            "count": len(results),
            "best_by_return": best_return["strategy"] if best_return else None,
            "best_by_sharpe": best_sharpe["strategy"] if best_sharpe else None,
            "best_by_drawdown": best_dd["strategy"] if best_dd else None,
            "status": "ok",
        }

    def multi_fund_backtest(self, fund_data, strategy="买入持有", **kwargs):
        """多基金回测：对多只基金执行同一策略

        Args:
            fund_data: {fund_code: nav_data, ...}
            strategy: 策略名
            **kwargs: 其他参数

        Returns:
            dict: {success, results:{fund_code: {...}}, summary}
        """
        results = {}
        for code, nav in fund_data.items():
            res = self.run(code, nav, strategy=strategy, **kwargs)
            results[code] = res

        successful = [r for r in results.values() if r.get("success")]
        if not successful:
            return {"success": False, "error": "所有基金回测失败", "status": "error"}

        best = max(successful, key=lambda r: r.get("report", {}).get("total_return", -999))
        return {
            "success": True,
            "strategy": strategy,
            "results": results,
            "total": len(fund_data),
            "successful": len(successful),
            "best_fund": best.get("fund_code") if best else None,
            "status": "ok",
        }

    def with_benchmark(self, fund_code, nav_data, bench_navs, strategy="买入持有", **kwargs):
        """带基准对比的回测：同时输出基金收益 vs 基准收益

        Args:
            fund_code: 基金代码
            nav_data: 基金净值
            bench_navs: 基准净值（如沪深300）
            strategy: 策略名
            **kwargs: 其他

        Returns:
            dict: {success, fund_result, bench_return, excess_return}
        """
        result = self.run(fund_code, nav_data, strategy=strategy,
                          bench_navs=bench_navs, **kwargs)
        if not result.get("success"):
            return result

        bench_engine = self._get_engine("benchmark")
        bench_nav_dict = {"bench": bench_navs}

        def bench_hold(ctx, code, row, rows):
            if ctx["day"] == 1:
                return {"action": "buy", "weight": 1.0}
            return {"action": "hold"}

        bench_report = bench_engine.run_fund(
            bench_nav_dict, bench_hold,
            commission_rate=0.0, initial_capital=self.initial_capital,
        )
        fund_rpt = result.get("report", {})
        fund_ret = fund_rpt.get("total_return", 0)
        bench_ret = bench_report.get("total_return", 0) if "error" not in bench_report else 0

        excess = fund_ret - bench_ret
        result["benchmark"] = {
            "bench_return": round(bench_ret, 4),
            "bench_return_pct": f"{bench_ret*100:.2f}%",
            "excess_return": round(excess, 4),
            "excess_return_pct": f"{excess*100:.2f}%",
        }
        return result

    @staticmethod
    def _extract_nav_values(nav_data):
        values = []
        if hasattr(nav_data, "columns"):
            col = "单位净值" if "单位净值" in nav_data.columns else "close"
            values = [float(v) for v in nav_data[col].tolist() if v is not None]
        elif isinstance(nav_data, list):
            values = [
                float(r.get("单位净值", r.get("close", 0)))
                for r in nav_data if isinstance(r, dict)
            ]
        return values

    @staticmethod
    def list_strategies():
        return list(ENHANCED_STRATEGIES.keys())
