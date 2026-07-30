# -*- coding: utf-8 -*-
"""金水谣系统 - JSONL 日志文件轮转工具

在写入 JSONL 日志前调用 check_and_rotate()，当文件超过阈值时自动轮转：
  当前文件 -> xxx.jsonl.1（覆盖已有备份），然后创建新的空文件。
最多保留 1 个备份，防止日志文件无限增长。

用法：
    from utils.log_rotation import check_and_rotate
    check_and_rotate("/path/to/xxx.jsonl", max_size_mb=5)

线程安全：使用 utils.locks.log_rotate_lock 保护轮转操作。
"""
import os
import sys
import logging

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
