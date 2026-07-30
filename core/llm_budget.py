# -*- coding: utf-8 -*-
"""【道衍推导·P0-G2】LLM 跨调用成本熔断闸

阳 = 严格预算（守钱）；阴 = 免费优先（省费主动）。
天 = 限额外部化（config/llm_budget.json）；地 = 隔离（不与路由耦合）；人 = 复盘（花费可查）。
知止：单日 / 单分钟 / 单笔三重上限，超阈即跳闸，强制走免费，绝不静默烧穿预算。

用法（调用方无需改动返回结构，本模块在 free_model_pool 内部透明接入）：
  from core.llm_budget import get_guard
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

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


class LLMBudgetGuard:
    """窗口化 Token/Cost 预算守卫（单例）。线程安全。"""
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
        self._minute_window = []          # [(ts, cost), ...] 最近 60 秒
        self._tripped = False
        self._trip_ts = 0.0
        self._trip_cooldown = 3600.0      # 跳闸冷却 1 小时（避免瞬间反复抖动）

    # ── 内部：日切 + 窗口裁剪 + 冷却恢复 ──
    def _rollover(self):
        now = time.time()
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if day != self._day_key:
            self._day_key = day
            self._daily_spent = 0.0
        cutoff = now - 60
        self._minute_window = [(t, c) for (t, c) in self._minute_window if t >= cutoff]
        if self._tripped and now - self._trip_ts >= self._trip_cooldown:
            self._tripped = False

    def estimate(self, prompt_chars, completion_chars=400, provider="deepseek"):
        """按字符粗估一次付费调用成本（中文约 2 字符/token）。仅用于发起前预判。"""
        cfg = _load_cfg()
        prices = cfg.get("prices", DEFAULT_PRICES).get(provider, DEFAULT_PRICES["deepseek"])
        in_t = max(prompt_chars, 1) / 2.0
        out_t = max(completion_chars, 1)
        return in_t / 1e6 * prices["input_yuan_per_1m"] + out_t / 1e6 * prices["output_yuan_per_1m"]

    def allow_paid(self, provider="deepseek", est_cost=None, prompt_chars=0):
        """是否允许发起一次付费调用。返回 True/False（False = 预算封顶，应降级免费）。"""
        cfg = _load_cfg()
        if not cfg.get("enabled", True):
            return True
        with _lock:
            self._rollover()
            if self._tripped:
                return False
            per_run = float(cfg.get("per_run_max_yuan", 0.05))
            if est_cost is None:
                est_cost = self.estimate(prompt_chars, 400, provider) if prompt_chars else 0.0
            if est_cost > per_run:
                return False
            if self._daily_spent + est_cost > float(cfg.get("daily_limit_yuan", 20.0)):
                self._trip("daily")
                return False
            minute_sum = sum(c for _, c in self._minute_window)
            if minute_sum + est_cost > float(cfg.get("per_minute_limit_yuan", 1.0)):
                return False
            return True

    def record(self, provider, in_tokens, out_tokens):
        """记录一次实际花费（来自 API usage）。返回 cost（免费池为 0）。"""
        cfg = _load_cfg()
        if not cfg.get("enabled", True):
            return 0.0
        if provider in ("siliconflow",) or provider is None:
            return 0.0
        prices = cfg.get("prices", DEFAULT_PRICES).get(provider, DEFAULT_PRICES["deepseek"])
        cost = (in_tokens or 0) / 1e6 * prices["input_yuan_per_1m"] + \
               (out_tokens or 0) / 1e6 * prices["output_yuan_per_1m"]
        if cost <= 0:
            return 0.0
        with _lock:
            self._rollover()
            self._daily_spent += cost
            self._minute_window.append((time.time(), cost))
            if self._daily_spent > float(cfg.get("daily_limit_yuan", 20.0)):
                self._trip("daily")
        return cost

    def _trip(self, reason):
        self._tripped = True
        self._trip_ts = time.time()
        try:
            if _load_cfg().get("notify", {}).get("on_trip", True):
                import sys
                sys.stderr.write(
                    f"[llm_budget] [ALERT] 成本熔断已触发({reason})，强制走免费模型直至冷却。\n")
        except Exception:
            pass

    @property
    def tripped(self):
        with _lock:
            self._rollover()
            return self._tripped

    def status(self):
        with _lock:
            self._rollover()
            cfg = _load_cfg()
            return {
                "enabled": cfg.get("enabled", True),
                "daily_spent": round(self._daily_spent, 4),
                "daily_limit": float(cfg.get("daily_limit_yuan", 20.0)),
                "minute_spent": round(sum(c for _, c in self._minute_window), 4),
                "per_minute_limit": float(cfg.get("per_minute_limit_yuan", 1.0)),
                "tripped": self._tripped,
            }


def get_guard():
    """获取全局成本闸单例。"""
    return LLMBudgetGuard()
