# -*- coding: utf-8 -*-
"""仓库卫生门禁 · 备份类/临时类文件不得入仓（JS-20260921-03）。

背景（真实事故）：2026-09-21 提交时用 `git add -A` 把 3 个历史遗留的一次性迁移备份
（`金水谣数据/predictions.json.invest_bak`、`knowledge/mirofish_db.json.invest_bak`、
`金水谣数据/brain_state.json.invest_bak`，合计 1.66 MB）一并扫进仓库。
根因：`.gitignore` 只有 `*.bak` / `*.json.bak.*` / `*.bak_cost_fix`，**没有覆盖 `*_bak`**
（标签后置写法，如 `<file>.<tag>_bak`），而自动同步脚本每 30 分钟 `git add -A`，
一旦产生就会自动入仓。

对策（两道）：
  ① .gitignore 补齐 `*_bak` / `*.bak_*`（防新增）；
  ② 本门禁扫 `git ls-files`，发现已跟踪的备份类文件即 FAIL（防存量复活）。

设计要点：
  - 纯标准库 + `git ls-files`，不依赖 git 在 PATH（可用 --git-dir 探测），失败降级为 WARN。
  - 白名单：确需入库的历史备份放 `ALLOWLIST`（写相对路径），但**必须写明理由**。
  - 只读，不做任何删除；清理动作由人执行（`git rm --cached`）。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 备份 / 临时 / 冲突残留类文件名模式（小写比对）
BACKUP_PAT = (
    ".bak",        # *.bak / *.json.bak.0 / *.bak_cost_fix / *.bak.field_migrate
    "_bak",        # <file>.<tag>_bak  ← 本次事故形态，必须覆盖
    ".orig",       # 合并冲突原始副本
    ".rej",        # patch 拒绝片段
    ".BASE.",      # 冲突副本 xxx.BASE.123.py
    ".LOCAL.",
    ".REMOTE.",
)
TMP_PAT = (".tmp", ".temp", ".swp", ".swo")

# 确需入库的例外（相对路径，必须带理由注释）
ALLOWLIST: tuple = ()

_GIT_CANDS = (
    r"E:\下载\Git\bin\git.exe",
    r"C:\Program Files\Git\bin\git.exe",
    r"C:\Program Files\Git\cmd\git.exe",
    "git",
)


def _git_exe() -> str | None:
    for c in _GIT_CANDS:
        if c == "git":
            return c
        if os.path.isfile(c):
            return c
    return None


def tracked_files() -> list:
    """返回 git 跟踪的文件相对路径列表；git 不可用返回空列表。"""
    g = _git_exe()
    if not g:
        return []
    try:
        r = subprocess.run([g, "-c", "core.quotepath=false", "ls-files"],
                           cwd=BASE_DIR, capture_output=True, timeout=60)
        if r.returncode != 0:
            return []
        return r.stdout.decode("utf-8", "replace").splitlines()
    except Exception:
        return []


def scan() -> list:
    """返回违规条目 [(rel_path, reason, size_bytes)]。"""
    out = []
    for rel in tracked_files():
        if rel in ALLOWLIST:
            continue
        base = os.path.basename(rel).lower()
        reason = None
        for p in BACKUP_PAT:
            if p in base:
                reason = "备份/冲突副本 (含 %r)" % p
                break
        if reason is None:
            for p in TMP_PAT:
                if base.endswith(p):
                    reason = "临时文件 (后缀 %r)" % p
                    break
        if reason is None:
            continue
        fp = os.path.join(BASE_DIR, rel)
        try:
            sz = os.path.getsize(fp)
        except OSError:
            sz = -1
        out.append((rel, reason, sz))
    return out


def check() -> tuple:
    """(ok, msg)。ok=False 表示存在违规。git 不可用 → (True, 'SKIP ...')。"""
    if not tracked_files():
        return True, "SKIP git 不可用或仓库为空，跳过仓库卫生检查"
    hits = scan()
    if not hits:
        return True, "无备份/临时类文件入仓（已扫 %d 个跟踪文件）" % len(tracked_files())
    total = sum(h[2] for h in hits if h[2] > 0)
    msg = ("检出 %d 个备份/临时类文件被 git 跟踪（合计 %.2f MB）: %s；"
           "处理: git rm --cached <文件> 保留本地，或确认无需保留后删除"
           % (len(hits), total / 1024 / 1024,
              "; ".join("%s(%s)" % (h[0], h[1]) for h in hits[:5])))
    return False, msg


def main() -> int:
    ok, msg = check()
    print("[repo-hygiene] %s" % msg)
    if msg.startswith("SKIP"):
        print("[repo-hygiene] WARN 跳过")
        return 0
    print("[repo-hygiene] %s" % ("OK 通过" if ok else "FAIL 未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
