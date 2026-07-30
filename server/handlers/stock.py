# -*- coding: utf-8 -*-
"""金水谣系统 - 股票子系统 API 路由处理（专用模块）

从 server/handlers/backtest.py 拆分出股票专属路由，职责更清晰。

路由：
  GET/POST  /api/stock/screen      — 股票多因子选股
  GET/POST  /api/stock/backtest    — 股票回测
  GET/POST  /api/stock/status      — 股票子系统状态
  GET/POST  /api/stock/factors     — 列出所有选股因子
"""
import json
import urllib.parse

from ..utils import log

_stock_domain = None


def get_stock_domain():
    global _stock_domain
    if _stock_domain is None:
        try:
            from domains.stock.domain import StockDomain
            d = StockDomain()
            d.setup()
            _stock_domain = d
        except Exception as e:
            log(f"[stock] StockDomain 初始化失败: {e}")
    return _stock_domain


def _parse_params(handler, parsed):
    params = {}
    try:
        qs = urllib.parse.parse_qs(parsed.query)
        for k, v in qs.items():
            params[k] = v[0] if len(v) == 1 else v
    except Exception as e:
        log(f"[stock] 解析 query 失败: {e}")
    cl = int(handler.headers.get("Content-Length", 0) or 0)
    if cl > 0:
        try:
            raw = handler.rfile.read(cl).decode("utf-8", errors="replace")
            if raw:
                body = json.loads(raw)
                if isinstance(body, dict):
                    params.update(body)
        except Exception as e:
            log(f"[stock] 解析 POST body 失败: {e}")
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


def handle_screen(handler, parsed):
    """GET/POST /api/stock/screen — 股票多因子选股"""
    params = _parse_params(handler, parsed)
    domain = get_stock_domain()
    if domain is None:
        handler._send_json({"ok": False, "error": "股票子系统不可用"}, 503)
        return

    top_n = _to_int(params.get("top_n"), 10)
    multi_factor = str(params.get("multi_factor", "true")).lower() in ("1", "true", "yes")
    force_refresh = str(params.get("force_refresh", "")).lower() in ("1", "true", "yes")

    try:
        if force_refresh:
            domain.fetch(None)
        res = domain.screen(
            pool=None, top_n=top_n,
            multi_factor=multi_factor,
            criteria={
                "min_score": _to_float(params.get("min_score"), 0),
                "require_technical": str(params.get("require_technical", "true")).lower() in ("1", "true"),
            },
        )
        if res.get("success"):
            handler._send_json({"ok": True, **res}, 200)
        else:
            handler._send_json(
                {"ok": False, "error": res.get("message", "选股失败"),
                 "status": res.get("status")}, 400)
    except Exception as e:
        log(f"[stock-screen] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_backtest(handler, parsed):
    """GET/POST /api/stock/backtest — 股票回测"""
    params = _parse_params(handler, parsed)
    domain = get_stock_domain()
    if domain is None:
        handler._send_json({"ok": False, "error": "股票子系统不可用"}, 503)
        return

    codes = params.get("codes")
    if codes:
        if isinstance(codes, str):
            codes = [c.strip() for c in codes.split(",") if c.strip()]
    strategy = params.get("strategy", "买入持有")

    try:
        if params.get("force_refresh"):
            domain.fetch(codes)
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
                {"ok": False, "error": res.get("message", "回测失败"),
                 "status": res.get("status")}, 400)
    except Exception as e:
        log(f"[stock-backtest] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_status(handler, parsed):
    """GET/POST /api/stock/status — 股票子系统状态"""
    domain = get_stock_domain()
    if domain is None:
        handler._send_json({"ok": False, "error": "股票子系统不可用"}, 503)
        return
    try:
        st = domain.status()
        handler._send_json({"ok": True, "status": st}, 200)
    except Exception as e:
        log(f"[stock-status] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_factors(handler, parsed):
    """GET/POST /api/stock/factors — 列出所有选股因子"""
    try:
        from domains.stock.stock_screener import StockScreener
        factors = StockScreener.list_factors()
        handler._send_json({"ok": True, "factors": factors, "count": len(factors)}, 200)
    except Exception as e:
        log(f"[stock-factors] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)
