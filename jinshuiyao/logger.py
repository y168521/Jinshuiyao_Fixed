# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 日志模块"""

import logging
import sys
from datetime import datetime


def setup_logger(name: str = "jinshuiyao", level: int = logging.INFO) -> logging.Logger:
    """创建统一日志器"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    logger.addHandler(handler)

    return logger


def get_logger(name: str = "jinshuiyao") -> logging.Logger:
    """获取已配置的日志器"""
    return logging.getLogger(name)