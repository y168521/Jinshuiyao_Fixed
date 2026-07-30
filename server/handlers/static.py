# -*- coding: utf-8 -*-
"""金水谣系统 - 静态文件 & 页面路由

路由（GET）：
  /                — 根路径（金水谣助手门户）
  /docs            — 接口文档页面
  /test-report     — 测试报告页面
  /health-check    — 系统体检中心页面
  /ai-test         — AI 用例生成页面
  /ai-agent        — AI 助手页面
  /workbench       — 金水谣工作台
  /jinshuiyao-guide — 金水谣导航页面
  /route           — 任务调度中枢页面
  /smart-coder     — 智能代码助手页面
  /open?file=xxx   — 打开文件（返回JSON，前端 fetch 静默调用）
  /api/audit       — 最近一次自动模型审查报告
  /api/run-tests   — 运行自动化测试（POST）
"""
import os
import json
import sys
import urllib.parse
import subprocess

from ..config import BASE_DIR, HTML_DIR, NAV_FILE, CONTROL_CENTER, ROOT_DIR, SYSTEM_PYTHON
from ..utils import log, open_local_file


# ---------------------------------------------------------------------------
# 页面路由映射表（路径 → HTML 文件名，统一逻辑）
# ---------------------------------------------------------------------------
_PAGE_ROUTES = {
    '/docs':             'api-docs.html',
    '/test-report':      'test-report.html',
    '/health-check':     'health-check.html',
    '/ai-test':          'ai-test.html',
    '/ai-agent':         'ai-agent.html',
    '/workbench':        'workbench.html',
    '/jinshuiyao-guide': 'jinshuiyao-guide.html',
    '/route':            'route.html',
    '/smart-coder':      'assistant.html',
    '/control-center':   'control-center.html',
    '/architecture':     'jinshuiyao-architecture.html',
    '/global-plan':      'jinshuiyao-global-plan.html',
    '/scheduler':        'scheduler.html',
    '/engine-dashboard': 'engine-dashboard.html',
    '/lottery-sources-health': 'lottery-sources-health.html',
    '/review-dashboard':    'review-dashboard.html',
    '/compare-tech':        'compare-tech.html',
    '/math-model':          'math-model.html',
    '/prediction-reference':'prediction-reference.html',
}

# 外部页面路由（不在 HTML_DIR 内的独立仪表板页面）
_EXTERNAL_PAGE_ROUTES = {
    '/dashboard':      os.path.join(BASE_DIR, 'frontend/dashboard', 'jinshuiyao-dashboard.html'),
    '/trend':          os.path.join(BASE_DIR, 'frontend/trend', 'jinshuiyao-trend.html'),
    '/quant':          os.path.join(BASE_DIR, 'frontend/quant-dashboard', 'index.html'),
    '/sync':           os.path.join(BASE_DIR, 'sync', 'sync_dashboard.html'),
    '/gap-analysis':   os.path.join(BASE_DIR, 'frontend/gap-analysis', 'jinshuiyao-gap-analysis.html'),
    '/deepseek-manual': os.path.join(BASE_DIR, 'AI代码助手(DeepSeek备用)', '使用说明.html'),
    '/fund-dashboard':  os.path.join(HTML_DIR, 'fund-dashboard.html'),
    '/lottery-dashboard': os.path.join(HTML_DIR, 'lottery-dashboard.html'),
    '/omission-heatmap': os.path.join(BASE_DIR, 'frontend/trend', 'omission-heatmap.html'),
    '/rotation-matrix': os.path.join(HTML_DIR, 'rotation-matrix.html'),
    '/filter-panel':    os.path.join(HTML_DIR, 'filter-panel.html'),
    '/prize-calculator': os.path.join(HTML_DIR, 'prize-calculator.html'),
    '/audit-dashboard':  os.path.join(HTML_DIR, 'audit-dashboard.html'),
    '/head-tail-analysis': os.path.join(HTML_DIR, 'head-tail-analysis.html'),
    '/lottery-sources-health': os.path.join(HTML_DIR, 'lottery-sources-health.html'),
}

# 彩票子系统路由（/lottery/xxx → lottery/xxx.html）
_LOTTERY_ROUTES = {
    '/lottery':              os.path.join(BASE_DIR, 'frontend', 'lottery', 'lottery-hub.html'),
    '/lottery/dashboard':    os.path.join(BASE_DIR, 'frontend', 'lottery', 'dashboard.html'),
    '/lottery/sources-health':  os.path.join(BASE_DIR, 'frontend', 'lottery', 'sources-health.html'),
    '/lottery/omission-heatmap': os.path.join(BASE_DIR, 'frontend', 'lottery', 'omission-heatmap.html'),
    '/lottery/rotation-matrix': os.path.join(BASE_DIR, 'frontend', 'lottery', 'rotation-matrix.html'),
    '/lottery/filter-panel':    os.path.join(BASE_DIR, 'frontend', 'lottery', 'filter-panel.html'),
    '/lottery/prize-calculator': os.path.join(BASE_DIR, 'frontend', 'lottery', 'prize-calculator.html'),
    '/lottery/head-tail-analysis': os.path.join(BASE_DIR, 'frontend', 'lottery', 'head-tail-analysis.html'),
    '/lottery/historical-same-period': os.path.join(BASE_DIR, 'frontend', 'lottery', 'historical-same-period.html'),
    '/lottery/number-follow-up':  os.path.join(BASE_DIR, 'frontend', 'lottery', 'number-follow-up.html'),
    '/lottery/audit-dashboard':   os.path.join(BASE_DIR, 'frontend', 'lottery', 'audit-dashboard.html'),
    '/lottery/ac-calculator':    os.path.join(BASE_DIR, 'frontend', 'lottery', 'ac-calculator.html'),
    '/lottery/trend-classification': os.path.join(BASE_DIR, 'frontend', 'lottery', 'trend-classification.html'),
    '/lottery/omission-table':    os.path.join(BASE_DIR, 'frontend', 'lottery', 'omission-table.html'),
}

# 基金/股票/足彩 子系统路由
_SUBSYSTEM_ROUTES = {
    '/fund':              os.path.join(BASE_DIR, 'frontend', 'fund', 'fund-hub.html'),
    '/fund/dashboard':    os.path.join(BASE_DIR, 'frontend', 'fund', 'dashboard.html'),
    '/fund/nav-trend':    os.path.join(BASE_DIR, 'frontend', 'fund', 'nav-trend.html'),
    '/fund/holdings':     os.path.join(BASE_DIR, 'frontend', 'fund', 'holdings.html'),
    '/fund/screener':     os.path.join(BASE_DIR, 'frontend', 'fund', 'screener.html'),
    '/fund/detail':       os.path.join(BASE_DIR, 'frontend', 'fund', 'fund-detail.html'),
    '/stock':             os.path.join(BASE_DIR, 'frontend', 'stock', 'stock-hub.html'),
    '/stock/dashboard':   os.path.join(BASE_DIR, 'frontend', 'stock', 'stock-dashboard.html'),
    '/football':          os.path.join(BASE_DIR, 'frontend', 'football', 'football-hub.html'),
    '/football/dashboard': os.path.join(BASE_DIR, 'frontend', 'football', 'dashboard.html'),
}

_PAGE_ERROR_MESSAGES = {
    '/docs':             '接口文档页面不存在',
    '/test-report':      '测试报告页面不存在',
    '/health-check':     '体检中心页面不存在',
    '/ai-test':          'AI用例页面不存在',
    '/ai-agent':         'AI助手页面不存在',
    '/workbench':        '工作台页面不存在',
    '/jinshuiyao-guide': '金水谣导航页面不存在',
    '/route':            '调度中枢页面不存在',
    '/smart-coder':      '智能代码助手页面不存在',
    '/control-center':   '总控台页面不存在',
    '/architecture':     '架构图页面不存在',
    '/global-plan':      '全局规划页面不存在',
    '/scheduler':        '定时任务监控页面不存在',
    '/engine-dashboard': '引擎效果看板页面不存在',
}


# ---------------------------------------------------------------------------
# GET 路由处理函数
# ---------------------------------------------------------------------------
def handle_page(handler, path):
    """处理已知页面路由（查表返回 HTML 文件）"""
    # 先查内部路由（HTML_DIR 下的文件）
    filename = _PAGE_ROUTES.get(path)
    if filename:
        page_file = os.path.join(HTML_DIR, filename)
        if os.path.isfile(page_file):
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/html; charset=utf-8')
            handler.end_headers()
            with open(page_file, 'rb') as f:
                handler.wfile.write(f.read())
        else:
            handler._send_json({"error": _PAGE_ERROR_MESSAGES.get(path, "页面不存在")}, 404)
        return True

    # 再查外部路由（独立仪表板等）
    ext_file = _EXTERNAL_PAGE_ROUTES.get(path)
    if ext_file:
        if os.path.isfile(ext_file):
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/html; charset=utf-8')
            handler.end_headers()
            with open(ext_file, 'rb') as f:
                handler.wfile.write(f.read())
        else:
            handler._send_json({"error": f"页面文件不存在: {path}"}, 404)
        return True

    # 再查彩票子系统路由（/lottery/xxx）
    lot_file = _LOTTERY_ROUTES.get(path)
    if lot_file:
        if os.path.isfile(lot_file):
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/html; charset=utf-8')
            handler.end_headers()
            with open(lot_file, 'rb') as f:
                handler.wfile.write(f.read())
        else:
            handler._send_json({"error": f"彩票页面不存在: {path}"}, 404)
        return True

    # 再查基金/股票/足彩 子系统路由
    sub_file = _SUBSYSTEM_ROUTES.get(path)
    if sub_file:
        if os.path.isfile(sub_file):
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/html; charset=utf-8')
            handler.end_headers()
            with open(sub_file, 'rb') as f:
                handler.wfile.write(f.read())
        else:
            handler._send_json({"error": f"子系统页面不存在: {path}"}, 404)
        return True

    return False


def handle_root(handler):
    """GET / — 根路径：直接返回金水谣助手门户（零基础中文主入口）"""
    if os.path.isfile(NAV_FILE):
        try:
            with open(NAV_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/html; charset=utf-8')
            handler.end_headers()
            handler.wfile.write(content.encode('utf-8'))
            return True
        except Exception:
            pass
    # 回退：返回总控台
    if os.path.isfile(CONTROL_CENTER):
        handler.send_response(302)
        handler.send_header('Location', '/control-center.html')
        handler.end_headers()
        return True
    return False


def handle_open(handler, parsed):
    """GET /open?file=xxx — 打开文件（返回JSON，前端fetch静默调用）
    注意：/open 路由必须在 / 之前检查，否则 / 路径中的 return 会导致此处死代码"""
    # 安全加固：执行类接口仅允许本机调用，屏蔽局域网越权打开/运行文件
    if not handler._is_local():
        handler._send_json({"ok": False, "error": "安全限制：打开/运行文件仅允许本机操作。"}, 403)
        return
    # P0-① 安全修复：即便本机，也仅接受同源请求，挡住本机浏览器中的恶意跨域网页
    origin = handler.headers.get('Origin')
    if origin and not handler._is_same_origin(origin):
        handler._send_json({"ok": False, "error": "安全限制：/open 仅接受同源请求。"}, 403)
        return
    params = urllib.parse.parse_qs(parsed.query)
    rel_path = params.get('file', [''])[0]
    mode = params.get('mode', ['auto'])[0]  # auto/run/view
    if rel_path:
        success = open_local_file(rel_path, mode)
        # 审计日志记录（成功或失败都记录，失败不影响主流程）
        try:
            from core.audit_log import log_event
            log_event(
                event_type="OPEN_FILE",
                subsystem="server",
                summary=f"{'打开成功' if success else '打开失败'}: {rel_path}",
                detail=f"文件={rel_path}, 模式={mode}, 成功={success}",
                data={"file": rel_path, "mode": mode, "success": success},
                level="info" if success else "error",
            )
        except Exception:
            pass  # 审计失败不影响主流程

        # 文件操作自动记录（新增/修改/删除/打开/运行 统一留痕）
        try:
            import operation_log
            operation_log.log_file_op(
                op=("run" if mode == "run" else "open"),
                path=rel_path,
                detail=f"模式={mode}, 成功={success}",
                level="info" if success else "error",
            )
        except Exception:
            pass  # 记录失败不影响主流程

        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json; charset=utf-8')
        handler._set_cors()  # P0-① 安全修复：CORS 仅同源反射，去掉全局 '*'
        handler.end_headers()
        if success:
            result = {"ok": True, "file": rel_path, "mode": mode}
        else:
            result = {"ok": False, "error": f"文件不存在或打开失败: {rel_path}"}
        handler.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))


def handle_audit(handler):
    """GET /api/audit — 获取最近一次自动模型审查报告"""
    report_path = os.path.join(BASE_DIR, '金水谣数据', 'log', 'auto_audit_report.json')
    if os.path.isfile(report_path):
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                report = json.load(f)
            handler._send_json(report)
        except Exception as e:
            handler._send_json({"error": f"读取审计报告失败: {e}"})
    else:
        handler._send_json({"error": "尚未生成审计报告，请稍候或运行 auto_audit.py"})


def handle_audit_trail(handler):
    """GET /api/audit-trail — 操作留痕看板数据（全中文）"""
    try:
        sys.path.insert(0, BASE_DIR)
        from tools.audit_trail import get_today_events, verify_chain, _get_git_user
        events = get_today_events()
        chain_ok, _ = verify_chain()
        data = {
            "user": _get_git_user(),
            "events": events,
            "chain_ok": chain_ok,
        }
        handler._send_json(data)
    except Exception as e:
        handler._send_json({"error": f"读取操作留痕数据失败: {e}", "events": [], "user": "未知", "chain_ok": False})


# ---------------------------------------------------------------------------
# POST 路由处理函数
# ---------------------------------------------------------------------------
def handle_run_tests(handler):
    """POST /api/run-tests — 运行自动化测试"""
    # 安全加固：运行测试会执行本机程序，仅允许本机调用
    if not handler._is_local():
        handler._send_json({"error": "安全限制：运行测试仅允许本机操作。"}, 403)
        return
    try:
        result = subprocess.run(
            [SYSTEM_PYTHON, 'scripts/smoke_test.py'],
            capture_output=True, text=True, cwd=BASE_DIR, timeout=60,
            env={**os.environ, 'PYTHONPATH': BASE_DIR}
        )
        handler._send_json({
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        })
    except subprocess.TimeoutExpired:
        handler._send_json({"error": "测试超时（60秒）", "returncode": -1})
    except Exception as e:
        log(f'运行测试异常: {e}')
        handler._send_json({"error": f"运行测试失败：{e}", "returncode": -1})
