# -*- coding: utf-8 -*-
"""精确复刻 chainmap.py 的 subprocess 调用，定位为何探路器未产出结果"""
import subprocess, sys, os

REPO = r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed"
ROOT = r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型"
PY = r"E:\Project_Env\jinshuiyao_env\Scripts\python.exe"

script = os.path.join(REPO, "tools", "route_probe.py")
out = os.path.join(ROOT, "金水谣数据", ".tmp_chain_map.json")

if os.path.isfile(out):
    os.remove(out)
print("PRE_EXISTS=", os.path.isfile(out), flush=True)
print("OUT_PATH=", out, flush=True)
print("CWD=", REPO, flush=True)

try:
    r = subprocess.run(
        [PY, script, "--json", out],
        capture_output=True, text=True, encoding="utf-8",
        timeout=180, cwd=REPO,
    )
    print("RC=", r.returncode, flush=True)
    print("STDOUT_TAIL=", (r.stdout or "")[-400:], flush=True)
    print("STDERR_TAIL=", (r.stderr or "")[-800:], flush=True)
    print("FILE_EXISTS_AFTER=", os.path.isfile(out), flush=True)
    if os.path.isfile(out):
        print("FILE_SIZE=", os.path.getsize(out), flush=True)
except Exception as e:
    import traceback
    print("EXC=", e, flush=True)
    traceback.print_exc()
