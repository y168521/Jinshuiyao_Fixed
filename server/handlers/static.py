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
    '/compare-tech':        'compare-tech.html',
    '/math-model':          'math-model.html',
    '/prediction-reference':'prediction-reference.html',
    '/chain-map':          'chain-map.html',
    '/agent-pipeline':     'agent-pipeline-visualizer.html',
    '/prediction-tracker': 'prediction-tracker.html',
    '/showcase':           'showcase.html',
    '/system-tools':       'system-tools.html',
    '/daily-report':       'daily-report.html',
    '/automation-status':  'automation-status.html',
    '/scheduler-board':    'scheduler-board.html',
    '/knowledge-browser':  'knowledge-browser.html',
    '/ai-usage':           'ai-usage.html',
    '/changelog':          'changelog.html',
}

# 外部页面路由（不在 HTML_DIR 内的独立仪表板页面）
_EXTERNAL_PAGE_ROUTES = {
    '/dashboard':      os.path.join(BASE_DIR, 'frontend/dashboard', 'jinshuiyao-dashboard.html'),
    '/trend':          os.path.join(BASE_DIR, 'frontend/trend', 'jinshuiyao-trend.html'),
    '/quant':          os.path.join(BASE_DIR, 'frontend/quant-dashboard', 'index.html'),
    '/gap-analysis':   os.path.join(BASE_DIR, 'frontend/gap-analysis', 'jinshuiyao-gap-analysis.html'),
    '/deepseek-manual': os.path.join(BASE_DIR, 'AI代码助手(DeepSeek备用)', '使用说明.html'),
    '/fund-dashboard':  os.path.join(BASE_DIR, 'frontend', 'fund', 'dashboard.html'),
    '/lottery-dashboard': os.path.join(HTML_DIR, 'lottery-dashboard.html'),
    '/rotation-matrix': os.path.join(BASE_DIR, 'frontend', 'lottery', 'rotation-matrix.html'),
    '/filter-panel':    os.path.join(BASE_DIR, 'frontend', 'lottery', 'filter-panel.html'),
    '/prize-calculator': os.path.join(BASE_DIR, 'frontend', 'lottery', 'prize-calculator.html'),
    '/audit-dashboard':  os.path.join(BASE_DIR, 'frontend', 'lottery', 'audit-dashboard.html'),
    '/automation-dashboard': os.path.join(HTML_DIR, 'automation-dashboard.html'),
    '/head-tail-analysis': os.path.join(BASE_DIR, 'frontend', 'lottery', 'head-tail-analysis.html'),
    # 轻量入口：A股每日情绪日报（独立脚本每日生成，最新一份始终覆盖此文件）
    '/daily-sentiment': os.path.join(ROOT_DIR, 'deliverables', 'A股情绪日报_最新.html'),
    # 股票系统同名入口（同一份独立日报，仅路由路径不同，便于从股票中心进入）
    '/stock/daily-sentiment': os.path.join(ROOT_DIR, 'deliverables', 'A股情绪日报_最新.html'),
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
    '/lottery/combo-calculator': os.path.join(BASE_DIR, 'frontend', 'lottery', 'combo-calculator.html'),
    '/lottery/trend-classification': os.path.join(BASE_DIR, 'frontend', 'lottery', 'trend-classification.html'),
    '/lottery/omission-table':    os.path.join(BASE_DIR, 'frontend', 'lottery', 'omission-table.html'),
    '/lottery/hot-rank':          os.path.join(BASE_DIR, 'frontend', 'lottery', 'hot-rank.html'),
}

# 基金/股票/足彩 子系统路由
_SUBSYSTEM_ROUTES = {
    '/fund':              os.path.join(BASE_DIR, 'frontend', 'fund', 'fund-hub.html'),
    '/fund/dashboard':    os.path.join(BASE_DIR, 'frontend', 'fund', 'dashboard.html'),
    '/fund/nav-trend':    os.path.join(BASE_DIR, 'frontend', 'fund', 'nav-trend.html'),
    '/fund/holdings':     os.path.join(BASE_DIR, 'frontend', 'fund', 'holdings.html'),
    '/fund/screener':     os.path.join(BASE_DIR, 'frontend', 'fund', 'screener.html'),
    '/fund/detail':       os.path.join(BASE_DIR, 'frontend', 'fund', 'fund-detail.html'),
    '/fund/dca':          os.path.join(BASE_DIR, 'frontend', 'fund', 'dca-simulator.html'),
    '/fund/portfolio':    os.path.join(BASE_DIR, 'frontend', 'fund', 'portfolio.html'),
    '/stock':             os.path.join(BASE_DIR, 'frontend', 'stock', 'stock-hub.html'),
    '/stock/dashboard':   os.path.join(BASE_DIR, 'frontend', 'stock', 'stock-dashboard.html'),
    '/stock/detail':      os.path.join(BASE_DIR, 'frontend', 'stock', 'stock-detail.html'),
    '/football':          os.path.join(BASE_DIR, 'frontend', 'football', 'football-hub.html'),
    '/football/dashboard': os.path.join(BASE_DIR, 'frontend', 'football', 'dashboard.html'),
    '/football/matches':   os.path.join(BASE_DIR, 'frontend', 'football', 'matches.html'),
    '/football/predict':   os.path.join(BASE_DIR, 'frontend', 'football', 'predict.html'),
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
            handler._send_json({"error": "页面不存在"}, 404)
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
        # 路径消毒（纵深防御，与 open_local_file 内部防护一致）：仅允许项目目录内相对路径
        cand = os.path.normpath(os.path.abspath(os.path.join(BASE_DIR, rel_path.replace('/', os.sep))))
        base_norm = os.path.normpath(os.path.abspath(BASE_DIR))
        if cand != base_norm and not cand.startswith(base_norm + os.sep):
            log(f'× /open 路径穿越被拒绝: {rel_path}')
            handler._send_json({"ok": False, "error": "安全限制：路径必须在项目目录内。"}, 403)
            return
        # 基金日报回退：当天报告未生成时自动打开最新一期（前端据此给友好提示）
        fallback_date = None
        fallback_hint = ""
        try:
            from server.utils import _fund_report_fallback
            rel_path2, fallback_date, fallback_hint = _fund_report_fallback(rel_path)
            if rel_path2 != rel_path.replace('/', os.sep):
                rel_path = rel_path2
        except Exception:
            pass
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
            if fallback_date:
                result.update({"fallback_date": fallback_date, "hint": fallback_hint})
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


def handle_automation_status(handler):
    """GET /api/automation-status — 自动化体系运行状态（自动同步/看门狗/蒸馏/vault/服务器）"""
    import datetime
    import re as _re
    LOG_DIR = os.path.join(BASE_DIR, '金水谣数据', 'log')

    def _read_tail(name, n=8):
        try:
            p = os.path.join(LOG_DIR, name)
            if not os.path.isfile(p):
                return []
            with open(p, encoding='utf-8', errors='replace') as f:
                return [ln.rstrip() for ln in f.readlines()[-n:] if ln.strip()]
        except Exception:
            return []

    def _last_line_ts(name):
        """从日志最后一行解析时间戳（ISO 或 自定义），无则 None"""
        lines = _read_tail(name, 1)
        if not lines:
            return None
        return _last_line_ts_from_lines(lines)

    def _last_line_ts_from_lines(lines):
        """从给定行列表最后一行解析时间戳"""
        if not lines:
            return None
        ln = lines[-1]
        m = _re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]', ln)
        if m:
            try:
                return datetime.datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S').isoformat()
            except Exception:
                return None
        m = _re.search(r'(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})', ln)
        if m:
            try:
                return datetime.datetime.strptime(m.group(1).replace('T', ' '), '%Y-%m-%d %H:%M:%S').isoformat()
            except Exception:
                return None
        m = _re.search(r'^(\d{14})', ln)  # distill.log 格式
        if m:
            try:
                return datetime.datetime.strptime(m.group(1), '%Y%m%d%H%M%S').isoformat()
            except Exception:
                return None
        return None

    def _tail_json(name):
        try:
            p = os.path.join(LOG_DIR, name)
            if os.path.isfile(p):
                with open(p, encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    # 1) 自动同步：最后活动时间 + 最近日志
    sync_lines = _read_tail('auto_sync.log', 10)
    sync_last = _last_line_ts('auto_sync.log')
    sync_ok = any('committed and pushed' in ln for ln in sync_lines) or sync_last is not None

    # 2) 看门狗：状态文件 + 最近日志（watchdog 写在外层 模型/金水谣数据/log/）
    wd_log_dir = os.path.join(BASE_DIR, '..', '金水谣数据', 'log')
    wd_state_path = os.path.join(wd_log_dir, 'watchdog_state.json')
    wd_log_path = os.path.join(wd_log_dir, 'watchdog.log')
    wd_state = {}
    try:
        if os.path.isfile(wd_state_path):
            with open(wd_state_path, encoding='utf-8') as f:
                wd_state = json.load(f)
    except Exception:
        pass
    wd_lines = _read_tail('watchdog.log', 10) if os.path.isfile(os.path.join(LOG_DIR, 'watchdog.log')) else []
    try:
        if os.path.isfile(wd_log_path):
            with open(wd_log_path, encoding='utf-8', errors='replace') as f:
                wd_lines = [ln.rstrip() for ln in f.readlines()[-10:] if ln.strip()]
    except Exception:
        pass
    wd_last = _last_line_ts_from_lines(wd_lines)
    wd_last_ok = any(('自动恢复' in ln) or ('[OK]' in ln) or ('巡检结束' in ln) for ln in wd_lines)

    # 3) 蒸馏：最近日志 + 队列文件行数
    dist_lines = _read_tail('distill.log', 10)
    dist_last = _last_line_ts('distill.log')
    queue_path = os.path.join(LOG_DIR, '待蒸馏队列.md')
    queue_lines = 0
    if os.path.isfile(queue_path):
        try:
            with open(queue_path, encoding='utf-8') as f:
                queue_lines = sum(1 for ln in f if ln.strip().startswith('### '))
        except Exception:
            pass

    # 4) vault 刷新：refresh.log（在 模型/obsidian-vault 目录）
    vault_last = None
    vault_lines = []
    refresh_log = os.path.join(BASE_DIR, '..', 'obsidian-vault', 'refresh.log')
    if os.path.isfile(refresh_log):
        try:
            with open(refresh_log, encoding='utf-8') as f:
                vault_lines = [ln.rstrip() for ln in f.readlines()[-3:] if ln.strip()]
            m = _re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]', vault_lines[-1] if vault_lines else '')
            if m:
                vault_last = m.group(1).replace(' ', 'T')
        except Exception:
            pass

    # 5) 服务器进程：18888 是否存活
    server_alive = False
    try:
        import socket
        s = socket.create_connection(('127.0.0.1', 18888), timeout=2)
        s.close()
        server_alive = True
    except Exception:
        pass

    # 6) 计划任务状态（无头子进程下 stdout 可能为空，用 exit code 判断）
    def _task_ok(name):
        try:
            r = subprocess.run(['schtasks', '/query', '/tn', name, '/fo', 'csv'],
                               capture_output=True, timeout=10)
            return r.returncode == 0
        except Exception:
            return False

    # 7) 数据真实性守卫：data_truth.log（自动同步第7步写入）
    dt_lines = _read_tail('data_truth.log', 6)
    dt_last = _last_line_ts('data_truth.log')
    dt_ok = None  # None=未知
    if dt_lines:
        last = dt_lines[-1]
        if '健康' in last:
            dt_ok = True
        elif '降级' in last:
            dt_ok = None
        elif '异常' in last:
            dt_ok = False

    data = {
        "updated_at": datetime.datetime.now().isoformat(),
        "server": {"alive": server_alive, "port": 18888},
        "auto_sync": {
            "ok": sync_ok,
            "last_run": sync_last,
            "recent": sync_lines[-5:],
            "task_ok": _task_ok("Jinshuiyao自动同步"),
        },
        "watchdog": {
            "ok": wd_last_ok or bool(wd_state),
            "last_run": wd_last,
            "recent": wd_lines[-5:],
            "task_ok": _task_ok("JinshuiyaoWatchdog"),
            "state": wd_state,
        },
        "distill": {
            "last_run": dist_last,
            "recent": dist_lines[-5:],
            "queue_count": queue_lines,
        },
        "vault": {
            "last_refresh": vault_last,
            "recent": vault_lines,
        },
        "data_truth": {
            "ok": dt_ok,
            "last_run": dt_last,
            "recent": dt_lines[-4:],
        },
    }

    # 8) 桌面程序（GUI）联动状态：心跳注册 + pid 存活检测
    try:
        from core.gui_registry import all_status
        data["guis"] = all_status(['fund', 'stock', 'creator', 'football', 'mirofish'])
    except Exception as e:
        data["guis"] = {"error": str(e)}

    handler._send_json(data)


# ---------------------------------------------------------------------------
# GET /api/logs — 统一日志联动查看
# ---------------------------------------------------------------------------
def handle_logs(handler):
    """GET /api/logs[?name=auto_sync.log][&tail=100][&list=1]

    list=1 时返回 log 目录下全部日志文件（名称/大小/修改时间/最后一行时间戳）；
    否则返回指定日志文件的末尾 tail 行。
    """
    import datetime
    LOG_DIR = os.path.join(BASE_DIR, '金水谣数据', 'log')
    q = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
    if q.get('list', [''])[0]:
        try:
            files = []
            for name in sorted(os.listdir(LOG_DIR)):
                p = os.path.join(LOG_DIR, name)
                if not os.path.isfile(p):
                    continue
                if not (name.endswith('.log') or name.endswith('.jsonl')):
                    continue
                try:
                    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M:%S')
                    size = os.path.getsize(p)
                except Exception:
                    mtime, size = '', 0
                tail = ''
                try:
                    with open(p, encoding='utf-8', errors='replace') as f:
                        lines = [ln.rstrip() for ln in f.readlines()[-3:] if ln.strip()]
                    tail = lines[-1] if lines else ''
                except Exception:
                    pass
                files.append({'name': name, 'size': size, 'mtime': mtime, 'last': tail})
            handler._send_json({'files': files, 'updated_at': datetime.datetime.now().isoformat()})
        except Exception as e:
            handler._send_json({'error': f'读取日志目录失败: {e}', 'files': []})
        return

    name = q.get('name', ['auto_sync.log'])[0]
    name = os.path.basename(name)  # 防路径穿越
    tail = 100
    try:
        tail = min(max(int(q.get('tail', ['100'])[0]), 1), 500)
    except Exception:
        pass
    p = os.path.join(LOG_DIR, name)
    if not os.path.isfile(p):
        handler._send_json({'error': f'日志不存在: {name}', 'lines': []})
        return
    try:
        with open(p, encoding='utf-8', errors='replace') as f:
            lines = [ln.rstrip() for ln in f.readlines()[-tail:] if ln.strip()]
        handler._send_json({'name': name, 'lines': lines, 'total': len(lines)})
    except Exception as e:
        handler._send_json({'error': f'读取日志失败: {e}', 'lines': []})


# ---------------------------------------------------------------------------
# POST 路由处理函数
# ---------------------------------------------------------------------------
def handle_time_check(handler):
    """GET /api/system/time-check — 系统时间偏差检测

    用 HTTP 响应 Date 头（权威时间源）对比本机时钟；偏差 >24h 判定异常。
    网络不可用时 checkable=false（跳过不告警，避免离线误报）。
    """
    try:
        import time as _time
        offset = None
        try:
            import requests
            r = requests.head(
                "https://www.baidu.com", timeout=6,
                headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code < 500 and r.headers.get("Date"):
                from email.utils import parsedate_to_datetime
                net_ts = parsedate_to_datetime(r.headers["Date"]).timestamp()
                offset = int(_time.time() - net_ts)
        except Exception:
            offset = None
        if offset is None:
            handler._send_json({"ok": True, "checkable": False,
                                "message": "网络不可用，跳过时间校验"})
            return
        bad = abs(offset) > 86400
        handler._send_json({
            "ok": True, "checkable": True,
            "offset_seconds": offset,
            "bad": bad,
            "message": ("⚠️ 本机时间与网络时间偏差 %d 秒，可能影响开奖数据抓取"
                        % abs(offset) if bad else "本机时间正常"),
        })
    except Exception as e:
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_backup(handler):
    """GET /api/system/backup — 一键创建数据快照（坚果云安全位置）

    复用 tools/auto_backup.py 的 create_snapshot（已含安全位置校验+旧快照清理）。
    """
    try:
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)
        from tools.auto_backup import create_snapshot, get_latest_snapshot
        q = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        if q.get('latest', [''])[0]:
            latest = None
            try:
                latest = get_latest_snapshot()
            except Exception:
                pass
            handler._send_json({'ok': True, 'latest': latest})
            return
        snap = create_snapshot()
        latest = None
        try:
            latest = get_latest_snapshot()
        except Exception:
            pass
        if not snap:
            handler._send_json({'ok': False, 'message': '备份失败：未生成快照（检查坚果云同步目录权限）'})
            return
        handler._send_json({'ok': True, 'message': '快照已创建', 'snapshot': snap, 'latest': latest})
    except Exception as e:
        handler._send_json({'ok': False, 'message': '备份异常：%s' % e})


def handle_frontend_errors(handler):
    """GET /api/frontend-errors?limit=50 — 前端错误收集（error-monitor 上报 JSONL）尾部 N 条"""
    import datetime
    LOG_DIR = os.path.join(BASE_DIR, '金水谣数据', 'log', 'err_log')
    q = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
    limit = 50
    try:
        limit = min(max(int(q.get('limit', ['50'])[0]), 1), 200)
    except Exception:
        pass
    p = os.path.join(LOG_DIR, 'frontend_errors.jsonl')
    if not os.path.isfile(p):
        handler._send_json({'ok': True, 'total': 0, 'errors': []})
        return
    try:
        rows = []
        with open(p, encoding='utf-8', errors='replace') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    rows.append({'raw': ln})
        total = len(rows)
        handler._send_json({'ok': True, 'total': total, 'errors': rows[-limit:]})
    except Exception as e:
        handler._send_json({'ok': False, 'message': '读取错误日志失败：%s' % e, 'total': 0, 'errors': []})


def handle_daily_report(handler):
    """GET /api/daily-report[?date=YYYY-MM-DD][&list=1] — 大脑日报读取

    list=1 返回全部日报日期列表；否则返回指定日期（默认最新）日报的 markdown 原文。
    """
    import datetime
    LOG_DIR = os.path.join(BASE_DIR, '金水谣数据', 'log')
    q = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
    if q.get('list', [''])[0]:
        dates = []
        try:
            for name in sorted(os.listdir(LOG_DIR)):
                if name.startswith('大脑日报_') and name.endswith('.md'):
                    dates.append(name[5:-3])
        except Exception:
            pass
        handler._send_json({'ok': True, 'dates': dates})
        return
    date = q.get('date', [''])[0]
    if date:
        date = os.path.basename(date)  # 防路径穿越
    if not date:
        try:
            from engines.brain_daily import _today
            date = _today()
        except Exception:
            date = datetime.datetime.now().strftime('%Y-%m-%d')
    p = os.path.join(LOG_DIR, '大脑日报_%s.md' % date)
    if not os.path.isfile(p):
        handler._send_json({'ok': True, 'date': date, 'exists': False, 'markdown': ''})
        return
    try:
        with open(p, encoding='utf-8', errors='replace') as f:
            md = f.read()
        handler._send_json({'ok': True, 'date': date, 'exists': True, 'markdown': md})
    except Exception as e:
        handler._send_json({'ok': False, 'message': '读取日报失败：%s' % e})


def handle_knowledge_list(handler):
    """GET /api/knowledge/list[?q=&subsystem=&limit=&offset=] — 知识卡片浏览（分页/筛选/搜索）

    读取 knowledge/mirofish_db.json 全部知识卡片，按 subsystem 筛选、关键词匹配标题+标签。
    """
    q = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
    limit, offset = 50, 0
    try:
        limit = min(max(int(q.get('limit', ['50'])[0]), 1), 200)
        offset = max(int(q.get('offset', ['0'])[0]), 0)
    except Exception:
        pass
    sub = q.get('subsystem', [''])[0]
    kw = q.get('q', [''])[0].strip().lower()
    try:
        from knowledge.mirofish_db import MiroFishDB
        import datetime
        cards = MiroFishDB()._data.get('cards', [])
    except Exception as e:
        handler._send_json({'ok': False, 'message': '读取知识库失败：%s' % e, 'total': 0, 'cards': []})
        return
    subs = {}
    filtered = []
    for c in cards:
        csub = c.get('subsystem') or c.get('category') or '其他'
        subs[csub] = subs.get(csub, 0) + 1
        if sub and csub != sub:
            continue
        if kw:
            hay = ((c.get('title') or '') + ' ' + ' '.join(c.get('tags') or [])).lower()
            if kw not in hay:
                continue
        filtered.append(c)
    total = len(filtered)
    page = filtered[offset:offset + limit]
    rows = []
    for c in page:
        created = c.get('created_at') or c.get('create_time') or ''
        rows.append({
            'id': c.get('id', ''),
            'title': c.get('title', ''),
            'content': (c.get('content') or '')[:400],
            'source': c.get('source', ''),
            'subsystem': c.get('subsystem') or c.get('category') or '其他',
            'tags': c.get('tags') or [],
            'score': c.get('score'),
            'created': str(created)[:19] if created else '',
        })
    handler._send_json({'ok': True, 'total': total, 'subsystems': subs, 'cards': rows})


def handle_changelog(handler):
    """GET /api/changelog — 最近更新日志（git log 最近 30 条提交）

    纯只读本仓库 git 历史，返回 hash/日期/提交信息，供前端展示"最近改了什么"。
    """
    import subprocess
    try:
        r = subprocess.run(
            ['git', '-C', BASE_DIR, 'log', '--pretty=%h|%ad|%s', '--date=short', '-30'],
            capture_output=True, timeout=10, encoding='utf-8', errors='replace')
        rows = []
        for line in (r.stdout or '').strip().splitlines():
            parts = line.split('|', 2)
            if len(parts) >= 3:
                rows.append({'hash': parts[0], 'date': parts[1], 'msg': parts[2]})
        handler._send_json({'ok': True, 'total': len(rows), 'logs': rows})
    except Exception as e:
        handler._send_json({'ok': False, 'message': '读取 git 日志失败：%s' % e, 'total': 0, 'logs': []})


def handle_run_tests(handler):
    """POST /api/run-tests — 运行自动化测试"""
    # 安全加固：运行测试会执行本机程序，仅允许本机调用
    if not handler._is_local():
        handler._send_json({"error": "安全限制：运行测试仅允许本机操作。"}, 403)
        return
    try:
        result = subprocess.run(
            [SYSTEM_PYTHON, 'tools/smoke_test.py'],
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
