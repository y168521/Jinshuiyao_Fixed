# -*- coding: utf-8 -*-
"""看门狗计划任务安装器（install_watchdog.py）

把 service-watchdog 自动化平移为 Windows 计划任务（进程外、0 成本、不烧 WorkBuddy 积分）。
必须用管理员身份运行（schtasks 需提权）。

路径全部用 __file__ 推导（不写死中文路径，规避编码问题）。
"""
import os
import subprocess
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_BASE)
_ROOT = os.path.dirname(_PROJ)                       # 模型/
CANDIDATES = [
    r"D:\Project_Env\jinshuiyao_env\Scripts\python.exe",          # 项目 venv（当前在用）
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Jinshuiyao", "venv", "Scripts", "python.exe"),  # AGENTS.md 约定的自动 venv
    os.path.join(_ROOT, "venv_314", "Scripts", "python.exe"),     # 旧版自动化 venv（迁移期兼容）
]
PY = next((p for p in CANDIDATES if os.path.isfile(p)), "")
SCRIPT = os.path.join(_PROJ, "scripts", "watchdog_service.py")


def main():
    if not os.path.isfile(PY):
        print("[install] 找不到 python: %s" % PY)
        return 2
    if not os.path.isfile(SCRIPT):
        print("[install] 找不到脚本: %s" % SCRIPT)
        return 2
    tr = '"%s" "%s"' % (PY, SCRIPT)                  # 含空格路径需引号
    cmd = ["schtasks", "/Create", "/TN", "JinshuiyaoWatchdog",
           "/SC", "HOURLY", "/F", "/TR", tr]
    print("[install] 执行: %s" % " ".join(cmd))
    rc = subprocess.run(cmd).returncode
    if rc == 0:
        print("[install] 成功：已创建每小时计划任务 JinshuiyaoWatchdog（进程外看门狗）。")
    else:
        print("[install] 失败(rc=%d)：请确认以管理员身份运行。" % rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
