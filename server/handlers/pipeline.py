# -*- coding: utf-8 -*-
"""流水线实时状态接口（阶段一·实时基建）。

路由：
  GET  /api/pipeline/status — 当前流水线状态（前端轮询 / 连接探测）
  POST /api/pipeline/run    — 触发一次服务端运行（仅本机；阶段二替换为真实 Agent）

安全：
  - /run 仅允许本机（127.0.0.1 / ::1）调用，防局域网越权触发
  - CORS：同源反射（与全局一致）+ 额外允许 null origin，
    以便用户直接双击 file:// 打开页面时也能读取状态（localhost 非敏感数据）
"""
import json

from ..utils import log


def _send_json(handler, data, code=200):
    """发送 JSON，CORS 允许同源或 file://(null) 来源。"""
    handler.send_response(code)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    origin = handler.headers.get('Origin')
    if origin and (handler._is_same_origin(origin) or origin == 'null'):
        handler.send_header('Access-Control-Allow-Origin', origin)
    handler.end_headers()
    handler.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))


def handle_pipeline_status(handler):
    """GET /api/pipeline/status — 返回实时流水线状态。"""
    try:
        from core.pipeline_state import get_state
        data = get_state()
        data["ok"] = True
        _send_json(handler, data)
    except Exception as e:
        log(f'[PIPELINE] status 异常: {e}')
        _send_json(handler, {"ok": False, "connected": True, "error": str(e)}, 500)


def handle_pipeline_run(handler):
    """POST /api/pipeline/run — 触发一次运行（仅本机）。

    请求体可选 JSON：{"topic": "研报主题"}；缺省则使用默认主题。
    """
    if not handler._is_local():
        _send_json(handler, {"ok": False, "error": "仅允许本机触发"}, 403)
        return
    try:
        topic = ""
        try:
            cl = int(handler.headers.get('Content-Length', 0) or 0)
            if cl:
                raw = handler.rfile.read(cl).decode('utf-8', errors='replace')
                topic = (json.loads(raw) or {}).get('topic', '') or ""
        except Exception:
            topic = ""
        from core.pipeline_state import start_run
        ok = start_run(topic)
        if ok:
            _send_json(handler, {"ok": True, "message": "流水线已启动（服务端实时推进）",
                                 "topic": topic or "默认主题"})
        else:
            _send_json(handler, {"ok": False, "message": "流水线正在运行中，请稍候"})
    except Exception as e:
        log(f'[PIPELINE] run 异常: {e}')
        _send_json(handler, {"ok": False, "error": str(e)}, 500)
