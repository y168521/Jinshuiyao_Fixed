# -*- coding: utf-8 -*-
"""金水谣系统 - 工具函数

跨模块复用的通用工具：日志、IP 检测、外部调用熔断、文件打开等。
"""
import os
import sys
import socket
import logging
import subprocess
import webbrowser
import concurrent.futures

from .config import (
    BASE_DIR, LOG_FILE, SYSTEM_PYTHON,
    _EXTERNAL_EXECUTOR, _EXT_TIMEOUT,
)


# ---------------------------------------------------------------------------
# 网络工具
# ---------------------------------------------------------------------------
def get_local_ip():
    """获取本机局域网IP地址"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ---------------------------------------------------------------------------
# GUI 跨会话启动（explorer 中转）
# ---------------------------------------------------------------------------
def _launch_gui_via_explorer(full_path: str) -> bool:
    """通过 explorer.exe 在用户桌面会话启动 GUI（隐藏启动器窗口）

    服务器进程可能运行在无桌面会话（watchdog DETACHED 拉起），直接 Popen
    的窗口用户看不到。explorer 常驻用户桌面会话，把任务交给它即可跨会话显示。
    返回 True 表示已交给 explorer（实际是否弹出由系统决定）。
    """
    import tempfile
    try:
        vbs = os.path.join(tempfile.gettempdir(),
                           'jinshuiyao_launch_%d.vbs' % os.getpid())
        python = SYSTEM_PYTHON.replace('.exe', 'w.exe')  # pythonw 无控制台窗口
        if not os.path.isfile(python):
            python = SYSTEM_PYTHON
        body = ('Set sh = CreateObject("WScript.Shell")\r\n'
                'sh.Run """%s"" ""%s""", 0, False\r\n'
                % (python.replace('"', '""'), full_path.replace('"', '""')))
        with open(vbs, 'w', encoding='utf-16-le', newline='') as f:
            f.write('\ufeff' + body)
        subprocess.Popen(['explorer.exe', vbs])
        return True
    except Exception:
        try:
            if os.path.isfile(vbs):
                os.remove(vbs)
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# 日志系统
# ---------------------------------------------------------------------------
_logger_obj = None


def _get_logger():
    """懒初始化模块级 logger（仅首次打开日志文件，之后复用句柄）。"""
    global _logger_obj
    if _logger_obj is None:
        _logger_obj = logging.getLogger("jinshuiyao")
        if not _logger_obj.handlers:
            try:
                os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
                _h = logging.FileHandler(LOG_FILE, encoding='utf-8')
                _h.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%H:%M:%S'))
                _logger_obj.addHandler(_h)
                _logger_obj.setLevel(logging.INFO)
            except Exception:
                _logger_obj = logging.getLogger("jinshuiyao")  # 失败则仅控制台
    return _logger_obj


def log(msg):
    """记录日志（使用 logging 模块，文件句柄常驻，避免每次调用都 open/close）"""
    line = f'[{__import__("datetime").datetime.now():%H:%M:%S}] {msg}'
    print(line)
    try:
        _get_logger().info(msg)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 外部调用并发执行器（带超时熔断）
# ---------------------------------------------------------------------------
def run_external(fn, timeout_key):
    """在受限线程池执行外部调用；返回 (resp_dict, status_code)。

    - 并发受限（_EXTERNAL_EXECUTOR 限制同时进行的外部调用数，避免线程暴涨）
    - 总超时熔断：超过 _EXT_TIMEOUT[timeout_key] 秒即返回 504，HTTP 连接不挂起
    - fn 内部应自行 try/except 返回正常响应字典；返回 (dict, status) 或 dict 均可
    """
    timeout = _EXT_TIMEOUT.get(timeout_key, 60)
    fut = _EXTERNAL_EXECUTOR.submit(fn)
    try:
        result = fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        logging.getLogger(__name__).warning(
            "[硬超时] 外部调用[%s]超过 %ss，已熔断返回 504", timeout_key, timeout)
        return ({"ok": False, "error": "处理超时（外部服务响应过慢），请稍后重试", "code": "TIMEOUT"}, 504)
    except Exception as e:
        logging.getLogger(__name__).exception("[硬超时] 外部调用[%s]异常", timeout_key)
        return ({"ok": False, "error": "处理异常：" + str(e)}, 500)
    if isinstance(result, tuple) and len(result) == 2:
        return result
    return (result, 200)


# ---------------------------------------------------------------------------
# 文件打开工具
# ---------------------------------------------------------------------------
_FUND_REPORT_RE = None  # 延迟导入（避免顶层依赖问题）


def _fund_report_fallback(rel_path: str):
    """基金日报回退：请求当天 fund_report_YYYY-MM-DD.html 不存在时，
    自动定位 fund_reports/ 下最新一期报告。

    Returns:
        (实际可打开的 rel_path, fallback_date 或 None, 提示语) 。
        非基金报告或不需回退时，fallback_date=None 且提示语为空。
    设计依据：基金日报每天 18:00 才生成（数据取自当日收盘后的净值），
    用户白天提前打开当天报告必然不存在——此处静默回退到最近一期，
    由前端通过 fallback_date 给出友好提示（参考 Superset 报告状态中性呈现、
    AI 报告系统"latest 恒可读"的通用模式）。
    """
    try:
        norm = rel_path.replace('/', os.sep)
        # 只对 fund_report_YYYY-MM-DD.html 这类路径做回退
        parts = norm.split(os.sep)
        filename = parts[-1] if parts else ''
        if not filename.lower().endswith('.html'):
            return rel_path, None, ''
        if not filename.startswith('fund_report_'):
            return rel_path, None, ''
        # 找到 fund_reports 目录
        idx = -1
        for i, p in enumerate(parts):
            if p == 'fund_reports':
                idx = i
                break
        if idx == -1:
            return rel_path, None, ''
        report_dir_rel = os.sep.join(parts[:idx + 1])
        report_dir_full = os.path.normpath(os.path.abspath(os.path.join(BASE_DIR, report_dir_rel)))
        if not os.path.isdir(report_dir_full):
            return rel_path, None, ''
        if os.path.isfile(os.path.normpath(os.path.abspath(os.path.join(BASE_DIR, norm)))):
            return rel_path, None, ''
        # 目录里找最新一期 fund_report_*.html
        import re
        _pat = re.compile(r'^fund_report_(\d{4}-\d{2}-\d{2})\.html$')
        candidates = []
        try:
            for name in os.listdir(report_dir_full):
                m = _pat.match(name)
                if m:
                    candidates.append((m.group(1), name))
        except OSError:
            return rel_path, None, ''
        if not candidates:
            return rel_path, None, ''
        candidates.sort(key=lambda x: x[0], reverse=True)
        latest_date, latest_name = candidates[0]
        new_rel = os.path.join(report_dir_rel, latest_name)
        log(f'=> [基金日报回退] {rel_path} 尚未生成，打开最新一期: {latest_date}')
        return new_rel, latest_date, f'今日报告 18:00 后生成，已打开最近一期 {latest_date}'
    except Exception:
        return rel_path, None, ''


def open_local_file(rel_path, mode='auto'):
    """根据文件类型和模式打开
    mode:
      auto - 根据扩展名自动判断(.py运行, .html浏览器, 其他记事本)
      run - 强制运行(.py/.bat直接执行)
      view - 强制查看(记事本打开任何文件)
    """
    # 统一路径分隔符
    rel_path = rel_path.replace('/', os.sep)
    full_path = os.path.normpath(os.path.abspath(os.path.join(BASE_DIR, rel_path)))
    base_norm = os.path.normpath(os.path.abspath(BASE_DIR))
    # 路径穿越防护：禁止逃出 BASE_DIR
    if full_path != base_norm and not full_path.startswith(base_norm + os.sep):
        log(f'× 路径穿越被拒绝: {rel_path} -> {full_path}')
        return False

    log(f'尝试打开: {rel_path} (mode={mode})')
    log(f'完整路径: {full_path}')

    # 检查路径是否存在
    if os.path.isdir(full_path):
        log(f'→ 打开文件夹: {full_path}')
        subprocess.Popen(['explorer.exe', full_path])  # JS-20260806-09：参数列表，消除引号注入歧义
        return True

    if not os.path.isfile(full_path):
        log(f'× 文件不存在: {full_path}')
        return False

    ext = os.path.splitext(full_path)[1].lower()

    # view模式：统一用记事本
    if mode == 'view':
        log(f'→ [查看模式] 记事本: {full_path}')
        try:
            subprocess.Popen(['notepad', full_path])
            return True
        except Exception as e:
            log(f'× 记事本失败: {e}')
            return False

    try:
        if ext == '.py':
            # 已知 GUI 文件列表（需要显示窗口）
            gui_files = [
                r'gui\main_window.py',
                r'domains\stock\stock_gui.py',
                r'domains\fund\fund_gui.py',
                r'domains\creator\creator_gui.py',
                r'jinshuiyao\football_gui.py',
                r'knowledge\mirofish_gui.py'
            ]

            # 判断是否是 GUI 文件
            is_gui_file = any(full_path.endswith(g) for g in gui_files)

            if mode in ('run', 'auto') and (mode == 'run' or is_gui_file):
                # run 模式：全部运行；auto 模式：仅 GUI 文件运行
                env = os.environ.copy()
                env['PYTHONPATH'] = BASE_DIR
                if is_gui_file:
                    # GUI 窗口必须显示在用户桌面会话。
                    # 服务器可能由 watchdog 以 DETACHED_PROCESS 拉起（无桌面会话），
                    # 直接 Popen 的 tkinter 窗口会跑到后台会话 → 用户看不到"打不开"。
                    # 方案：写临时 vbs(UTF-16LE BOM，中文路径安全) → explorer.exe 中转
                    #（explorer 运行在用户桌面会话，由它调 wscript 隐藏启动器窗口）。
                    try:
                        ok = _launch_gui_via_explorer(full_path)
                        if ok:
                            return True
                        log(f'× explorer 中转失败，回退直接启动: {full_path}')
                    except Exception as e:
                        log(f'× explorer 中转异常: {e}，回退直接启动')
                    log(f'→ [运行-GUI-回退] {SYSTEM_PYTHON} "{full_path}" (窗口显示)')
                    result = subprocess.Popen(
                        [SYSTEM_PYTHON, full_path],
                        cwd=BASE_DIR,
                        env=env
                    )
                else:
                    log(f'→ [运行-脚本] {SYSTEM_PYTHON} "{full_path}" (无窗口)')
                    result = subprocess.Popen(
                        [SYSTEM_PYTHON, full_path],
                        cwd=BASE_DIR,
                        env=env,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
            else:
                # auto 模式下非 GUI 的 .py 文件用记事本查看（安全）
                log(f'→ [自动模式] 记事本: {full_path}')
                result = subprocess.Popen(['notepad', full_path])
            log(f'  PID={result.pid}')
            return True
        elif ext == '.bat':
            if mode == 'run':
                log(f'→ [运行模式] cmd /c "{full_path}"')
                # 改为参数列表调用，避免 shell=True（路径来自 BASE_DIR 内受信文件，无外部输入）
                result = subprocess.Popen(
                    ['cmd', '/c', full_path],
                    shell=False,
                    cwd=BASE_DIR,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                log(f'  PID={result.pid}')
                return True
            else:
                log(f'→ [查看模式] 记事本: {full_path}')
                subprocess.Popen(['notepad', full_path])
                return True
        elif ext == '.html':
            log(f'→ 浏览器打开: {full_path}')
            from .config import safe_open_browser
            safe_open_browser('file:///' + full_path)
            return True
        else:
            log(f'→ 记事本: {full_path}')
            result = subprocess.Popen(['notepad', full_path])
            log(f'  PID={result.pid}')
            return True
    except Exception as e:
        log(f'× 启动失败: {e}')
        return False
