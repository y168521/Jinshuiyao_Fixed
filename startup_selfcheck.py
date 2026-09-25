# -*- coding: utf-8 -*-
"""
金水谣启动自检模块（被 server 的 /api/selfcheck 调用）。
检查各核心模块能否正常加载、关键启动脚本与同步台账是否存在，
返回 {all_passed, summary, departments}，供网页「一键功能自检」展示。

设计：纯标准库，不依赖任何第三方包；任何单项失败都不影响其它项检查。
"""
import os
import sys
import time
import logging
import importlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger("jinshuiyao.startup_selfcheck")

# JS-20260925-08：自检结果必须落盘。
# 此前 server/__init__.py 提示「详见 金水谣数据/log/selfcheck.log」，
# 但全仓“只读不写”（health.py 也读它）
# → 用户被告知去看一个不存在的文件，异常内容永远看不到。
# 这是「告警指向空气」的又一例。
SELFCHECK_LOG = os.path.join(BASE_DIR, "金水谣数据", "log", "selfcheck.log")
SELFCHECK_LOG_MAX_BYTES = 512 * 1024  # 超过则保留后半段，防日志无限膨胀

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
    """导入检查。name 支持点分包路径（如 core.ai.ai_service）。
    
    JS-20260925-08：原先传的是「目录」+「裸模块名」，
    模块迁到子包后路径没跟着改 → 功能明明可用却报 3 项异常。
    **假警会淹没真问题**，比没有告警更糟。
    """
    saved = list(sys.path)
    try:
        if path and path not in sys.path:
            sys.path.insert(0, path)
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)
        importlib.import_module(name)
        return True, "可正常加载"
    except Exception as e:
        return False, f"加载失败: {e}"
    finally:
        sys.path[:] = saved


def _render_report_text(report):
    """把自检结果渲染成纯文本（供 /api/selfcheck/history 直读）。"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    head = "启动自检: " + (
        "全部通过" if report.get("all_passed")
        else "存在异常（见下方 NG 项）")
    lines = ["[%s] %s" % (ts, head)]
    for k, v in (report.get("departments") or {}).items():
        flag = "OK " if v.get("passed") else "NG "
        lines.append("  %s %s: %s" % (flag, k, v.get("note", "")))
    lines.append("")
    return "\n".join(lines)


def _append_selfcheck_log(report):
    """把自检结果追加到 selfcheck.log。
    
    落盘失败不能让自检本身崩掉（自检是启动链路上的一环），
    但也绝不能静默吞掉——写 warning。
    """
    try:
        os.makedirs(os.path.dirname(SELFCHECK_LOG), exist_ok=True)
        keep = None
        if os.path.isfile(SELFCHECK_LOG) and \
                os.path.getsize(SELFCHECK_LOG) > SELFCHECK_LOG_MAX_BYTES:
            with open(SELFCHECK_LOG, "r", encoding="utf-8", errors="replace") as f:
                keep = f.read()[-SELFCHECK_LOG_MAX_BYTES // 2:]
        mode = "w" if keep else "a"
        with open(SELFCHECK_LOG, mode, encoding="utf-8") as f:
            if keep:
                f.write("...(较早内容已截断)...\n")
                f.write(keep)
            f.write(_render_report_text(report))
    except Exception as e:
        logger.warning("[启动自检] 结果落盘失败（异常内容将无法追溯）: %s", e)


def run_startup_check_safe():

    deps = {}

    # 1) 核心功能模块
    checks = [
        # JS-20260925-08：用点分包路径，不再用「目录+裸模块名」
        ("视频提取", "core.infra.video_extractor", None),
        ("内容提炼", "core.ai.content_refiner", None),
        ("知识库归档", "archive_knowledge",
         os.path.join(BASE_DIR, "knowledge", "用户知识库")),
        ("知识库体检", "lint_knowledge",
         os.path.join(BASE_DIR, "knowledge", "用户知识库")),
        ("任务智能路由", "jinshuiyao_router", BASE_DIR),
        ("AI服务", "core.ai.ai_service", None),
    ]
    for label, mod, p in checks:
        ok, note = _check_import(mod, p)
        deps[label] = {"passed": ok, "note": note}

    # 1.5) 可选功能（未实现不算异常，仅展示状态）
    try:
        ok, note = _check_import("device_sync", os.path.join(BASE_DIR, "sync"))
        deps["跨设备同步"] = {
            "passed": True,
            "note": ("可正常加载" if ok else "未启用（本机无 sync/device_sync.py，属可选功能）"),
        }
    except Exception as e:
        deps["跨设备同步"] = {"passed": True, "note": f"未启用（{e}）"}

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

    # 3) 同步台账（跨设备看板数据，可选功能）
    sf = os.path.join(BASE_DIR, "sync", "sync_state.json")
    ok = os.path.isfile(sf)
    deps["跨设备同步台账"] = {"passed": True,
                             "note": ("存在" if ok else "未启用（本机无同步台账，属可选功能）")}

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

    report = {"all_passed": all_ok, "summary": summary, "departments": deps}
    _append_selfcheck_log(report)
    return report
