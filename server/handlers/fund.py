# -*- coding: utf-8 -*-
"""金水谣系统 - 基金子系统 API 路由处理（专用模块）

从 server/handlers/backtest.py 拆分出基金专属路由，职责更清晰。

路由：
  GET/POST  /api/fund/backtest      — 基金回测（指定策略）
  GET/POST  /api/fund/compare       — 基金横向对比
  GET/POST  /api/fund/strategies    — 列出所有可用策略
  GET/POST  /api/fund/compare-strategies — 同一基金多策略对比
  GET/POST  /api/fund/status        — 基金子系统状态

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
            domain.fetch(codes or domain.active_funds())

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
            domain.fetch(codes or domain.active_funds())

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


def handle_pool(handler, parsed):
    """GET/POST /api/fund/pool — 当前基金池（持仓优先，回退内置池），返回名称+代码"""
    domain = get_fund_domain()
    if domain is None:
        handler._send_json({"ok": False, "error": "基金子系统不可用"}, 503)
        return
    try:
        pool = []
        mgr = _get_portfolio_manager()
        source = "default"
        if mgr is not None:
            holdings = mgr.get_holdings()
            if holdings:
                source = "holdings"
                for h in holdings:
                    code = str(h.get("code", "")).strip()
                    if code:
                        pool.append({"code": code, "name": h.get("name") or code})
        if not pool:
            name_map = {}
            try:
                if domain._fetcher is not None:
                    name_map = domain._fetcher.get_fund_names_map()
            except Exception as e:
                log(f"[fund-pool] 基金名称映射获取失败: {e}")
            for code in domain.DEFAULT_FUNDS:
                cache = domain._data_cache.get(code, {})
                info = cache.get("info", {}) if isinstance(cache, dict) else {}
                name = info.get("基金名称") or name_map.get(code) or code
                pool.append({"code": code, "name": name})
        handler._send_json({"ok": True, "pool": pool, "count": len(pool), "source": source}, 200)
    except Exception as e:
        log(f"[fund-pool] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


_PERIOD_DAYS = {"1m": 30, "3m": 90, "6m": 180, "1y": 365, "3y": 1095}


def handle_nav_series(handler, parsed):
    """POST /api/fund/nav-series — 基金净值序列（前端图表真实数据源）

    body: {codes?: [code...], period?: "1m"|"3m"|"6m"|"1y"|"3y"|"all" (默认 1y)}
    返回每只基金的净值序列 + 关键指标 + 数据来源诚实标记(mode)。
    """
    params = _parse_params(handler, parsed)
    domain = get_fund_domain()
    if domain is None:
        handler._send_json({"ok": False, "error": "基金子系统不可用"}, 503)
        return

    codes = _parse_codes(params.get("codes"))
    period = str(params.get("period", "1y")).strip() or "1y"
    days = _PERIOD_DAYS.get(period, _PERIOD_DAYS["1y"])
    cutoff = None
    if days is not None and period != "all":
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        if not domain._data_cache:
            domain.fetch(codes or domain.active_funds())
        target = codes or list(domain._data_cache.keys())

        funds = []
        for code in target:
            cache = domain._data_cache.get(code)
            if not isinstance(cache, dict) or "nav" not in cache:
                continue
            nav_df = cache["nav"]
            try:
                dates = nav_df["净值日期"].astype(str).tolist()
                vals = nav_df["单位净值"].astype(float).tolist()
            except Exception as e:
                log(f"[fund-nav-series] {code} 列解析失败: {e}")
                continue
            series = [{"date": d, "value": round(v, 4)} for d, v in zip(dates, vals)
                      if cutoff is None or d >= cutoff]
            if not series:
                series = [{"date": d, "value": round(v, 4)} for d, v in zip(dates, vals)]

            metrics = {}
            if len(series) >= 2:
                first, last = series[0]["value"], series[-1]["value"]
                metrics["period_return"] = round(last / first - 1, 4) if first else 0
                peak = first
                max_dd = 0.0
                for pt in series:
                    v = pt["value"]
                    if v > peak:
                        peak = v
                    dd = (peak - v) / peak if peak > 0 else 0.0
                    if dd > max_dd:
                        max_dd = dd
                metrics["max_drawdown"] = round(-max_dd, 4)

            info = cache.get("info", {})
            name = info.get("基金名称") or info.get("name") or code
            mode = domain._data_mode.get(code, "unknown")
            funds.append({
                "code": code,
                "name": name,
                "mode": mode,
                "period": period,
                "start": series[0]["date"] if series else None,
                "end": series[-1]["date"] if series else None,
                "points": len(series),
                "nav_series": series,
                "metrics": metrics,
            })

        handler._send_json({
            "ok": True,
            "funds": funds,
            "count": len(funds),
            "period": period,
            "mock_count": sum(1 for f in funds if f["mode"] == "mock"),
        }, 200)
    except Exception as e:
        log(f"[fund-nav-series] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_holdings_detail(handler, parsed):
    """POST /api/fund/holdings — 单只基金持仓穿透（行业分布 + 前十大重仓股）

    body: {code: "000001"}
    返回行业分布（估算）、集中度指标、重仓股明细，含数据来源诚实标记。
    """
    params = _parse_params(handler, parsed)
    domain = get_fund_domain()
    if domain is None:
        handler._send_json({"ok": False, "error": "基金子系统不可用"}, 503)
        return
    code = str(params.get("code", "")).strip()
    if not code:
        handler._send_json({"ok": False, "error": "基金代码不能为空"}, 400)
        return
    try:
        cache = domain._data_cache.get(code)
        if not isinstance(cache, dict) or "holdings" not in cache:
            domain.fetch([code])
        cache = domain._data_cache.get(code, {})
        holdings_df = cache.get("holdings") if isinstance(cache, dict) else None

        if holdings_df is None or (hasattr(holdings_df, "empty") and holdings_df.empty):
            handler._send_json({
                "ok": True,
                "code": code,
                "available": False,
                "error": "该基金暂无持仓数据（部分基金不披露/接口无返回）",
                "mode": "none",
            }, 200)
            return

        stocks = []
        if hasattr(holdings_df, "columns"):
            import pandas as pd
            df = holdings_df
            ratio_col = "占净值比例" if "占净值比例" in df.columns else None
            work = df.copy()
            if ratio_col:
                work[ratio_col] = pd.to_numeric(work[ratio_col], errors="coerce")
                work = work.sort_values(ratio_col, ascending=False)
            for _, row in work.head(10).iterrows():
                def _num(col):
                    v = row.get(col)
                    try:
                        if v is None or (hasattr(v, "items") and v != v):
                            return None
                        f = float(v)
                        return None if f != f else f
                    except (TypeError, ValueError):
                        return None
                stocks.append({
                    "name": str(row.get("股票名称", "")),
                    "code": str(row.get("股票代码", "")),
                    "ratio": _num("占净值比例"),
                    "value": _num("持仓市值"),
                    "shares": _num("持股数"),
                })

        analysis = {}
        if domain._analyzer is not None:
            try:
                analysis = domain._analyzer.analyze_holdings(holdings_df)
            except Exception as e:
                log(f"[fund-holdings] 分析失败: {e}")
        if not isinstance(analysis, dict) or "error" in analysis:
            analysis = {}
        industry = analysis.get("行业分布", {})

        mode = domain._data_mode.get(code, "unknown")
        handler._send_json({
            "ok": True,
            "code": code,
            "available": True,
            "mode": mode,
            "name": cache.get("info", {}).get("基金名称") or code,
            "industry": industry,
            "concentration": {
                "top10_ratio": analysis.get("十大重仓占比"),
                "top1_ratio": analysis.get("第一大重仓占比"),
                "hhi": analysis.get("持仓集中度(HHI)"),
                "stock_count": analysis.get("持股数量"),
                "style": analysis.get("风格倾向"),
                "level": analysis.get("集中度评价"),
            },
            "stocks": stocks,
        }, 200)
    except Exception as e:
        log(f"[fund-holdings] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def _get_portfolio_manager():
    try:
        from domains.fund.fund_data_manager import FundDataManager
        return FundDataManager()
    except Exception as e:
        log(f"[fund] FundDataManager 初始化失败: {e}")
        return None


def handle_portfolio_list(handler, parsed):
    """GET /api/fund/portfolio — 获取个人持仓列表"""
    mgr = _get_portfolio_manager()
    if mgr is None:
        handler._send_json({"ok": False, "error": "持仓管理器不可用"}, 503)
        return
    try:
        holdings = mgr.get_holdings()
        summary = mgr.get_portfolio_summary()
        handler._send_json({"ok": True, "holdings": holdings, "summary": summary}, 200)
    except Exception as e:
        log(f"[fund-portfolio] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_portfolio_add(handler, parsed):
    """POST /api/fund/portfolio/add — 添加持仓"""
    params = _parse_params(handler, parsed)
    mgr = _get_portfolio_manager()
    if mgr is None:
        handler._send_json({"ok": False, "error": "持仓管理器不可用"}, 503)
        return
    code = params.get("code", "").strip()
    if not code:
        handler._send_json({"ok": False, "error": "基金代码不能为空"}, 400)
        return
    try:
        holding = {
            "code": code,
            "name": params.get("name", code),
            "shares": _to_float(params.get("shares"), 0),
            "cost": _to_float(params.get("cost"), 0),
            "type": params.get("type", "混合型"),
        }
        ok = mgr.add_holding(holding)
        handler._send_json({"ok": ok, "message": "添加成功" if ok else "添加失败"}, 200)
    except Exception as e:
        log(f"[fund-portfolio-add] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_portfolio_update(handler, parsed):
    """POST /api/fund/portfolio/update — 更新持仓"""
    params = _parse_params(handler, parsed)
    mgr = _get_portfolio_manager()
    if mgr is None:
        handler._send_json({"ok": False, "error": "持仓管理器不可用"}, 503)
        return
    code = params.get("code", "").strip()
    if not code:
        handler._send_json({"ok": False, "error": "基金代码不能为空"}, 400)
        return
    try:
        kwargs = {k: params[k] for k in ("name", "shares", "cost", "type") if k in params}
        ok = mgr.update_holding(code, **kwargs)
        handler._send_json({"ok": ok, "message": "更新成功" if ok else "更新失败"}, 200)
    except Exception as e:
        log(f"[fund-portfolio-update] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_portfolio_remove(handler, parsed):
    """POST /api/fund/portfolio/remove — 删除持仓"""
    params = _parse_params(handler, parsed)
    mgr = _get_portfolio_manager()
    if mgr is None:
        handler._send_json({"ok": False, "error": "持仓管理器不可用"}, 503)
        return
    code = params.get("code", "").strip()
    if not code:
        handler._send_json({"ok": False, "error": "基金代码不能为空"}, 400)
        return
    try:
        ok = mgr.remove_holding(code)
        handler._send_json({"ok": ok, "message": "删除成功" if ok else "删除失败"}, 200)
    except Exception as e:
        log(f"[fund-portfolio-remove] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


# ---------------------------------------------------------------------------
# 基金外围风险档案（经理变更 / 规模清盘 / 限购额度）— JS-20260921-01
#
# 领域层 domains/fund/fund_profile_risk.py 早已实现，日报也在用，但 Web 层
# 一直取不到：这是「数据有了、界面看不见」的典型断点。
#
# 两条硬约束（合规 + 体验）：
#   ① **默认只读缓存、绝不联网**——Web 请求必须秒回，且免费公开源严禁高频抓取；
#      只有显式 refresh=1 才走网络。
#   ② **取不到就标 unavailable，绝不编造**——与全项目"暂缺就写暂缺"的诚实口径一致。
# ---------------------------------------------------------------------------

# 档位排序：聚合时取三者中最严重的那个
_LEVEL_ORDER = {"danger": 4, "warn": 3, "notice": 2, "safe": 1, "info": 1, "unknown": 0}


def _load_monitor_config():
    """读监控配置（code → name/manager/investment）。

    唯一真源是 scripts/daily_fund_monitor.py 的 FUND_CONFIG（8 只基金的日投额与
    配置经理名都在这里）。读不到就返回空 dict —— 调用方会退化为"只有代码、无配置"，
    此时经理不符类提示不产生（没有配置就无从比对），但绝不影响其它两项评估。
    """
    try:
        import importlib
        mod = importlib.import_module("scripts.daily_fund_monitor")
        cfg = {}
        for f in getattr(mod, "FUND_CONFIG", []) or []:
            code = str(f.get("code", "")).strip()
            if code:
                cfg[code] = f
        return cfg
    except Exception as e:
        log(f"[fund-profile] 读取监控配置失败（退化为无配置）: {e}")
        return {}


def _default_profile_codes(config):
    """未指定 codes 时的默认清单：监控配置里的基金（保序）"""
    return list(config.keys())


def _worst_level(levels):
    """取最严重档位。info 与 safe 同义（都是"没事"），统一归一成 safe——
    否则汇总里会多出一个 info 桶，前端的"正常"计数就漏了（实测踩到）。"""
    best = "unknown"
    for lv in levels:
        norm = "safe" if lv == "info" else lv
        if _LEVEL_ORDER.get(norm, 0) > _LEVEL_ORDER.get(best, 0):
            best = norm
    return "safe" if best == "info" else best


def handle_profile(handler, parsed):
    """GET/POST /api/fund/profile — 基金外围风险档案（经理变更 / 规模清盘 / 限购额度）

    参数:
      codes   : 逗号分隔的基金代码；缺省 = 监控配置里的全部基金
      refresh : '1' 才强制联网重抓（慢，串行限速）；默认只读缓存

    返回:
      {ok, count, summary:{danger,warn,notice,safe,unknown,stale,unavailable},
       profiles:[{code, name, manager, scale, limit, limit_change,
                  level, stale, unavailable, fetched_at}]}
    """
    params = _parse_params(handler, parsed)
    config = _load_monitor_config()
    codes = _parse_codes(params.get("codes")) or _default_profile_codes(config)
    if not codes:
        handler._send_json({
            "ok": False, "error": "未指定基金代码，且未能读到监控配置",
            "hint": "用 ?codes=005698,270042 指定，或先配置 scripts/daily_fund_monitor.py 的 FUND_CONFIG",
        }, 400)
        return

    refresh = str(params.get("refresh", "")).strip().lower() in ("1", "true", "yes")
    if refresh:
        log(f"[fund-profile] refresh=1，将联网重抓 {len(codes)} 只（串行限速）")

    try:
        from domains.fund.fund_profile_risk import FundProfileFetcher
    except Exception as e:
        log(f"[fund-profile] 领域模块不可用: {e}")
        handler._send_json({"ok": False, "error": "基金外围风险模块不可用"}, 503)
        return

    try:
        # enabled=False ⇒ _http_get 直接返回 None，即"只走缓存"；
        # 缓存过期时会返回带 stale=True 的旧数据（诚实标注），不会静默假装新鲜。
        fetcher = FundProfileFetcher(delay=0.6, enabled=bool(refresh))
    except Exception as e:
        log(f"[fund-profile] 采集器初始化失败: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)
        return

    profiles = []
    summary = {"danger": 0, "warn": 0, "notice": 0, "safe": 0,
               "unknown": 0, "stale": 0, "unavailable": 0}
    for code in codes:
        cfg = config.get(code, {})
        try:
            prof = fetcher.get_profile(
                code,
                cfg.get("manager"),
                plan_investment_monthly=cfg.get("investment", 3000),
                use_cache=not refresh,
            )
        except Exception as e:
            log(f"[fund-profile] {code} 采集异常: {e}")
            profiles.append({
                "code": code, "name": cfg.get("name", code),
                "level": "unknown", "stale": False, "unavailable": True,
                "error": str(e),
            })
            summary["unknown"] += 1
            summary["unavailable"] += 1
            continue

        manager = prof.get("manager") or {}
        scale = prof.get("scale") or {}
        limit = prof.get("limit") or {}
        unavailable = not bool(manager.get("ok") or scale.get("ok"))
        level = _worst_level([manager.get("level", "unknown"),
                              scale.get("level", "unknown"),
                              limit.get("level", "unknown")])
        if unavailable:
            level = "unknown"
        stale = bool(prof.get("stale"))
        profiles.append({
            "code": code,
            "name": cfg.get("name") or code,
            "manager": manager,
            "scale": scale,
            "limit": limit,
            "limit_change": prof.get("limit_change", "same"),
            "level": level,
            "stale": stale,
            "unavailable": unavailable,
            "fetched_at": prof.get("fetched_at", ""),
        })
        summary[level] = summary.get(level, 0) + 1
        if stale:
            summary["stale"] += 1
        if unavailable:
            summary["unavailable"] += 1

    handler._send_json({
        "ok": True,
        "count": len(profiles),
        "refresh": refresh,
        "cache_only": not refresh,
        "source_note": "数据来源：天天基金公开页面（低速抓取、只标来源不改写）；"
                       "默认读本地缓存，refresh=1 才联网",
        "summary": summary,
        "profiles": profiles,
    }, 200)
