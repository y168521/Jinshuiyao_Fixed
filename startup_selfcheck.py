# -*- coding: utf-8 -*-
"""
金水谣启动自检模块（被 server 的 /api/selfcheck 调用）。
检查各核心模块能否正常加载、关键启动脚本与同步台账是否存在，
返回 {all_passed, summary, departments}，供网页「一键功能自检」展示。

设计：纯标准库，不依赖任何第三方包；任何单项失败都不影响其它项检查。
"""
import os
import sys
import importlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# 终端编码自适应：GBK 环境降级为纯文本符号，UTF-8 正常显示 Emoji
# ---------------------------------------------------------------------------
def _safe_icon(emoji: str, fallback: str) -> str:
    """根据 stdout 编码选择 Emoji 或纯文本替代符号"""
    enc = (getattr(sys.stdout, 'encoding', '') or '').lower()
    if 'utf' in enc:
        return emoji
    return fallback

_ICON_OK   = lambda: _safe_icon("✅", "[OK]")
_ICON_WARN = lambda: _safe_icon("⚠️", "[!!]")
_ICON_ERR  = lambda: _safe_icon("❌", "[XX]")
_ICON_INFO = lambda: _safe_icon("ℹ️", "[--]")


def _check_import(name, path=None):
    saved = list(sys.path)
    try:
        if path and path not in sys.path:
            sys.path.insert(0, path)
        importlib.import_module(name)
        return True, "可正常加载"
    except Exception as e:
        return False, f"加载失败: {e}"
    finally:
        sys.path[:] = saved


def run_startup_check_safe():
    deps = {}

    # 1) 核心功能模块
    checks = [
        ("视频提取", "video_extractor", os.path.join(BASE_DIR, "core")),
        ("内容提炼", "content_refiner", os.path.join(BASE_DIR, "core")),
        ("知识库归档", "archive_knowledge",
         os.path.join(BASE_DIR, "knowledge", "用户知识库")),
        ("知识库体检", "lint_knowledge",
         os.path.join(BASE_DIR, "knowledge", "用户知识库")),
        ("跨设备同步", "device_sync", os.path.join(BASE_DIR, "sync")),
        ("任务智能路由", "jinshuiyao_router", BASE_DIR),
        ("AI服务", "ai_service", os.path.join(BASE_DIR, "core")),
    ]
    for label, mod, p in checks:
        ok, note = _check_import(mod, p)
        deps[label] = {"passed": ok, "note": note}

    # 2) 启动脚本是否齐全（模型根目录入口 或 Jinshuiyao_Fixed/launch.bat 任一存在即可启动）
    root_entry = os.path.join(os.path.dirname(BASE_DIR), "启动金水谣助手.bat")
    internal = os.path.join(BASE_DIR, "launch.bat")
    launcher_ok = os.path.isfile(root_entry) or os.path.isfile(internal)
    deps["启动脚本"] = {"passed": launcher_ok,
                      "note": "入口齐全（根目录启动器 / launch.bat）" if launcher_ok
                      else "缺失（无法启动网页版）"}
    py_launcher = os.path.join(BASE_DIR, "launch_jinshuiyao.py")
    deps["Python启动器"] = {"passed": os.path.isfile(py_launcher),
                          "note": "存在" if os.path.isfile(py_launcher) else "缺失"}

    # 3) 同步台账（跨设备看板数据）
    sf = os.path.join(BASE_DIR, "sync", "sync_state.json")
    ok = os.path.isfile(sf)
    deps["跨设备同步台账"] = {"passed": ok,
                             "note": "存在" if ok else "缺失（看板无数据）"}

    # 4) 知识库目录
    kb = os.path.join(BASE_DIR, "knowledge", "用户知识库")
    ok = os.path.isdir(kb)
    deps["知识库目录"] = {"passed": ok, "note": "存在" if ok else "缺失"}

    # 5) Python 版本检测
    py_ver = sys.version_info
    py_ok = py_ver >= (3, 8)
    deps["Python版本"] = {
        "passed": py_ok,
        "note": f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"
                + ("（推荐 3.14+）" if py_ver >= (3, 14) else
                   "（兼容，推荐升级至 3.14）" if py_ver >= (3, 8) else
                   "（版本过低）")
    }

    # 6) 核心依赖完整性
    _CORE_DEPS = ["requests", "numpy", "pandas", "cryptography", "bs4", "lxml"]
    missing = []
    for dep in _CORE_DEPS:
        try:
            importlib.import_module(dep)
        except ImportError:
            missing.append(dep)
    dep_ok = len(missing) == 0
    deps["核心依赖"] = {
        "passed": dep_ok,
        "note": "全部就绪（%d 项）" % len(_CORE_DEPS) if dep_ok
                else "缺失: " + ", ".join(missing) + "（pip install -r requirements.txt）"
    }

    # 6.5) 备份目录隔离（防乱守卫）：备份必须独立于坚果云同步盘/项目目录
    try:
        saved = list(sys.path)
        tools_dir = os.path.join(BASE_DIR, "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import auto_backup as _ab
        safe = _ab.is_safe_backup_location()
        backup_loc = _ab.BACKUP_ROOT
        sys.path[:] = saved
        deps["备份目录隔离"] = {
            "passed": safe,
            "note": ("安全（%s，独立于同步盘）" % backup_loc) if safe
                    else "危险：备份目录落在同步盘/项目内，每次启动会污染同步树！"
        }
    except Exception as e:
        deps["备份目录隔离"] = {"passed": False, "note": "自检失败: %s" % e}

    all_ok = all(v.get("passed", False) for v in deps.values())
    bad = sum(1 for v in deps.values() if not v.get("passed", False))
    summary = (f"{_ICON_OK()} 全部功能模块正常，可以放心使用。" if all_ok
               else f"{_ICON_WARN()} 检测到 {bad} 项异常，请在下方逐项查看并联系助手处理。")

    return {"all_passed": all_ok, "summary": summary, "departments": deps}
