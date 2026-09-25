# -*- coding: utf-8 -*-
"""基金定投模拟（微笑曲线）—— 从 BacktestEngine 抽出的独立逻辑"""
import logging

logger = logging.getLogger(__name__)


def simulate_dca(engine, nav_data, amount_per_period=1000.0, every=5,
                 fee_rate=0.0015, **kwargs):
    """定投模拟（微笑曲线）：固定金额每 every 个交易日买入，输出累计份额/成本摊薄/收益率曲线。

    Args:
        engine: BacktestEngine 实例（用于 _extract_single_nav）
        nav_data: 单只基金净值（DataFrame|list[dict]）或 {code: df}
        amount_per_period: 每期定投金额
        every: 定投频率（每 N 个交易日买入一次）
        fee_rate: 每笔申购费
        **kwargs: start_index

    Returns:
        dict: 定投结果
    """
    try:
        rows = engine._extract_single_nav(nav_data)
        if not rows:
            return {"error": "无有效基金净值数据", "status": "no_data"}
        if amount_per_period <= 0:
            return {"error": "定投金额必须为正", "status": "invalid"}
        if every <= 0:
            return {"error": "定投频率必须为正", "status": "invalid"}

        rows = sorted(rows, key=lambda r: str(r.get("date", "")))
        start_index = max(1, int(kwargs.get("start_index", 1)))

        curve, purchases, cumulative_shares, total_invested = _build_dca_curve(
            rows, start_index, every, amount_per_period, fee_rate)

        if total_invested <= 0:
            return {"error": "无有效定投记录（净值数据不足或频率过高）", "status": "no_data"}

        return _build_dca_report(curve, purchases, cumulative_shares, total_invested,
                                 amount_per_period, every, fee_rate)
    except Exception as e:
        logger.error("定投模拟失败: %s", e)
        return {"error": str(e), "status": "error"}


def _build_dca_curve(rows, start_index, every, amount_per_period, fee_rate):
    """逐期构建定投曲线，返回 (curve, purchases, cumulative_shares, total_invested)"""
    cumulative_shares = 0.0
    total_invested = 0.0
    purchases = []
    curve = []

    for i, row in enumerate(rows, start=1):
        nav = row.get("close", 0.0)
        if nav <= 0:
            continue
        purchased = (i >= start_index) and ((i - start_index) % every == 0)

        shares_bought = 0.0
        if purchased:
            shares_bought = amount_per_period / (nav * (1 + fee_rate))
            cumulative_shares += shares_bought
            total_invested += amount_per_period
            purchases.append({
                "date": row["date"], "nav": round(nav, 4),
                "shares_bought": round(shares_bought, 6),
                "amount": amount_per_period,
            })

        if cumulative_shares > 0:
            market_value = cumulative_shares * nav
            avg_cost = total_invested / cumulative_shares
            return_pct = (market_value - total_invested) / total_invested if total_invested > 0 else 0.0
        else:
            market_value = avg_cost = return_pct = 0.0

        curve.append({
            "date": row["date"], "nav": round(nav, 4),
            "purchased": purchased,
            "shares_bought": round(shares_bought, 6) if purchased else 0.0,
            "cumulative_shares": round(cumulative_shares, 6),
            "invested": round(total_invested, 2),
            "market_value": round(market_value, 2),
            "avg_cost": round(avg_cost, 4),
            "return_pct": round(return_pct, 4),
        })

    return curve, purchases, cumulative_shares, total_invested


def _build_dca_report(curve, purchases, cumulative_shares, total_invested,
                      amount_per_period, every, fee_rate):
    """从定投曲线生成结果报告"""
    final_value = curve[-1]["market_value"]
    total_return = (final_value - total_invested) / total_invested if total_invested else 0.0

    max_dd = _curve_max_drawdown(curve, "market_value")
    max_dd_r = _curve_max_drawdown(curve, "return_pct", relative=False)

    avg_cost = (total_invested / cumulative_shares) if cumulative_shares > 0 else 0.0
    break_even_nav = avg_cost

    summary = (
        f"定投模拟：每{every}期投{amount_per_period:.0f}元，共{len(purchases)}期，"
        f"累计投入{total_invested:.0f} → 市值{final_value:.2f} "
        f"(收益率{total_return*100:.2f}%，最大回撤{max_dd*100:.2f}%，"
        f"累计份额{cumulative_shares:.2f}，平均成本{avg_cost:.4f})"
    )

    return {
        "type": "dca", "status": "ok",
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


def _curve_max_drawdown(curve, key, relative=True):
    """计算曲线某字段的最大回撤"""
    if not curve:
        return 0.0
    peak = curve[0][key]
    max_dd = 0.0
    for pt in curve:
        v = pt[key]
        if v > peak:
            peak = v
        if relative:
            dd = (peak - v) / peak if peak > 0 else 0.0
        else:
            dd = (peak - v) if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd
