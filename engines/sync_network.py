# -*- coding: utf-8 -*-
"""金水谣系统 - 离线优先同步管理器子模块（JS-20260810-10 由 engines/sync_manager.py 拆分）

NetworkDetector - 轻量级网络状态检测（不依赖第三方网络检测库，requests 超时探测）"""
import os
import json
import time
import logging
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# 用于网络探测的轻量级 URL 列表（按优先级排序）
_PROBE_URLS = [
    "https://www.baidu.com",
    "https://www.qq.com",
    "https://httpbin.org/get",
]

# 网络检测默认超时（秒）
_DEFAULT_NETWORK_TIMEOUT = 3

# 离线队列文件名
_OFFLINE_QUEUE_FILENAME = "offline_queue.jsonl"

# 同步历史最大保留条数
_MAX_SYNC_HISTORY = 50



class NetworkDetector:
    """轻量级网络状态检测

    使用 requests HEAD 请求探测网络连通性，不依赖第三方网络检测库。
    采用 URL 直连方式，避免 DNS 查询在某些离线环境中被劫持的问题。
    """

    def __init__(self):
        self._cache_online: Optional[bool] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 30.0  # 缓存有效期 30 秒
        self._last_latency: float = -1.0
        self._lock = threading.Lock()

    def is_online(self, timeout: float = _DEFAULT_NETWORK_TIMEOUT) -> bool:
        """检测网络是否可用

        尝试以 HEAD 请求连接一个轻量级 URL，超时由调用者指定。
        结果会被缓存，在 TTL 内的重复调用直接返回缓存值。

        Args:
            timeout: 连接超时秒数，默认 3 秒

        Returns:
            True 表示网络可用，False 表示不可用
        """
        # 检查缓存
        now = time.time()
        with self._lock:
            if self._cache_online is not None and (now - self._cache_time) < self._cache_ttl:
                return self._cache_online

        # 实际探测
        try:
            import requests
        except ImportError:
            logger.warning("requests 库不可用，默认视为离线")
            with self._lock:
                self._cache_online = False
                self._cache_time = now
            return False

        online = False
        latency = float("inf")

        for url in _PROBE_URLS:
            try:
                start = time.time()
                resp = requests.head(
                    url,
                    timeout=timeout,
                    allow_redirects=True,
                    headers={"Connection": "close"},
                )
                elapsed_ms = (time.time() - start) * 1000.0
                # 任何 2xx/3xx 响应都视为在线
                if resp.status_code < 400:
                    online = True
                    latency = elapsed_ms
                    break  # 第一个成功即返回
            except requests.RequestException:
                continue

        # 写入缓存
        with self._lock:
            self._cache_online = online
            self._cache_time = now
            # 顺便缓存延迟（供 get_network_info 使用）
            if online:
                self._last_latency = latency

        status = "在线" if online else "离线"
        logger.debug("网络检测结果: %s (延迟 %.1fms)", status, latency if online else -1)
        return online

    def get_network_info(self) -> dict:
        """获取网络详细信息

        Returns:
            包含 online/latency_ms/last_check 的字典
        """
        online = self.is_online()
        latency = -1.0
        if online:
            with self._lock:
                latency = getattr(self, "_last_latency", -1.0)
        return {
            "online": online,
            "latency_ms": round(latency, 1),
            "last_check": datetime.now().isoformat(timespec="seconds"),
        }

    def invalidate_cache(self):
        """清除网络状态缓存，强制下次检测时重新探测"""
        with self._lock:
            self._cache_online = None
            self._cache_time = 0.0


# ═══════════════════════════════════════════════════════════════════════════
# OfflineQueue - 离线操作队列
# ═══════════════════════════════════════════════════════════════════════════
