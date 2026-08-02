# -*- coding: utf-8 -*-
"""GUI 运行状态注册（web 控制中心 ↔ 桌面程序联动）

GUI 启动时 register() 写入心跳（pid/标题/时间），进程退出自动清理；
服务器 /api/automation-status 通过 check() 检测各 GUI 是否仍在运行。
文件统一放在 金水谣数据/log/gui_status.json，GUI 失败退出不会留下脏状态
（register 时以当前 pid 为准，check 时校验 pid 存活）。
"""
import atexit
import json
import os
import sys
import threading

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATUS_FILE = os.path.join(_PROJECT_ROOT, '金水谣数据', 'log', 'gui_status.json')

_lock = threading.Lock()
_registered = {}


def register(name, window_title=''):
    """注册 GUI 运行状态。name 固定为 5 个 GUI 的标识名。"""
    _lock.acquire()
    try:
        status = {
            'pid': os.getpid(),
            'title': window_title,
            'started_at': _now_iso(),
        }
        data = _read()
        data[name] = status
        _write(data)
        _registered[name] = True
    finally:
        _lock.release()

    def _cleanup():
        _unregister(name)

    atexit.register(_cleanup)
    return True


def _unregister(name):
    _lock.acquire()
    try:
        data = _read()
        if data.get(name, {}).get('pid') == os.getpid():
            data.pop(name, None)
            _write(data)
    finally:
        _lock.release()


def running(name):
    """检测 GUI 是否仍在运行（读心跳 + pid 存活校验）"""
    data = _read()
    rec = data.get(name)
    if not rec:
        return False
    pid = rec.get('pid')
    if not pid:
        return False
    if sys.platform == 'win32':
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def status(name):
    """返回 {running, pid, title, started_at} 或 None（无记录）"""
    data = _read()
    rec = data.get(name)
    if not rec:
        return None
    return {
        'running': running(name),
        'pid': rec.get('pid'),
        'title': rec.get('title', ''),
        'started_at': rec.get('started_at'),
    }


def all_status(names):
    """批量状态：{name: {running, pid, title, started_at}}"""
    return {n: status(n) for n in names}


def _pid_alive_windows(pid):
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            exit_code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(h)
            return bool(ok) and exit_code.value == 259  # 259=STILL_ACTIVE
        except Exception:
            return False
    except Exception:
        return True  # 无法判定时保守认为存活


def _read():
    try:
        with open(_STATUS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _write(data):
    try:
        os.makedirs(os.path.dirname(_STATUS_FILE), exist_ok=True)
        with open(_STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _now_iso():
    import datetime
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
