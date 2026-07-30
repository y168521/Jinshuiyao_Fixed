# -*- coding: utf-8 -*-
"""回测引擎

核心能力：
  1. 历史数据回放（按时间线逐步推进）
  2. 策略信号执行（买入/卖出/持有）
  3. 资金曲线跟踪
  4. 交易记录归档
  5. 与现有预测引擎对接
"""
import os
import re
import json
import logging
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


class BacktestEngine:
    """通用回测引擎

    支持股票、彩票等多种资产的回测。
    彩票回测：验证预测号码在历史期数中的命中率
    股票回测：验证买卖信号在历史K线中的收益表现
    """

    def __init__(self, name="default", initial_capital=100000.0,
                 commission_rate=0.0003, slippage=0.001):
        """
        Args:
            name: 回测任务名称
            initial_capital: 初始资金
            commission_rate: 手续费率（默认万3）
            slippage: 滑点（默认0.1%）
        """
        self.name = name
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage = slippage

        # 状态
        self.cash = initial_capital
        self.positions = {}  # {symbol: {"shares": int, "cost": float}}
        self.trades = []     # 交易记录
        self.daily_values = []  # 每日资产总值 [(date, value), ...]
        self.signals = []    # 信号记录
        self.running = False

    # ------------------------------------------------------------------
    # 股票回测接口
    # ------------------------------------------------------------------

    def run_stock(self, data_dict, strategy_func, **kwargs):
        """执行股票策略回测

        Args:
            data_dict: {symbol: DataFrame|list[dict]} 历史K线数据（需含 date/close）
            strategy_func: 策略函数 func(context, symbol, row, rows_so_far) -> signal
                           signal: {"action": "buy"/"sell"/"hold", "weight": 0-1}
            **kwargs: 额外参数

        Returns:
            dict: 回测结果报告
        """
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
        """统一时间线回测循环。

        Args:
            normalized: {symbol: [{"date": str, "close": float}, ...]} 已归一化的价格序列
            strategy_func: 同 run_stock

        Returns:
            dict: 回测结果报告（_build_report）
        """
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

                # 获取当前持仓市值
                pos = self.positions.get(sym, {"shares": 0, "cost": 0})
                if pos["shares"] > 0:
                    day_value += pos["shares"] * row.get("close", 0)

                # 调用策略函数
                try:
                    signal = strategy_func(context, sym, row, rows)
                except Exception as e:
                    logger.error("策略执行错误 %s@%s: %s", sym, date, e)
                    signal = {"action": "hold"}

                # 执行信号
                self._execute_signal(sym, row, signal, date)

            # 记录每日资产
            self.daily_values.append({"date": date, "value": day_value})

        self.running = False
        return self._build_report()

    def _normalize_price_df(self, df):
        """将股票K线（DataFrame 或 list[dict]）归一化为 [{"date","close"}]。"""
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

    def run_lottery(self, history_data, predictor_func, **kwargs):
        """执行彩票预测回测

        Args:
            history_data: [{"period": int, "nums": str, "time": str}, ...]
            predictor_func: 预测函数 func(history_so_far) -> predictions
            **kwargs: lot(彩种), top_n(推荐数量)

        Returns:
            dict: 回测结果报告
        """
        self.reset()
        lot = kwargs.get("lot", "未知彩种")
        top_n = kwargs.get("top_n", 5)

        hits = 0
        total = 0
        hit_records = []

        # 滑动窗口回测
        window_size = kwargs.get("window_size", 50)
        min_periods = kwargs.get("min_periods", 10)

        for i in range(min_periods, len(history_data)):
            train_data = history_data[max(0, i - window_size):i]
            actual = history_data[i]

            try:
                predictions = predictor_func(train_data, lot=lot)
            except Exception as e:
                logger.error("预测失败 period=%s: %s", actual.get("period"), e)
                continue

            # 统计命中（修正：位置/顺序感知、按彩种的正确判定，杜绝“任中1码即算命中”失真）
            actual_str = actual.get("nums", "")
            for pred in predictions[:top_n]:
                pred_str = pred.get("nums", "") if isinstance(pred, dict) else str(pred)
                is_hit, tier = self._evaluate_hit(lot, pred_str, actual_str, kwargs.get("min_hit", 3))
                total += 1
                if is_hit:
                    hits += 1
                    hit_records.append({
                        "period": actual.get("period"),
                        "tier": tier,
                        "prediction": pred_str,
                        "actual": actual_str,
                    })

        hit_rate = hits / total if total > 0 else 0
        return {
            "type": "lottery",
            "lot": lot,
            "total_tests": total,
            "hits": hits,
            "hit_rate": round(hit_rate, 4),
            "profit_ratio": round(hit_rate * kwargs.get("odds", 1) - 1, 4),
            "hit_records": hit_records[-20:],  # 最近20条
            "summary": f"{lot} 回测 {total} 期，命中 {hits} 次，命中率 {hit_rate:.2%}",
        }

    # ------------------------------------------------------------------
    # 基金回测接口
    # ------------------------------------------------------------------

    def run_fund(self, nav_data, strategy_func, **kwargs):
        """执行基金净值回测

        基金按净值申赎，无盘中价格，故以「单位净值」等价收盘价，复用统一时间线循环。
        基金执行价即当日净值：滑点=0；赎回费默认 0.15%（commission_rate），建模真实交易成本，
        避免回测收益被忽视费用而虚高（失败案例：忽略交易成本）。

        Args:
            nav_data: {fund_code: DataFrame|list[dict]} 历史净值（需含 净值日期/单位净值 或 date/close）
            strategy_func: 策略函数 func(context, code, row, rows_so_far) -> signal
            **kwargs: commission_rate(赎回费,默认0.0015)、initial_capital 等

        Returns:
            dict: 回测结果报告（type="fund"）
        """
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
        """将基金净值（DataFrame 或 list[dict]）归一化为 [{"date","close"}]，close=单位净值。"""
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
    # 基金定投模拟（微笑曲线）
    # ------------------------------------------------------------------

    def simulate_dca(self, nav_data, amount_per_period=1000.0, every=5,
                     fee_rate=0.0015, **kwargs):
        """定投模拟（微笑曲线）：固定金额每 every 个交易日买入，输出累计份额/成本摊薄/收益率曲线。

        与 run_fund 的 fund_strategy_dca 区别：本函数为专门的定投教育/测算工具，
        不依赖权重与持仓状态，逐期记录累计份额、平均成本(成本摊薄)、市值与收益率曲线，
        直观展示「下跌摊薄成本、上涨兑现收益」的微笑曲线效应。

        失败案例吸收：申购费 fee_rate 计入成本基数(份额=金额/(净值*(1+费率)))，
        避免回测收益被忽视费用而虚高（踩失败案例「忽略交易成本」）。

        Args:
            nav_data: 单只基金净值（DataFrame|list[dict]）或 {code: df}（取第一只）
            amount_per_period: 每期定投金额（元，默认1000）
            every: 定投频率（每 N 个交易日买入一次，默认5）
            fee_rate: 每笔申购费（默认0.15%，建模真实成本）
            **kwargs: start_index(默认1，从第几期开始买) 等

        Returns:
            dict: {type:"dca", total_invested, final_value, total_shares, avg_cost,
                   total_return, max_drawdown, num_purchases, break_even_nav,
                   curve:[...], summary, status}
        """
        try:
            rows = self._extract_single_nav(nav_data)
            if not rows:
                return {"error": "无有效基金净值数据", "status": "no_data"}
            if amount_per_period <= 0:
                return {"error": "定投金额必须为正", "status": "invalid"}
            if every <= 0:
                return {"error": "定投频率必须为正", "status": "invalid"}

            # 按日期升序（定投依赖时间顺序，_normalize_nav_df 不保证排序）
            rows = sorted(rows, key=lambda r: str(r.get("date", "")))
            start_index = max(1, int(kwargs.get("start_index", 1)))

            cumulative_shares = 0.0
            total_invested = 0.0
            purchases = []
            curve = []

            for i, row in enumerate(rows, start=1):
                nav = row.get("close", 0.0)
                if nav <= 0:
                    continue
                purchased = (i >= start_index) and ((i - start_index) % every == 0)

                if purchased:
                    # 申购费计入成本：实际买到份额 = 金额 / (净值*(1+费率))
                    shares_bought = amount_per_period / (nav * (1 + fee_rate))
                    cumulative_shares += shares_bought
                    total_invested += amount_per_period
                    purchases.append({
                        "date": row["date"], "nav": round(nav, 4),
                        "shares_bought": round(shares_bought, 6),
                        "amount": amount_per_period,
                    })

                # 每个交易日记录市值与收益曲线（含非定投日，展示完整微笑曲线）
                if cumulative_shares > 0:
                    market_value = cumulative_shares * nav
                    avg_cost = total_invested / cumulative_shares
                    return_pct = (market_value - total_invested) / total_invested if total_invested > 0 else 0.0
                else:
                    market_value = 0.0
                    avg_cost = 0.0
                    return_pct = 0.0

                curve.append({
                    "date": row["date"],
                    "nav": round(nav, 4),
                    "purchased": purchased,
                    "shares_bought": round(shares_bought, 6) if purchased else 0.0,
                    "cumulative_shares": round(cumulative_shares, 6),
                    "invested": round(total_invested, 2),
                    "market_value": round(market_value, 2),
                    "avg_cost": round(avg_cost, 4),
                    "return_pct": round(return_pct, 4),
                })

            if total_invested <= 0:
                return {"error": "无有效定投记录（净值数据不足或频率过高）", "status": "no_data"}

            final_value = curve[-1]["market_value"]
            total_return = (final_value - total_invested) / total_invested if total_invested else 0.0

            # 市值最大回撤（微笑曲线右半段兑现收益时的回撤）
            peak = curve[0]["market_value"]
            max_dd = 0.0
            for pt in curve:
                v = pt["market_value"]
                if v > peak:
                    peak = v
                dd = (peak - v) / peak if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd

            # 收益率曲线最大回撤（基于 return_pct）
            peak_r = curve[0]["return_pct"]
            max_dd_r = 0.0
            for pt in curve:
                r = pt["return_pct"]
                if r > peak_r:
                    peak_r = r
                dd = (peak_r - r) if peak_r > 0 else 0.0
                if dd > max_dd_r:
                    max_dd_r = dd

            break_even_nav = (total_invested / cumulative_shares) if cumulative_shares > 0 else 0.0
            avg_cost = (total_invested / cumulative_shares) if cumulative_shares > 0 else 0.0

            summary = (
                f"定投模拟：每{every}期投{amount_per_period:.0f}元，共{len(purchases)}期，"
                f"累计投入{total_invested:.0f} → 市值{final_value:.2f} "
                f"(收益率{total_return*100:.2f}%，最大回撤{max_dd*100:.2f}%，"
                f"累计份额{cumulative_shares:.2f}，平均成本{avg_cost:.4f})"
            )

            return {
                "type": "dca",
                "status": "ok",
                "total_invested": round(total_invested, 2),
                "final_value": round(final_value, 2),
                "total_shares": round(cumulative_shares, 4),
                "avg_cost": round(avg_cost, 4),
                "break_even_nav": round(break_even_nav, 4),
                "total_return": round(total_return, 4),
                "total_return_pct": f"{total_return*100:.2f}%",
                "max_drawdown": round(max_dd, 4),
                "max_drawdown_pct": f"{max_dd*100:.2f}%",
                "return_curve_max_drawdown": round(max_dd_r, 4),
                "num_purchases": len(purchases),
                "fee_rate": fee_rate,
                "amount_per_period": amount_per_period,
                "every": every,
                "curve": curve,
                "purchases": purchases,
                "summary": summary,
            }
        except Exception as e:
            logger.error("定投模拟失败: %s", e)
            return {"error": str(e), "status": "error"}

    def _extract_single_nav(self, nav_data):
        """从 单只df/list 或 {code: df} 中提取单只基金的归一化净值序列。"""
        if isinstance(nav_data, dict):
            items = list(nav_data.values())
            if not items:
                return []
            nav_data = items[0]
        return self._normalize_nav_df(nav_data)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _find_row_by_date(self, df, date):
        """按日期查找行"""
        if hasattr(df, "iterrows"):
            for _, row in df.iterrows():
                if str(row.get("date", "")) == str(date):
                    return row.to_dict() if hasattr(row, "to_dict") else dict(row)
        elif isinstance(df, list):
            for row in df:
                if str(row.get("date", "")) == str(date):
                    return row
        return None

    def _execute_signal(self, sym, row, signal, date):
        """执行交易信号"""
        action = signal.get("action", "hold")
        if action == "hold":
            return

        price = row.get("close", 0)
        if price <= 0:
            return

        # 滑点
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
                # 成本（含手续费）超出现金：缩减份额以刚好容纳手续费，避免整笔被拒
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

    def _parse_numbers(self, nums_str):
        """解析号码字符串为数字列表"""
        if not nums_str:
            return []
        import re
        return [int(x) for x in re.findall(r'\d+', str(nums_str))]

    @staticmethod
    def _split_balls(nums_str):
        """将 '1,2,3+4' 拆成 (红球列表, 蓝球列表)；无'+'时蓝球为空。"""
        s = str(nums_str or "").strip()
        if "+" in s:
            parts = s.split("+")
            reds = [int(x) for x in re.findall(r"\d+", parts[0])]
            blues = [int(x) for x in re.findall(r"\d+", parts[1])] if len(parts) > 1 else []
            return reds, blues
        return [int(x) for x in re.findall(r"\d+", s)], []

    def _evaluate_hit(self, lot, pred_str, actual_str, min_hit):
        """按彩种计算是否命中，返回 (is_hit, tier_label)。

        修正要点（相比旧的 set交集+min_hit=1）：
          - 3D/七星彩：位置完全匹配=直选；顺序无关多重集匹配=组选。不再“任中1码即算命中”。
          - 双色球/大乐透/七乐彩：按红球交集数判奖级，min_hit 为该彩种“小奖”红球阈值。
          - 快乐8：按选中号交集数判奖级，min_hit 为小奖阈值。
        这样回测命中率才反映真实预测能力，而非随机猜的必然结果。
        """
        if not pred_str or not actual_str:
            return False, ""
        lot = lot or ""
        if lot in ("福彩3D", "排列三", "七星彩"):
            pred_digits = self._parse_numbers(pred_str)
            act_digits = self._parse_numbers(actual_str)
            if not pred_digits or not act_digits:
                return False, ""
            if pred_digits == act_digits:
                return True, "直选"
            if sorted(pred_digits) == sorted(act_digits):
                return True, "组选"
            return False, ""
        # 多球种：红球交集
        pred_reds, pred_blues = self._split_balls(pred_str)
        act_reds, act_blues = self._split_balls(actual_str)
        red_common = len(set(pred_reds) & set(act_reds))
        blue_common = len(set(pred_blues) & set(act_blues))
        if red_common >= min_hit:
            tier = f"{red_common}红" + (f"+{blue_common}蓝" if blue_common else "")
            return True, tier
        return False, f"{red_common}红"

    def _build_report(self):
        """生成回测报告"""
        if not self.daily_values:
            return {"error": "无回测数据"}

        final_value = self.daily_values[-1]["value"]
        total_return = (final_value - self.initial_capital) / self.initial_capital

        # 计算最大回撤
        max_dd = self._calc_max_drawdown()

        # 计算夏普比率（简化版，假设无风险利率0）
        returns = []
        for i in range(1, len(self.daily_values)):
            prev = self.daily_values[i - 1]["value"]
            curr = self.daily_values[i]["value"]
            if prev > 0:
                returns.append((curr - prev) / prev)

        sharpe = 0
        if returns:
            avg_ret = sum(returns) / len(returns)
            var = sum((r - avg_ret) ** 2 for r in returns) / len(returns)
            std = var ** 0.5
            if std > 0:
                sharpe = (avg_ret / std) * (252 ** 0.5)  # 年化

        # 胜率
        win_trades = sum(1 for t in self.trades if t.get("action") == "sell" and t.get("revenue", 0) > t.get("cost", 0))
        total_trades = sum(1 for t in self.trades if t.get("action") == "sell")

        return {
            "name": self.name,
            "type": "stock",
            "initial_capital": self.initial_capital,
            "final_value": round(final_value, 2),
            "total_return": round(total_return, 4),
            "total_return_pct": f"{total_return*100:.2f}%",
            "max_drawdown": round(max_dd, 4),
            "max_drawdown_pct": f"{max_dd*100:.2f}%",
            "sharpe_ratio": round(sharpe, 3),
            "total_trades": total_trades,
            "win_trades": win_trades,
            "win_rate": round(win_trades / total_trades, 4) if total_trades > 0 else 0,
            "trade_count": len(self.trades),
            "daily_values": self.daily_values,
            "trades": self.trades,
            "summary": (f"回测完成: 初始{self.initial_capital:.0f} → 最终{final_value:.2f} "
                       f"(收益率{total_return*100:.2f}%, 最大回撤{max_dd*100:.2f}%, 夏普{sharpe:.2f})"),
        }

    def _calc_max_drawdown(self):
        """计算最大回撤"""
        peak = self.daily_values[0]["value"]
        max_dd = 0
        for dv in self.daily_values:
            val = dv["value"]
            if val > peak:
                peak = val
            dd = (peak - val) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        return max_dd

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
            # 简化：假设按最新价
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
# 策略签名与股票策略一致：func(context, code, row, rows_so_far) -> signal
# ======================================================================

def fund_strategy_buy_hold(ctx, code, row, rows, **_):
    """买入持有：首日满仓买入，之后长期持有。"""
    if ctx["day"] == 1:
        return {"action": "buy", "weight": 1.0}
    return {"action": "hold"}


def fund_strategy_dca(ctx, code, row, rows, every=5, weight=0.2, **_):
    """定投（微笑曲线）：每 every 个交易日买入固定权重，长期摊薄成本。不主动卖出。"""
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


# 基金回测可选策略表（FundDomain.backtest 按中文名选取）
FUND_STRATEGIES = {
    "买入持有": fund_strategy_buy_hold,
    "定投": fund_strategy_dca,
    "均线择时": fund_strategy_ma_timing,
}


# 股票回测策略（StockDomain.backtest / /api/backtest?type=stock 使用）
def stock_strategy_buy_hold(context, symbol, row, rows_so_far):
    """股票买入持有策略：每个标的首个交易日满仓买入一次，之后一直持有。

    context 在标的间共享，故用 per-symbol 状态位确保每只股票只买入一次，
    避免每个交易日重复买入（现金耗尽后自然不再买入，但显式状态位更稳健）。
    """
    st = context.setdefault("_stock_state", {}).setdefault(symbol, {"bought": False})
    if not st["bought"]:
        st["bought"] = True
        return {"action": "buy", "weight": 1.0}
    return {"action": "hold"}
