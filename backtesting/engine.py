# -*- coding: utf-8 -*-
"""回测引擎

核心能力：
  1. 历史数据回放（按时间线逐步推进）
  2. 策略信号执行（买入/卖出/持有）
  3. 资金曲线跟踪
  4. 交易记录归档
  5. 与现有预测引擎对接

按职责拆分的子模块：
  - engine_dca: 基金定投模拟（微笑曲线）
  - engine_lottery: 彩票回测 + 命中判定
  - engine_report: 回测报告生成 + 指标计算
"""
import logging

from . import engine_dca
from . import engine_lottery
from . import engine_report

logger = logging.getLogger(__name__)


class BacktestEngine:
    """通用回测引擎

    支持股票、彩票等多种资产的回测。
    彩票回测：验证预测号码在历史期数中的命中率
    股票回测：验证买卖信号在历史K线中的收益表现
    """

    def __init__(self, name="default", initial_capital=100000.0,
                 commission_rate=0.0003, slippage=0.001):
        self.name = name
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage = slippage

        self.cash = initial_capital
        self.positions = {}  # {symbol: {"shares": int, "cost": float}}
        self.trades = []
        self.daily_values = []
        self.signals = []
        self.running = False

    # ------------------------------------------------------------------
    # 股票回测接口
    # ------------------------------------------------------------------

    def run_stock(self, data_dict, strategy_func, **kwargs):
        """执行股票策略回测"""
        normalized = {}
        for sym, df in data_dict.items():
            rows = self._normalize_price_df(df)
            if rows:
                normalized[sym] = rows
        if not normalized:
            return {"error": "无有效股票数据"}
        return self._run_normalized(normalized, strategy_func)

    # ------------------------------------------------------------------
    # 共享时间线回测循环（股票/基金复用）
    # ------------------------------------------------------------------

    def _run_normalized(self, normalized, strategy_func):
        """统一时间线回测循环"""
        self.reset()
        self.running = True

        all_dates = set()
        for sym, rows in normalized.items():
            for r in rows:
                if r.get("date"):
                    all_dates.add(r["date"])

        sorted_dates = sorted(all_dates)
        logger.info("回测时间线: %d 个交易日", len(sorted_dates))

        context = {"day": 0, "total_days": len(sorted_dates)}

        for date in sorted_dates:
            context["day"] += 1
            day_value = self.cash

            for sym, rows in normalized.items():
                row = next((r for r in rows if r.get("date") == date), None)
                if row is None:
                    continue

                pos = self.positions.get(sym, {"shares": 0, "cost": 0})
                if pos["shares"] > 0:
                    day_value += pos["shares"] * row.get("close", 0)

                try:
                    signal = strategy_func(context, sym, row, rows)
                except Exception as e:
                    logger.error("策略执行错误 %s@%s: %s", sym, date, e)
                    signal = {"action": "hold"}

                self._execute_signal(sym, row, signal, date)

            self.daily_values.append({"date": date, "value": day_value})

        self.running = False
        return self._build_report()

    def _normalize_price_df(self, df):
        """将股票K线归一化为 [{"date","close"}]"""
        rows = []
        if hasattr(df, "iterrows"):
            for _, row in df.iterrows():
                d = row.get("date")
                c = row.get("close")
                if d is None or c is None:
                    continue
                rows.append({"date": str(d), "close": float(c)})
        elif isinstance(df, list):
            for row in df:
                if isinstance(row, dict) and row.get("date") is not None and row.get("close") is not None:
                    rows.append({"date": str(row["date"]), "close": float(row["close"])})
        return rows

    # ------------------------------------------------------------------
    # 彩票回测接口（委托 engine_lottery）
    # ------------------------------------------------------------------

    def run_lottery(self, history_data, predictor_func, **kwargs):
        """执行彩票预测回测"""
        return engine_lottery.run_lottery(self, history_data, predictor_func, **kwargs)

    # ------------------------------------------------------------------
    # 基金回测接口
    # ------------------------------------------------------------------

    def run_fund(self, nav_data, strategy_func, **kwargs):
        """执行基金净值回测"""
        self.slippage = 0.0
        self.commission_rate = kwargs.get("commission_rate", 0.0015)

        normalized = {}
        for code, df in nav_data.items():
            rows = self._normalize_nav_df(df)
            if rows:
                normalized[code] = rows
        if not normalized:
            return {"error": "无有效基金净值数据"}

        report = self._run_normalized(normalized, strategy_func)
        report["type"] = "fund"
        return report

    def _normalize_nav_df(self, df):
        """将基金净值归一化为 [{"date","close"}]，close=单位净值"""
        rows = []
        if hasattr(df, "iterrows"):
            for _, row in df.iterrows():
                d = row.get("净值日期") or row.get("date")
                c = row.get("单位净值") or row.get("close")
                if d is None or c is None:
                    continue
                rows.append({"date": str(d), "close": float(c)})
        elif isinstance(df, list):
            for row in df:
                if not isinstance(row, dict):
                    continue
                d = row.get("净值日期") or row.get("date")
                c = row.get("单位净值") or row.get("close")
                if d is None or c is None:
                    continue
                rows.append({"date": str(d), "close": float(c)})
        return rows

    # ------------------------------------------------------------------
    # 基金定投模拟（委托 engine_dca）
    # ------------------------------------------------------------------

    def simulate_dca(self, nav_data, amount_per_period=1000.0, every=5,
                     fee_rate=0.0015, **kwargs):
        """定投模拟（微笑曲线）"""
        return engine_dca.simulate_dca(self, nav_data, amount_per_period, every,
                                       fee_rate, **kwargs)

    def _extract_single_nav(self, nav_data):
        """从 单只df/list 或 {code: df} 中提取单只基金的归一化净值序列"""
        if isinstance(nav_data, dict):
            items = list(nav_data.values())
            if not items:
                return []
            nav_data = items[0]
        return self._normalize_nav_df(nav_data)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _execute_signal(self, sym, row, signal, date):
        """执行交易信号"""
        action = signal.get("action", "hold")
        if action == "hold":
            return

        price = row.get("close", 0)
        if price <= 0:
            return

        if action == "buy":
            price *= (1 + self.slippage)
        elif action == "sell":
            price *= (1 - self.slippage)

        pos = self.positions.get(sym, {"shares": 0, "cost": 0})

        if action == "buy":
            weight = signal.get("weight", 0.2)
            max_spend = self.cash * weight
            shares = int(max_spend / price)
            if shares <= 0:
                return
            cost = shares * price * (1 + self.commission_rate)
            if cost > self.cash:
                affordable = self.cash / (price * (1 + self.commission_rate))
                shares = int(affordable)
                if shares <= 0:
                    return
                cost = shares * price * (1 + self.commission_rate)
            self.cash -= cost
            pos["shares"] += shares
            pos["cost"] += cost
            self.positions[sym] = pos
            self.trades.append({
                "date": date, "symbol": sym, "action": "buy",
                "shares": shares, "price": round(price, 2),
                "cost": round(cost, 2),
            })

        elif action == "sell":
            shares = pos.get("shares", 0)
            if shares <= 0:
                return
            revenue = shares * price * (1 - self.commission_rate)
            self.cash += revenue
            self.trades.append({
                "date": date, "symbol": sym, "action": "sell",
                "shares": shares, "price": round(price, 2),
                "revenue": round(revenue, 2),
            })
            pos["shares"] = 0
            pos["cost"] = 0
            self.positions[sym] = pos

        self.signals.append({"date": date, "symbol": sym, "action": action, "price": price})

    # ------------------------------------------------------------------
    # 报告生成（委托 engine_report）
    # ------------------------------------------------------------------

    def _build_report(self):
        """生成回测报告"""
        return engine_report.build_report(self)

    def _calc_max_drawdown(self):
        """计算最大回撤"""
        return engine_report.calc_max_drawdown(self.daily_values)

    # ------------------------------------------------------------------
    # 彩票命中判定（委托 engine_lottery）
    # ------------------------------------------------------------------

    def _parse_numbers(self, nums_str):
        return engine_lottery.parse_numbers(nums_str)

    @staticmethod
    def _split_balls(nums_str):
        return engine_lottery.split_balls(nums_str)

    def _evaluate_hit(self, lot, pred_str, actual_str, min_hit):
        return engine_lottery.evaluate_hit(lot, pred_str, actual_str, min_hit)

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def reset(self):
        """重置回测状态"""
        self.cash = self.initial_capital
        self.positions = {}
        self.trades = []
        self.daily_values = []
        self.signals = []
        self.running = False

    def summary(self):
        """当前状态摘要"""
        total_pos_value = 0
        for sym, pos in self.positions.items():
            total_pos_value += pos.get("shares", 0) * pos.get("cost", 0)
        total = self.cash + total_pos_value
        return {
            "cash": round(self.cash, 2),
            "positions_value": round(total_pos_value, 2),
            "total": round(total, 2),
            "return": round((total - self.initial_capital) / self.initial_capital, 4),
        }


# ======================================================================
# 基金内置回测策略（无未来函数：均线择时只用窗口内历史净值）
# ======================================================================

def fund_strategy_buy_hold(ctx, code, row, rows, **_):
    """买入持有：首日满仓买入，之后长期持有。"""
    if ctx["day"] == 1:
        return {"action": "buy", "weight": 1.0}
    return {"action": "hold"}


def fund_strategy_dca(ctx, code, row, rows, every=5, weight=0.2, **_):
    """定投（微笑曲线）：每 every 个交易日买入固定权重，长期摊薄成本。"""
    if ctx["day"] % every == 0:
        return {"action": "buy", "weight": weight}
    return {"action": "hold"}


def fund_strategy_ma_timing(ctx, code, row, rows, window=20, weight=0.5, **_):
    """均线择时：净值上穿 window 日均线买入，下穿卖出。仅用历史窗口，无未来函数。"""
    idx = next((i for i, r in enumerate(rows) if r["date"] == row["date"]), -1)
    if idx <= window:
        return {"action": "hold"}
    past = [rows[i]["close"] for i in range(idx - window, idx)]
    ma = sum(past) / len(past)
    cur = row["close"]
    st = ctx.setdefault("_fund_state", {}).setdefault(code, {"pos": 0})
    if cur > ma and st["pos"] == 0:
        st["pos"] = 1
        return {"action": "buy", "weight": weight}
    if cur < ma and st["pos"] == 1:
        st["pos"] = 0
        return {"action": "sell"}
    return {"action": "hold"}


FUND_STRATEGIES = {
    "买入持有": fund_strategy_buy_hold,
    "定投": fund_strategy_dca,
    "均线择时": fund_strategy_ma_timing,
}


# ======================================================================
# 股票回测策略
# ======================================================================

def stock_strategy_buy_hold(context, symbol, row, rows_so_far):
    """股票买入持有策略：每个标的首个交易日满仓买入一次，之后一直持有。"""
    st = context.setdefault("_stock_state", {}).setdefault(symbol, {"bought": False})
    if not st["bought"]:
        st["bought"] = True
        return {"action": "buy", "weight": 1.0}
    return {"action": "hold"}
