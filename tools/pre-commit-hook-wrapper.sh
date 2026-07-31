#!/bin/sh
# 金水谣 · pre-commit hook（shell wrapper，跨平台兼容）
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
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

echo "[pre-commit] ========================================"
echo "[pre-commit] 全部检查通过，可以提交！"
echo "[pre-commit] ========================================"
exit 0
