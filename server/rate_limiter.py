# -*- coding: utf-8 -*-
"""【道衍推导·P0-G3】请求限流 + 全局异常流量跳闸

天 = 阈值可配（常量集中，按需外置）；地 = 隔离（单例，不污染路由逻辑）；人 = 复盘（跳闸写日志可查）。
知止：每 IP 令牌桶防单点滥用；全局 QPS 突增 ≥500% 即跳闸，拒绝洪水并告警，
     守护本机不被刷爆、也不让异常流量烧穿付费预算。

用法（在 server/router.py 的 do_GET/do_POST 入口注入）：
  from .rate_limiter import rate_limiter
  ok, retry_after = rate_limiter().allow(self.client_address[0])
  if not ok:
      self.send_response(429); self.send_header('Retry-After', str(retry_after)); ...
      return
注：本机 127.0.0.1 永远放行（主人操作不受限）；/health 健康检查在 router 层豁免。
"""
import time
import threading
from collections import deque

# ── 阈值（如需外部化，可后续搬进 config/rate_limit.json）──
_MAX_BUCKET = 10            # 单 IP 突发令牌上限
_REFILL_PER_SEC = 0.5       # 单 IP 令牌补充速率（=30 个/分钟）
_ANOMALY_MULT = 5.0         # 全局突增倍数阈值（500%）
_ANOMALY_WINDOW = 60        # 全局滑动窗口（秒）
_ANOMALY_LOOKBACK = 5       # 当前突增判定窗口（秒）
_ANOMALY_MIN_BASE = 1.0     # 基线最小每秒均值，避免极小值误判
_TRIP_COOLDOWN = 60.0       # 全局跳闸冷却（秒），冷却后自动恢复


class RateLimiter:
    """单例限流器：每 IP 令牌桶 + 全局异常流量检测。"""
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
        self._buckets = {}              # ip -> [tokens, last_ts]
        self._bl = threading.Lock()
        self._global_ts = deque()       # 全局请求时间戳（滑动窗口）
        self._gl = threading.Lock()
        self._anomaly_tripped = False
        self._anomaly_ts = 0.0

    def _bucket_allow(self, ip):
        now = time.time()
        b = self._buckets.get(ip)
        if b is None:
            # 首个请求消耗 1 令牌，其余留在桶里
            self._buckets[ip] = [float(_MAX_BUCKET - 1), now]
            return True
        tokens, last = b
        tokens = min(_MAX_BUCKET, tokens + (now - last) * _REFILL_PER_SEC)
        if tokens >= 1.0:
            b[0] = tokens - 1.0
            b[1] = now
            return True
        b[1] = now
        return False

    def _note_global(self):
        now = time.time()
        with self._gl:
            self._global_ts.append(now)
            cutoff = now - _ANOMALY_WINDOW
            while self._global_ts and self._global_ts[0] < cutoff:
                self._global_ts.popleft()
            # 冷却恢复
            if self._anomaly_tripped and now - self._anomaly_ts >= _TRIP_COOLDOWN:
                self._anomaly_tripped = False
            # 异常流量判定
            if not self._anomaly_tripped and len(self._global_ts) > _ANOMALY_WINDOW * _ANOMALY_MIN_BASE:
                total = len(self._global_ts)
                baseline = total / _ANOMALY_WINDOW
                cur = sum(1 for t in self._global_ts if t >= now - _ANOMALY_LOOKBACK)
                cur_per_sec = cur / _ANOMALY_LOOKBACK
                if baseline >= _ANOMALY_MIN_BASE and cur_per_sec >= _ANOMALY_MULT * baseline:
                    self._anomaly_tripped = True
                    self._anomaly_ts = now
                    import sys
                    sys.stderr.write(
                        "[rate_limiter] [ALERT] 检测到全局流量突增(≥500%)，已跳闸限流并告警管理员。\n")

    def allow(self, ip):
        """返回 (ok, retry_after_sec)。本机(127.0.0.1/::1)永远放行。"""
        if ip in ("127.0.0.1", "::1", "localhost"):
            self._note_global()
            return True, 0
        self._note_global()
        if self._anomaly_tripped:
            return False, 1
        with self._bl:
            ok = self._bucket_allow(ip)
        return ok, (0 if ok else 1)

    @property
    def anomaly_tripped(self):
        with self._gl:
            # 顺带做冷却恢复检查
            if self._anomaly_tripped and time.time() - self._anomaly_ts >= _TRIP_COOLDOWN:
                self._anomaly_tripped = False
            return self._anomaly_tripped


def rate_limiter():
    """获取全局限流器单例。"""
    return RateLimiter()
