# -*- coding: utf-8 -*-
"""金水谣系统 - 量化扫描 API 路由处理

将独立 quant_server.py 的功能集成到主服务器。
"""
import json, os, re
from datetime import datetime
from ..utils import log

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIRS = [
    os.path.join(HERE, "stockcache"),
    os.path.join(HERE, "金水谣数据", "stock", "cache"),
]
KNOWLEDGE_PATHS = [
    os.path.join(HERE, "knowledge", "mirofish_db.json"),
]
SYMBOL_NAMES = {
    "sh000001": "上证指数", "sh000300": "沪深300", "sz399001": "深证成指",
    "sh000688": "科创50", "sz399006": "创业板指", "sh000016": "上证50",
    "sh000905": "中证500", "sh000852": "中证1000",
}


def _ensure_utf8(body):
    return body.encode("utf-8") if isinstance(body, str) else body


def _find_cache(sym):
    for d in CACHE_DIRS:
        p = os.path.join(d, f"{sym}_daily.json")
        if os.path.exists(p):
            return p
    return None


def _build_stock_payload(sym):
    path = _find_cache(sym)
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            series = json.load(f)
    except Exception:
        return None
    if not isinstance(series, list) or len(series) < 2:
        return None
    latest = series[-1]
    prev = series[-2]
    daily = series[-120:]
    change_pct = round((latest["close"] - prev["close"]) / prev["close"] * 100, 3)
    return {
        "symbol": sym,
        "name": SYMBOL_NAMES.get(sym, sym),
        "latest": {"date": latest.get("date"), "open": latest.get("open"),
                   "high": latest.get("high"), "low": latest.get("low"),
                   "close": latest.get("close"), "volume": latest.get("volume")},
        "prev": {"date": prev.get("date"), "close": prev.get("close")},
        "change_pct": change_pct,
        "daily": daily,
        "live": True,
        "served_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _load_knowledge():
    for p in KNOWLEDGE_PATHS:
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                return d if isinstance(d, list) else d.get("cards") or d.get("data") or []
            except Exception:
                return []
    return []


def _search_knowledge(query, limit=6):
    cards = _load_knowledge()
    if not cards:
        return []
    q = (query or "").strip().lower()
    tokens = [t for t in (q.split() if q else ["板块", "stock", "量化", "事件"]) if t]
    scored = []
    for c in cards:
        title = str(c.get("title", ""))
        content = str(c.get("content", ""))
        tags = c.get("tags")
        tags = tags if isinstance(tags, str) else " ".join(tags) if isinstance(tags, list) else ""
        hay = (title + " " + content + " " + tags + " " +
               str(c.get("domain", "")) + " " + str(c.get("engine_hook", ""))).lower()
        hit = sum(1 for t in tokens if t in hay)
        if hit == 0:
            continue
        try:
            pri = int(c.get("priority", 0))
        except Exception:
            pri = 0
        try:
            uc = int(c.get("use_count", 0))
        except Exception:
            uc = 0
        scored.append((hit, pri, uc, c))
    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    out = []
    for _, _, _, c in scored[:limit]:
        out.append({"title": c.get("title"), "content": str(c.get("content", ""))[:400],
                    "tags": c.get("tags"), "domain": c.get("domain"),
                    "category": c.get("category"), "engine_hook": c.get("engine_hook")})
    return out


def _upsert_knowledge(card):
    for p in KNOWLEDGE_PATHS:
        if os.path.exists(p):
            break
    else:
        return {"error": "knowledge file not found"}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"error": "read failed: " + str(e)}
    if not isinstance(data, dict) or "cards" not in data:
        return {"error": "cards node missing"}
    cards = data["cards"]
    title = (card.get("title") or "").strip()
    if not title:
        return {"error": "title required"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for c in cards:
        if (c.get("title") or "").strip() == title:
            c["content"] = card.get("content", c.get("content"))
            c["use_count"] = int(c.get("use_count", 0)) + 1
            c["updated"] = now
            if card.get("tags"):
                c["tags"] = card["tags"]
            break
    else:
        cards.append({"id": "evt_" + datetime.now().strftime("%Y%m%d%H%M%S%f")[:17],
                      "title": title, "content": card.get("content", ""),
                      "category": card.get("category", "deduction"),
                      "domain": card.get("domain", "stock"),
                      "tags": card.get("tags", []),
                      "source": card.get("source", "dashboard"),
                      "engine_hook": card.get("engine_hook", "event_deduction"),
                      "priority": int(card.get("priority", 5)),
                      "effectiveness": 0, "use_count": 1, "last_used": now,
                      "created": now, "updated": now,
                      "subsystem": card.get("subsystem", "stock")})
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return {"error": "write failed: " + str(e)}
    return {"ok": True, "title": title, "total": len(cards), "upserted": True}


def handle_stock(handler, parsed):
    """GET /api/quant/stock/<sym> — 量化扫描用股票日线数据"""
    m = re.match(r"^/api/quant/stock/([\w]+)$", parsed.path)
    if not m:
        handler._send_json({"error": "bad path"}, 400)
        return
    sym = m.group(1)
    payload = _build_stock_payload(sym)
    if payload is None:
        handler._send_json({"error": "no cache data", "symbol": sym}, 404)
        return
    handler._send_json(payload, 200)


def handle_knowledge_search(handler, parsed):
    """GET /api/quant/knowledge/search — 知识库检索（量化事件推演上下文注入）"""
    from urllib.parse import parse_qs
    qs = parse_qs(parsed.query)
    q = (qs.get("q") or ["板块 stock 量化 事件"])[0]
    limit = int((qs.get("limit") or ["6"])[0])
    cards = _search_knowledge(q, limit)
    handler._send_json({"query": q, "count": len(cards), "cards": cards}, 200)


def handle_knowledge_upsert(handler, parsed):
    """POST /api/quant/knowledge — upsert 知识卡片（事件推演结论回写）"""
    try:
        cl = int(handler.headers.get("Content-Length", 0) or 0)
        raw = handler.rfile.read(cl).decode("utf-8", errors="replace") if cl else "{}"
        body = json.loads(raw)
    except Exception as e:
        handler._send_json({"error": "bad body: " + str(e)}, 400)
        return
    res = _upsert_knowledge(body)
    handler._send_json(res, 200 if "ok" in res else 400)
