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
