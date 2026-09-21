# -*- coding: utf-8 -*-
"""金水谣 · git hooks 安装器（幂等 · 跨平台）

把仓库内「规范源」hook 复制到 <git-dir>/hooks/，让新克隆/协作者一条命令获得
pre-commit 钩子（AST+审计+收工门禁），避免「本地 .git/hooks 手改了但仓库没有」的漂移。

用法：
  py -3.14 tools/install_hooks.py

行为：
  - Windows: 复制 tools/pre-commit-hook.bat -> <git-dir>/hooks/pre-commit
  - Linux/Mac: 复制 tools/pre-commit-hook.sh -> <git-dir>/hooks/pre-commit
  - 幂等：重复运行直接覆盖，不影响其他 hook
  - 紧急绕过：git commit --no-verify
"""
import os
import sys
import stat
import shutil
import subprocess

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_IS_WINDOWS = sys.platform == "win32"
_SRC = os.path.join(_ROOT, "tools", "pre-commit-hook-wrapper.sh")


# JS-20260921-03：本机 git 不在 PATH（真实 git 在 E:\下载\Git\bin\git.exe），
# 直接 subprocess(["git", ...]) 必然 FileNotFoundError → 安装器永远失败、
# 仓库内的 hook 规范源永远分发不到 .git/hooks。改为「候选 git → 兜底 <ROOT>/.git」。
_GIT_CANDS = [
    os.environ.get("GIT_EXE", ""),
    r"E:\下载\Git\bin\git.exe",
    r"C:\Program Files\Git\bin\git.exe",
    r"C:\Program Files\Git\cmd\git.exe",
    "git",
]


def _git_dir():
    for exe in _GIT_CANDS:
        if not exe:
            continue
        try:
            out = subprocess.check_output(
                [exe, "rev-parse", "--git-dir"], cwd=_ROOT, text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            continue
        if out:
            if not os.path.isabs(out):
                out = os.path.join(_ROOT, out)
            return os.path.abspath(out)
    # 兜底：标准布局就是 <仓库根>/.git（含 worktree 场景也先按此处理并校验）
    fallback = os.path.join(_ROOT, ".git")
    if os.path.isdir(fallback):
        print(f"[install_hooks] 提示: git 不可用，回退到 {fallback}")
        return fallback
    print("[install_hooks] 无法定位 git 目录: 既无可用 git，也未找到 <仓库根>/.git")
    sys.exit(1)


def main():
    if not os.path.isfile(_SRC):
        print(f"[install_hooks] 源 hook 不存在: {_SRC}")
        sys.exit(1)

    gdir = _git_dir()
    hooks_dir = os.path.join(gdir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    dst = os.path.join(hooks_dir, "pre-commit")

    shutil.copyfile(_SRC, dst)
    # Windows + Linux 统一用 sh wrapper（Git for Windows 自带 sh.exe 可执行）

    print(f"[install_hooks] ✅ 已安装 pre-commit hook -> {dst}")
    print(f"[install_hooks] 后续提交自动运行: AST 语法检查 + 跨文档审计 + 收工门禁三件套")
    print(f"[install_hooks] 紧急绕过：git commit --no-verify")


if __name__ == "__main__":
    main()
