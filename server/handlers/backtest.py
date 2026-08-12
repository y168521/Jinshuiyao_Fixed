# -*- coding: utf-8 -*-
"""金水谣系统 - 股基回测 / 基金对比 API 路由处理

路由：
  GET  /api/backtest        — 统一股基回测（type=fund|stock，默认 fund）
  POST /api/backtest        — 同上（JSON body 优先，query 兜底）
  GET  /api/fund-backtest   — 基金回测（策略：买入持有/均线择时/定投）
  POST /api/fund-backtest   — 同上
  GET  /api/fund-compare    — 基金横向对比视图（多基金同屏对比）
  POST /api/fund-compare    — 同上

债务-201（W63补72）：参数工具/基金域单例已合一至 fund.py，本模块 import 复用。

均为只读分析端点（纯计算，不执行文件/不越权），对局域网开放。
"""
from ..utils import log
from .fund import _parse_codes, _parse_params, _to_float, _to_int, get_fund_domain

# ─── 域实例单例（惰性初始化，跨请求复用 _data_cache）───
# 基金域单例统一由 fund.py 持有（债务-201 合一）；股票域本模块持有。
_stock_domain = None


def get_stock_domain():
    """获取（惰性初始化并 setup 的）StockDomain 单例。"""
    global _stock_domain
    if _stock_domain is None:
        try:
            from domains.stock.domain import StockDomain
            d = StockDomain()
            d.setup()
            _stock_domain = d
        except Exception as e:
            log(f"[stock-backtest] StockDomain 初始化失败: {e}")
    return _stock_domain


# ─── 参数解析工具（债务-201 已合一至 fund.py，本模块 import 复用）───

def _ensure_fund_data(domain, codes, force_refresh):
    """确保基金缓存有数据：空缓存或强制刷新时先抓取（避免每次请求重抓）。"""
    if force_refresh or not domain._data_cache:
        domain.fetch(codes or domain.active_funds())


# ─── 基金回测（核心实现，供 /api/fund-backtest 与 /api/backtest?type=fund 复用）───

def _run_fund_backtest(handler, params):
    domain = get_fund_domain()
    if domain is None:
        handler._send_json({"ok": False, "error": "基金子系统不可用"}, 503)
        return

    codes = _parse_codes(params.get("codes"))
    strategy = params.get("strategy", "买入持有")
    force_refresh = str(params.get("force_refresh", "")).lower() in ("1", "true", "yes")

    try:
        _ensure_fund_data(domain, codes, force_refresh)

        if strategy == "定投":
            amount = _to_float(params.get("amount_per_period"), 1000.0)
            every = _to_int(params.get("every"), 5)
            res = domain.simulate_dca(
                None,
                amount_per_period=amount,
                every=every,
                fee_rate=_to_float(params.get("fee_rate"), 0.0015),
            )
        else:
            res = domain.backtest(
                None,
                strategy=strategy,
                initial_capital=_to_float(params.get("initial_capital"), 100000.0),
                commission_rate=_to_float(params.get("commission_rate"), 0.0015),
            )

        if res.get("success"):
            handler._send_json({"ok": True, **res}, 200)
        else:
            handler._send_json(
                {"ok": False, "error": res.get("message", "回测失败"), "status": res.get("status")},
                400,
            )
    except Exception as e:
        log(f"[fund-backtest] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


# ─── 股票回测（供 /api/backtest?type=stock 复用）───

def _run_stock_backtest(handler, params):
    domain = get_stock_domain()
    if domain is None:
        handler._send_json({"ok": False, "error": "股票子系统不可用"}, 503)
        return

    codes = _parse_codes(params.get("codes"))
    strategy = params.get("strategy", "买入持有")
    force_refresh = str(params.get("force_refresh", "")).lower() in ("1", "true", "yes")

    try:
        if force_refresh or not domain._data_cache:
            target = codes
            if target and isinstance(target[0], (list, tuple)):
                target = [c for c, _ in target]
            domain.fetch(target or domain.DEFAULT_STOCK_POOL)

        res = domain.backtest(
            codes,
            strategy=strategy,
            initial_capital=_to_float(params.get("initial_capital"), 100000.0),
            commission_rate=_to_float(params.get("commission_rate"), 0.0003),
        )
        if res.get("success"):
            handler._send_json({"ok": True, **res}, 200)
        else:
            handler._send_json(
                {"ok": False, "error": res.get("message", "回测失败"), "status": res.get("status")},
                400,
            )
    except Exception as e:
        log(f"[stock-backtest] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


# ─── 基金对比视图 ───

def _run_fund_compare(handler, params):
    domain = get_fund_domain()
    if domain is None:
        handler._send_json({"ok": False, "error": "基金子系统不可用"}, 503)
        return

    codes = _parse_codes(params.get("codes"))
    top_n = _to_int(params.get("top_n"), 0) or None
    force_refresh = str(params.get("force_refresh", "")).lower() in ("1", "true", "yes")

    try:
        res = domain.compare_funds(codes, top_n=top_n, force_refresh=force_refresh)
        if res.get("success"):
            handler._send_json({"ok": True, **res}, 200)
        else:
            handler._send_json(
                {"ok": False, "error": res.get("message", "对比失败"), "status": res.get("status")},
                400,
            )
    except Exception as e:
        log(f"[fund-compare] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


# ─── 对外路由函数 ───

def handle_fund_backtest(handler, parsed):
    """GET/POST /api/fund-backtest — 基金回测（买入持有/均线择时/定投）"""
    _run_fund_backtest(handler, _parse_params(handler, parsed))


def handle_fund_compare(handler, parsed):
    """GET/POST /api/fund-compare — 基金横向对比视图"""
    _run_fund_compare(handler, _parse_params(handler, parsed))


def handle_backtest(handler, parsed):
    """GET/POST /api/backtest — 统一股基回测（type=fund|stock，默认 fund）"""
    params = _parse_params(handler, parsed)
    btype = str(params.get("type") or "fund").lower()
    if btype == "stock":
        _run_stock_backtest(handler, params)
    else:
        _run_fund_backtest(handler, params)
