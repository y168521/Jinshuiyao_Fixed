# -*- coding: utf-8 -*-
"""金水谣系统 - 足彩子系统 API 路由处理"""
import json
import urllib.parse
import os

from ..utils import log

_football_domain = None


def get_football_domain():
    global _football_domain
    if _football_domain is None:
        try:
            from domains.football.domain import FootballDomain
            d = FootballDomain()
            d.setup()
            _football_domain = d
        except Exception as e:
            log(f"[football] FootballDomain 初始化失败: {e}")
    return _football_domain


def _parse_params(handler, parsed):
    params = {}
    try:
        qs = urllib.parse.parse_qs(parsed.query)
        for k, v in qs.items():
            params[k] = v[0] if len(v) == 1 else v
    except Exception as e:
        log(f"[football] 解析 query 失败: {e}")
    cl = int(handler.headers.get("Content-Length", 0) or 0)
    if cl > 0:
        try:
            raw = handler.rfile.read(cl).decode("utf-8", errors="replace")
            if raw:
                body = json.loads(raw)
                if isinstance(body, dict):
                    params.update(body)
        except Exception as e:
            log(f"[football] 解析 POST body 失败: {e}")
    return params


def _load_matches():
    """读取真实赛事缓存：金水谣数据/football_matches.json（体彩官方竞彩抓取）"""
    try:
        json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                 '金水谣数据', 'football_matches.json')
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            matches = payload.get('matches', [])
            if matches:
                return matches, payload.get('fetched_at', ''), payload.get('source', '')
    except Exception as e:
        log(f"[football] 读取赛事缓存失败: {e}")
    return None, '', ''


def _refresh_matches():
    """联网刷新真实赛事（体彩官方竞彩 API 主源 + 500.com 兜底）"""
    from domains.football.fetcher import fetch_matches
    return fetch_matches(force_refresh=True)


def handle_status(handler, parsed):
    """GET/POST /api/football/status — 足彩子系统健康状态"""
    domain = get_football_domain()
    st = {"domain_ready": domain is not None, "csv_data": False, "engine_ready": False}
    try:
        if domain:
            st = domain.status()
        matches, fetched_at, source = _load_matches()
        st["csv_data"] = matches is not None and len(matches) > 0
        st["csv_count"] = len(matches) if matches else 0
        st["fetched_at"] = fetched_at
        st["source"] = source
        try:
            from jinshuiyao.models.poisson_model import PoissonModel
            st["engine_ready"] = True
        except Exception:
            st["engine_ready"] = False
        handler._send_json({"ok": True, "status": st}, 200)
    except Exception as e:
        log(f"[football-status] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_matches(handler, parsed):
    """GET/POST /api/football/matches — 获取比赛列表（真实数据）；force_refresh=1 时联网更新"""
    params = _parse_params(handler, parsed)
    league = params.get("league", "").strip()
    limit = int(params.get("limit", 50))
    force = str(params.get("force_refresh", "")).lower() in ("1", "true", "yes")
    try:
        if force:
            try:
                _refresh_matches()
            except Exception as e:
                log(f"[football-matches] 联网刷新失败，使用缓存: {e}")
        matches, fetched_at, source = _load_matches()
        if matches is None:
            handler._send_json({"ok": False, "error": "暂无赛事数据，请先刷新（体彩官方竞彩接口）"}, 404)
            return
        if league:
            matches = [m for m in matches if league.lower() in (m.get('league', '') + m.get('competition', '')).lower()]
        matches = matches[:limit]
        handler._send_json({"ok": True, "matches": matches, "count": len(matches),
                            "fetched_at": fetched_at, "source": source}, 200)
    except Exception as e:
        log(f"[football-matches] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_predict(handler, parsed):
    """GET/POST /api/football/predict — 比赛预测（使用真实 ML Pipeline）"""
    params = _parse_params(handler, parsed)
    home = params.get("home", "").strip()
    away = params.get("away", "").strip()
    bankroll = float(params.get("bankroll", 1000.0))
    try:
        domain = get_football_domain()
        if domain:
            result = domain.generate({"home": home, "away": away, "bankroll": bankroll})
        else:
            result = {}

        # 构造标准响应
        if result and result.get('status') == 'completed' and result.get('predictions'):
            pred = result['predictions'][0]
            prediction = {
                "home": home or "主队",
                "away": away or "客队",
                "home_prob": round(result['model_prob'].get('win', 0.333) * 100, 1),
                "draw_prob": round(result['model_prob'].get('draw', 0.333) * 100, 1),
                "away_prob": round(result['model_prob'].get('lose', 0.333) * 100, 1),
                "recommendation": pred.get('recommendation', '—'),
                "confidence": pred.get('confidence', '中'),
                "score_paths": result.get('score_paths', []),
                "expected_goals": result.get('expected_goals', {}),
                "market_margin": result.get('market_margin', 0),
                "ev": pred.get('ev', 0),
                "suggested_stake": pred.get('suggested_stake', 0),
                "tier": pred.get('tier', 'medium'),
            }
        else:
            prediction = {
                "home": home or "主队",
                "away": away or "客队",
                "home_prob": 33.3, "draw_prob": 33.3, "away_prob": 33.3,
                "recommendation": "数据不足", "confidence": "低",
                "score_paths": [],
                "expected_goals": {},
            }

        handler._send_json({"ok": True, "prediction": prediction}, 200)
    except Exception as e:
        log(f"[football-predict] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)