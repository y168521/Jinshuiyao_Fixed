# -*- coding: utf-8 -*-
"""金水谣 �ة pre-commit AI 语义审查桥接脚本 (precommit_ai_review.py)

由 pre-commit hook (pre-commit-hook-wrapper.sh) 调用：
  1. git diff --cached 收集本次暂存的 .py 文件
  2. 调用 tools/ai_review_agent.py 做 AI 语义审查（DeepSeek/硅基流动）
  3. 检出 P0 问题 -> 打印详情并 exit 1（阻断提交）
     P1/P2/P3 -> 打印摘要但放行
  4. 跳过方式（三选一）：
     - git -c ai.review=0 commit -m "..."   （git 临时配置，最标准）
     - AI_REVIEW_SKIP=1 git commit -m "..."
     - git commit --no-verify               （跳过全部钩子）

设计约束：
  - AI 审查异常（网络/超时/无密钥）时只警告放行，不误伤正常提交
  - 无 .py 改动时零开销直接通过
  - 自动同步（自动同步.ps1）同样受此钩子保护，防坏代码入库
"""

import json
import os
import subprocess
import sys
import time

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Jinshuiyao_Fixed/
_AGENT = os.path.join(_BASE, "tools", "ai_review_agent.py")


def _git(args):
    try:
        out = subprocess.check_output(
            ["git"] + args, cwd=_BASE, text=True, timeout=20,
            errors="replace",
        )
        return out.strip()
    except Exception:
        return ""


def _staged_py_files():
    """本次暂存的 .py 文件列表（绝对路径）。新增/修改/复制；跳过删除。"""
    out = _git(["-c", "core.quotepath=false", "diff", "--cached",
                "--name-only", "--diff-filter=ACM"])
    if not out:
        return []
    return [os.path.join(_BASE, f) for f in out.splitlines()
            if f.endswith(".py") and os.path.isfile(os.path.join(_BASE, f))]


def _skip_requested():
    """跳过 AI 审查的判断：AI_REVIEW_SKIP=1 或 git config ai.review=0"""
    if os.environ.get("AI_REVIEW_SKIP") == "1":
        return True
    val = _git(["config", "--get", "ai.review"])
    return val.strip() == "0"


def main():
    start = time.time()
    print("[pre-commit] AI 语义审查开始 ...")

    if _skip_requested():
        print("[pre-commit] SKIP AI 语义审查（AI_REVIEW_SKIP / git -c ai.review=0）")
        return 0

    files = _staged_py_files()
    if not files:
        print("[pre-commit] SKIP AI 语义审查（无暂存 .py 文件）")
        return 0

    print(f"[pre-commit] AI 语义审查 {len(files)} 个 .py 文件 ...")
    cmd = [sys.executable, _AGENT, "--files", ",".join(files), "--json"]
    try:
        proc = subprocess.run(
            cmd, cwd=_BASE, capture_output=True, timeout=300,
        )
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        print("[pre-commit] WARN AI 审查超时（>300s），放行本次提交")
        return 0
    except Exception as e:
        print(f"[pre-commit] WARN AI 审查调用失败: {e}，放行本次提交")
        return 0

    if proc.returncode != 0 or not stdout.strip():
        err = (stderr or "").strip()[:300]
        print(f"[pre-commit] WARN AI 审查未产出结果 (rc={proc.returncode}) {err}")
        print("[pre-commit] 放行本次提交（可 git -c ai.review=0 commit 显式跳过）")
        return 0

    try:
        report = json.loads(stdout)
    except json.JSONDecodeError:
        print("[pre-commit] WARN AI 审查输出解析失败，放行本次提交")
        return 0

    issues = report.get("issues", [])
    p0 = [i for i in issues if i.get("severity") == "P0"]
    p1 = [i for i in issues if i.get("severity") == "P1"]
    others = len(issues) - len(p0) - len(p1)

    if p0:
        print("[pre-commit] FAIL AI 语义审查检出 P0 问题（阻断提交）:")
        for i in p0[:10]:
            f = i.get("file", "")
            line = i.get("line", "")
            print(f"  [P0] {f}:{line} {i.get('description', '')[:150]}")
            hint = i.get("fix_hint")
            if hint:
                print(f"       修复: {hint[:150]}")
        print("[pre-commit] 如确认为误报，可跳过: git -c ai.review=0 commit ...")
        return 1

    print(f"[pre-commit] OK AI 语义审查通过 "
          f"({len(files)} 文件, P0={len(p0)}, P1={len(p1)}, 其他={others}, "
          f"{int((time.time() - start) * 1000)}ms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
