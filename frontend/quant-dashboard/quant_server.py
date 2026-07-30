# -*- coding: utf-8 -*-
"""金水谣 · 量化仪表盘 本地服务（零依赖，仅标准库）

职责：
  1) 托管仪表盘静态文件（index.html / styles.css / app.js / vendor / data）
  2) 暴露 /api/stock/<sym> 直接读取金水谣真实日线 金水谣数据/stock/cache/<sym>_daily.json
     → 与前端同源，无 CORS；前端失败自动回退 data/real_stock.json 静态快照

运行：python quant_server.py [--port 8891]
"""
import argparse
import json
import os
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIRS = [
    os.path.normpath(os.path.join(HERE, "..", "..", "金水谣数据", "stock", "cache")),
    os.path.normpath(os.path.join(HERE, "..", "金水谣数据", "stock", "cache")),
]
SYMBOL_NAMES = {
    "sh000001": "上证指数",
    "sh000300": "沪深300",
    "sz399001": "深证成指",
}
ALLOWED = set(SYMBOL_NAMES.keys())

# 知识库（金水谣 MiroFish）：用于事件推演上下文注入
KNOWLEDGE_PATHS = [
    os.path.normpath(os.path.join(HERE, "..", "knowledge", "mirofish_db.json")),
    os.path.normpath(os.path.join(HERE, "..", "..", "Jinshuiyao_Fixed", "knowledge", "mirofish_db.json")),
]


def find_knowledge():
    for p in KNOWLEDGE_PATHS:
        if os.path.exists(p):
            return p
    return None


def find_cache(sym):
    """定位真实日线缓存文件（金水谣数据/stock/cache/<sym>_daily.json）。"""
    for d in CACHE_DIRS:
        p = os.path.join(d, f"{sym}_daily.json")
        if os.path.exists(p):
            return p
    return None


def load_knowledge():
    p = find_knowledge()
    if not p:
        return []
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return []
    if isinstance(d, list):
        return d
    return d.get("cards") or d.get("data") or []


def search_knowledge(query, limit=6):
    """按词项匹配标题/内容/标签/域/钩子，返回相关度最高的若干卡。"""
    cards = load_knowledge()
    if not cards:
        return []
    q = (query or "").strip().lower()
    # 默认聚焦股票/板块/事件语境
    tokens = [t for t in (q.split() if q else ["板块", "stock", "量化", "事件"]) if t]
    scored = []
    for c in cards:
        title = str(c.get("title", ""))
        content = str(c.get("content", ""))
        tags = c.get("tags")
        tags = tags if isinstance(tags, str) else " ".join(tags) if isinstance(tags, list) else ""
        hay = (title + " " + content + " " + str(tags) + " " + str(c.get("domain", "")) + " " + str(c.get("engine_hook", ""))).lower()
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
        out.append({
            "title": c.get("title"),
            "content": str(c.get("content", ""))[:400],
            "tags": c.get("tags"),
            "domain": c.get("domain"),
            "category": c.get("category"),
            "engine_hook": c.get("engine_hook"),
        })
    return out


def upsert_knowledge(card):
    """事件推演结论回写金水谣知识库：按 title 幂等 upsert。"""
    p = find_knowledge()
    if not p:
        return {"error": "knowledge file not found"}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"error": "read failed: " + str(e)}
    if not isinstance(data, dict) or "cards" not in data:
        return {"error": "cards node missing in knowledge json"}
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
        newc = {
            "id": "evt_" + datetime.now().strftime("%Y%m%d%H%M%S%f")[:17],
            "title": title,
            "content": card.get("content", ""),
            "category": card.get("category", "deduction"),
            "domain": card.get("domain", "stock"),
            "tags": card.get("tags", []),
            "source": card.get("source", "dashboard"),
            "engine_hook": card.get("engine_hook", "event_deduction"),
            "priority": int(card.get("priority", 5)),
            "effectiveness": 0,
            "use_count": 1,
            "last_used": now,
            "created": now,
            "updated": now,
            "subsystem": card.get("subsystem", "stock"),
        }
        cards.append(newc)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return {"error": "write failed: " + str(e)}
    return {"ok": True, "title": title, "total": len(cards), "upserted": True}


def build_stock_payload(sym):
    path = find_cache(sym)
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
        "latest": {
            "date": latest.get("date"), "open": latest.get("open"),
            "high": latest.get("high"), "low": latest.get("low"),
            "close": latest.get("close"), "volume": latest.get("volume"),
        },
        "prev": {"date": prev.get("date"), "close": prev.get("close")},
        "change_pct": change_pct,
        "daily": daily,
        "live": True,
        "served_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if not isinstance(body, bytes):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path):
        # 防目录穿越
        rel = os.path.normpath(path).lstrip("/\\")
        full = os.path.join(HERE, rel)
        if not full.startswith(HERE) or not os.path.isfile(full):
            self._send(404, {"error": "not found"})
            return
        ctype = "text/html; charset=utf-8"
        if full.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif full.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif full.endswith(".json"):
            ctype = "application/json; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/" or route == "/index.html":
            self._serve_static("index.html")
            return
        m = re.match(r"^/api/stock/([\w]+)$", route)
        if m:
            sym = m.group(1)
            if sym not in ALLOWED:
                self._send(400, {"error": "unsupported symbol", "allowed": list(ALLOWED)})
                return
            payload = build_stock_payload(sym)
            if payload is None:
                self._send(404, {"error": "no cache data", "symbol": sym})
                return
            self._send(200, payload)
            return
        # 知识库检索（事件推演上下文注入）
        if route == "/api/knowledge" or route.startswith("/api/knowledge?"):
            qs = parse_qs(parsed.query)
            q = (qs.get("q") or ["板块 stock 量化 事件"])[0]
            limit = int((qs.get("limit") or ["6"])[0])
            cards = search_knowledge(q, limit)
            self._send(200, {"query": q, "count": len(cards), "cards": cards})
            return
        # 静态资源
        self._serve_static(route)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/knowledge":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception as e:
                self._send(400, {"error": "bad body: " + str(e)})
                return
            res = upsert_knowledge(body)
            self._send(200 if "ok" in res else 400, res)
            return
        self._send(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # 静默


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8891)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"金水谣量化仪表盘 → http://{args.host}:{args.port}/")
    print(f"真实数据目录: {CACHE_DIRS[0]}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
