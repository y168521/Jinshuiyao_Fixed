# -*- coding: utf-8 -*-
"""【道衍推导·P1-G6】统一遥测槽

阳 = 全量采集（可观测）；阴 = 异步落盘（不阻塞主链路）。
天 = 结构外部化（字段固定）；地 = 隔离（仅追加写 jsonl，不读业务状态）；人 = 复盘（/api/telemetry 可查）。
知止：只追加、带锁、异常静默，绝不因遥测失败影响主流程。

每次 LLM 调用结束即记一条：ts / provider / model / in_tokens / out_tokens / cost_yuan / latency_ms。
汇聚后可算免费占比、付费花费、P95 时延、错误率——这正是「自动驾驶式省钱」的量化看板底座。
"""
import os
import json
import time
import threading

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATH = os.path.join(_PROJECT_ROOT, "金水谣数据", "telemetry.jsonl")
_lock = threading.Lock()


def record(**fields):
    """追加一条遥测记录（异常静默，绝不抛错影响主链路）。"""
    try:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")}
        rec.update(fields)
        line = json.dumps(rec, ensure_ascii=False)
        with _lock:
            with open(_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def recent(n=200):
    """返回最近 n 条遥测记录（供 /api/telemetry 查询）。"""
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        out = []
        for ln in lines[-n:]:
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
        return out
    except FileNotFoundError:
        return []


def summary(n=500):
    """聚合最近 n 条：免费/付费调用数、估算花费、平均/P95 时延。"""
    evs = recent(n)
    if not evs:
        return {"count": 0}
    paid = [e for e in evs if (e.get("cost_yuan") or 0) > 0]
    lats = sorted(e.get("latency_ms", 0) for e in evs if e.get("latency_ms") is not None)
    avg_lat = sum(lats) / len(lats) if lats else 0
    p95_lat = lats[int(len(lats) * 0.95) - 1] if lats else 0
    total_cost = sum(e.get("cost_yuan", 0) or 0 for e in evs)
    return {
        "count": len(evs),
        "paid_calls": len(paid),
        "free_calls": len(evs) - len(paid),
        "free_ratio": round((len(evs) - len(paid)) / len(evs), 3),
        "total_cost_yuan": round(total_cost, 4),
        "avg_latency_ms": round(avg_lat, 1),
        "p95_latency_ms": round(p95_lat, 1),
    }


def dashboard(days=14, max_events=3000):
    """用量看板聚合（W63补99 / JS-20260816-04）：
    返回 按日趋势 / 按供应商 / 按模型 / 总量 四维数据，供 /api/telemetry/dashboard。
    纯函数、只读、异常静默——遥测失败绝不影响调用方。
    """
    try:
        evs = recent(max_events)
        if not evs:
            return {"ok": True, "empty": True, "daily": [], "providers": [],
                    "models": [], "totals": {"count": 0, "free_calls": 0,
                                             "paid_calls": 0, "cost_yuan": 0.0}}
        day_tok = {}
        day_cnt = {}
        day_cost = {}
        prov = {}
        mods = {}
        tot_cost = 0.0
        paid_calls = 0
        for e in evs:
            d = (e.get("ts") or "")[:10]
            day_cnt[d] = day_cnt.get(d, 0) + 1
            day_tok[d] = day_tok.get(d, 0) + int(e.get("in_tokens", 0) or 0) + int(e.get("out_tokens", 0) or 0)
            c = float(e.get("cost_yuan", 0) or 0)
            day_cost[d] = day_cost.get(d, 0) + c
            tot_cost += c
            if c > 0:
                paid_calls += 1
            p = e.get("provider") or "unknown"
            pv = prov.setdefault(p, {"provider": p, "calls": 0, "cost_yuan": 0.0, "tokens": 0})
            pv["calls"] += 1
            pv["cost_yuan"] = round(pv["cost_yuan"] + c, 4)
            pv["tokens"] += int(e.get("in_tokens", 0) or 0) + int(e.get("out_tokens", 0) or 0)
            m = e.get("model") or "unknown"
            mv = mods.setdefault(m, {"model": m, "calls": 0, "cost_yuan": 0.0, "latency_total": 0.0, "latency_n": 0})
            mv["calls"] += 1
            mv["cost_yuan"] = round(mv["cost_yuan"] + c, 4)
            lat = e.get("latency_ms")
            if lat is not None:
                mv["latency_total"] += float(lat)
                mv["latency_n"] += 1
        daily = []
        for d in sorted(day_cnt)[-days:]:
            daily.append({"date": d, "calls": day_cnt[d], "tokens": day_tok[d],
                          "cost_yuan": round(day_cost.get(d, 0), 4)})
        for m in mods.values():
            if m["latency_n"]:
                m["avg_latency_ms"] = round(m["latency_total"] / m["latency_n"], 1)
            m.pop("latency_total", None)
            m.pop("latency_n", None)
        return {
            "ok": True,
            "empty": False,
            "days": len(daily),
            "daily": daily,
            "providers": sorted(prov.values(), key=lambda x: -x["calls"]),
            "models": sorted(mods.values(), key=lambda x: -x["calls"])[:12],
            "totals": {
                "count": len(evs),
                "free_calls": len(evs) - paid_calls,
                "paid_calls": paid_calls,
                "free_ratio": round((len(evs) - paid_calls) / len(evs), 3) if evs else 0,
                "cost_yuan": round(tot_cost, 4),
            },
        }
    except Exception:
        return {"ok": False, "error": "遥测聚合失败", "daily": [], "providers": [], "models": [],
                "totals": {"count": 0, "free_calls": 0, "paid_calls": 0, "cost_yuan": 0.0}}
