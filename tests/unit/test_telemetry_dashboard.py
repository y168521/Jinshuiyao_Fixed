# -*- coding: utf-8 -*-
"""JS-20260816-04 · telemetry.dashboard 用量看板聚合测试

验证 core/telemetry.dashboard 对 jsonl 遥测数据的四维聚合：
按日趋势 / 按供应商 / 按模型 / 总量，纯函数零网络依赖。
"""
import json


def _write_telemetry(tmp_path, monkeypatch, rows):
    log = tmp_path / "telemetry_test.jsonl"
    with open(log, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    monkeypatch.setattr("core.telemetry._PATH", str(log))
    from core.telemetry import dashboard
    return dashboard()


def test_dashboard_empty(tmp_path, monkeypatch):
    d = _write_telemetry(tmp_path, monkeypatch, [])
    assert d["ok"] is True
    assert d["empty"] is True
    assert d["totals"]["count"] == 0


def test_dashboard_aggregates(tmp_path, monkeypatch):
    rows = [
        {"ts": "2026-08-15T10:00:00+08:00", "provider": "zhipu", "model": "glm-4.5-air",
         "in_tokens": 100, "out_tokens": 50, "cost_yuan": 0.0, "latency_ms": 120.0},
        {"ts": "2026-08-15T11:00:00+08:00", "provider": "zhipu", "model": "glm-4.5-air",
         "in_tokens": 200, "out_tokens": 80, "cost_yuan": 0.0, "latency_ms": 150.0},
        {"ts": "2026-08-16T09:00:00+08:00", "provider": "deepseek", "model": "deepseek-chat",
         "in_tokens": 300, "out_tokens": 100, "cost_yuan": 0.0123, "latency_ms": 800.0},
    ]
    d = _write_telemetry(tmp_path, monkeypatch, rows)
    assert d["ok"] is True and d["empty"] is False
    # 按日趋势
    assert [x["date"] for x in d["daily"]] == ["2026-08-15", "2026-08-16"]
    assert d["daily"][0]["calls"] == 2
    assert d["daily"][0]["tokens"] == 430
    assert d["daily"][1]["calls"] == 1
    # 按供应商
    by_prov = {p["provider"]: p for p in d["providers"]}
    assert by_prov["zhipu"]["calls"] == 2
    assert by_prov["zhipu"]["cost_yuan"] == 0.0
    assert by_prov["deepseek"]["calls"] == 1
    assert by_prov["deepseek"]["cost_yuan"] == 0.0123
    # 按模型
    by_mod = {m["model"]: m for m in d["models"]}
    assert by_mod["glm-4.5-air"]["calls"] == 2
    assert by_mod["glm-4.5-air"]["avg_latency_ms"] == 135.0
    # 总量
    assert d["totals"]["count"] == 3
    assert d["totals"]["free_calls"] == 2
    assert d["totals"]["paid_calls"] == 1
    assert abs(d["totals"]["cost_yuan"] - 0.0123) < 1e-6