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
def open_local_file(rel_path, mode='auto'):
    """根据文件类型和模式打开
    mode:
      auto - 根据扩展名自动判断(.py运行, .html浏览器, 其他记事本)
      run  - 强制运行(.py/.bat直接执行)
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
        subprocess.Popen(f'explorer "{full_path}"')
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
                    log(f'→ [运行-GUI] {SYSTEM_PYTHON} "{full_path}" (窗口显示)')
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
