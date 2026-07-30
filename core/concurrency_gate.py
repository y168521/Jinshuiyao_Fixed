# -*- coding: utf-8 -*-
"""【道衍推导·P2-G5】并发门 + 背压

阳 = 限流保稳定；阴 = 快速失败不雪崩。
天 = 上限外部化（config/model_router.json: max_concurrent / acquire_timeout）；地 = 隔离（单例信号量）；人 = 复盘（可查 active 数）。
知止：限制同时进行的 LLM 调用数，超出进入有界等待；等待超时即快速失败（BUSY_OVERLOAD），
     由上层路由降级，绝不无限制堆积线程把服务拖垮。

用法（在 model_router.route 入口注入）：
  from core.concurrency_gate import get_gate
  if not get_gate(max_concurrent).acquire(timeout=acquire_timeout):
      return None, "BUSY_OVERLOAD", {...}
  try: ... finally: gate.release()
"""
import threading


class ConcurrencyGate:
    """有界信号量实现的并发门（单例）。"""
    _instance = None
    _ilock = threading.Lock()

    def __new__(cls, max_concurrent=8):
        if cls._instance is None:
            with cls._ilock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init(max_concurrent)
        return cls._instance

    def _init(self, max_concurrent):
        self._max = int(max_concurrent)
        self._sem = threading.Semaphore(self._max)

    def acquire(self, timeout=2.0):
        """尝试获取一个并发槽，超时返回 False（应快速失败）。"""
        return self._sem.acquire(timeout=timeout)

    def release(self):
        """释放一个并发槽。"""
        try:
            self._sem.release()
        except Exception:
            pass

    @property
    def active(self):
        """当前活跃并发数（监控用）。"""
        return self._max - self._sem._value

    @property
    def max_concurrent(self):
        return self._max


def get_gate(max_concurrent=8):
    """获取全局并发门单例。"""
    return ConcurrencyGate(max_concurrent)
