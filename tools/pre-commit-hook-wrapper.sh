#!/bin/sh
# 金水谣 · pre-commit hook（shell wrapper，跨平台兼容，规范源 v2）
# 仓库根用 git 自定位，避免 Git Bash 下 pwd 返回 /c/Users 前缀被外壳误拼为 C:\c\Users 导致找不到脚本（2026-08-03 修复 JS-20260803-02）。
# v2 (W63补70)：补第3步 page_api_lint（防空壳死链，与已装 hook 对齐）+ 第4步操作留痕（audit_trail）；
#               删除遗留 pre-commit-hook.sh/.bat；install_hooks.py 复制本文件为唯一规范源。
# v3 (W63补118)：解释器定位改为"候选路径逐个探测"。原兜底有两个致命问题——
#                ①PY="py -3.14" 在下述调用处写成 "$PY"，sh 会把 "py -3.14" 当成一个程序名，必然 command not found (rc=127)；
#                ②本机装 Python 3.14 时用了 Include_launcher=0，压根没有 py.exe 启动器。
#                系统重装后 LOCALAPPDATA/APPDATA 下的旧 venv 也已不存在，而项目 venv 路径随机器盘符变化
#                （台式=D 盘、笔记本=E 盘，统一 <盘符>:\Project_Env\jinshuiyao_env），故按盘符逐个探测。
ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$ROOT" ]; then
  ROOT=$(cd "$(dirname "$0")/../.." && pwd)
fi
PY=""
for CAND in \
  "$LOCALAPPDATA/Jinshuiyao/venv/Scripts/python.exe" \
  "$APPDATA/Jinshuiyao/venv/Scripts/python.exe" \
  "D:/Project_Env/jinshuiyao_env/Scripts/python.exe" \
  "E:/Project_Env/jinshuiyao_env/Scripts/python.exe" \
  "C:/Project_Env/jinshuiyao_env/Scripts/python.exe" \
  "F:/Project_Env/jinshuiyao_env/Scripts/python.exe" \
  "G:/Project_Env/jinshuiyao_env/Scripts/python.exe" \
  "H:/Project_Env/jinshuiyao_env/Scripts/python.exe" \
  "E:/Python314/python.exe" \
  "C:/Python314/python.exe"
do
  if [ -n "$CAND" ] && [ -f "$CAND" ]; then PY="$CAND"; break; fi
done
if [ -z "$PY" ]; then
  PY=$(command -v python 2>/dev/null)
fi
if [ -z "$PY" ]; then
  echo "[pre-commit] FAIL 找不到可用的 Python 解释器，无法执行提交前检查。"
  echo "[pre-commit] 修复: 建 venv 到 <盘符>:\\Project_Env\\jinshuiyao_env，或保证 python 在 PATH 中"
  exit 1
fi
echo "[pre-commit] 解释器: $PY"

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

echo "[pre-commit] 3/4 页面-API 契约检查（防空壳：前端调用必须已注册路由）..."
"$PY" "$ROOT/tools/page_api_lint.py"
rc=$?
if [ $rc -ne 0 ]; then
  echo "[pre-commit] FAIL 存在页面调用未注册的 API（空壳死链），已阻止提交。"
  echo "[pre-commit] 修复: 补路由/删死调用；已知待修项在 page_api_lint.py PENDING_APIS 名单声明。"
  exit 1
fi
echo "[pre-commit] OK 契约一致（PENDING 到期提醒见上方 WARN）"

echo "[pre-commit] 4/4 操作留痕（审计轨迹，WARN 不阻断）..."
FILES=$(git diff --cached --name-only 2>/dev/null | sed ':a;N;$!ba;s/\n/|/g')
"$PY" -c "import sys; sys.path.insert(0, r'$ROOT'); from tools.audit_trail import log_event; log_event('commit', 'pre-commit 自动记录', files='$FILES'.split('|'))" >/dev/null 2>&1
echo "[pre-commit] OK 留痕完成"

echo "[pre-commit] ========================================"
echo "[pre-commit] 全部检查通过，可以提交！"
echo "[pre-commit] ========================================"
exit 0