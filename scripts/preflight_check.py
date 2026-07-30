# -*- coding: utf-8 -*-
"""金水谣引擎 - 前置检查脚本

每次修改代码前必须运行此脚本，它会检查所有反复出问题的点。
如果任何一项失败，脚本退出码非0，阻止后续操作。

用法: python scripts/preflight_check.py
"""
import os
import sys
import re
import subprocess

# -----------------------------------------------------------------------
# 项目根目录定位
# -----------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.normpath(os.path.join(_THIS_DIR, ".."))
os.chdir(PROJECT_DIR)

# 颜色输出（Windows CMD 支持）
_PASS = "\033[32m[PASS]\033[0m"
_FAIL = "\033[31m[FAIL]\033[0m"
_WARN = "\033[33m[WARN]\033[0m"

results = []  # 每项为 (名称, 通过布尔, 详情)


def check(name, passed, detail=""):
    """记录一项检查结果"""
    results.append((name, passed, detail))
    tag = _PASS if passed else _FAIL
    print(f"{tag} {name}: {detail}")


# =====================================================================
# 检查项1: GUI sys.path 检查
# =====================================================================
def check_gui_syspath():
    """遍历所有 GUI 文件，确认每个文件前30行内都有 sys.path.insert 或类似路径设置"""
    # audio_toolkit.py 是工具脚本而非独立GUI窗口，不列入
    gui_files = [
        "gui/main_window.py",
        "domains/stock/stock_gui.py",
        "domains/fund/fund_gui.py",
        "domains/creator/creator_gui.py",
        "jinshuiyao/football_gui.py",
        "knowledge/mirofish_gui.py",
    ]
    ok_count = 0
    fail_list = []
    for rel in gui_files:
        fp = os.path.join(PROJECT_DIR, rel)
        if not os.path.isfile(fp):
            fail_list.append(f"{rel} (文件不存在)")
            continue
        with open(fp, "r", encoding="utf-8") as f:
            head = "".join(f.readlines()[:30])
        if "sys.path" in head and ("insert" in head or "append" in head):
            ok_count += 1
        else:
            fail_list.append(rel)
    passed = len(fail_list) == 0
    detail = f"{ok_count}/{len(gui_files)} 文件都有路径设置"
    if fail_list:
        detail += f" | 缺失: {', '.join(fail_list)}"
    check("GUI sys.path", passed, detail)
    return passed


# =====================================================================
# 检查项2: 注册表完整性
# =====================================================================
def check_registry():
    """确认 domains/__init__.py 注册了所有子系统"""
    init_path = os.path.join(PROJECT_DIR, "domains", "__init__.py")
    with open(init_path, "r", encoding="utf-8") as f:
        content = f.read()
    expected = ["lottery", "football", "stock", "music", "fund", "creator"]
    missing = []
    for name in expected:
        if f'register("{name}"' not in content:
            missing.append(name)
    passed = len(missing) == 0
    detail = f"{len(expected)-len(missing)}/{len(expected)} 个子系统已注册"
    if missing:
        detail += f" | 缺失: {', '.join(missing)}"
    check("注册表", passed, detail)
    return passed


# =====================================================================
# 检查项3: __init__.py 导出检查
# =====================================================================
def check_init_exports():
    """确认每个 domains/ 子目录的 __init__.py 都导出了 Domain 类"""
    subdirs = ["lottery", "football", "stock", "music", "fund", "creator"]
    ok_count = 0
    fail_list = []
    for sub in subdirs:
        init_path = os.path.join(PROJECT_DIR, "domains", sub, "__init__.py")
        if not os.path.isfile(init_path):
            fail_list.append(f"domains/{sub}/__init__.py (不存在)")
            continue
        with open(init_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 查找 Domain 类导出，如 LotteryDomain, StockDomain 等
        if "Domain" in content:
            ok_count += 1
        else:
            fail_list.append(f"domains/{sub}/__init__.py")
    passed = len(fail_list) == 0
    detail = f"{ok_count}/{len(subdirs)} 正确"
    if fail_list:
        detail += f" | 缺失: {', '.join(fail_list)}"
    check("__init__.py导出", passed, detail)
    return passed


# =====================================================================
# 检查项4: 启动脚本编码检查
# =====================================================================
def _read_bat(fp):
    """读取 bat 文件，兼容 UTF-8 和 GBK 编码"""
    for enc in ("utf-8", "gbk", "gb2312"):
        try:
            with open(fp, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(fp, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def check_bat_encoding():
    """确认所有 .bat 文件声明了 UTF-8 编码 (chcp 65001)"""
    bat_files = [
        "run.bat",
        "启动导航.bat",
        "jinshuiyao-guide/launcher.bat",
        "jinshuiyao-guide/protocol_handler.bat",
    ]
    ok_count = 0
    fail_list = []
    for rel in bat_files:
        fp = os.path.join(PROJECT_DIR, rel)
        if not os.path.isfile(fp):
            fail_list.append(f"{rel} (不存在)")
            continue
        content = _read_bat(fp)
        if "65001" in content or "utf-8" in content.lower():
            ok_count += 1
        else:
            fail_list.append(rel)
    passed = len(fail_list) == 0
    detail = f"{ok_count}/{len(bat_files)} 文件有编码声明"
    if fail_list:
        detail += f" | 缺失: {', '.join(fail_list)}"
    check("启动脚本编码", passed, detail)
    return passed


# =====================================================================
# 检查项5: Python路径统一性
# =====================================================================
def check_python_path():
    """确认所有启动文件指向同一Python（D:\\python38）"""
    bat_files = ["run.bat", "启动导航.bat", "jinshuiyao-guide/launcher.bat"]
    expected = r"D:\python38"
    ok_count = 0
    fail_list = []
    for rel in bat_files:
        fp = os.path.join(PROJECT_DIR, rel)
        if not os.path.isfile(fp):
            continue
        content = _read_bat(fp)
        if expected in content:
            ok_count += 1
        else:
            fail_list.append(rel)
    passed = len(fail_list) == 0
    detail = f"{ok_count}/{len(bat_files)} 指向 {expected}"
    if fail_list:
        detail += f" | 异常: {', '.join(fail_list)}"
    check("Python路径统一性", passed, detail)
    return passed


# =====================================================================
# 检查项6: 入口文件直接运行检查
# =====================================================================
def check_main_guard():
    """确认每个 GUI 文件可以直接 python xxx.py 运行（有 __name__ == '__main__'）"""
    gui_files = [
        "gui/main_window.py",
        "domains/stock/stock_gui.py",
        "domains/fund/fund_gui.py",
        "domains/creator/creator_gui.py",
        "jinshuiyao/football_gui.py",
        "knowledge/mirofish_gui.py",
    ]
    ok_count = 0
    fail_list = []
    for rel in gui_files:
        fp = os.path.join(PROJECT_DIR, rel)
        if not os.path.isfile(fp):
            fail_list.append(f"{rel} (不存在)")
            continue
        with open(fp, "r", encoding="utf-8") as f:
            content = f.read()
        if "__name__" in content and "__main__" in content:
            ok_count += 1
        else:
            fail_list.append(rel)
    passed = len(fail_list) == 0
    detail = f"{ok_count}/{len(gui_files)} 有主入口保护"
    if fail_list:
        detail += f" | 缺失: {', '.join(fail_list)}"
    check("入口文件直接运行", passed, detail)
    return passed


# =====================================================================
# 检查项7: domain.py vs gui.py 分离检查
# =====================================================================
def check_html_buttons():
    """确认 control-center.html 的按钮指向的是 GUI 文件而非 domain.py"""
    html_path = os.path.join(PROJECT_DIR, "jinshuiyao-guide", "control-center.html")
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    # 查找所有 openSubsystem 和 window.open 中指向 domain.py 的情况
    bad = []
    for m in re.finditer(r"openSubsystem\(['\"]([^'\"]+)['\"]", content):
        path = m.group(1)
        if "domain.py" in path:
            bad.append(f"openSubsystem('{path}')")
    for m in re.finditer(r"window\.open\(['\"]/open\?file=([^'\"&]+)", content):
        path = m.group(1)
        if "domain.py" in path:
            bad.append(f"window.open('{path}')")
    passed = len(bad) == 0
    detail = "无按钮指向 domain.py" if passed else f"发现 {len(bad)} 处指向 domain.py"
    if bad:
        detail += f": {', '.join(bad[:3])}"
    check("control-center.html", passed, detail)
    return passed


# =====================================================================
# 检查项8: 依赖完整性
# =====================================================================
def check_dependencies():
    """检查 tkinter, akshare, matplotlib 等关键依赖
    优先使用系统Python(D:\\python38)检查，因为TRAE的Python是精简版"""
    deps = ["tkinter", "akshare", "matplotlib", "pandas", "numpy"]
    ok_count = 0
    fail_list = []
    # 优先用系统Python检查
    system_py = r"D:\python38\python.exe"
    use_subprocess = os.path.isfile(system_py)
    for mod in deps:
        found = False
        if use_subprocess:
            try:
                subprocess.run(
                    [system_py, "-c", f"import {mod}"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                found = True
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
        else:
            try:
                __import__(mod)
                found = True
            except ImportError:
                pass
        if found:
            ok_count += 1
        else:
            fail_list.append(mod)
    passed = len(fail_list) == 0
    detail = f"{ok_count}/{len(deps)} 可用"
    if fail_list:
        detail += f" | 缺失: {', '.join(fail_list)}"
    check("依赖完整性", passed, detail)
    return passed


# =====================================================================
# 检查项9: server 包完整性检查
# =====================================================================
def check_guide_server_pythonpath():
    """确认 server/ 包存在且可导入"""
    fp = os.path.join(PROJECT_DIR, "server", "__init__.py")
    passed = os.path.isfile(fp)
    detail = "server/__init__.py 存在" if passed else "server/__init__.py 不存在"
    check("server 包完整性", passed, detail)
    return passed


# =====================================================================
# 主流程
# =====================================================================
def main():
    print("=" * 40)
    print("  金水谣引擎 - 前置检查清单")
    print("=" * 40)

    checks = [
        check_gui_syspath,
        check_registry,
        check_init_exports,
        check_bat_encoding,
        check_python_path,
        check_main_guard,
        check_html_buttons,
        check_dependencies,
        check_guide_server_pythonpath,
    ]

    for fn in checks:
        try:
            fn()
        except Exception as e:
            check(fn.__name__, False, f"检查异常: {e}")

    passed_count = sum(1 for _, p, _ in results if p)
    total_count = len(results)
    fail_count = total_count - passed_count

    print("-" * 40)
    if fail_count == 0:
        print(f"总结: {passed_count}/{total_count} 全部通过")
        print("可以安全提交修改！")
        sys.exit(0)
    else:
        print(f"总结: {passed_count}/{total_count} 通过, {fail_count} 失败")
        print("请修复失败项后再提交修改！")
        sys.exit(1)


if __name__ == "__main__":
    main()
