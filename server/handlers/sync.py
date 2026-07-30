# -*- coding: utf-8 -*-
"""金水谣系统 - 跨设备同步端点

路由（GET）：
  /sync             — 跨设备任务同步看板（HTML）
  /sync-api/state   — 读取跨设备任务同步状态与总账

路由（POST）：
  /sync-api/task     — 记录一条任务完成状态
  /sync-api/identity — 修改本机设备名
"""
import os
import json

from ..config import SYNC_DIR
from ..utils import log


# ---------------------------------------------------------------------------
# GET 路由处理函数
# ---------------------------------------------------------------------------
def handle_sync_dashboard(handler):
    """GET /sync — 跨设备任务同步看板（HTML）"""
    try:
        html_path = os.path.join(SYNC_DIR, 'sync_dashboard.html')
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
