# -*- coding: utf-8 -*-
"""金水谣系统 - 前端错误上报端点

接收前端 JS 通过 sendBeacon 上报的运行时错误，追加写入 JSONL 日志文件。
日志位置：金水谣数据/log/err_log/frontend_errors.jsonl

路由（POST）：
  /api/error-report — 接收前端错误上报（仅限本机请求）
"""
import os
import json
import threading
from datetime import datetime

from ..config import BASE_DIR
from ..utils import log

# 日志轮转（防止 JSONL 文件无限增长）
import sys as _sys
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _proj_root not in _sys.path:
    _sys.path.insert(0, _proj_root)
from utils.log_rotation import check_and_rotate

# 日志文件路径（不硬编码，基于 BASE_DIR 动态拼接）
_LOG_DIR = os.path.join(BASE_DIR, "金水谣数据", "log", "err_log")
_LOG_FILE = os.path.join(_LOG_DIR, "frontend_errors.jsonl")

# 写入锁（线程安全，参考 core/conversation_log.py）
_write_lock = threading.Lock()

# 单条日志字段最大长度（防止恶意超大 payload）
_MAX_FIELD_LEN = 2000


def _truncate(text, max_len=_MAX_FIELD_LEN):
    """截断过长文本"""
    if not text or not isinstance(text, str):
        return str(text) if text is not None else ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "...[truncated]"


def handle_error_report(handler):
    """POST /api/error-report — 接收前端 JS 错误上报

    请求体 JSON：{message, source, lineno, colno, stack, page, ua, timestamp}
    仅接受本机（localhost）请求，写入失败不影响主流程。
    """
    try:
        # 仅允许本机请求（复用 router 中的 _is_local 检查）
        if not handler._is_local():
            handler._send_json({"ok": False, "error": "仅限本机请求"}, 403)
            return

        # 读取请求体
        try:
            cl = int(handler.headers.get('Content-Length', 0) or 0)
        except (ValueError, TypeError):
            cl = 0
        body = handler.rfile.read(cl).decode('utf-8', errors='replace') if cl else '{}'

        try:
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError):
            handler._send_json({"ok": False, "error": "无效的JSON"}, 400)
            return

        # 构造日志记录
        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message": _truncate(data.get("message", "")),
            "source": _truncate(data.get("source", ""), 500),
            "lineno": data.get("lineno", 0),
            "colno": data.get("colno", 0),
            "stack": _truncate(data.get("stack", "")),
            "page": _truncate(data.get("page", ""), 500),
            "ua": _truncate(data.get("ua", ""), 300),
            "timestamp": data.get("timestamp", ""),
        }

        # 追加写入 JSONL 文件（线程锁保护）
        try:
            os.makedirs(_LOG_DIR, exist_ok=True)
            check_and_rotate(_LOG_FILE, max_size_mb=5)
            with _write_lock:
                with open(_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            # 写入失败不影响主流程，仅记录服务端日志
            log(f'[error-report] 写入失败: {e}')

        handler._send_json({"ok": True})

    except Exception as e:
        # 顶层兜底：任何异常都不应导致 500 影响前端
        try:
            log(f'[error-report] 处理异常: {e}')
            handler._send_json({"ok": True})
        except Exception:
            pass
