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


def _git_dir():
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--git-dir"], cwd=_ROOT, text=True
        ).strip()
    except Exception as e:
        print(f"[install_hooks] 无法定位 git 目录: {e}")
        sys.exit(1)
    if not os.path.isabs(out):
        out = os.path.join(_ROOT, out)
    return os.path.abspath(out)


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
