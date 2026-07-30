# -*- coding: utf-8 -*-
"""
金水谣万物引擎 - 环境检测脚本

功能：
  1. 检测系统Python（D:/python38 等候选路径）是否存在
  2. 检测所有关键依赖是否已安装
  3. 缺失依赖自动尝试pip安装
  4. 生成检测报告到 金水谣数据/log/env_check.log

用法：
  python scripts/check_env.py
"""

import os
import sys
import subprocess
import importlib
from datetime import datetime

# ================================================================
# 配置
# ================================================================
try:
    from config.path_resolver import get_system_python, get_system_pythonw
    SYSTEM_PYTHON = get_system_python() or r'D:\python38\python.exe'
    SYSTEM_PYTHONW = get_system_pythonw() or r'D:\python38\pythonw.exe'
except ImportError:
    SYSTEM_PYTHON = r'D:\python38\python.exe'
    SYSTEM_PYTHONW = r'D:\python38\pythonw.exe'
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, '金水谣数据', 'log')
LOG_FILE = os.path.join(LOG_DIR, 'env_check.log')

# 关键依赖列表（模块名: 显示名称）
DEPENDENCIES = {
    'tkinter': 'tkinter (GUI必需)',
    'akshare': 'akshare (数据获取)',
    'matplotlib': 'matplotlib (图表)',
    'numpy': 'numpy (数值计算)',
    'pandas': 'pandas (数据处理)',
    'requests': 'requests (网络请求)',
    'bs4': 'bs4 / beautifulsoup4 (网页解析)',
    'lxml': 'lxml (XML解析)',
    'openpyxl': 'openpyxl (Excel读写)',
    'PIL': 'PIL / pillow (图像处理)',
}

# pip包名映射（模块名 -> pip安装名）
PIP_MAP = {
    'tkinter': None,  # tkinter无法通过pip安装
    'akshare': 'akshare',
    'matplotlib': 'matplotlib',
    'numpy': 'numpy',
    'pandas': 'pandas',
    'requests': 'requests',
    'bs4': 'beautifulsoup4',
    'lxml': 'lxml',
    'openpyxl': 'openpyxl',
    'PIL': 'pillow',
}

# ANSI颜色
COLOR_GREEN = '\033[92m'
COLOR_RED = '\033[91m'
COLOR_YELLOW = '\033[93m'
COLOR_RESET = '\033[0m'


def ensure_dir(path):
    """确保目录存在"""
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def log_line(msg):
    """打印并记录一行日志"""
    print(msg)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
    except Exception:
        pass


def check_python():
    """检测系统Python是否存在"""
    results = []
    py_exists = os.path.isfile(SYSTEM_PYTHON)
    pyw_exists = os.path.isfile(SYSTEM_PYTHONW)

    if py_exists and pyw_exists:
        # 获取版本
        try:
            ver = subprocess.check_output(
                [SYSTEM_PYTHON, '--version'],
                stderr=subprocess.STDOUT, text=True, timeout=10
            ).strip()
        except Exception as e:
            ver = f'无法获取版本 ({e})'
        msg = f'[OK] {ver} @ {SYSTEM_PYTHON}'
        results.append(('OK', msg))
    else:
        msg = f'[FAIL] 系统Python不存在: {SYSTEM_PYTHON}'
        results.append(('FAIL', msg))

    # 同时显示当前解释器
    cur_ver = f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'
    msg = f'[INFO] 当前解释器: Python {cur_ver} @ {sys.executable}'
    results.append(('INFO', msg))

    return results


def check_dependency(mod_name, display_name):
    """
    检测单个依赖
    返回: (status, message)
    status: OK / FAIL / WARN
    """
    # tkinter特殊处理
    if mod_name == 'tkinter':
        try:
            importlib.import_module('tkinter')
            return 'OK', f'[OK] {display_name}'
        except ImportError:
            return 'FAIL', f'[FAIL] {display_name} 缺失（tkinter是Python内置模块，请重新安装完整版Python）'

    # 其他模块
    try:
        importlib.import_module(mod_name)
        return 'OK', f'[OK] {display_name}'
    except ImportError:
        # 尝试pip安装
        pip_pkg = PIP_MAP.get(mod_name)
        if pip_pkg:
            install_msg = try_install(pip_pkg)
            if install_msg:
                return 'OK', f'[OK] {display_name} (已自动安装)'
            else:
                return 'FAIL', f'[FAIL] {display_name} 缺失，自动安装失败，请手动执行: pip install {pip_pkg}'
        else:
            return 'FAIL', f'[FAIL] {display_name} 缺失，无法自动安装'


def try_install(package):
    """尝试用pip安装包，返回是否成功"""
    pip_exe = os.path.join(os.path.dirname(SYSTEM_PYTHON), 'pip.exe')
    if not os.path.isfile(pip_exe):
        pip_exe = os.path.join(os.path.dirname(sys.executable), 'pip.exe')
    if not os.path.isfile(pip_exe):
        pip_exe = 'pip'

    try:
        subprocess.check_call(
            [pip_exe, 'install', '--quiet', package],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120
        )
        return True
    except Exception:
        return False


def print_colored(status, msg):
    """带颜色输出到控制台"""
    if status == 'OK':
        print(f'{COLOR_GREEN}{msg}{COLOR_RESET}')
    elif status == 'FAIL':
        print(f'{COLOR_RED}{msg}{COLOR_RESET}')
    elif status == 'WARN':
        print(f'{COLOR_YELLOW}{msg}{COLOR_RESET}')
    else:
        print(msg)


def main():
    ensure_dir(LOG_DIR)

    # 清空日志
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        f.write('')

    # 报告头
    header = [
        '=' * 40,
        '  金水谣万物引擎 - 环境检测',
        '=' * 40,
    ]
    for line in header:
        log_line(line)

    # 检测Python
    log_line('')
    log_line('[Python 环境]')
    for status, msg in check_python():
        print_colored(status, msg)
        log_line(msg)

    # 检测依赖
    log_line('')
    log_line('[依赖检测]')
    ok_count = 0
    fail_count = 0
    for mod_name, display_name in DEPENDENCIES.items():
        status, msg = check_dependency(mod_name, display_name)
        print_colored(status, msg)
        log_line(msg)
        if status == 'OK':
            ok_count += 1
        else:
            fail_count += 1

    # 报告尾
    log_line('')
    log_line('=' * 40)
    summary = f'总结: {ok_count}/{len(DEPENDENCIES)} 通过, {fail_count} 失败'
    log_line(summary)
    log_line(f'报告保存: {LOG_FILE}')
    log_line('=' * 40)

    print('')
    print_colored('INFO' if fail_count == 0 else 'WARN', summary)
    print(f'检测报告已保存: {LOG_FILE}')

    return fail_count == 0


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
