# -*- coding: utf-8 -*-
"""万物预测引擎 - 文件启动器
用法: python launcher.py "文件路径" "打开方式"
打开方式: run(运行Python) / view(记事本打开) / browse(浏览器打开) / folder(打开文件夹)

此脚本用于从HTML导航指南中一键打开文件。
跨平台兼容：Windows/macOS/Linux（无桌面环境时静默跳过）。
"""
import os
import sys
import subprocess
import platform

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDE_DIR = os.path.dirname(os.path.abspath(__file__))

_IS_WINDOWS = platform.system() == "Windows"


def _safe_open_local(path):
    """跨平台打开本地文件/文件夹"""
    try:
        if _IS_WINDOWS:
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def _safe_open_browser(url):
    """跨平台打开浏览器"""
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


def open_file(filepath, mode="view"):
    """根据模式打开文件"""
    # 处理相对路径
    if not os.path.isabs(filepath):
        # 先在项目目录找，再在指南目录找
        test1 = os.path.join(BASE_DIR, filepath)
        test2 = os.path.join(GUIDE_DIR, filepath)
        if os.path.exists(test1):
            filepath = test1
        elif os.path.exists(test2):
            filepath = test2
        else:
            # 文件不存在，尝试打开文件夹
            folder = os.path.join(BASE_DIR, os.path.dirname(filepath))
            if os.path.isdir(folder):
                _safe_open_local(folder)
            return

    if not os.path.exists(filepath):
        # 尝试打开所在文件夹
        folder = os.path.dirname(filepath)
        if os.path.isdir(folder):
            _safe_open_local(folder)
        return

    if mode == "run":
        # 运行Python脚本
        kwargs = {"cwd": os.path.dirname(filepath)}
        if _IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        subprocess.Popen([sys.executable, filepath], **kwargs)
    elif mode == "browse":
        # 浏览器打开HTML
        _safe_open_browser("file:///" + filepath.replace("\\", "/"))
    elif mode == "folder":
        # 打开文件夹并选中文件
        folder = os.path.dirname(filepath)
        _safe_open_local(folder)
    else:
        # 默认：用系统关联程序打开（记事本打开txt/json/py等）
        _safe_open_local(filepath)


def main():
    if len(sys.argv) < 2:
        print('用法: python launcher.py "文件路径" "打开方式"')
        print('打开方式: run / view / browse / folder')
        sys.exit(1)
    filepath = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "view"
    open_file(filepath, mode)


if __name__ == "__main__":
    main()
