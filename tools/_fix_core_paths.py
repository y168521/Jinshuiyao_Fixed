# -*- coding: utf-8 -*-
"""修正 core/ 子包中基于 __file__ 的项目根路径计算（深度 +1）。

将 os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
替换为 os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

仅处理 core/ 下的 .py 文件，且只替换恰好两层 dirname 的形式（不动已有的三层）。
"""
import os

CORE = r"c:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\core"
OLD = "os.path.dirname(os.path.dirname(os.path.abspath(__file__)))"
NEW = "os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))"

files = []
for r, d, fs in os.walk(CORE):
    d[:] = [x for x in d if x != "__pycache__"]
    for f in fs:
        if f.endswith(".py"):
            files.append(os.path.join(r, f))

cnt = 0
for fp in files:
    with open(fp, "r", encoding="utf-8") as f:
        c = f.read()
    if OLD in c:
        c = c.replace(OLD, NEW)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(c)
        n = c.count(NEW)
        cnt += 1
        print(f"  {os.path.relpath(fp, CORE)}")

print(f"\n已修正 {cnt} 个文件中的路径计算")
