# -*- coding: utf-8 -*-
"""金水谣系统 - JSONL 日志文件轮转工具

统一日志轮转模块（2026-08-10 架构体检合并：原 core/log_rotation.py 并入此处）。

两个轮转风格并存：
  - check_and_rotate()：覆盖式，最多保留 1 个备份（写入前调用，轻量）
  - rotate_log()：递进式，保留 N 个备份（原 core 版，watchdog 等场景使用）

用法：
    from utils.log_rotation import check_and_rotate, rotate_log
    check_and_rotate("/path/to/xxx.jsonl", max_size_mb=5)
    rotate_log("/path/to/xxx.log", max_size_mb=5, keep_backups=3)

线程安全：使用 utils.locks.log_rotate_lock 保护轮转操作。
"""
import os
import sys
import logging
from typing import Optional

from .locks import log_rotate_lock

logger = logging.getLogger(__name__)


def _safe_icon(emoji: str, fallback: str) -> str:
    """根据 stdout 编码选择 Emoji 或纯文本替代符号"""
    enc = (getattr(sys.stdout, 'encoding', '') or '').lower()
    if 'utf' in enc:
        return emoji
    return fallback


def check_and_rotate(filepath, max_size_mb=5):
    """检查日志文件大小，超过阈值时执行轮转。

    轮转逻辑：
      1. 将当前文件重命名为 filepath.1（已有 .1 则覆盖）
      2. 后续写入会自动创建新文件（追加模式 open 时自动创建）

    Args:
        filepath: 日志文件绝对路径（如 xxx.jsonl）
        max_size_mb: 触发轮转的大小阈值（MB），默认 5MB

    Returns:
        bool: True 表示执行了轮转，False 表示无需轮转或出错
    """
    try:
        # 文件不存在则无需轮转
        if not os.path.isfile(filepath):
            return False

        # 检查文件大小
        file_size = os.path.getsize(filepath)
        max_size_bytes = max_size_mb * 1024 * 1024

        if file_size < max_size_bytes:
            return False

        # 需要轮转 —— 加锁防止并发冲突
        with log_rotate_lock:
            # 双重检查：拿到锁后再确认一次（可能其他线程已轮转）
            if not os.path.isfile(filepath):
                return False
            if os.path.getsize(filepath) < max_size_bytes:
                return False

            backup_path = filepath + ".1"

            # 已有备份则先删除（覆盖式，最多保留1个备份）
            if os.path.isfile(backup_path):
                os.remove(backup_path)

            # 重命名当前文件为备份
            os.rename(filepath, backup_path)

            icon = _safe_icon("🔄", "[ROTATE]")
            logger.info(
                "%s 日志轮转: %s (%.2f MB) -> %s",
                icon, os.path.basename(filepath),
                file_size / (1024 * 1024),
                os.path.basename(backup_path),
            )
            return True

    except Exception as e:
        # 轮转失败不应阻断主流程，仅记录警告
        logger.warning("[log_rotation] 轮转检查异常 (%s): %s", filepath, e)
        return False


def rotate_log(log_path: str, max_size_mb: float = 5, keep_backups: int = 3) -> bool:
    """递进式日志轮转：文件超限时重命名 .bak.1，旧备份递进，保留最近 N 个。

    （2026-08-10 由 core/log_rotation.py 并入，API 兼容：log_path/max_size_mb/keep_backups）

    Args:
        log_path: 日志文件路径
        max_size_mb: 最大文件大小（MB），超过此值触发轮转，默认 5
        keep_backups: 保留的备份文件数量，默认 3

    Returns:
        bool: 是否执行了轮转操作
    """
    try:
        if not log_path or max_size_mb <= 0:
            return False
        if keep_backups < 1:
            keep_backups = 1
        if not os.path.isfile(log_path):
            return False
        max_size_bytes = max_size_mb * 1024 * 1024
        file_size = os.path.getsize(log_path)
        if file_size < max_size_bytes:
            return False

        with log_rotate_lock:
            # 双重检查：拿到锁后再确认（其他线程可能已轮转）
            if not os.path.isfile(log_path):
                return False
            if os.path.getsize(log_path) < max_size_bytes:
                return False
            oldest_path = "{}.bak.{}".format(log_path, keep_backups)
            if os.path.isfile(oldest_path):
                try:
                    os.remove(oldest_path)
                except OSError:
                    pass
            for i in range(keep_backups - 1, 0, -1):
                src = "{}.bak.{}".format(log_path, i)
                dst = "{}.bak.{}".format(log_path, i + 1)
                if os.path.isfile(src):
                    try:
                        os.rename(src, dst)
                    except OSError:
                        pass
            backup_path = "{}.bak.1".format(log_path)
            os.rename(log_path, backup_path)
            logger.info("日志轮转完成: %s -> %s (%.2f MB)", log_path, backup_path, file_size / (1024 * 1024))
        return True
    except Exception as e:
        logger.warning("[log_rotation] 递进轮转异常 (%s): %s", log_path, e)
        return False


def get_log_size_mb(log_path: str) -> Optional[float]:
    """获取日志文件大小（MB），文件不存在或异常时返回 None。"""
    try:
        if not os.path.isfile(log_path):
            return None
        return os.path.getsize(log_path) / (1024 * 1024)
    except Exception:
        return None
