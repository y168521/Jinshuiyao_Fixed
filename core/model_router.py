# -*- coding: utf-8 -*-
"""【道衍推导·JS-20260727-32】
  阴阳：阳=免费优先(省费主动)；阴=付费兜底(守底，烧脑才花)。
  天地人：天=策略可配(auto/free_only/smart_only)；地=阈值/关键词外部化(config/model_router.json)；人=复盘(路由统计可见)。
  知止：默认保守免费，仅当数据过长/含深度推理词才升付费；绝不因路由错误而静默失败(双向兜底)。

金水谣 · 智能模型路由（大脑调度中枢）
  根据任务类型/复杂度，自动决定用免费小模型还是付费大模型：
    - 轻量(意图分类/记忆/提醒/复核)        → 免费
    - 日常对话                            → 免费；但含深度推理词或超长 → 付费
    - 数据总结/联网问答                    → 数据短免费，过长付费
  两端都带失败兜底：免费失败转付费，付费失败转免费，绝不静默崩。
  每次调用写统计(金水谣数据/model_route_stats.jsonl)，花费可见、可控。
"""
import json
import os
import time
import threading

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "model_router.json")
_STATS_PATH = os.path.join(_PROJECT_ROOT, "金水谣数据", "model_route_stats.jsonl")

_lock = threading.Lock()
_cfg_cache = None
_cfg_mtime = 0
_free_cfgs_cache = None


def _load_cfg():
    global _cfg_cache, _cfg_mtime
    try:
        mtime = os.path.getmtime(_CONFIG_PATH)
    except Exception as e:
        # 配置缺失 → 按默认策略（降级说明，C-013）
        import logging
        logging.getLogger(__name__).debug("[model_router] 配置 mtime 读取失败: %s", e)
        mtime = 0
    if _cfg_cache is not None and mtime == _cfg_mtime:
        return _cfg_cache
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            c = json.load(f)
    except Exception as e:
        # 配置损坏 → 用默认策略（降级说明，C-013）
        import logging
        logging.getLogger(__name__).debug("[model_router] 配置加载失败，用默认: %s", e)
        c = {"policy": "auto", "thresholds": {}, "deep_keywords": [], "log_calls": True}
    _cfg_cache = c
    _cfg_mtime = mtime
    return c


def _free_cfgs():
    global _free_cfgs_cache
    if _free_cfgs_cache is None:
        from core.free_model_pool import get_free_provider_cfgs
        _free_cfgs_cache = get_free_provider_cfgs()
    return _free_cfgs_cache


def _has_deep_keyword(text, keywords):
    t = text or ""
    for kw in keywords:
        if kw and kw in t:
            return kw
    return None


def classify(task_type, text, data_len=0):
    """返回 ('free'|'paid', reason)。纯函数（不联网），供测试与路由共用。

    判定逻辑（auto 策略下）：
      - 轻量任务(classify/reminder/memory/review)     → 永远免费
      - 显式烧脑(deep_reason/reasoning)               → 永远付费
      - 总结类(data_summary/web_qa)                   → 数据短免费，过长付费
      - 对话(chat)                                    → 默认免费；超长或含深度推理词升付费
      - 未知任务                                      → 保守免费（先省钱，失败由兜底处理）
    """
    cfg = _load_cfg()
    policy = (cfg.get("policy") or "auto").lower()
    th = cfg.get("thresholds", {}) or {}
    long_summary_chars = int(th.get("long_summary_chars", 1500))
    max_context_chars = int(th.get("max_context_chars", 800))
    deep = cfg.get("deep_keywords", []) or []

    if policy == "free_only":
        return "free", "策略=仅免费(用户指定)"
    if policy == "smart_only":
        return "paid", "策略=仅智能(用户指定)"

    t = (task_type or "").lower()
    # 轻量任务永远免费
    if t in ("classify", "reminder", "memory", "review"):
        return "free", f"轻量任务:{t}"
    # 显式烧脑
    if t in ("deep_reason", "reasoning"):
        return "paid", f"显式烧脑任务:{t}"
    # 总结类：按数据长度分
    if t in ("data_summary", "web_qa"):
        if data_len > long_summary_chars:
            return "paid", f"数据过长({data_len}字>{long_summary_chars})需更强总结"
        return "free", "短数据免费总结"
    # 对话：默认免费，深度词/超长升付费
    if t == "chat":
        if data_len > max_context_chars:
            return "paid", f"对话超长({data_len}字>{max_context_chars})"
        kw = _has_deep_keyword(text, deep)
        if kw:
            return "paid", f"对话含深度推理词「{kw}」"
        return "free", "日常对话"
    # 未知任务：保守免费（先省钱，失败由兜底处理）
    return "free", "默认免费(未知任务类型)"


def route(task_type, system, user, *, max_tokens=800, temperature=0.7,
          force_json=False, data_len=0, timeout=None):
    # ── P2-G5 并发门：限制同时 LLM 调用数，超出快速失败（背压，防线程堆积雪崩）──
    from core.concurrency_gate import get_gate
    _gcfg = _load_cfg()
    _gate = get_gate(int(_gcfg.get("max_concurrent", 8)))
    if not _gate.acquire(timeout=float(_gcfg.get("acquire_timeout", 2.0))):
        return None, "BUSY_OVERLOAD", {"reason": "并发达上限，请稍后重试",
                                       "policy": _gcfg.get("policy", "auto"),
                                       "task_type": task_type}
    try:
        return _route_body(task_type, system, user, max_tokens=max_tokens,
                           temperature=temperature, force_json=force_json,
                           data_len=data_len, timeout=timeout)
    finally:
        _gate.release()


def _route_body(task_type, system, user, *, max_tokens=800, temperature=0.7,
                force_json=False, data_len=0, timeout=None):
    # ── P1-G8 统一超时：默认从 config/model_router.json 的 call_timeout_seconds 取，
    #    替代原先硬编码的 90；配合 G7 熔断器 failure_threshold 形成跨供应商重试上限，
    #    杜绝单供应商卡死长挂、拖垮整笔请求。
    if timeout is None:
        timeout = int(_load_cfg().get("call_timeout_seconds", 60))
    """统一路由入口。返回 (text, error, meta)。

    meta = {decision, reason, policy, task_type, used}
      used ∈ free / free-fallback / paid / paid-fallback / none
    双向兜底：主选失败 → 切另一侧；绝不静默失败(两侧都挂才返回错误)。
    """
    from core import free_model_pool
    decision, reason = classify(task_type, user, data_len)
    meta = {"decision": decision, "reason": reason,
            "policy": _load_cfg().get("policy", "auto"), "task_type": task_type}
    if decision == "paid":
        text, err = free_model_pool.call_paid(
            system, user, timeout=timeout, max_tokens=max_tokens,
            temperature=temperature, force_json_mode=force_json)
        if text is not None and not err:
            return _done("paid", task_type, reason, text, user_prompt=user)
        # 付费失败 → 免费兜底
        text2, err2, _ = free_model_pool.call_ai_failover(
            _free_cfgs(), system, user, timeout=timeout, max_tokens=max_tokens,
            temperature=temperature, force_json_mode=force_json)
        if text2 is not None and not err2:
            return _done("free-fallback", task_type, reason + "(付费失败转免费)", text2, user_prompt=user)
        return None, err or err2, meta
    else:
        text, err, _ = free_model_pool.call_ai_failover(
            _free_cfgs(), system, user, timeout=timeout, max_tokens=max_tokens,
            temperature=temperature, force_json_mode=force_json)
        if text is not None and not err:
            return _done("free", task_type, reason, text, user_prompt=user)
        # 免费失败 → 付费兜底（安全网，绝不静默失败）
        text2, err2 = free_model_pool.call_paid(
            system, user, timeout=timeout, max_tokens=max_tokens,
            temperature=temperature, force_json_mode=force_json)
        if text2 is not None and not err2:
            return _done("paid-fallback", task_type, reason + "(免费失败转付费)", text2, user_prompt=user)
        return None, err or err2, meta


def _done(used, task_type, reason, text, user_prompt=None, cfg=None):
    cfg = cfg or _load_cfg()
    if cfg.get("log_calls", True):
        _log(used, task_type, reason)
    # ── P2-G4 影子测试：主链路成功后，按配置抽样异步跑候选模型 + 裁判评分（不阻塞）──
    if user_prompt is not None:
        try:
            from core import model_shadow
            model_shadow.maybe_shadow(task_type, user_prompt, text, used)
        except Exception:
            pass
    return text, None, {"used": used, "reason": reason,
                        "policy": cfg.get("policy", "auto"), "task_type": task_type}


def _log(used, task_type, reason):
    try:
        line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                           "task_type": task_type, "used": used, "reason": reason},
                          ensure_ascii=False)
        with _lock:
            with open(_STATS_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def route_report() -> str:
    """人类可读的路由统计报告（供「模型路由」查询意图调用）。"""
    cfg = _load_cfg()
    counts = {}
    try:
        with open(_STATS_PATH, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    d = json.loads(ln)
                except Exception:
                    continue
                u = d.get("used", "unknown")
                counts[u] = counts.get(u, 0) + 1
    except FileNotFoundError:
        pass
    total = sum(counts.values())
    paid = counts.get("paid", 0) + counts.get("paid-fallback", 0)
    free = counts.get("free", 0) + counts.get("free-fallback", 0)
    lines = [
        "【模型路由报告】",
        f"当前策略：{cfg.get('policy', 'auto')}",
        f"累计调用：{total} 次（免费 {free} / 付费 {paid}）",
    ]
    for k in ("free", "free-fallback", "paid", "paid-fallback"):
        if counts.get(k):
            lines.append(f"  - {k}: {counts[k]} 次")
    if total == 0:
        lines.append("（暂无记录，助手调用模型后会产生统计）")
    return "\n".join(lines)
