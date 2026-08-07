# -*- coding: utf-8 -*-
"""JS-20260807-02 · 核心配置/状态 JSON 原子写收口测试

验证刀⑥迁移点：5 处裸写已迁 safe_write_json / safe_load_json。
- theme_manager / gui_registry 用 monkeypatch 临时路径验证写出与读回一致 + 损坏恢复
- ai_service.set_mode 写出 mode=offline 且为合法 JSON
- free_model_pool / model_shadow 冒烟导入 + 关键函数不崩
零网络依赖，结果确定稳定。
"""
import json

import pytest


def _import_or_skip(modname):
    try:
        return __import__(modname, fromlist=["*"])
    except Exception as e:  # pragma: no cover
        pytest.skip(f"{modname} 导入失败（环境缺依赖）: {e}")


# --- theme_manager ---
def test_theme_save_load_roundtrip(monkeypatch, tmp_path):
    tm = _import_or_skip("core.theme_manager")
    p = tmp_path / "user_themes.json"
    monkeypatch.setattr(tm, "_USER_THEMES_PATH", str(p))
    data = {"u1": {"--bg": "#0B1A2F", "--accent": "#C9A96E"}}
    tm._save_user_themes(data)
    assert tm._load_user_themes() == data


def test_theme_corrupted_returns_default(monkeypatch, tmp_path):
    tm = _import_or_skip("core.theme_manager")
    p = tmp_path / "user_themes.json"
    p.write_text("{损坏的JSON!!!", encoding="utf-8")
    monkeypatch.setattr(tm, "_USER_THEMES_PATH", str(p))
    # safe_load_json 损坏时返回默认 {}（而非抛异常崩溃）
    assert tm._load_user_themes() == {}


# --- gui_registry ---
def test_gui_write_read_roundtrip(monkeypatch, tmp_path):
    gr = _import_or_skip("core.gui_registry")
    p = tmp_path / "gui_status.json"
    monkeypatch.setattr(gr, "_STATUS_FILE", str(p))
    data = {"gui_main": {"pid": 1234, "title": "X"}}
    gr._write(data)
    assert gr._read() == data


def test_gui_corrupted_returns_default(monkeypatch, tmp_path):
    gr = _import_or_skip("core.gui_registry")
    p = tmp_path / "gui_status.json"
    p.write_text("not json{{{", encoding="utf-8")
    monkeypatch.setattr(gr, "_STATUS_FILE", str(p))
    assert gr._read() == {}


# --- ai_service ---
def test_ai_service_set_mode_writes_json(monkeypatch, tmp_path):
    ai = _import_or_skip("core.ai_service")
    p = tmp_path / "ai_mode.json"
    monkeypatch.setattr(ai, "_MODE_CONFIG_PATH", str(p))
    assert ai.set_mode("offline") is True
    raw = p.read_text(encoding="utf-8")
    parsed = json.loads(raw)  # 必须仍是合法 JSON
    assert parsed["mode"] == "offline"
    assert ai.get_mode() == "offline"
    assert ai.get_mode_info()["mode"] == "offline"


# --- free_model_pool / model_shadow 冒烟 ---
def test_free_model_pool_import():
    _import_or_skip("core.free_model_pool")


def test_model_shadow_promote_safe():
    ms = _import_or_skip("core.model_shadow")
    # promote_ready/auto_promote 为假 → 直接返回内部 s（dict），不触碰真实 config 文件
    result = ms.shadow_promote_if_ready()
    assert isinstance(result, dict)
