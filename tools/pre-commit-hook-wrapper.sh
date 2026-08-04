#!/bin/sh
# 金水谣 · pre-commit hook（shell wrapper，跨平台兼容）
# 仓库根用 git 自定位，避免 Git Bash 下 pwd 返回 /c/Users 前缀被外壳误拼为 C:\c\Users 导致找不到脚本（2026-08-03 修复 JS-20260803-02）。
ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$ROOT" ]; then
  ROOT=$(cd "$(dirname "$0")/../.." && pwd)
fi
PY="$LOCALAPPDATA/Jinshuiyao/venv/Scripts/python.exe"
if [ ! -f "$PY" ]; then
  PY="$APPDATA/Jinshuiyao/venv/Scripts/python.exe"
fi
if [ ! -f "$PY" ]; then
  PY="py -3.14"
fi

echo "[pre-commit] ========================================"
echo "[pre-commit] 金水谣 · 提交前检查"
echo "[pre-commit] ========================================"

echo "[pre-commit] 1/4 系统一致性检测..."
"$PY" "$ROOT/tools/check_consistency.py"
rc=$?
if [ $rc -ne 0 ]; then
  echo "[pre-commit] FAIL 系统一致性检测未通过 (rc=$rc)！"
  echo "[pre-commit] 运行: python tools/check_consistency.py"
  exit 1
fi
echo "[pre-commit] OK 一致性通过"

echo "[pre-commit] 2/4 AI 语义审查（暂存 .py，P0 阻断）..."
"$PY" "$ROOT/tools/precommit_ai_review.py"
rc=$?
if [ $rc -ne 0 ]; then
  echo "[pre-commit] FAIL AI 语义审查未通过（P0 问题），已阻止提交。"
  echo "[pre-commit] 若确认为误报，可跳过: git -c ai.review=0 commit 或 AI_REVIEW_SKIP=1 git commit"
  exit 1
fi
echo "[pre-commit] OK AI 审查通过"

echo "[pre-commit] ========================================"
echo "[pre-commit] 全部检查通过，可以提交！"
echo "[pre-commit] ========================================"
exit 0
