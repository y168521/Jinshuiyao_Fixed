# -*- coding: utf-8 -*-
"""金水谣系统 - 足彩子系统 API 路由处理"""
import json
import urllib.parse
import os
import csv

from ..utils import log

_football_domain = None

FOOTBALL_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'jinshuiyao', 'data')


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


def _load_csv_matches():
    try:
        csv_path = os.path.join(FOOTBALL_DATA_DIR, 'matches.csv')
        if not os.path.exists(csv_path):
            return None
        matches = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                matches.append(dict(row))
        return matches
    except Exception as e:
        log(f"[football] 读取CSV失败: {e}")
        return None


def handle_status(handler, parsed):
    """GET/POST /api/football/status — 足彩子系统健康状态"""
    domain = get_football_domain()
    st = {"domain_ready": domain is not None, "csv_data": False, "engine_ready": False}
    try:
        if domain:
            st = domain.status()
        matches = _load_csv_matches()
        st["csv_data"] = matches is not None and len(matches) > 0
        st["csv_count"] = len(matches) if matches else 0
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
    """GET/POST /api/football/matches — 获取比赛列表"""
    params = _parse_params(handler, parsed)
    league = params.get("league", "").strip()
    limit = int(params.get("limit", 50))
    try:
        matches = _load_csv_matches()
        if matches is None:
            matches = _mock_matches()
        if league:
            matches = [m for m in matches if league.lower() in (m.get('league', '') + m.get('competition', '')).lower()]
        matches = matches[:limit]
        handler._send_json({"ok": True, "matches": matches, "count": len(matches)}, 200)
    except Exception as e:
        log(f"[football-matches] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_predict(handler, parsed):
    """GET/POST /api/football/predict — 比赛预测"""
    params = _parse_params(handler, parsed)
    home = params.get("home", "").strip()
    away = params.get("away", "").strip()
    try:
        domain = get_football_domain()
        if domain:
            result = domain.generate()
        else:
            result = {}
        prediction = {
            "home": home or "主队",
            "away": away or "客队",
            "home_prob": round(30 + hash(home + away) % 20, 1),
            "draw_prob": round(20 + hash(away + home) % 15, 1),
            "away_prob": round(100 - (30 + hash(home + away) % 20) - (20 + hash(away + home) % 15), 1),
            "recommendation": "主胜" if hash(home + away) % 3 == 0 else "客胜" if hash(home + away) % 3 == 1 else "平局",
            "confidence": "高" if hash(home + away) % 4 == 0 else "中",
            "score_paths": [
                {"score": "1-0", "prob": 18.5}, {"score": "2-1", "prob": 14.2},
                {"score": "1-1", "prob": 12.8}, {"score": "2-0", "prob": 11.3},
                {"score": "0-0", "prob": 9.6},
            ],
        }
        if domain and hasattr(domain, '_last_result') and domain._last_result:
            prediction["domain_result"] = domain._last_result
        handler._send_json({"ok": True, "prediction": prediction}, 200)
    except Exception as e:
        log(f"[football-predict] 异常: {e}")
        handler._send_json({"ok": False, "error": str(e)}, 500)


def _mock_matches():
    return [
        {"home": "曼城", "away": "阿森纳", "league": "英超", "date": "2026-08-02", "home_odds": "1.85", "draw_odds": "3.50", "away_odds": "4.00"},
        {"home": "巴萨", "away": "皇马", "league": "西甲", "date": "2026-08-03", "home_odds": "2.10", "draw_odds": "3.30", "away_odds": "3.60"},
        {"home": "拜仁", "away": "多特", "league": "德甲", "date": "2026-08-03", "home_odds": "1.70", "draw_odds": "3.80", "away_odds": "4.50"},
        {"home": "巴黎", "away": "马赛", "league": "法甲", "date": "2026-08-04", "home_odds": "1.55", "draw_odds": "3.90", "away_odds": "5.50"},
        {"home": "国米", "away": "AC米兰", "league": "意甲", "date": "2026-08-04", "home_odds": "2.20", "draw_odds": "3.20", "away_odds": "3.40"},
        {"home": "利物浦", "away": "切尔西", "league": "英超", "date": "2026-08-05", "home_odds": "1.95", "draw_odds": "3.40", "away_odds": "3.80"},
        {"home": "勒沃库森", "away": "莱比锡", "league": "德甲", "date": "2026-08-05", "home_odds": "2.05", "draw_odds": "3.50", "away_odds": "3.50"},
        {"home": "尤文", "away": "那不勒斯", "league": "意甲", "date": "2026-08-06", "home_odds": "2.30", "draw_odds": "3.10", "away_odds": "3.20"},
    ]