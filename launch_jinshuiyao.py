# -*- coding: utf-8 -*-
"""
金水谣助手启动器（由 .bat 调用）。
职责：打印中文启动提示、自动打开浏览器、启动网页服务器。
纯中文由 Python 处理，不受 Windows 批处理编码影响。
"""
import os
import sys
import time
import webbrowser
import threading
import shutil
import stat

# ── pyc 缓存策略（2026-08-04 优化：秒开） ──
# 之前双保险是"禁止生成 pyc + 每次启动清空 __pycache__"，代价是 410+ 个 .py
# 每次全量重编译，启动明显变慢（坚果云同步 + 后台审查Pipeline 双重拖累）。
# 现在改为：允许写字节码缓存 + 仅当源码最新 mtime 与标记不一致时才清空重编译。
# Python 自身有 pyc 失效机制（源码 mtime/size 变化自动重编译），"源码即真理"仍成立。
# sys.dont_write_bytecode 不再启用，缓存保留 → 启动秒开。

BASE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# 启动日志双写：任何崩溃/异常都落盘到 %LOCALAPPDATA%\Jinshuiyao\launch.log
# 双击 bat 无可见控制台时也能事后查错，绝不静默消失。
# ---------------------------------------------------------------------------
class _Tee:
    def __init__(self, stream, logf):
        self.stream = stream
        self.logf = logf

    def write(self, data):
        try:
            self.stream.write(data)
        except Exception:
            pass
        try:
            self.logf.write(data)
            self.logf.flush()
        except Exception:
            pass

    def flush(self):
        try:
            self.stream.flush()
        except Exception:
            pass
        try:
            self.logf.flush()
        except Exception:
            pass

    @property
    def encoding(self):
        return getattr(self.stream, 'encoding', 'utf-8')

    def isatty(self):
        return getattr(self.stream, 'isatty', lambda: False)()

    def fileno(self):
        return self.stream.fileno()


def _install_log_tee():
    try:
        localapp = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        log_dir = os.path.join(localapp, 'Jinshuiyao')
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, 'launch.log')
        # 日志轮转：超过5MB截断保留后半
        if os.path.isfile(log_path) and os.path.getsize(log_path) > 5 * 1024 * 1024:
            try:
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                with open(log_path, 'w', encoding='utf-8') as f:
                    f.write(content[len(content)//2:])
            except Exception:
                pass
        lf = open(log_path, 'a', encoding='utf-8')
        sys.stdout = _Tee(sys.stdout, lf)
        sys.stderr = _Tee(sys.stderr, lf)
        return log_path
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 运行时自举：换电脑免改 —— 自动建立本机 venv 并安装依赖
# ---------------------------------------------------------------------------
def ensure_runtime():
    """换电脑自愈：确保运行环境可用，无需手动修改任何路径。

    哨兵 requests：能导入即依赖齐全，直接用当前解释器起服务（门户已验证无需
    第三方库即可开，仅 AI/数据类高级功能受限）。
    若缺失：在本机 %LOCALAPPDATA%\\Jinshuiyao\\venv 建 venv 并 pip install（首次需联网）。
      - 安装成功 -> 用 venv python 重启本脚本（os.execv，同一窗口内完成）。
      - 安装失败/超时 -> 不阻塞！直接用当前解释器起基础门户（功能受限，可后续
        双击「安装依赖.bat」补全）。绝不再因依赖问题导致“窗口卡死/打不开”。
    """
    try:
        import requests  # 哨兵：能导入即依赖齐全
        return
    except ImportError:
        pass

    import subprocess

    localapp = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    venv_dir = os.path.join(localapp, 'Jinshuiyao', 'venv')
    venv_py = os.path.join(venv_dir, 'Scripts', 'python.exe') if os.name == 'nt' \
        else os.path.join(venv_dir, 'bin', 'python')

    # 已在 canonical venv 中但依赖仍缺失（多半离线）→ 直接起基础门户，不再重建
    if sys.prefix == venv_dir:
        print("[运行时] 依赖未完全安装，将以基础模式启动门户；")
        print("        联网后双击「安装依赖.bat」补全依赖即可启用全部功能。")
        return

    print("[运行时] 首次在本机启动，正在准备独立运行环境（仅需一次）……")
    try:
        if not os.path.isfile(venv_py):
            subprocess.run([sys.executable, '-m', 'venv', venv_dir], check=True)
        req = os.path.join(BASE, 'requirements.txt')
        if os.path.isfile(req):
            print("[运行时] 正在安装依赖（首次需联网，请稍候，最多约 15 分钟）……")
            subprocess.run([venv_py, '-m', 'pip', 'install', '-r', req],
                           check=True, timeout=900,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[运行时] 依赖安装完成，切换至独立环境重启……")
            os.execv(venv_py, [venv_py, os.path.abspath(__file__)])
        else:
            print("[运行时] 未找到 requirements.txt，直接以基础模式启动。")
    except subprocess.TimeoutExpired:
        print("[运行时] 依赖安装超时（网络较慢）。先以基础模式启动门户；")
        print("        联网后双击「安装依赖.bat」补全依赖即可启用全部功能。")
    except Exception as e:
        print(f"[运行时] 自动准备环境失败（{e}）。先以基础模式启动门户；")
        print("        如需全部功能，请双击「安装依赖.bat」或运行 pip install -r requirements.txt")
    # 失败/超时分支：不重启，直接返回，由 main 用当前解释器起服务（门户必开）


# ---------------------------------------------------------------------------
# 第一层防护：启动前哨（快速预检，3秒内完成）
# ---------------------------------------------------------------------------
def preflight_check():
    """
    启动前快速检查，发现致命问题则阻止启动并给出中文提示。
    返回 True 表示可以继续启动，False 表示有致命问题。
    """
    import py_compile
    import socket

    print("\n[启动前哨] 正在快速体检……")
    issues = []

    # 1) 关键文件语法快检（只查最核心的几个）
    critical = ["main.py", "config.py", os.path.join("server", "__init__.py"),
                os.path.join("server", "router.py")]
    for rel in critical:
        fp = os.path.join(BASE, rel)
        if os.path.isfile(fp):
            try:
                py_compile.compile(fp, doraise=True)
            except py_compile.PyCompileError as e:
                issues.append(f"  语法错误: {rel}（{e}）")

    # 2) 端口是否被占
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    port_busy = sock.connect_ex(("127.0.0.1", 18888)) == 0
    sock.close()
    if port_busy:
        # 尝试自动清理（与launch.bat相同的逻辑）
        try:
            import subprocess
            out = subprocess.check_output(
                ["netstat", "-ano"], stderr=subprocess.DEVNULL).decode("utf-8", "ignore")
            for line in out.splitlines():
                if ":18888" in line and "LISTENING" in line:
                    pid = line.split()[-1]
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print("[启动前哨] 已自动清理占用端口的旧进程。")
                    port_busy = False
                    break
        except Exception:
            pass
        if port_busy:
            issues.append("  端口18888被占用且无法自动清理，请关闭旧的金水谣窗口后重试。")

    # 3) server包能否找到
    server_init = os.path.join(BASE, "server", "__init__.py")
    if not os.path.isfile(server_init):
        issues.append("  server/__init__.py 不存在，服务器模块缺失。")

    # 4) 自动备份（静默，不阻塞）
    try:
        sys.path.insert(0, os.path.join(BASE, "tools"))
        from auto_backup import create_snapshot
        snap_dir, count = create_snapshot("启动")
        if snap_dir:
            print(f"[启动前哨] 已自动备份 {count} 个关键文件。")
    except Exception:
        pass

    if issues:
        print("\n" + "!" * 44)
        print("  启动前哨发现以下问题，暂时无法启动：")
        print()
        for iss in issues:
            print(iss)
        print()
        print("  建议：双击「体检修复.bat」做全面检查，")
        print("  或把上面的错误信息发给AI助手处理。")
        print("!" * 44)
        input("\n按回车键退出…")
        return False

    print("[启动前哨] 全部通过，正在启动……\n")
    return True


def _on_rm_error(func, path, exc_info):
    """rmtree 的 onerror 回调：碰到只读/占用文件时去掉只读位重试，仍失败则忽略。"""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def _purge_pycache(root):
    """清空项目下所有 __pycache__（仅在源码有改动时调用一次）。"""
    removed = 0
    for dirpath, dirnames, _ in os.walk(root):
        # 不进入第三方虚拟环境目录，避免误删其缓存导致全部重编译/变慢
        dirnames[:] = [d for d in dirnames if d not in ("venv", ".venv", "node_modules")]
        for d in list(dirnames):
            if d == "__pycache__":
                cache_dir = os.path.join(dirpath, d)
                try:
                    shutil.rmtree(cache_dir, onerror=_on_rm_error)
                    removed += 1
                except Exception:
                    pass
    if removed:
        print(f"[启动前哨] 已清理 {removed} 个 __pycache__ 缓存目录，将从源码重新编译。")


_PYCACHE_MARK = ".pyc_mark"


def _latest_py_mtime(root):
    """项目下所有 .py 源码的最新 mtime（排除虚拟环境/缓存目录）。"""
    latest = 0.0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("venv", ".venv", "node_modules", "__pycache__")]
        for fn in filenames:
            if fn.endswith(".py"):
                try:
                    latest = max(latest, os.path.getmtime(os.path.join(dirpath, fn)))
                except Exception:
                    pass
    return latest


def _purge_pycache_if_stale(root):
    """源码有改动 → 清一次 __pycache__ 并刷新标记；无改动 → 保留缓存（秒开）。

    跨设备同步：坚果云同步会更新 .py 的 mtime，比对标记发现变化即清一次重编译，
    杜绝"脏 pyc 跑旧代码"；日常无改动时缓存保留，不再每次全量重编译。
    """
    mark_path = os.path.join(root, _PYCACHE_MARK)
    try:
        last_mark = ""
        if os.path.isfile(mark_path):
            with open(mark_path, "r", encoding="utf-8") as f:
                last_mark = f.read().strip()
        cur = "%.3f" % _latest_py_mtime(root)
        if last_mark and last_mark == cur and os.path.isfile(mark_path):
            return 0
        removed = _purge_pycache(root)
        try:
            with open(mark_path, "w", encoding="utf-8") as f:
                f.write(cur)
        except Exception:
            pass
        return removed
    except Exception:
        try:
            return _purge_pycache(root)
        except Exception:
            return 0


def main():
    log_path = _install_log_tee()
    try:
        ensure_runtime()  # 换电脑自愈：确保 venv/依赖就绪（必要时会重启本脚本）
        os.chdir(BASE)
        if BASE not in sys.path:
            sys.path.insert(0, BASE)

        # 第一层防护：启动前哨
        if not preflight_check():
            return

        # 统一日志配置（与 main.py / 导航服务器共用 config/logging_config.py）
        try:
            from config.logging_config import setup_logging
            setup_logging()
        except Exception:
            pass  # 配置加载失败不阻塞启动

        print("=" * 44)
        print("金水谣助手 - 正在启动网页版……")
        print(f"已找到运行环境：{sys.executable}")
        if log_path:
            print(f"启动日志已记录到：{log_path}")
        print("浏览器将自动打开；用完关闭本窗口即可停止。")
        print("若浏览器未自动弹出，请手动打开：http://localhost:18888/")
        print("=" * 44)

        # 启动前按需清理 __pycache__：源码有改动才清一次（否则保留字节码缓存秒开）
        try:
            _purge_pycache_if_stale(BASE)
        except Exception:
            pass

        from server import main as server_main

        # 自动记录：每天首次启动时记一条"助手已就绪"任务（无需手动，自动同步到另一台设备）
        try:
            sys.path.insert(0, os.path.join(BASE, "sync"))
            import device_sync
            today = time.strftime("%Y%m%d")
            did = "TS-DAILY-" + today
            st = device_sync.get_state()
            if did not in st.get("tasks", {}):
                device_sync.record_task(
                    did, f"金水谣助手已启动并就绪（{today}）",
                    "done", "每日首次启动自动记录，表示本机助手可用", device_sync.identify_device())
        except Exception:
            pass

        # 直接在主线程启动服务器（server.main 内部会按实际端口自动打开浏览器、并持续服务）
        # 主线程阻塞于此；关闭本窗口即停止服务。若启动失败会打印明确错误而非静默退出。
        server_main()
    except Exception as e:
        print("\n[致命错误] 服务器未能启动：", e)
        import traceback
        traceback.print_exc()
        input("\n按回车键退出…")


if __name__ == "__main__":
    main()
