# -*- coding: utf-8 -*-
"""
金水谣系统 - 日志轮转模块

提供日志文件自动轮转功能，当日志文件超过指定大小时，
自动将当前文件重命名为带序号后缀的备份文件，并保留最近 N 个备份。

Usage:
    from core.log_rotation import rotate_log

    rotated = rotate_log("金水谣数据/log/health_log.jsonl", max_size_mb=5, keep_backups=3)
    if rotated:
        print("日志已轮转")
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def rotate_log(log_path: str, max_size_mb: float = 5, keep_backups: int = 3) -> bool:
    """检查并执行日志文件轮转

    当日志文件大小超过 max_size_mb 时，将当前文件重命名为 .bak.1，
    旧的 .bak.1 递进为 .bak.2，依此类推。
    超出 keep_backups 数量的旧备份将被删除。

    Args:
        log_path: 日志文件路径
        max_size_mb: 最大文件大小（MB），超过此值触发轮转，默认 5
        keep_backups: 保留的备份文件数量，默认 3

    Returns:
        bool: 是否执行了轮转操作。如果文件不存在、大小未超限或发生错误则返回 False

    Examples:
        >>> rotated = rotate_log("data/log/health_log.jsonl", max_size_mb=5, keep_backups=3)
        >>> if rotated:
        ...     print("日志文件已轮转")
    """
    try:
        # 参数校验
        if not log_path:
            logger.debug("log_path 为空，跳过轮转")
            return False

        if max_size_mb <= 0:
            logger.warning("max_size_mb 必须大于 0，当前值: %s，跳过轮转", max_size_mb)
            return False

        if keep_backups < 1:
            keep_backups = 1

        # 检查文件是否存在
        if not os.path.isfile(log_path):
            logger.debug("日志文件不存在，跳过轮转: %s", log_path)
            return False

        # 检查文件大小
        max_size_bytes = max_size_mb * 1024 * 1024
        file_size = os.path.getsize(log_path)

        if file_size < max_size_bytes:
            logger.debug("日志文件大小未超限 (%.2f MB < %.2f MB)，跳过轮转: %s",
                         file_size / (1024 * 1024), max_size_mb, log_path)
            return False

        logger.info("日志文件大小超限 (%.2f MB >= %.2f MB)，开始轮转: %s",
                    file_size / (1024 * 1024), max_size_mb, log_path)

        # 按轮转逻辑重命名备份文件
        # 先删除最旧的备份（超出 keep_backups 数量的）
        oldest_backup = keep_backups
        oldest_path = "{}.bak.{}".format(log_path, oldest_backup)
        if os.path.isfile(oldest_path):
            try:
                os.remove(oldest_path)
                logger.debug("已删除最旧备份: %s", oldest_path)
            except OSError as e:
                logger.warning("删除旧备份失败: %s, 错误: %s", oldest_path, e)

        # 将 .bak.N-1 重命名为 .bak.N（从高到低依次递进）
        for i in range(keep_backups - 1, 0, -1):
            src = "{}.bak.{}".format(log_path, i)
            dst = "{}.bak.{}".format(log_path, i + 1)
            if os.path.isfile(src):
                try:
                    os.rename(src, dst)
                    logger.debug("备份递进: %s -> %s", src, dst)
                except OSError as e:
                    logger.warning("备份递进失败: %s -> %s, 错误: %s", src, dst, e)

        # 将当前日志文件重命名为 .bak.1
        backup_path = "{}.bak.1".format(log_path)
        try:
            os.rename(log_path, backup_path)
            logger.info("日志轮转完成: %s -> %s (原大小: %.2f MB)",
                        log_path, backup_path, file_size / (1024 * 1024))
        except OSError as e:
            logger.error("日志轮转重命名失败: %s -> %s, 错误: %s", log_path, backup_path, e)
            return False

        return True

    except Exception as e:
        logger.error("日志轮转异常: %s, 文件: %s", e, log_path, exc_info=True)
        return False


def get_log_size_mb(log_path: str) -> Optional[float]:
    """获取日志文件大小（MB）

    Args:
        log_path: 日志文件路径

    Returns:
        float or None: 文件大小（MB），文件不存在或异常时返回 None
    """
    try:
        if not os.path.isfile(log_path):
            return None
        return os.path.getsize(log_path) / (1024 * 1024)
    except Exception as e:
        logger.debug("获取日志文件大小失败: %s, 错误: %s", log_path, e)
        return None
