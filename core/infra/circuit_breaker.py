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
from typing import Callable, Optional, Any, Dict

logger = logging.getLogger(__name__)

# 状态常量
STATE_CLOSED = "closed"       # 正常：请求正常通过
STATE_OPEN = "open"           # 熔断：拒绝请求，直接降级
STATE_HALF_OPEN = "half_open"  # 半开：尝试一次请求探测


class CircuitBreaker:
    """熔断器 - 单个子系统/数据源的熔断状态管理

    典型用法:
        cb = CircuitBreaker("stock_akshare", failure_threshold=3, recovery_timeout=60)
        try:
            result = cb.call(fetch_real_data, fallback=mock_data)
        except Exception:
            ...
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 1,
    ):
        """
        Args:
            name: 熔断器名称（用于日志和状态查询）
            failure_threshold: 连续失败多少次后熔断，默认3次
            recovery_timeout: 熔断后多少秒进入半开状态尝试恢复，默认60秒
            half_open_max_calls: 半开状态最多允许几次探测请求，默认1次
        """
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
        """当前状态（自动检查是否应从open转为half_open）"""
        with self._lock:
            if self._state == STATE_OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = STATE_HALF_OPEN
                    self._half_open_calls = 0
                    logger.info("[熔断器 %s] 进入半开状态，尝试恢复", self.name)
            return self._state

    def can_execute(self) -> bool:
        """是否允许执行真实请求（单次锁获取，避免TOCTOU竞争）"""
        with self._lock:
            # 内联状态转换检查（不再调用 self.state 属性）
            if self._state == STATE_OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = STATE_HALF_OPEN
                    self._half_open_calls = 0
                    logger.info("[熔断器 %s] 进入半开状态，尝试恢复", self.name)
                else:
                    return False
            if self._state == STATE_HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    return False
                self._half_open_calls += 1
                return True
            return True  # CLOSED

    def record_success(self):
        """记录一次成功"""
        with self._lock:
            self._total_success += 1
            if self._state in (STATE_HALF_OPEN, STATE_OPEN):
                logger.info("[熔断器 %s] 恢复正常（成功探测）", self.name)
            self._state = STATE_CLOSED
            self._failure_count = 0
            self._half_open_calls = 0

    def record_failure(self):
        """记录一次失败"""
        with self._lock:
            self._total_failure += 1
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == STATE_HALF_OPEN:
                # 半开状态下失败，立即回到熔断
                self._state = STATE_OPEN
                logger.warning("[熔断器 %s] 半开探测失败，重新熔断", self.name)
            elif self._failure_count >= self.failure_threshold:
                if self._state != STATE_OPEN:
                    self._state = STATE_OPEN
                    logger.warning(
                        "[熔断器 %s] 连续失败%d次，触发熔断（%d秒后重试）",
                        self.name, self._failure_count, self.recovery_timeout,
                    )

    def record_fallback(self):
        """记录一次降级使用"""
        with self._lock:
            self._total_fallback += 1

    def call(
        self,
        func: Callable,
        fallback: Optional[Callable] = None,
        *args,
        **kwargs,
    ) -> Any:
        """执行函数调用，自动熔断降级

        Args:
            func: 真实数据源函数
            fallback: 降级函数（熔断或失败时调用），为None则失败时抛出异常
            *args, **kwargs: 传递给func和fallback的参数

        Returns:
            func或fallback的返回值

        Raises:
            当fallback为None且调用失败时，原样抛出异常
        """
        if not self.can_execute():
            # 熔断中，直接降级
            self.record_fallback()
            logger.debug("[熔断器 %s] 熔断中，使用降级数据", self.name)
            if fallback is not None:
                return fallback(*args, **kwargs)
            raise RuntimeError(f"Circuit breaker '{self.name}' is open")

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            logger.warning("[熔断器 %s] 调用失败: %s", self.name, e)
            if fallback is not None:
                self.record_fallback()
                return fallback(*args, **kwargs)
            raise

    def get_stats(self) -> dict:
        """获取熔断器统计信息"""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state,
                "failure_count": self._failure_count,
                "total_success": self._total_success,
                "total_failure": self._total_failure,
                "total_fallback": self._total_fallback,
                "last_failure": (
                    datetime.fromtimestamp(self._last_failure_time).strftime("%Y-%m-%d %H:%M:%S")
                    if self._last_failure_time else None
                ),
            }

    def reset(self):
        """重置熔断器状态（用于测试）"""
        with self._lock:
            self._state = STATE_CLOSED
            self._failure_count = 0
            self._last_failure_time = 0.0
            self._half_open_calls = 0
            self._total_success = 0
            self._total_failure = 0
            self._total_fallback = 0


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
