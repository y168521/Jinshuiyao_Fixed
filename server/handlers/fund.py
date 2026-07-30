# -*- coding: utf-8 -*-
"""金水谣系统 - 基金子系统 API 路由处理（专用模块）

从 server/handlers/backtest.py 拆分出基金专属路由，职责更清晰。

路由：
  GET/POST  /api/fund/backtest      — 基金回测（指定策略）
  GET/POST  /api/fund/compare       — 基金横向对比
  GET/POST  /api/fund/strategies    — 列出所有可用策略
  GET/POST  /api/fund/compare-strategies — 同一基金多策略对比
  GET/POST  /api/fund/status        — 基金子系统状态
  GET/POST  /api/fund/with-benchmark — 带基准对比的回测

均为只读分析端点（纯计算，不执行文件/不越权），对局域网开放。
"""
import json
import urllib.parse

from ..utils import log

_fund_domain = None
_fund_backtest = None


def get_fund_domain():
    global _fund_domain
    if _fund_domain is None:
        try:
            from domains.fund.domain import FundDomain
            d = FundDomain()
            d.setup()
            _fund_domain = d
        except Exception as e:
            log(f"[fund] FundDomain 初始化失败: {e}")
    return _fund_domain


def get_fund_backtest():
    global _fund_backtest
    if _fund_backtest is None:
        try:
            from domains.fund.fund_backtest import FundBacktestEngine
            _fund_backtest = FundBacktestEngine()
        except Exception as e:
            log(f"[fund] FundBacktestEngine 初始化失败: {e}")
    return _fund_backtest


def _parse_params(handler, parsed):
    params = {}
    try:
        qs = urllib.parse.parse_qs(parsed.query)
        for k, v in qs.items():
            params[k] = v[0] if len(v) == 1 else v
    except Exception as e:
        log(f"[fund] 解析 query 失败: {e}")
    cl = int(handler.headers.get("Content-Length", 0) or 0)
    if cl > 0:
        try:
            raw = handler.rfile.read(cl).decode("utf-8", errors="replace")
            if raw:
                body = json.loads(raw)
                if isinstance(body, dict):
                    params.update(body)
        except Exception as e:
            log(f"[fund] 解析 POST body 失败: {e}")
    return params


def _to_float(val, default):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _to_int(val, default):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _parse_codes(val):
    if val is None:
        return None
    if isinstance(val, (list, tuple)):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        return [c.strip() for c in val.split(",") if c.strip()]
    return [str(val).strip()] if val else None


def handle_backtest(handler, parsed):
    """GET/POST /api/fund/backtest — 基金回测（买入持有/均线择时/定投/网格定投等）"""
    params = _parse_params(handler, parsed)
    domain = get_fund_domain()
    if domain is None:
        handler._send_json({"ok": False, "error": "基金子系统不可用"}, 503)
        return

    codes = _parse_codes(params.get("codes"))
    strategy = params.get("strategy", "买入持有")
    force_refresh = str(params.get("force_refresh", "")).lower() in ("1", "true", "yes")

    try:
        if force_refresh or not domain._data_cache:
            domain.fetch(codes or domain.DEFAULT_FUNDS)

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
            use_enhanced = str(params.get("enhanced", "")).lower() in ("1", "true", "yes")
            if use_enhanced:
                engine = get_fund_backtest()
                if engine is None:
                    handler._send_json({"ok": False, "error": "增强回测引擎不可用"}, 503)
                    return
                bench_navs = None
                bench_code = params.get("benchmark", "")
                if bench_code:
                    try:
                        from domains.stock.fetcher import StockFetcher
                        sf = StockFetcher()
                        bench_df = sf.get_history(bench_code)
                        bench_navs = bench_df
                    except Exception as e:
                        log(f"[fund] 获取基准数据失败: {e}")
                target_codes = codes or list(domain._data_cache.keys())
                if isinstance(target_codes, list) and len(target_codes) == 1:
                    code = target_codes[0]
                    nav = domain._data_cache.get(code, {}).get("nav")
                    if nav is not None:
                        strategy_args = {}
                        if strategy == "目标止盈":
                            strategy_args["target"] = _to_float(params.get("target"), 0.20)
                        elif strategy in ("定投", "定投+止盈"):
                            strategy_args["every"] = _to_int(params.get("every"), 5)
                            strategy_args["weight"] = _to_float(params.get("weight"), 0.2)
                        res = engine.run(
                            code, nav, strategy=strategy,
                            bench_navs=bench_navs,
                            strategy_args=strategy_args,
                            initial_capital=_to_float(params.get("initial_capital"), 100000.0),
                            commission_rate=_to_float(params.get("commission_rate"), 0.0015),
                        )
                        handler._send_json({"ok": True, **res}, 200)
                        return
                res = domain.backtest(
                    None,
                    strategy=strategy,
                    initial_capital=_to_float(params.get("initial_capital"), 100000.0),
                    commission_rate=_to_float(params.get("commission_rate"), 0.0015),
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
                {"ok": False, "error": res.get("message", res.get("error", "回测失败")),
                 "status": res.get("status")}, 400)
    except Exception as e:
        log(f"[fund-backtest] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_compare(handler, parsed):
    """GET/POST /api/fund/compare — 基金横向对比"""
    params = _parse_params(handler, parsed)
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
                {"ok": False, "error": res.get("message", "对比失败"),
                 "status": res.get("status")}, 400)
    except Exception as e:
        log(f"[fund-compare] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_strategies(handler, parsed):
    """GET/POST /api/fund/strategies — 列出所有可用策略"""
    try:
        from domains.fund.fund_backtest import ENHANCED_STRATEGIES, STRATEGY_DESCRIPTIONS
        strategies = []
        for name in ENHANCED_STRATEGIES:
            strategies.append({
                "name": name,
                "description": STRATEGY_DESCRIPTIONS.get(name, ""),
            })
        handler._send_json({"ok": True, "strategies": strategies, "count": len(strategies)}, 200)
    except Exception as e:
        log(f"[fund-strategies] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_compare_strategies(handler, parsed):
    """GET/POST /api/fund/compare-strategies — 同一基金多策略对比"""
    params = _parse_params(handler, parsed)
    domain = get_fund_domain()
    engine = get_fund_backtest()
    if domain is None or engine is None:
        handler._send_json({"ok": False, "error": "基金子系统不可用"}, 503)
        return

    codes = _parse_codes(params.get("codes"))
    force_refresh = str(params.get("force_refresh", "")).lower() in ("1", "true", "yes")

    try:
        if force_refresh or not domain._data_cache:
            domain.fetch(codes or domain.DEFAULT_FUNDS)

        target = (codes or list(domain._data_cache.keys()))[:3]
        results = {}
        for code in target:
            nav = domain._data_cache.get(code, {}).get("nav")
            if nav is not None:
                res = engine.compare_strategies(code, nav,
                    initial_capital=_to_float(params.get("initial_capital"), 100000.0),
                    commission_rate=_to_float(params.get("commission_rate"), 0.0015),
                )
                if res.get("success"):
                    results[code] = res

        handler._send_json({
            "ok": True,
            "results": results,
            "fund_count": len(results),
        }, 200)
    except Exception as e:
        log(f"[fund-compare-strategies] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_status(handler, parsed):
    """GET/POST /api/fund/status — 基金子系统健康状态"""
    domain = get_fund_domain()
    if domain is None:
        handler._send_json({"ok": False, "error": "基金子系统不可用"}, 503)
        return
    try:
        st = domain.status()
        handler._send_json({"ok": True, "status": st}, 200)
    except Exception as e:
        log(f"[fund-status] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)
