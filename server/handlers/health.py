# -*- coding: utf-8 -*-
"""金水谣系统 - 健康检查 & 状态端点

路由：
  GET /health                  — 健康检查（前端定时探测 + 运维监控）
  GET /status                  — 子系统状态（兼容旧前端）
  GET /api/selfcheck           — 启动自检报告
  GET /api/selfcheck/history   — 自检历史日志
  GET /api/ip                  — 本机局域网 IP
  GET /api/test-results        — 最近测试结果
  GET /api/fund-notification   — 基金日报通知状态
  GET /api/fund-notification/read — 标记通知已读
  GET /api/ai/mode             — 当前 AI 运行模式
  GET /api/ai/mode/set         — 切换 AI 运行模式（GET 变体）
  GET /api/ai/status           — AI 服务详细状态
"""
import os
import json

from .. import config as _config
from ..utils import log, get_local_ip


def handle_health(handler):
    """GET /health — 健康检查端点（供前端定时探测 + 运维监控）"""
    _dt = __import__('datetime')
    _time = __import__('time')
    cls = handler.__class__
    uptime = int(_time.time() - cls._start_time)
    health = {
        "status": "ok",
        "uptime_seconds": uptime,
        "port": _config.PORT,
        "requests_total": cls._request_count,
        "errors_total": cls._error_count,
        "error_rate": round(cls._error_count / max(cls._request_count, 1), 4),
        "recent_errors": cls._errors_recent[-5:],
        "ai_mode": "unknown",
        "timestamp": _dt.datetime.now().isoformat(),
        "version": _config.SERVER_VERSION,
        "started_at": _dt.datetime.fromtimestamp(cls._start_time).isoformat(),
    }
    # 检测 AI 状态（仅查密钥文件，不发起网络请求避免卡住）
    try:
        key_file = None
        # 安全铁律（JS-20260724）：仅检测安全目录密钥（项目根明文回退已移除）
        for _kf in (os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets", "deepseek_key.txt"),):
            if os.path.isfile(_kf) and os.path.getsize(_kf) > 5:
                key_file = _kf
                break
        health["ai_mode"] = "configured" if key_file else "no_key"
    except Exception:
        health["ai_mode"] = "error"
    # 检测知识库
    try:
        kb_dir = os.path.join(_config.BASE_DIR, 'knowledge', '用户知识库')
        if os.path.isdir(kb_dir):
            health["knowledge_cards"] = len([f for f in os.listdir(kb_dir) if f.endswith('.md') and not f.startswith('INDEX')])
        else:
            health["knowledge_cards"] = -1
    except Exception:
        health["knowledge_cards"] = -1
    handler._send_json(health)


def handle_status(handler):
    """GET /status — 子系统状态API（兼容旧前端）"""
    status = {"server": "online", "timestamp": __import__("datetime").datetime.now().isoformat()}
    # 检测各子系统关键文件是否存在
    checks = {
        "lottery": "gui/main_window.py",
        "stock": "domains/stock/stock_gui.py",
        "football": "jinshuiyao/football_gui.py",
        "knowledge": "knowledge/mirofish_gui.py",
        "fund": "domains/fund/fund_gui.py",
        "music": "audio_toolkit.py",
        "creator": "domains/creator/creator_gui.py",
    }
    for name, rel in checks.items():
        fp = os.path.join(_config.BASE_DIR, rel.replace("/", os.sep))
        status[name] = {"exists": os.path.isfile(fp), "path": rel}
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler._set_cors()  # P0-① 同源反射(JS-20260806-09)：去掉全局 '*'
    handler.end_headers()
    handler.wfile.write(json.dumps(status, ensure_ascii=False).encode('utf-8'))


def handle_selfcheck(handler):
    """GET /api/selfcheck — 获取最近一次启动自检报告（独特测试工程）"""
    try:
        from startup_selfcheck import run_startup_check_safe
        report = run_startup_check_safe()
        handler._send_json(report)
    except Exception as e:
        handler._send_json({"all_passed": False, "summary": f"自检接口异常: {e}", "departments": {}})


def handle_selfcheck_history(handler):
    """GET /api/selfcheck/history — 获取自检历史日志（最近10条）"""
    try:
        log_path = os.path.join(_config.BASE_DIR, '金水谣数据', 'log', 'selfcheck.log')
        content = ""
        if os.path.isfile(log_path):
            with open(log_path, 'r', encoding='utf-8') as f:
                content = f.read()
        handler._send_json({"log": content, "time": os.path.getmtime(log_path) if os.path.isfile(log_path) else 0})
    except Exception as e:
        handler._send_json({"log": f"读取失败: {e}", "time": 0})


def handle_ip(handler):
    """GET /api/ip — 获取本机局域网IP（手机端用）"""
    ip = get_local_ip()
    handler._send_json({"ip": ip, "port": _config.PORT, "url": f"http://{ip}:{_config.PORT}/"})


def handle_test_results(handler):
    """GET /api/test-results — 获取最近测试结果"""
    log_path = os.path.join(_config.BASE_DIR, '金水谣数据', 'log', 'smoke_test.log')
    if os.path.isfile(log_path):
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()
        handler._send_json({"log": content, "time": os.path.getmtime(log_path)})
    else:
        handler._send_json({"log": "暂无测试记录", "time": 0})


def handle_fund_notification(handler):
    """GET /api/fund-notification — 获取基金日报通知状态"""
    notif_path = os.path.join(_config.BASE_DIR, '金水谣数据', 'fund_reports', '.notification.json')
    if os.path.isfile(notif_path):
        try:
            with open(notif_path, 'r', encoding='utf-8') as f:
                notification = json.load(f)
            handler._send_json({"has_notification": True, "data": notification})
        except Exception as e:
            handler._send_json({"has_notification": False, "error": str(e)})
    else:
        handler._send_json({"has_notification": False})


def handle_fund_notification_read(handler):
    """GET /api/fund-notification/read — 标记通知为已读"""
    notif_path = os.path.join(_config.BASE_DIR, '金水谣数据', 'fund_reports', '.notification.json')
    if os.path.isfile(notif_path):
        try:
            with open(notif_path, 'r', encoding='utf-8') as f:
                notification = json.load(f)
            notification["is_read"] = True
            with open(notif_path, 'w', encoding='utf-8') as f:
                json.dump(notification, f, ensure_ascii=False, indent=2)
            handler._send_json({"ok": True})
        except Exception as e:
            handler._send_json({"ok": False, "error": str(e)})
    else:
        handler._send_json({"ok": False, "error": "通知文件不存在"})


def handle_ai_mode(handler):
    """GET /api/ai/mode — 获取当前AI运行模式（online/offline）"""
    try:
        from core.ai_service import get_mode_info
        info = get_mode_info()
        handler._send_json(info)
    except Exception as e:
        handler._send_json({"mode": "online", "error": str(e)})


def handle_ai_mode_set_get(handler):
    """GET /api/ai/mode/set — 切换AI运行模式（GET 兼容，从 query 读取 mode 参数）"""
    try:
        import urllib.parse
        parsed = urllib.parse.urlparse(handler.path)
        qs = urllib.parse.parse_qs(parsed.query)
        new_mode = qs.get('mode', ['online'])[0]
        _do_mode_switch(handler, new_mode)
    except Exception as e:
        handler._send_json({"ok": False, "error": str(e)})


def handle_ai_mode_set_post(handler):
    """POST /api/ai/mode/set — 切换AI运行模式（JSON body: {"mode": "online"|"offline"}）"""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length).decode('utf-8', errors='replace')
        data = json.loads(body) if body else {}
        new_mode = data.get('mode', 'online')
        _do_mode_switch(handler, new_mode)
    except Exception as e:
        handler._send_json({"ok": False, "error": str(e)})


def _do_mode_switch(handler, new_mode):
    """模式切换公共逻辑（GET / POST 共用）"""
    if new_mode not in ('online', 'offline'):
        handler._send_json({"ok": False, "error": f"不支持的模式: {new_mode}"})
        return
    try:
        from core.ai_service import set_mode
        success = set_mode(new_mode)
        if success:
            log(f'AI模式已切换为: {new_mode}')
            handler._send_json({"ok": True, "mode": new_mode, "message": f"已切换为{new_mode}模式"})
        else:
            handler._send_json({"ok": False, "error": "切换失败"})
    except Exception as e:
        handler._send_json({"ok": False, "error": str(e)})


# ---------------------------------------------------------------------------
# /api/ai/status — 内存缓存 + 后台异步探测（响应 < 5ms）
# ---------------------------------------------------------------------------
import threading as _threading
import time as _time

_ai_status_cache = {"data": None, "ts": 0}
_AI_STATUS_TTL = 5  # 缓存有效期（秒）
_ai_status_lock = _threading.Lock()
_ai_status_refreshing = False


def _refresh_ai_status_bg():
    """后台线程：刷新 AI 状态缓存（不阻塞 HTTP 请求）"""
    global _ai_status_refreshing
    try:
        from core.ai_service import get_ai_service
        ai = get_ai_service()
        data = ai.stats
        with _ai_status_lock:
            _ai_status_cache["data"] = data
            _ai_status_cache["ts"] = _time.time()
    except Exception as e:
        # 探测失败：保留旧缓存，仅更新错误标记
        with _ai_status_lock:
            if _ai_status_cache["data"] is not None:
                _ai_status_cache["data"]["_cache_error"] = str(e)
            else:
                _ai_status_cache["data"] = {"error": str(e), "available": False}
            _ai_status_cache["ts"] = _time.time()
    finally:
        _ai_status_refreshing = False


def handle_ai_status(handler):
    """GET /api/ai/status — 获取AI服务详细状态（缓存优先，后台刷新）"""
    global _ai_status_refreshing
    now = _time.time()
    with _ai_status_lock:
        cached = _ai_status_cache["data"]
        age = now - _ai_status_cache["ts"]
    # 缓存有效：直接返回
    if cached is not None and age < _AI_STATUS_TTL:
        result = dict(cached)
        result["_cache_age_s"] = round(age, 1)
        handler._send_json(result)
        return
    # 缓存过期或为空：触发后台刷新，同时返回旧缓存或占位
    if not _ai_status_refreshing:
        _ai_status_refreshing = True
        t = _threading.Thread(target=_refresh_ai_status_bg, daemon=True, name="ai-status-refresh")
        t.start()
    if cached is not None:
        result = dict(cached)
        result["_cache_age_s"] = round(age, 1)
        result["_refreshing"] = True
        handler._send_json(result)
    else:
        handler._send_json({"available": False, "_refreshing": True,
                            "info": "AI状态首次加载中，请稍后重试"})
