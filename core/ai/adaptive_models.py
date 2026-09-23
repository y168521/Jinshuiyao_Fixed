# -*- coding: utf-8 -*-
"""云端模型智能匹配：模型额度耗尽/不可用时自动探测并切换可用模型

背景（W63补52 / JS-20260806-06）：百炼 qwen-plus 免费额度耗尽返回 403，
用户要求"没有额度就自动匹配有额度的模型"，不要手动逐个切换。
百炼有 100+ 模型、每个都有独立免费额度（/models 端点实测可用，236 个模型）。

本模块：
  - list_llm_models(): GET 百炼 /compatible-mode/v1/models，过滤出 LLM
  - probe_model(): 对单个模型发最小 chat 请求（200=可用，403=额度/权限不可用）
  - find_working_model(): 优先探测白名单（用户确认有额度的模型）→ 全量列表，
    并行探测，返回第一个可用模型；结果内存缓存(TTL) + 持久化到 secrets 目录
    （<provider>_model.txt，同步盘外，不污染仓库）
  - remember_model()/current_model(): 读写持久化选择
"""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

_SECRETS_DIR = os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets")

# 候选白名单（按优先级排序；实测过有免费额度的放前面）
DASHSCOPE_CANDIDATES = [
    "qwen3.6-flash",
    "qwen3.7-flash-2026-07-15",
    "qwen3.7-flash",
    "qwen3-32b",
    "qwen-max",
    "qwen-mt-flash",
    "qwen-plus",
    "deepseek-r1-distill-qwen-32b",
    "deepseek-r1-distill-qwen-7b",
    "qwen3-30b-a3b",
    "qwen-turbo",
    "qwen-long",
]

# 非对话模型特征（image/ocr/audio/embedding 等不可用于 chat）
_NON_LLM_HINTS = (
    "image", "-vl", "ocr", "audio", "embedding", "rerank",
    "video", "tts", "asr", "multimodal",
)

_DASHSCOPE_MODELS_URL = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1/models")
_DASHSCOPE_CHAT_URL = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")

_cache = {}          # provider -> (model, ts)
_cache_lock = threading.Lock()
_CACHE_TTL = 300     # 可用模型缓存 5 分钟
_FAIL_TTL = 60       # 全失败后 60 秒内不再重复探测

_PROBE_TIMEOUT = 8
_MAX_WORKERS = 8
_MAX_FULL_SCAN = 24  # 全量探测上限，避免 100+ 模型全部请求


def _meta_file(provider):
    return os.path.join(_SECRETS_DIR, "%s_model.txt" % provider)


def _is_llm(model_id):
    """过滤非对话模型（image/ocr/audio 等）"""
    mid = (model_id or "").lower()
    if "/" in mid:  # 三方托管（kimi/xxx、glm/xxx 等）先排除，只匹配自有模型
        return False
    return not any(h in mid for h in _NON_LLM_HINTS)


def list_llm_models(api_key, timeout=12):
    """GET /models 拉取百炼模型列表并过滤出 LLM（失败返回空列表）"""
    try:
        import requests
        r = requests.get(_DASHSCOPE_MODELS_URL,
                         headers={"Authorization": "Bearer %s" % api_key},
                         timeout=timeout)
        if r.status_code != 200:
            return []
        data = r.json().get("data", [])
        return [m.get("id") for m in data if _is_llm(m.get("id"))]
    except Exception:
        return []


def probe_model(api_key, model, timeout=_PROBE_TIMEOUT):
    """对单个模型发最小 chat 请求：200=可用，其余=不可用/额度耗尽"""
    try:
        import requests
        r = requests.post(
            _DASHSCOPE_CHAT_URL,
            headers={"Authorization": "Bearer %s" % api_key},
            json={"model": model,
                  "messages": [{"role": "user", "content": "hi"}],
                  "max_tokens": 1},
            timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _probe_batch(api_key, models):
    """并行探测一批模型，按输入顺序返回第一个可用的"""
    if not models:
        return ""
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
        futures = {ex.submit(probe_model, api_key, m): m for m in models}
        results = {}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    for m in models:
        if results.get(m):
            return m
    return ""


def find_working_model(provider, api_key, preferred=None):
    """探测并返回可用模型（""=全部不可用）

    顺序：内存缓存 → preferred 单测 → 白名单并行 → 全量列表并行。
    找到后写入持久化 + 缓存；全失败缓存 60 秒防频繁探测。
    """
    now = time.time()
    with _cache_lock:
        hit = _cache.get(provider)
        if hit and now - hit[1] < _CACHE_TTL:
            return hit[0]
        if hit and hit[0] == "" and now - hit[1] < _FAIL_TTL:
            return ""

    # preferred（当前配置模型）先单测
    if preferred and probe_model(api_key, preferred):
        remember_model(provider, preferred)
        return preferred

    # 白名单并行
    candidates = [m for m in DASHSCOPE_CANDIDATES if m != preferred]
    found = _probe_batch(api_key, candidates)
    if not found:
        # 白名单全失败 → 全量列表探测（限数量）
        all_models = list_llm_models(api_key)
        rest = [m for m in all_models
                if m not in candidates and m != preferred]
        found = _probe_batch(api_key, rest[:_MAX_FULL_SCAN])

    with _cache_lock:
        _cache[provider] = (found, now)
    if found:
        remember_model(provider, found)
    return found


def remember_model(provider, model):
    """持久化当前可用模型选择（secrets 目录，同步盘外）"""
    if not model:
        return
    try:
        os.makedirs(_SECRETS_DIR, exist_ok=True)
        with open(_meta_file(provider), "w", encoding="utf-8") as f:
            f.write(model)
    except Exception:
        pass


def current_model(provider, default=""):
    """读取持久化的模型选择（无则返回 default）"""
    try:
        p = _meta_file(provider)
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                m = f.read().strip()
            if m:
                return m
    except Exception:
        pass
    return default


def clear_cache(provider=None):
    """清缓存（测试/调试用）"""
    with _cache_lock:
        if provider:
            _cache.pop(provider, None)
        else:
            _cache.clear()


if __name__ == "__main__":
    # 独立自测：不依赖真实密钥时只验证过滤逻辑
    assert _is_llm("qwen3.6-flash")
    assert not _is_llm("qwen-image-3.0")
    assert not _is_llm("qwen-vl-plus")
    assert not _is_llm("kimi/kimi-k3")
    assert _is_llm("deepseek-r1-distill-qwen-32b")
    assert not _is_llm("qwen3-embedding")
    print("[adaptive_models._self_test] 过滤逻辑通过")
