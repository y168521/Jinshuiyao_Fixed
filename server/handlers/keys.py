# -*- coding: utf-8 -*-
"""金水谣系统 - API密钥统一管理端点

路由：
  GET  /api/keys          — 列出所有密钥槽位状态（是否已配置+掩码）
  POST /api/keys/save     — 保存密钥到 ~/.jinshuiyao-secrets/<file>
  POST /api/keys/test     — 测试密钥连通性（可带 value 只测不存）
  POST /api/keys/identify — 智能识别粘贴的密钥属于哪个平台

安全铁律（JS-20260724）：
  密钥只写 ~/.jinshuiyao-secrets/（同步盘外），权限 600；
  槽位名白名单校验，防路径穿越；
  响应永不含完整密钥，仅掩码（前4+后4）。
"""
import json
import os
import sys
import threading

try:
    from ..utils import log
except ImportError:  # 独立自测（python keys.py）时无包上下文
    def log(*a, **k):
        pass

_SECRETS_DIR = os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets")

# 统一密钥槽位表：前端面板 / set_secret.py / 各模块读取 共用同一白名单
KEY_SLOTS = {
    "deepseek_key": {
        "file": "deepseek_key.txt",
        "name": "DeepSeek（付费兜底）",
        "desc": "AI对话/代码助手付费兜底，也供 AI深度版基金日报等生成",
        "test_url": "https://api.deepseek.com/models",
        "test_headers": {"Authorization": "Bearer {key}"},
        "test_method": "GET",
        "test_expected": 200,
    },
    "siliconflow_key": {
        "file": "siliconflow_key.txt",
        "name": "硅基流动（免费模型池）",
        "desc": "免费模型池（GLM-4-9B / Qwen 等），审查/降级等脏活用",
        "test_url": "https://api.siliconflow.cn/v1/models",
        "test_headers": {"Authorization": "Bearer {key}"},
        "test_method": "GET",
        "test_expected": 200,
    },
    "dashscope_key": {
        "file": "dashscope_key.txt",
        "name": "阿里云百炼（通义千问）",
        "desc": "阿里云百炼 OpenAI兼容接口（qwen3.6-flash / qwen-max 等，默认用免费额度模型）",
        # 百炼未保证 /models 端点（实测常 404），用官方明确的 chat/completions
        # 最小请求测试（约 10 token 消耗）；模型用 qwen3.6-flash 免费额度
        "test_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "test_headers": {"Authorization": "Bearer {key}"},
        "test_method": "POST",
        "test_body": {"model": "qwen3.6-flash",
                      "messages": [{"role": "user", "content": "hi"}],
                      "max_tokens": 1},
        "test_expected": 200,
    },
    "zhipu_key": {
        "file": "zhipu_key.txt",
        "name": "智谱（GLM 大模型）",
        "desc": "智谱开放平台 OpenAI兼容接口（glm-4.5-air 等，付费兜底可选）",
        # 官方文档：base_url https://open.bigmodel.cn/api/paas/v4，Bearer 鉴权
        "test_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "test_headers": {"Authorization": "Bearer {key}"},
        "test_method": "POST",
        "test_body": {"model": "glm-4.5-air",
                      "messages": [{"role": "user", "content": "hi"}],
                      "max_tokens": 1},
        "test_expected": 200,
    },
    "moonshot_key": {
        "file": "moonshot_key.txt",
        "name": "月之暗面（Kimi）",
        "desc": "Kimi OpenAI兼容接口（kimi-k2.6 等，官方支持 /v1/models）",
        "test_url": "https://api.moonshot.cn/v1/models",
        "test_headers": {"Authorization": "Bearer {key}"},
        "test_method": "GET",
        "test_expected": 200,
    },
    "tavily_key": {
        "file": "tavily_key.txt",
        "name": "Tavily（联网搜索）",
        "desc": "AI助手联网搜索用（agent_web_search）",
        "test_url": "https://api.tavily.com/search",
        "test_headers": {"Content-Type": "application/json"},
        "test_method": "POST",
        "test_body": {"query": "ping", "max_results": 1},
        "test_expected": 200,
    },
    "douyin_cookie": {
        "file": "douyin_cookie.txt",
        "name": "抖音 Cookie（视频提取）",
        "desc": "视频文案提取的抖音登录 Cookie",
        "test_method": "none",
    },
}

_LOCK = threading.Lock()


def _slot_file(slot):
    """槽位名 → 密钥文件绝对路径（白名单校验，防路径穿越）"""
    info = KEY_SLOTS.get(slot)
    if not info:
        raise ValueError("未知密钥槽位: %s" % slot)
    return os.path.join(_SECRETS_DIR, info["file"])


def _read_slot_value(slot):
    """读取槽位当前值（不存在返回空串）"""
    try:
        p = _slot_file(slot)
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def _mask(key):
    """掩码：前4后4，中间省略号"""
    if not key:
        return ""
    if len(key) <= 10:
        return key[:2] + "…" + key[-2:]
    return key[:4] + "…" + key[-4:]


def _write_secret(slot, value):
    """把 value 写入 ~/.jinshuiyao-secrets/<file>，权限 600"""
    value = (value or "").strip()
    if not value:
        raise ValueError("密钥为空")
    os.makedirs(_SECRETS_DIR, exist_ok=True)
    p = _slot_file(slot)
    with open(p, "w", encoding="utf-8") as f:
        f.write(value + "\n")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


def _http_test(key, info, timeout=10):
    """对单个槽位发起连通性测试，返回 (ok, detail)"""
    method = info.get("test_method", "GET")
    url = info.get("test_url")
    if method == "none" or not url:
        return None, "该类型不支持在线测试"
    try:
        import requests
    except Exception:
        return False, "无 requests 库"
    headers = {k: v.format(key=key) for k, v in info.get("test_headers", {}).items()}
    try:
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=timeout)
        else:
            r = requests.post(url, headers=headers, json=info.get("test_body", {}), timeout=timeout)
        if r.status_code == info.get("test_expected", 200):
            return True, "连接正常（HTTP %d）" % r.status_code
        return False, "HTTP %d：%s" % (r.status_code, (r.text or "")[:120].replace("\n", " "))
    except Exception as e:
        return False, "连接失败：%s" % type(e).__name__


def handle_keys_list(handler):
    """GET /api/keys — 列出所有密钥槽位状态（只回掩码，绝不回明文）"""
    items = []
    for slot, info in KEY_SLOTS.items():
        val = _read_slot_value(slot)
        items.append({
            "slot": slot,
            "file": info["file"],
            "name": info["name"],
            "desc": info["desc"],
            "configured": bool(val),
            "masked": _mask(val),
        })
    handler._send_json({"ok": True, "keys": items})


def handle_keys_save(handler):
    """POST /api/keys/save — 保存密钥到安全目录"""
    try:
        body = json.loads(handler._read_body() or "{}")
    except Exception:
        body = {}
    slot = (body.get("slot") or "").strip()
    value = (body.get("value") or "").strip()
    try:
        p = _write_secret(slot, value)
    except ValueError as e:
        handler._send_json({"ok": False, "error": str(e)})
        return
    except Exception as e:
        log(f"[keys] 保存 {slot} 失败: {e}")
        handler._send_json({"ok": False, "error": "写入失败: %s" % e})
        return
    log(f"[keys] 已保存密钥槽位: {slot}")
    handler._send_json({"ok": True, "masked": _mask(value), "path": p})


def _auto_match_dashscope(key, info):
    """百炼智能匹配：当前测试模型不可用(额度耗尽)时自动探测可用模型

    找到可用模型则：更新本槽位测试模型 + 同步 ai_service PROVIDERS 默认模型，
    返回 (ok, detail)；全部不可用返回 (False, None)。
    """
    try:
        from core.adaptive_models import find_working_model
        best = find_working_model(
            "dashscope", key,
            preferred=info["test_body"].get("model", ""))
        if not best:
            return False, None
        info["test_body"]["model"] = best
        try:
            from core.ai_service import PROVIDERS
            if "dashscope" in PROVIDERS:
                PROVIDERS["dashscope"]["model"] = best
        except Exception:
            pass
        ok, detail = _http_test(key, info)
        return ok, detail
    except Exception:
        return False, None


def handle_keys_test(handler):
    """POST /api/keys/test — 测试密钥连通性（带 value 只测不存）

    百炼槽位：默认模型额度耗尽(403)时自动智能匹配可用模型并切换。
    """
    try:
        body = json.loads(handler._read_body() or "{}")
    except Exception:
        body = {}
    slot = (body.get("slot") or "").strip()
    value = (body.get("value") or "").strip()
    info = KEY_SLOTS.get(slot)
    if not info:
        handler._send_json({"ok": False, "error": "未知密钥槽位"})
        return
    key = value or _read_slot_value(slot)
    if not key:
        handler._send_json({"ok": False, "error": "该槽位未配置密钥，请先填写再测试"})
        return
    ok, detail = _http_test(key, info)
    if ok is None:
        handler._send_json({"ok": True, "note": detail})
        return
    if not ok and slot == "dashscope_key":
        # 智能匹配：默认模型不可用 → 自动探测可用模型并切换
        m_ok, m_detail = _auto_match_dashscope(key, info)
        if m_ok:
            handler._send_json({
                "ok": True,
                "detail": "当前模型额度不可用，已自动切换为可用模型 %s，测试通过（HTTP 200）"
                          % info["test_body"]["model"],
                "switched_model": info["test_body"]["model"],
            })
            return
        if m_detail is not None:
            ok, detail = m_ok, m_detail
    handler._send_json({"ok": ok, "detail": detail})


def handle_keys_identify(handler):
    """POST /api/keys/identify — 智能识别粘贴的密钥属于哪个平台

    依次对全部 LLM 平台（DeepSeek / 硅基流动 / 阿里云百炼 / 智谱 / 月之暗面）
    发起最小探测请求，命中的平台即为识别结果；全部未命中时返回
    manual_slots（可手动选择的平台清单）供前端兜底选择。
    """
    try:
        body = json.loads(handler._read_body() or "{}")
    except Exception:
        body = {}
    value = (body.get("value") or "").strip()
    if not value:
        handler._send_json({"ok": False, "error": "请先粘贴密钥"})
        return
    llm_slots = ("deepseek_key", "siliconflow_key", "dashscope_key",
                 "zhipu_key", "moonshot_key")
    results = []
    for slot in llm_slots:
        info = KEY_SLOTS[slot]
        ok, detail = _http_test(value, info)
        # 百炼：默认模型额度耗尽时自动探测可用模型，能命中说明 key 属于百炼
        if not ok and slot == "dashscope_key":
            m_ok, m_detail = _auto_match_dashscope(value, info)
            if m_ok:
                ok, detail = True, "HTTP 200 (model=%s)" % info["test_body"]["model"]
        results.append({"slot": slot, "name": info["name"], "ok": ok, "detail": detail})
    hits = [r for r in results if r["ok"]]
    manual = [{"slot": s, "name": KEY_SLOTS[s]["name"]} for s in llm_slots]
    if hits:
        handler._send_json({"ok": True, "hits": hits, "results": results, "manual_slots": manual})
    else:
        handler._send_json({"ok": False, "results": results, "manual_slots": manual})


def _self_test():
    """独立自测：槽位白名单 + 掩码 + 写入/读取/清理"""
    import tempfile
    import shutil

    global _SECRETS_DIR
    tmp = tempfile.mkdtemp(prefix="keys_selftest_")
    old = _SECRETS_DIR
    _SECRETS_DIR = tmp
    try:
        assert "deepseek_key" in KEY_SLOTS
        assert "dashscope_key" in KEY_SLOTS
        assert _mask("sk-abcdef1234567890") == "sk-a…7890"
        assert _mask("") == ""
        p = _write_secret("dashscope_key", "sk-test123")
        assert os.path.isfile(p)
        assert _read_slot_value("dashscope_key") == "sk-test123"
        try:
            _slot_file("../evil")
            assert False, "应拒绝非法槽位名"
        except ValueError:
            pass
        print("[keys._self_test] 全部通过")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        _SECRETS_DIR = old


if __name__ == "__main__":
    sys.exit(_self_test())
