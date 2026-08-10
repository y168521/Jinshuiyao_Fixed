# -*- coding: utf-8 -*-
"""金水谣系统 - 离线优先同步管理器子模块（JS-20260810-10 由 engines/sync_manager.py 拆分）

OfflineQueue - 离线请求队列（本地 JSONL 持久化，联网后回放）"""
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



class OfflineQueue:
    """离线操作队列 - 离线时缓存待同步的操作

    使用 JSONL 格式（每行一个 JSON 对象）持久化到磁盘。
    文件路径: <data_dir>/sync/offline_queue.jsonl

    线程安全：所有文件操作通过锁保护。
    """

    def __init__(self, data_dir: str = "金水谣数据"):
        self._queue_dir = os.path.join(data_dir, "sync")
        self._queue_file = os.path.join(self._queue_dir, _OFFLINE_QUEUE_FILENAME)
        self._lock = threading.Lock()
        self._ensure_dir()

    def _ensure_dir(self):
        """确保队列目录存在"""
        try:
            os.makedirs(self._queue_dir, exist_ok=True)
        except OSError as e:
            logger.error("创建同步队列目录失败 [%s]: %s", self._queue_dir, e)
            raise

    def enqueue(self, operation: str, data: dict):
        """将操作加入队列

        Args:
            operation: 操作类型，如 "sync_knowledge", "report_analytics",
                       "download_update" 等
            data: 操作附带的数据字典
        """
        entry = {
            "operation": operation,
            "data": data,
            "enqueued_at": datetime.now().isoformat(timespec="seconds"),
        }
        line = json.dumps(entry, ensure_ascii=False)

        with self._lock:
            try:
                with open(self._queue_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                logger.info("操作已加入离线队列: %s (队列长度=%d)",
                            operation, self._peek_unlocked())
            except OSError as e:
                logger.error("写入离线队列失败 [%s]: %s", self._queue_file, e)
                raise

    def dequeue_all(self) -> list:
        """取出所有待同步操作

        读取后将清空队列文件。

        Returns:
            操作条目列表，每个条目为 dict，包含 operation/data/enqueued_at
        """
        with self._lock:
            entries = []
            if not os.path.isfile(self._queue_file):
                return entries
            try:
                with open(self._queue_file, "r", encoding="utf-8") as f:
                    for raw_line in f:
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            entry = json.loads(raw_line)
                            entries.append(entry)
                        except json.JSONDecodeError as e:
                            logger.warning("离线队列中有无法解析的行，已跳过: %s", e)
                            continue
            except OSError as e:
                logger.error("读取离线队列失败 [%s]: %s", self._queue_file, e)
                raise

            # 读取成功后清空文件
            try:
                with open(self._queue_file, "w", encoding="utf-8") as f:
                    pass  # 清空文件内容
            except OSError as e:
                logger.error("清空离线队列文件失败: %s", e)

            logger.info("从离线队列取出 %d 条操作", len(entries))
            return entries

    def peek(self) -> int:
        """查看队列中有多少待同步操作

        Returns:
            待同步操作数量
        """
        with self._lock:
            return self._peek_unlocked()

    def _peek_unlocked(self) -> int:
        """不加锁的内部计数方法（调用方须持有锁）"""
        if not os.path.isfile(self._queue_file):
            return 0
        try:
            count = 0
            with open(self._queue_file, "r", encoding="utf-8") as f:
                for raw_line in f:
                    if raw_line.strip():
                        count += 1
            return count
        except OSError as e:
            logger.error("读取离线队列计数失败: %s", e)
            return -1

    def clear(self):
        """清空队列（同步成功后调用）"""
        with self._lock:
            try:
                if os.path.isfile(self._queue_file):
                    with open(self._queue_file, "w", encoding="utf-8") as f:
                        pass
                    logger.info("离线队列已清空")
                else:
                    logger.debug("离线队列文件不存在，无需清空")
            except OSError as e:
                logger.error("清空离线队列失败: %s", e)
                raise


# ═══════════════════════════════════════════════════════════════════════════
# SyncManager - 同步管理器
# ═══════════════════════════════════════════════════════════════════════════
