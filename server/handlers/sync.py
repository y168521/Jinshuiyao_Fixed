# -*- coding: utf-8 -*-
"""金水谣系统 - 跨设备同步端点

路由（GET）：
  /sync             — 跨设备任务同步看板（HTML）
  /sync-api/state   — 读取跨设备任务同步状态与总账

路由（POST）：
  /sync-api/task     — 记录一条任务完成状态
  /sync-api/identity — 修改本机设备名

说明：跨设备同步为可选功能（依赖 sync/device_sync.py，本机未安装）。
      所有端点诚实降级，不抛 500：返回 available=false + 中文说明。
"""
import os
import json

from ..config import SYNC_DIR
from ..utils import log


def _sync_available():
    """检测 device_sync 是否可用（可选功能）"""
    try:
        import device_sync  # noqa: F401
        return True
    except Exception:
        return False


_UNAVAILABLE = {"available": False, "error": "跨设备同步模块未安装（可选功能，本机未启用）"}


# ---------------------------------------------------------------------------
# GET 路由处理函数
# ---------------------------------------------------------------------------
def handle_sync_dashboard(handler):
    """GET /sync — 跨设备任务同步看板（HTML）"""
    html_path = os.path.join(SYNC_DIR, 'sync_dashboard.html')
    if not os.path.isfile(html_path):
        html = ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                "<title>跨设备同步</title></head><body style='font-family:微软雅黑;padding:2em'>"
                "<h2>跨设备任务同步</h2>"
                "<p>本机未启用跨设备同步（可选功能，缺少 sync/device_sync.py）。</p>"
                "<p>需要时可在 sync/ 目录放置 device_sync.py 后重启服务。</p>"
                "</body></html>")
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/html; charset=utf-8')
        handler.end_headers()
        handler.wfile.write(html.encode('utf-8'))
        return
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/html; charset=utf-8')
        handler.end_headers()
        handler.wfile.write(html.encode('utf-8'))
    except Exception as e:
        handler._send_json({"error": "看板加载失败: %s" % e}, 500)


def handle_sync_state(handler):
    """GET /sync-api/state — 读取跨设备任务同步状态与总账"""
    if not _sync_available():
        handler._send_json(dict(_UNAVAILABLE))
        return
    try:
        from device_sync import get_state, status as sync_status
        data = get_state()
        data["status"] = sync_status()
        handler._send_json(data)
    except Exception as e:
        handler._send_json({"error": "读取同步状态失败: %s" % e}, 500)


# ---------------------------------------------------------------------------
# POST 路由处理函数
# ---------------------------------------------------------------------------
def handle_sync_task(handler):
    """POST /sync-api/task — 跨设备同步：记录一条任务完成状态"""
    if not _sync_available():
        handler._send_json(dict(_UNAVAILABLE))
        return
    if not handler._is_local():
        handler._send_json({"error": "安全限制：同步写入仅允许本机操作。"}, 403)
        return
    try:
        cl = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(cl).decode('utf-8', errors='replace') if cl else '{}'
        d = json.loads(body) if body else {}
        from device_sync import record_task, identify_device
        t = record_task(
            d.get('id', 'TS-000'),
            d.get('title', '未命名任务'),
            d.get('status', 'done'),
            d.get('note', ''),
            device=identify_device())
        handler._send_json({"ok": True, "task": t})
    except Exception as e:
        handler._send_json({"ok": False, "error": "记录失败: %s" % e}, 500)


def handle_sync_identity(handler):
    """POST /sync-api/identity — 跨设备同步：修改本机设备名（仅本机）"""
    if not _sync_available():
        handler._send_json(dict(_UNAVAILABLE))
        return
    if not handler._is_local():
        handler._send_json({"error": "安全限制：改名仅允许本机操作。"}, 403)
        return
    try:
        cl = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(cl).decode('utf-8', errors='replace') if cl else '{}'
        d = json.loads(body) if body else {}
        from device_sync import set_identity
        dev = set_identity(d.get('device', ''))
        handler._send_json({"ok": True, "device": dev})
    except Exception as e:
        handler._send_json({"ok": False, "error": "改名失败: %s" % e}, 500)
