# -*- coding: utf-8 -*-
"""
金水谣 · 服务存活看门狗 (watchdog_service.py)
====================================================

一句话：盯着 18888 端口的网页服务，挂了/假死了就自动把它拉起来，让你睡安稳觉。

设计对齐项目铁律（见 .workbuddy/memory/MEMORY.md）：
  - 重启只用 `py -3.14`：托管 3.13.12 会让 ensure_runtime 误判首启→联网 pip 卡死+孤儿双进程。
  - 重启前先 taskkill 清 18888 旧进程。
  - 重启后必须验证 /health=200 且功能端点可达，才算成功。

探测策略（LLM Ops 看门狗原则：不能只看 /health，要探功能性端点+超时）：
  - 第一层 /health：超时/拒绝 = 进程已死 → 重启。
  - 第二层 /api/lottery/sources-health：/health 正常但此端点超时 = 假死(死锁) → 重启。
  - 任何返回 HTTP 状态码（含 5xx）都算“进程还活着”，不重启（5xx 是代码 bug，重启无用且会循环）。

安全闸：
  - COOLDOWN_SEC 冷却期（默认 600s）内不重复重启，避免抖动风暴。
  - 连续重启失败 MAX_CONSEC_FAIL（默认 3）次即熔断并写告警，退出码 2，等待人工介入。
  - 绝不删除任何文件、绝不改业务代码。

用法：
  python watchdog_service.py            # 常规巡检（必要时重启）
  python watchdog_service.py --check-only   # 只探测、绝不重启（用于测试/巡检）
  python watchdog_service.py --force-restart  # 无条件重启一次（紧急恢复用）
"""

import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error
import socket
import datetime

# ----------------------------------------------------------------------------
# 路径与常量
# ----------------------------------------------------------------------------
BASE = os.path.dirname(os.path.abspath(__file__))          # .../Jinshuiyao_Fixed/scripts
ROOT = os.path.dirname(BASE)                              # .../Jinshuiyao_Fixed
WORKSPACE = os.path.dirname(ROOT)                         # .../模型 (工作区根)
APP = os.path.join(ROOT, "launch_jinshuiyao.py")          # 启动入口
PORT = 18888
HEALTH_URL = f"http://127.0.0.1:{PORT}/health"
FUNC_URL = f"http://127.0.0.1:{PORT}/api/lottery/sources-health"

LOG_DIR = os.path.join(WORKSPACE, "金水谣数据", "log")
STATE_FILE = os.path.join(LOG_DIR, "watchdog_state.json")
WATCHDOG_LOG = os.path.join(LOG_DIR, "watchdog.log")

# 探活参数
HEALTH_TIMEOUT = 5        # /health 探测超时（秒）
FUNC_TIMEOUT = 8          # 功能端点探测超时（秒，更长避免误判正常慢响应）
PROBE_RETRY = 2           # 探测失败重试次数
PROBE_INTERVAL = 1        # 重试间隔（秒）

# 重启/熔断参数
TASKKILL_GRACE = 2         # kill 后等待端口释放（秒）
STARTUP_WAIT = 40          # 重启后等待服务绑定端口的最长总时间（秒）
STARTUP_POLL = 3           # 重启后探活轮询间隔（秒）
COOLDOWN_SEC = 600         # 重启冷却：10 分钟内不重复重启
MAX_CONSEC_FAIL = 3        # 连续重启失败上限 → 熔断告警
ALERT_RATELIMIT_SEC = 600  # F13 告警限流：同类告警 10 分钟内只报一次，避免半夜刷屏

def _resolve_python():
    """解析重启所用的 Python 解释器绝对路径。

    根因（2026-07-26 看门狗自动重启失败）：原先用 ["py","-3.14"] 作为 DETACHED
    无头子进程的启动命令，依赖 `py` 启动器在子进程 PATH 中可被找到；一旦不可见，
    子进程静默起不来、launch.log 为空、看门狗盲等 40s 后判失败。改为在启动时把
    `py -3.14` 解析成绝对路径缓存下来，彻底去除对 `py` 启动器的运行时依赖。
    解析失败则回退到看门狗自身解释器（自动化均用 venv_314/py-3.14 运行本脚本）。
    """
    try:
        import shutil
        py = shutil.which("py")
        if py:
            out = subprocess.run([py, "-3.14", "-c", "import sys; print(sys.executable)"],
                                 capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
    except Exception:
        pass
    return sys.executable

PY_LAUNCHER = _resolve_python()   # 绝对路径，避免 DETACHED 下找不到 `py` 启动器
PY_ARGS = []                      # 已是完整解释器，无需再传 -3.14


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------
def ts_now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg, level="INFO"):
    line = f"[{ts_now()}][{level}] {msg}"
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line)


def load_state():
    try:
        if os.path.isfile(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "last_restart_ts": 0,
        "consecutive_restarts": 0,
        "consecutive_failures": 0,
        "last_status": "unknown",
        "last_check_ts": 0,
    }


def save_state(state):
    """F12 原子写：先落 .tmp 再 os.replace，避免半写损坏导致误判幽灵重启。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        log(f"保存状态文件失败: {e}", "WARN")


def ratelimited_alert(key, msg, level="ALERT", state=None):
    """
    F13 告警限流：同类 key 在 ALERT_RATELIMIT_SEC 内只真正打印一次，
    避免服务长期异常时每小时重复刷屏。命中限流返回 False（仅更新时间戳）。
    """
    state = state if state is not None else load_state()
    now = int(time.time())
    rl = state.setdefault("alert_ratelimit", {})
    if key in rl and now - rl[key] < ALERT_RATELIMIT_SEC:
        return False
    rl[key] = now
    save_state(state)
    log(msg, level)
    return True


def get_18888_pid():
    """返回当前占用 18888 LISTENING 的 PID，无则 None。"""
    try:
        # 注意：netstat 在中文代码页下输出含非 UTF-8 字节，必须 errors="ignore"
        # 否则整段解码抛异常导致 PID 识别失败（本机实测 byte 0xbb）。
        out = subprocess.check_output(
            ["netstat", "-ano"], stderr=subprocess.DEVNULL
        ).decode("utf-8", "ignore")
        for line in out.splitlines():
            if ":18888" in line and "LISTENING" in line:
                parts = line.split()
                return int(parts[-1])
    except Exception as e:
        log(f"netstat 查询失败: {e}", "WARN")
    return None


def probe_url(url, timeout):
    """返回 ('OK', status) / ('TIMEOUT', None) / ('REFUSED', None) / ('ERROR', None)。"""
    for attempt in range(PROBE_RETRY):
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return ("OK", resp.status)
        except urllib.error.HTTPError as e:
            # 拿到状态码 = 进程活着（含 4xx/5xx），不算死
            return ("OK", e.code)
        except socket.timeout:
            if attempt < PROBE_RETRY - 1:
                time.sleep(PROBE_INTERVAL)
                continue
            return ("TIMEOUT", None)
        except (ConnectionRefusedError, urllib.error.URLError) as e:
            # 中文 Windows 下 URLError 文案为「积极拒绝」且不含英文 "refused"，
            # 故同时按 winerror=10061 / 错误码识别连接被拒，避免误判为 ERROR。
            reason = getattr(e, "reason", None)
            winerr = getattr(reason, "winerror", None)
            refused = (
                "refused" in str(e).lower()
                or "10061" in str(e)
                or winerr == 10061
            )
            if refused:
                return ("REFUSED", None)
            if attempt < PROBE_RETRY - 1:
                time.sleep(PROBE_INTERVAL)
                continue
            return ("ERROR", None)
    return ("ERROR", None)


def assess():
    """
    评估服务状态。
    返回 (need_restart: bool, reason: str, detail: dict)
    """
    h_kind, h_status = probe_url(HEALTH_URL, HEALTH_TIMEOUT)
    detail = {"health": f"{h_kind}:{h_status}"}

    if h_kind in ("TIMEOUT", "REFUSED", "ERROR"):
        return True, f"/health 无响应({h_kind})，进程可能已死", detail

    # /health 正常 → 再探功能端点，识别“假死”
    f_kind, f_status = probe_url(FUNC_URL, FUNC_TIMEOUT)
    detail["func"] = f"{f_kind}:{f_status}"
    if f_kind == "TIMEOUT":
        return True, f"/health 正常但功能端点超时({f_kind})，疑似死锁假死", detail

    return False, "服务存活（/health 与功能端点均响应）", detail


def restart_server(force=False):
    """安全重启：kill 旧进程 → 用 py -3.14 拉起。返回 (success: bool, msg: str)。"""
    old_pid = get_18888_pid()
    if old_pid and not force:
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(old_pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
            )
            log(f"已 taskkill 旧进程 PID={old_pid}")
        except Exception as e:
            log(f"taskkill PID={old_pid} 失败: {e}", "WARN")
        time.sleep(TASKKILL_GRACE)

    # 兜底：若仍占用，再清一次
    still = get_18888_pid()
    if still:
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(still)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
            )
            log(f"兜底 taskkill PID={still}")
        except Exception:
            pass
        time.sleep(TASKKILL_GRACE)

    # 用项目铁律指定的解释器拉起（DETACHED 无窗口，日志由 launch_jinshuiyao.py 自写 launch.log）
    try:
        log(f"正在用 {PY_LAUNCHER} {' '.join(PY_ARGS)} 拉起 {os.path.basename(APP)} ...")
        subprocess.Popen(
            [PY_LAUNCHER] + PY_ARGS + [APP],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except Exception as e:
        return False, f"拉起失败: {e}"

    # 等待服务绑定并探活
    waited = 0
    while waited < STARTUP_WAIT:
        time.sleep(STARTUP_POLL)
        waited += STARTUP_POLL
        kind, status = probe_url(HEALTH_URL, HEALTH_TIMEOUT)
        if kind == "OK":
            fk, fs = probe_url(FUNC_URL, FUNC_TIMEOUT)
            if fk == "OK":
                return True, f"重启成功，{waited}s 后服务恢复(health={status}, func={fs})"
            if fk == "TIMEOUT":
                # 起来但功能端点仍超时 → 仍算失败
                return False, f"重启后功能端点仍超时({waited}s)，疑似未真正恢复"
        # 否则继续等
    return False, f"重启后 {STARTUP_WAIT}s 内未探活成功"


def main():
    check_only = "--check-only" in sys.argv
    force_restart = "--force-restart" in sys.argv

    os.makedirs(LOG_DIR, exist_ok=True)
    state = load_state()
    state["last_check_ts"] = int(time.time())

    log(f"===== 看门狗巡检开始 (check_only={check_only}, force={force_restart}) =====")

    if force_restart:
        log("收到 --force-restart，无条件重启一次。")
        ok, msg = restart_server(force=True)
        state["last_restart_ts"] = int(time.time())
        if ok:
            state["consecutive_failures"] = 0
            state["consecutive_restarts"] = state.get("consecutive_restarts", 0) + 1
            state["last_status"] = "force-restart-ok"
        else:
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
            state["last_status"] = "force-restart-fail"
        log(msg, "OK" if ok else "ERROR")
        save_state(state)
        sys.exit(0 if ok else 2)

    need, reason, detail = assess()
    state["last_status"] = ("alive" if not need else "need-restart") + " | " + json.dumps(detail, ensure_ascii=False)

    if not need:
        log(f"服务正常：{reason}  {detail}")
        # 正常也重置连败计数（说明环境稳定）
        state["consecutive_failures"] = 0
        save_state(state)
        log("===== 巡检结束：无需操作 =====")
        sys.exit(0)

    log(f"检测到异常：{reason}  {detail}")
    if check_only:
        log("--check-only 模式：仅告警，不执行重启。", "WARN")
        save_state(state)
        sys.exit(1)

    # 冷却期判定
    now = time.time()
    if now - state.get("last_restart_ts", 0) < COOLDOWN_SEC:
        remain = int(COOLDOWN_SEC - (now - state.get("last_restart_ts", 0)))
        ratelimited_alert("cooldown", f"冷却期内（剩 {remain}s），跳过本次重启，避免抖动风暴。", "WARN", state)
        save_state(state)
        sys.exit(1)

    # 熔断判定
    if state.get("consecutive_failures", 0) >= MAX_CONSEC_FAIL:
        ratelimited_alert("circuit_breaker", f"⚠ 已连续 {MAX_CONSEC_FAIL} 次重启失败，触发熔断！停止自动重启，请人工排查。", "ALERT", state)
        save_state(state)
        sys.exit(2)

    # 执行重启
    ok, msg = restart_server(force=False)
    state["last_restart_ts"] = int(time.time())
    if ok:
        state["consecutive_failures"] = 0
        state["consecutive_restarts"] = state.get("consecutive_restarts", 0) + 1
        log(msg, "OK")
        save_state(state)
        log("===== 巡检结束：已自动恢复 =====")
        sys.exit(0)
    else:
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        ratelimited_alert("restart_fail", msg, "ERROR", state)
        save_state(state)
        log(f"===== 巡检结束：重启失败({state['consecutive_failures']}/{MAX_CONSEC_FAIL}) =====")
        sys.exit(2)


if __name__ == "__main__":
    main()
