# -*- coding: utf-8 -*-
"""【道衍推导·JS-20260727-24】
  阴阳：阳=故障转移尝试(主动求生)；阴=付费兜底+全挂告警(守底，绝不静默失败)。
  天地人：天=规划政策变体覆盖；地=隔离(配置外部化不动代码)；人=复盘(探活状态可查)。
  知止：免费池全挂必写all_down告警并回退；绝不因"省费"而静默丢弃请求。

金水谣 · 免费模型池管理器（前瞻性四件套）

背景：用户后续会接多个免费模型，且免费模型政策非一成不变（可能下架/转收费/限流/上新）。
本模块把"用哪些免费模型"从代码里抽离成配置清单，并提供：
  1. 配置外部化：config/free_models.json 列出免费模型池，换模型=改清单、不动代码
  2. 轮转/优先级：按 priority 升序选模（也可用 SILICONFLOW_MODEL 指定单模型，兼容旧行为）
  3. 故障转移：免费池逐个尝试，全挂回退付费兜底（DeepSeek）
  4. 自动探活：health_check_all() 轻量请求更新健康状态，识别 down / degraded
  5. 状态文件 + 全挂告警：金水谣数据/free_model_status.json，全挂写告警标记

覆盖政策变体：
  - 下架（404 / Model disabled）→ 探活发现 → 标记 down → 自动跳过
  - 转收费（带 "Pro/" 前缀或 403）→ 标记 down
  - 限流收紧（429）→ 标记 degraded（降级但不直接弃用）
  - 上新 → 在 free_models.json 把预留位 enabled=true 并填真实 id 即可
"""
import json
import os
import sys
import time
import threading
from utils.safe_json import safe_write_json

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "free_models.json")
_STATUS_PATH = os.path.join(_PROJECT_ROOT, "金水谣数据", "free_model_status.json")

_lock = threading.Lock()
_status_cache = {}  # model_id -> {healthy, degraded, error, ts, failures, provider}


def _read_secret(fname):
    """从安全目录读取密钥（与 ai_review_agent 同约定：仅 ~/.jinshuiyao-secrets）"""
    d = os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets")
    p = os.path.join(d, fname)
    if os.path.isfile(p):
        try:
            return open(p, "r").read().strip()
        except Exception:
            pass
    return ""


def load_pool_config(path=_CONFIG_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # 配置缺失/损坏 → 返回空池，调用方会回退付费兜底（fail-safe 不 fail-closed）
        return {"providers": {}, "fallback": {}, "health_check": {}, "notify": {}}


def build_single_cfg(provider, pdata, model_entry):
    """由 provider 配置 + 单模型条目构造 call_ai 所需的 cfg dict"""
    return {
        "base_url": pdata.get("base_url"),
        "api_key": _read_secret(pdata.get("api_key_file", "")) or os.environ.get(pdata.get("api_key_env", ""), ""),
        "model": model_entry.get("id"),
        "json_mode": pdata.get("json_mode", False),
        "_provider": provider,
        "_model_id": model_entry.get("id"),
    }


def _find_model_cfg(cfg, model_id):
    for prov, pdata in cfg.get("providers", {}).items():
        for m in pdata.get("models", []):
            if m.get("id") == model_id:
                return build_single_cfg(prov, pdata, m)
    return None


def _load_health_exclusions(status_path=_STATUS_PATH, max_age_sec=3 * 3600):
    """【P0-G1】读取探活状态文件，返回 (down_set, degraded_set)。

    仅信任新鲜（≤3h）的状态；过期/缺失则视为无排除项（全量尝试，fail-safe）。
    这样把「health_check_all 算出挂了」变成「路由真正绕开挂的」，形成闭环。
    """
    down, degraded = set(), set()
    try:
        if time.time() - os.path.getmtime(status_path) > max_age_sec:
            return down, degraded
        with open(status_path, "r", encoding="utf-8") as f:
            st = json.load(f)
        down = set(st.get("down", []) or [])
        degraded = set(st.get("degraded", []) or [])
    except Exception:
        pass
    return down, degraded


def get_free_provider_cfgs(config_path=_CONFIG_PATH, respect_env=True):
    """返回按 priority 升序排序的已启用免费 cfg 列表。

    respect_env=True 且设了 SILICONFLOW_MODEL 时，仅返回该单模型（兼容旧行为）。
    没设则返回整个池，供故障转移逐个尝试。

    【P0-G1 健康闭环】若探活状态标出 dead/degraded，则跳过 dead、降权 degraded，
    让路由自动绕开已知不可用的模型，不再每次白试。
    """
    cfg = load_pool_config(config_path)
    if respect_env:
        env_model = os.environ.get("SILICONFLOW_MODEL")
        if env_model:
            single = _find_model_cfg(cfg, env_model)
            if single:
                return [single]
    models = []
    for prov, pdata in cfg.get("providers", {}).items():
        for m in pdata.get("models", []):
            if not m.get("enabled", True):
                continue
            models.append((m.get("priority", 99), build_single_cfg(prov, pdata, m)))
    # ── P0-G1 健康闭环：跳过已判 dead，降权 degraded ──
    down, degraded = _load_health_exclusions(_STATUS_PATH)
    if down or degraded:
        models = [(p, c) for (p, c) in models if c.get("_model_id") not in down]
        models = [(99 if c.get("_model_id") in degraded else p, c) for (p, c) in models]
    models.sort(key=lambda x: x[0])
    return [c for _, c in models]


def pick_cfg_for_task(cfg_list, complexity="medium", config_path=_CONFIG_PATH):
    """自动精准匹配：按任务复杂度从免费池挑质量合适的模型。

    核心理念（用户约定）：不需要高级推理的任务优先免费；实在不行才付费。
    复杂度分级：
      - "light"    → 简单/机械任务（闲聊、字段提取、格式化）：用质量分 50-75 的轻量模型，快且省
      - "medium"   → 常规任务（日常审查、总结）：用质量分最高且健康的首选模型（默认行为）
      - "heavy"    → 复杂推理（深层代码审查、跨文件分析）：必须质量分 ≥85，否则退化到付费兜底

    实现：按质量分阈值取第一个健康（非 down）模型；找不到符合的返回 None（调用方退付费兜底）。"""
    cfg = load_pool_config(config_path)
    if not cfg_list:
        return None
    # 从配置读取 quality，fallback：cfg 内嵌或按需默认
    quality_by_id = {}
    for prov, pdata in cfg.get("providers", {}).items():
        for m in pdata.get("models", []):
            quality_by_id[m.get("id")] = int(m.get("quality", 0))
    down, _ = _load_health_exclusions(_STATUS_PATH)
    if complexity == "heavy":
        need = 85
    elif complexity == "light":
        # 轻量任务选第一个质量 ≤70 的健康模型（省时间），无则降级选最低质量可用
        light = [c for c in cfg_list if c.get("_model_id") not in down
                 and quality_by_id.get(c.get("_model_id"), 100) <= 70]
        if light:
            return light[0]
        return cfg_list[0] if cfg_list and cfg_list[0].get("_model_id") not in down else None
    else:
        need = 0
    for c in cfg_list:
        if c.get("_model_id") in down:
            continue
        if quality_by_id.get(c.get("_model_id"), 0) >= need:
            return c
    return None


def get_fallback_cfg(config_path=_CONFIG_PATH):
    """付费兜底配置（DeepSeek），仅在免费池全挂时启用"""
    cfg = load_pool_config(config_path)
    fb = cfg.get("fallback", {})
    if not fb:
        return None
    return {
        "base_url": "https://api.deepseek.com/chat/completions",
        "api_key": _read_secret(fb.get("api_key_file", "deepseek_key.txt")) or os.environ.get(fb.get("api_key_env", "DEEPSEEK_API_KEY"), ""),
        "model": os.environ.get(fb.get("model_env", "DEEPSEEK_MODEL"), fb.get("default_model", "deepseek-v4-pro")),
        "json_mode": False,
        "_provider": "deepseek",
        "_model_id": "fallback",
    }


# ── 轻量 HTTP 调用（自包含，避免与 ai_review_agent 循环依赖；供探活/兜底使用）──
def _http_call(cfg, system_prompt, user_prompt, timeout=30, max_tokens=64, temperature=0.1):
    if not cfg.get("api_key") or not cfg.get("base_url"):
        return None, "NO_CFG"
    import urllib.request
    body = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if cfg.get("json_mode"):
        body["response_format"] = {"type": "json_object"}
    payload = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"}
    try:
        req = urllib.request.Request(cfg["base_url"], data=payload, headers=headers)
        _t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        _dt = (time.time() - _t0) * 1000
        # ── P0-G2 成本回写 + P1-G6 遥测：从 usage 计算真实花费与令牌 ──
        try:
            usage = data.get("usage") or {}
            _in = int(usage.get("prompt_tokens", 0) or 0)
            _out = int(usage.get("completion_tokens", 0) or 0)
            _cost = 0.0
            if _in or _out:
                from core.llm_budget import get_guard
                _cost = get_guard().record(cfg.get("_provider"), _in, _out)
            from core.telemetry import record as _tel
            _tel(provider=cfg.get("_provider"), model=cfg.get("_model_id"),
                 in_tokens=_in, out_tokens=_out,
                 cost_yuan=round(_cost, 6), latency_ms=round(_dt, 1))
        except Exception:
            pass
        return data["choices"][0]["message"]["content"], None
    except Exception as e:
        return None, f"HTTP_ERROR: {e}"


def call_ai_failover(cfg_list, system_prompt, user_prompt, call_fn=None,
                     timeout=120, max_tokens=64, temperature=0.1, force_json_mode=None,
                     allow_paid_fallback=True):
    """遍历免费模型池故障转移调用。

    call_fn: 注入的审查调用函数（默认用自带 _http_call）；返回 (text, error, used_cfg)
    全挂 → 回退付费；再挂 → 返回 ALL_FREE_DOWN 错误。
    max_tokens/temperature: 透传给 call_fn（默认 64/0.1 保持与旧健康检查兼容）。
    force_json_mode: None=沿用各 cfg 自带 json_mode（代码审查用）；False=强制关闭（自然语言总结/聊天用）；True=强制开启。
    """
    fn = call_fn or _http_call
    last_err = None
    # ── P1-G7 LLM 级熔断：为每个模型建一个熔断器（复用 core.circuit_breaker）──
    from core.circuit_breaker import get_breaker
    for cfg in cfg_list:
        mid = cfg.get("_model_id")
        cb = get_breaker("llm:" + str(mid), failure_threshold=3, recovery_timeout=60)
        # 熔断器 open → 直接跳过该供应商，避免反复白试（与 G1 健康闭环叠加）
        if cb.state == "open":
            last_err = "CB_OPEN:" + str(mid)
            continue
        c = cfg
        if force_json_mode is not None:
            c = dict(cfg)
            c["json_mode"] = bool(force_json_mode)
        text, err = fn(c, system_prompt, user_prompt,
                       timeout=timeout, max_tokens=max_tokens, temperature=temperature)
        if text is not None and not err:
            cb.record_success()          # 成功 → 复位熔断
            _mark_healthy(mid)
            return text, None, cfg
        cb.record_failure()              # 失败 → 累计，达阈值即熔断（G8 重试上限）
        last_err = err
        _mark_unhealthy(mid, err)
    # 全挂 → 回退付费兜底（受成本闸约束，预算封顶则跳过付费，避免失控）
    # allow_paid_fallback=False（代码审查场景：用户约定"能用免费就用，不然就算了"）时彻底跳过付费
    if allow_paid_fallback:
        fb = get_fallback_cfg()
        _budget_ok = True
        try:
            from core.llm_budget import get_guard
            _budget_ok = get_guard().allow_paid(provider="deepseek", prompt_chars=len(user_prompt or ""))
        except Exception:
            _budget_ok = True
        if fb and fb.get("api_key") and _budget_ok:
            c = fb
            if force_json_mode is not None:
                c = dict(fb)
                c["json_mode"] = bool(force_json_mode)
            text, err = (call_fn or _http_call)(c, system_prompt, user_prompt,
                                                timeout=timeout, max_tokens=max_tokens, temperature=temperature)
        if text is not None and not err:
            return text, None, fb
        last_err = err
    elif allow_paid_fallback and fb and fb.get("api_key") and not _budget_ok:
        last_err = "BUDGET_TRIPPED"
    elif not allow_paid_fallback:
        last_err = "PAID_FALLBACK_DISABLED"
    return None, f"ALL_FREE_DOWN+fallback_failed:{last_err}", None


def call_paid(system_prompt, user_prompt, timeout=120, max_tokens=800, temperature=0.7, force_json_mode=None):
    """直接走付费兜底（DeepSeek）。供 model_router 判定为「烧脑任务」时优先使用；不自动 free-fallback（由 router 控制双向兜底）。

    force_json_mode: None=沿用 fallback 自带 json_mode；True/False=强制开关。
    """
    fb = get_fallback_cfg()
    if not fb or not fb.get("api_key"):
        return None, "NO_PAID_KEY"
    # ── P0-G2 成本闸：预算封顶时拒绝付费，交由路由降级到免费，绝不静默烧穿预算 ──
    try:
        from core.llm_budget import get_guard
        if not get_guard().allow_paid(provider="deepseek", prompt_chars=len(user_prompt or "")):
            return None, "BUDGET_TRIPPED"
    except Exception:
        pass
    c = fb
    if force_json_mode is not None:
        c = dict(fb)
        c["json_mode"] = bool(force_json_mode)
    return _http_call(c, system_prompt, user_prompt, timeout=timeout, max_tokens=max_tokens, temperature=temperature)


def _mark_healthy(model_id):
    if not model_id:
        return
    with _lock:
        st = _status_cache.setdefault(model_id, {})
        st.update({"healthy": True, "degraded": False, "error": "", "ts": time.time(), "failures": 0})


def _mark_unhealthy(model_id, err):
    if not model_id:
        return
    err_s = str(err)
    with _lock:
        st = _status_cache.setdefault(model_id, {"healthy": True, "failures": 0})
        st["failures"] = st.get("failures", 0) + 1
        st["healthy"] = False
        st["error"] = err_s
        st["ts"] = time.time()
        # 429 限流 → 降级（degraded），不直接弃用
        if "429" in err_s:
            st["degraded"] = True


def health_check_all(config_path=_CONFIG_PATH, status_path=_STATUS_PATH, call_fn=None):
    """主动探活：对每个启用免费模型发轻量请求，更新健康状态；全挂写告警。

    返回摘要 dict。供 scripts/free_model_health_check.py 定时调用（前瞻性主动巡检，而非被动等挂）。
    """
    cfg = load_pool_config(config_path)
    fn = call_fn or _http_call
    hc = cfg.get("health_check", {})
    if not hc.get("enabled", True):
        return {"skipped": True}
    timeout = int(hc.get("timeout_seconds", 15))
    probe = hc.get("probe_prompt", "ping")
    summary = {"checked": [], "down": [], "degraded": [], "all_down": False,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")}
    for prov, pdata in cfg.get("providers", {}).items():
        for m in pdata.get("models", []):
            if not m.get("enabled", True):
                continue
            mid = m.get("id")
            single = build_single_cfg(prov, pdata, m)
            text, err = fn(single, "你是健康检查器，只回复 pong", probe, timeout)
            entry = {"id": mid, "provider": prov, "healthy": err is None,
                     "error": str(err) if err else "", "ts": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")}
            summary["checked"].append(entry)
            if err:
                _mark_unhealthy(mid, err)
                if "429" in str(err):
                    entry["degraded"] = True
                    summary["degraded"].append(mid)
                else:
                    summary["down"].append(mid)
            else:
                _mark_healthy(mid)
            with _lock:
                _status_cache[mid] = {k: entry[k] for k in ("id", "provider", "healthy", "error", "ts")}
                _status_cache[mid]["degraded"] = entry.get("degraded", False)
                _status_cache[mid]["failures"] = _status_cache.get(mid, {}).get("failures", 0)
    # 修正(JS-20260805): 原只认 down 不认 degraded → 全模型被限流(429)时告警不响(监控盲区)。
    # 现 all_down = 所有已检模型均不可用(down 或 degraded)。degraded 仍可被路由降权尝试, 但告警会响, 避免"免费池全限流偷偷烧付费"无提醒。
    summary["all_down"] = (bool(summary["down"]) or bool(summary["degraded"])) and (len(summary["down"]) + len(summary["degraded"])) == len(summary["checked"])
    # 写状态文件 + 全挂告警
    try:
        out = {"ts": summary["ts"], "checked": summary["checked"],
               "down": summary["down"], "degraded": summary["degraded"],
               "all_down": summary["all_down"]}
        # 刀⑥(JS-20260807-02): 原子写，避免状态文件半写撕裂；safe_write_json 已含 makedirs+备份
        if not safe_write_json(status_path, out, backup=True):
            print(f"[free_model_pool] 状态文件写入失败: {status_path}", file=sys.stderr)
        if summary["all_down"] and cfg.get("notify", {}).get("on_all_free_down", True):
            print(f"[free_model_pool] [ALERT] 所有免费模型不可用，已回退付费兜底。状态见 {status_path}",
                  file=sys.stderr)
    except Exception as e:
        # 刀⑥: 原 except:pass 静默吞错，改为 stderr 告警（与全挂告警同通道），不丢故障信号
        print(f"[free_model_pool] 状态文件写入异常: {status_path} ({e})", file=sys.stderr)
    return summary


if __name__ == "__main__":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(json.dumps(health_check_all(), ensure_ascii=False, indent=2))
