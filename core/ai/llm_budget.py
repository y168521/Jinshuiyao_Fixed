# -*- coding: utf-8 -*-
"""【道衍推导·P0-G2】LLM 跨调用成本熔断闸

阳 = 严格预算（守钱）；阴 = 免费优先（省费主动）。
天 = 限额外部化（config/llm_budget.json）；地 = 隔离（不与路由耦合）；人 = 复盘（花费可查）。
知止：单日 / 单分钟 / 单笔三重上限，超阈即跳闸，强制走免费，绝不静默烧穿预算。

用法（调用方无需改动返回结构，本模块在 free_model_pool 内部透明接入）：
  from core.ai.llm_budget import get_guard
  g = get_guard()
  if not g.allow_paid(provider="deepseek", prompt_chars=len(user_prompt)):
      # 预算已封顶 → 不发起付费调用，交由路由降级到免费
      ...
  cost = g.record("deepseek", in_tokens, out_tokens)   # 实际花费回写
"""
import os
import json
import time
import threading

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "llm_budget.json")

_lock = threading.Lock()
_cfg_cache = None
_cfg_mtime = 0

DEFAULT_PRICES = {"deepseek": {"input_yuan_per_1m": 0.5, "output_yuan_per_1m": 4.0}}


def _load_cfg():
    global _cfg_cache, _cfg_mtime
    try:
        mtime = os.path.getmtime(_CONFIG_PATH)
    except Exception:
        mtime = 0
    if _cfg_cache is not None and mtime == _cfg_mtime:
        return _cfg_cache
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            c = json.load(f)
    except Exception:
        c = {"enabled": False, "daily_limit_yuan": 20.0,
             "per_minute_limit_yuan": 1.0, "per_run_max_yuan": 0.05,
             "prices": DEFAULT_PRICES, "notify": {"on_trip": True}}
    _cfg_cache = c
    _cfg_mtime = mtime
    return c


def _estimate_cost(prompt_chars, completion_chars, provider, cfg):
    """按字符粗估一次付费调用成本（中文约 2 字符/token）。"""
    prices = cfg.get("prices", DEFAULT_PRICES).get(provider, DEFAULT_PRICES["deepseek"])
    in_t = max(prompt_chars, 1) / 2.0
    out_t = max(completion_chars, 1)
    return in_t / 1e6 * prices["input_yuan_per_1m"] + out_t / 1e6 * prices["output_yuan_per_1m"]


def _calc_usage_cost(provider, model, in_tokens, out_tokens, cfg):
    """按 provider:model 三级回退定价，返回本次花费（免费模型为 0）。"""
    if provider in ("siliconflow", "ollama") or provider is None:
        return 0.0
    prices_cfg = cfg.get("prices", DEFAULT_PRICES)
    key = f"{provider}:{model}" if model else provider
    prices = (prices_cfg.get(key) or prices_cfg.get(provider)
              or DEFAULT_PRICES.get(provider) or DEFAULT_PRICES["deepseek"])
    return (in_tokens or 0) / 1e6 * prices["input_yuan_per_1m"] + \
        (out_tokens or 0) / 1e6 * prices["output_yuan_per_1m"]


def _notify_trip(reason):
    """成本熔断告警（失败不抛出）。"""
    try:
        if _load_cfg().get("notify", {}).get("on_trip", True):
            import sys
            sys.stderr.write(
                f"[llm_budget] [ALERT] 成本熔断已触发({reason})，强制走免费模型直至冷却。\n")
    except Exception as _ne:
        import logging
        logging.getLogger(__name__).debug("[llm_budget] 熔断告警发送失败: %s", _ne)


def _check_allow_paid(guard, provider, est_cost, prompt_chars, cfg):
    """预算检查核心逻辑（假定已上锁 + rollover）。返回是否允许付费。"""
    if guard._tripped:
        return False
    if est_cost is None:
        est_cost = guard.estimate(prompt_chars, 400, provider) if prompt_chars else 0.0
    if est_cost > float(cfg.get("per_run_max_yuan", 0.05)):
        return False
    if guard._daily_spent + est_cost > float(cfg.get("daily_limit_yuan", 20.0)):
        guard._trip("daily")
        return False
    minute_sum = sum(c for _, c in guard._minute_window)
    if minute_sum + est_cost > float(cfg.get("per_minute_limit_yuan", 1.0)):
        return False
    return True


def _rollover_guard(guard):
    """日切 + 分钟窗口裁剪 + 跳闸冷却恢复。"""
    now = time.time()
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    if day != guard._day_key:
        guard._day_key = day
        guard._daily_spent = 0.0
    guard._minute_window = [(t, c) for (t, c) in guard._minute_window if t >= now - 60]
    if guard._tripped and now - guard._trip_ts >= guard._trip_cooldown:
        guard._tripped = False


def _record_spending(guard, cost, cfg):
    """记录花费（假定已上锁 + rollover）。"""
    guard._daily_spent += cost
    guard._minute_window.append((time.time(), cost))
    if guard._daily_spent > float(cfg.get("daily_limit_yuan", 20.0)):
        guard._trip("daily")


def _build_status(guard, cfg):
    """构造状态字典（假定已上锁 + rollover）。"""
    return {
        "enabled": cfg.get("enabled", True),
        "daily_spent": round(guard._daily_spent, 4),
        "daily_limit": float(cfg.get("daily_limit_yuan", 20.0)),
        "minute_spent": round(sum(c for _, c in guard._minute_window), 4),
        "per_minute_limit": float(cfg.get("per_minute_limit_yuan", 1.0)),
        "tripped": guard._tripped,
    }


class LLMBudgetGuard:
    _instance = None
    _ilock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._ilock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._daily_spent = 0.0
        self._day_key = time.strftime("%Y-%m-%d")
        self._minute_window = []
        self._tripped = False
        self._trip_ts = 0.0
        self._trip_cooldown = 3600.0

    def _rollover(self):
        _rollover_guard(self)

    def estimate(self, prompt_chars, completion_chars=400, provider="deepseek"):
        return _estimate_cost(prompt_chars, completion_chars, provider, _load_cfg())

    def allow_paid(self, provider="deepseek", est_cost=None, prompt_chars=0):
        cfg = _load_cfg()
        if not cfg.get("enabled", True):
            return True
        with _lock:
            self._rollover()
            return _check_allow_paid(self, provider, est_cost, prompt_chars, cfg)

    def record(self, provider, in_tokens, out_tokens, model=None):
        cfg = _load_cfg()
        if not cfg.get("enabled", True):
            return 0.0
        cost = _calc_usage_cost(provider, model, in_tokens, out_tokens, cfg)
        if cost <= 0:
            return 0.0
        with _lock:
            self._rollover()
            _record_spending(self, cost, cfg)
        return cost

    def _trip(self, reason):
        self._tripped, self._trip_ts = True, time.time()
        _notify_trip(reason)

    @property
    def tripped(self):
        with _lock:
            self._rollover()
            return self._tripped

    def status(self):
        with _lock:
            self._rollover()
            return _build_status(self, _load_cfg())


def get_guard():
    """获取全局成本闸单例。"""
    return LLMBudgetGuard()
