# -*- coding: utf-8 -*-
"""
金水谣万物引擎 · 统一日志配置

所有模块统一使用此配置，避免各模块各自定义日志格式。

使用方式：
    from config.logging_config import setup_logging
    setup_logging()  # 在 main.py 或 server 启动时调用一次
    logger = logging.getLogger(__name__)
"""
import os
import sys
import logging
from logging.handlers import RotatingFileHandler

# 日志目录
_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_SCRIPT_DIR, "金水谣数据", "log")

# 统一日志格式
LOG_FORMAT = "[%(asctime)s] %(name)-18s %(levelname)-5s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_initialized = False


def setup_logging(level=None, log_to_file=True):
    """初始化全局日志配置（幂等，多次调用不会重复添加 handler）

    Args:
        level: 日志级别，默认从环境变量 LOG_LEVEL 读取，缺省 INFO
        log_to_file: 是否同时写入文件日志（默认 True）
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    # 解析日志级别
    if level is None:
        level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_str, logging.INFO)

    # 根 logger 配置
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除已有 handler（避免重复）
    root_logger.handlers.clear()

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    root_logger.addHandler(console_handler)

    # 文件 handler（可选）
    if log_to_file:
        os.makedirs(_LOG_DIR, exist_ok=True)
        log_file = os.path.join(_LOG_DIR, "jinshuiyao.log")
        try:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10MB
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
            root_logger.addHandler(file_handler)
        except (OSError, PermissionError):
            # 无写入权限时静默降级为仅控制台
            pass

    # 降低第三方库的日志噪音
    for noisy in ("urllib3", "requests", "matplotlib", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
