# -*- coding: utf-8 -*-
"""子系统熔断降级模块

为各子系统提供熔断器（Circuit Breaker）模式：
  - 连续失败达到阈值后自动熔断，停止请求真实数据源
  - 熔断期间自动降级为模拟/备用数据
  - 半开状态探测：熔断到期后尝试一次请求，成功则恢复，失败则继续熔断

配合 audit_log 自动记录所有关键操作，形成闭环。
"""
import os
import time
import json
import logging
import threading
from datetime import datetime
from typing import Callable, Optional, Dict

logger = logging.getLogger(__name__)

# 状态常量
STATE_CLOSED = "closed"       # 正常：请求正常通过
STATE_OPEN = "open"           # 熔断：拒绝请求，直接降级
STATE_HALF_OPEN = "half_open"  # 半开：尝试一次请求探测


def _maybe_transition_to_half_open(cb) -> None:
    """若处于 open 且已过恢复期，则转为 half_open（调用方需持锁）。"""
    if cb._state == STATE_OPEN and time.time() - cb._last_failure_time >= cb.recovery_timeout:
        cb._state = STATE_HALF_OPEN
        cb._half_open_calls = 0
        logger.info("[熔断器 %s] 进入半开状态，尝试恢复", cb.name)


def _cb_state(cb) -> str:
    with cb._lock:
        _maybe_transition_to_half_open(cb)
        return cb._state


def _cb_can_execute(cb) -> bool:
    with cb._lock:
        _maybe_transition_to_half_open(cb)
        if cb._state == STATE_OPEN:
            return False
        if cb._state == STATE_HALF_OPEN:
            if cb._half_open_calls >= cb.half_open_max_calls:
                return False
            cb._half_open_calls += 1
            return True
        return True


def _cb_record_success(cb) -> None:
    with cb._lock:
        cb._total_success += 1
        if cb._state in (STATE_HALF_OPEN, STATE_OPEN):
            logger.info("[熔断器 %s] 恢复正常（成功探测）", cb.name)
        cb._state = STATE_CLOSED
        cb._failure_count = 0
        cb._half_open_calls = 0


def _cb_record_failure(cb) -> None:
    with cb._lock:
        cb._total_failure += 1
        cb._failure_count += 1
        cb._last_failure_time = time.time()
        if cb._state == STATE_HALF_OPEN:
            cb._state = STATE_OPEN
            logger.warning("[熔断器 %s] 半开探测失败，重新熔断", cb.name)
        elif cb._failure_count >= cb.failure_threshold:
            if cb._state != STATE_OPEN:
                cb._state = STATE_OPEN
                logger.warning("[熔断器 %s] 连续失败%d次，触发熔断（%d秒后重试）",
                               cb.name, cb._failure_count, cb.recovery_timeout)


def _cb_record_fallback(cb) -> None:
    with cb._lock:
        cb._total_fallback += 1


def _cb_call(cb, func: Callable, fallback: Optional[Callable] = None, *args, **kwargs):
    """执行函数调用，自动熔断降级。fallback 为 None 且失败时抛出异常。"""
    if not _cb_can_execute(cb):
        _cb_record_fallback(cb)
        logger.debug("[熔断器 %s] 熔断中，使用降级数据", cb.name)
        if fallback is not None:
            return fallback(*args, **kwargs)
        raise RuntimeError(f"Circuit breaker '{cb.name}' is open")
    try:
        result = func(*args, **kwargs)
        _cb_record_success(cb)
        return result
    except Exception as e:
        _cb_record_failure(cb)
        logger.warning("[熔断器 %s] 调用失败: %s", cb.name, e)
        if fallback is not None:
            _cb_record_fallback(cb)
            return fallback(*args, **kwargs)
        raise


def _cb_get_stats(cb) -> dict:
    with cb._lock:
        return {
            "name": cb.name, "state": cb._state,
            "failure_count": cb._failure_count,
            "total_success": cb._total_success,
            "total_failure": cb._total_failure,
            "total_fallback": cb._total_fallback,
            "last_failure": (datetime.fromtimestamp(cb._last_failure_time)
                              .strftime("%Y-%m-%d %H:%M:%S") if cb._last_failure_time else None),
        }


def _cb_reset(cb) -> None:
    with cb._lock:
        cb._state = STATE_CLOSED
        cb._failure_count = 0
        cb._last_failure_time = 0.0
        cb._half_open_calls = 0
        cb._total_success = 0
        cb._total_failure = 0
        cb._total_fallback = 0


class CircuitBreaker:
    """熔断器：单个子系统/数据源的熔断状态管理（方法委托模块级函数）。"""

    def __init__(self, name: str, failure_threshold: int = 3,
                 recovery_timeout: int = 60, half_open_max_calls: int = 1):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self._state = STATE_CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0
        self._lock = threading.RLock()
        self._total_success = 0
        self._total_failure = 0
        self._total_fallback = 0

    @property
    def state(self) -> str:
        return _cb_state(self)

    def can_execute(self) -> bool:
        return _cb_can_execute(self)

    def record_success(self):
        _cb_record_success(self)

    def record_failure(self):
        _cb_record_failure(self)

    def record_fallback(self):
        _cb_record_fallback(self)

    def call(self, func: Callable, fallback: Optional[Callable] = None, *args, **kwargs):
        return _cb_call(self, func, fallback, *args, **kwargs)

    def get_stats(self) -> dict:
        return _cb_get_stats(self)

    def reset(self):
        _cb_reset(self)


# ---------------------------------------------------------------------------
# 全局熔断器注册表
# ---------------------------------------------------------------------------

class CircuitBreakerRegistry:
    """熔断器注册表 - 管理所有子系统的熔断器实例（单例模式）"""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._breakers: Dict[str, CircuitBreaker] = {}
                    cls._instance._lock = threading.Lock()
        return cls._instance

    def get(self, name: str, **kwargs) -> CircuitBreaker:
        """获取或创建熔断器"""
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name, **kwargs)
            return self._breakers[name]

    def list_all(self) -> Dict[str, dict]:
        """列出所有熔断器状态"""
        with self._lock:
            return {name: cb.get_stats() for name, cb in self._breakers.items()}

    def reset_all(self):
        """重置所有熔断器（用于测试）"""
        with self._lock:
            for cb in self._breakers.values():
                cb.reset()


# 便捷函数
def get_breaker(name: str, **kwargs) -> CircuitBreaker:
    """获取全局熔断器实例"""
    return CircuitBreakerRegistry().get(name, **kwargs)


def all_breaker_stats() -> Dict[str, dict]:
    """获取所有熔断器统计"""
    return CircuitBreakerRegistry().list_all()
