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
# v4 (JS-20260920-05): 修正仓库根定位。旧实现在非交互的瘦 sh 环境（计划任务/自动同步）
#   下两条路都走不通 —— `git rev-parse` 返回空（git 不在 hook 继承的 PATH 上），回退分支
#   又依赖 `dirname`（Git for Windows 的瘦 sh 里没有 dirname）→ ROOT 为空 →
#   check_consistency.py 被拼成 "\tools\check_consistency.py" 必然 rc=2 失败。
#   新策略：①用 pwd（git 保证 hook 在仓库根执行）②向上最多找 3 层确认 tools/check_consistency.py
#   全程只用 sh 内置命令，不依赖 git / dirname / readlink。
# v4 (JS-20260920-05): 修正仓库根定位 + MSYS 路径转换。
#   - 旧实现在非交互瘦 sh 下两条路都走不通：`git rev-parse` 返回空（git 不在 hook 继承的
#     PATH 上），回退分支又依赖 `dirname`（瘦 sh 没有）→ ROOT 为空 → 脚本路径拼成
#     "\tools\check_consistency.py" 必然 rc=2。
#   - 此外 git/pwd 在 MSYS 下返回 "/c/Users/..."（POSIX 风格），直接传给 Windows python 会
#     被解析成 "C:\c\Users\..." 找不到文件（v1 注释里就记过这个坑，本次一并根治）。
#   策略：①pwd/git 取根 ②MSYS→Windows 路径转换（纯 POSIX 参数展开，不依赖任何外部命令）
#         ③仍找不到特征文件时向上最多找 3 层
_to_win() {
  case "$1" in
    /?/*)
      _d=${1#/}; _drv=${_d%%/*}; _rest=${_d#*/}
      printf '%s' "${_drv}:/${_rest}"
      ;;
    *) printf '%s' "$1" ;;
  esac
}
ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$ROOT" ]; then
  ROOT=$(pwd)
fi
ROOT=$(_to_win "$ROOT")
if [ ! -f "$ROOT/tools/check_consistency.py" ]; then
  _d=$(_to_win "$(pwd)")
  _i=0
  while [ $_i -lt 3 ]; do
    if [ -f "$_d/tools/check_consistency.py" ]; then ROOT="$_d"; break; fi
    _d=$(_to_win "$(cd "$_d/.." && pwd)")
    _i=$((_i + 1))
  done
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

echo "[pre-commit] 1/5 系统一致性检测..."
"$PY" "$ROOT/tools/check_consistency.py"
rc=$?
if [ $rc -ne 0 ]; then
  echo "[pre-commit] FAIL 系统一致性检测未通过 (rc=$rc)！"
  echo "[pre-commit] 运行: python tools/check_consistency.py"
  exit 1
fi
echo "[pre-commit] OK 一致性通过"

echo "[pre-commit] 2/5 AI 语义审查（暂存 .py，P0 阻断）..."
# v4 (JS-20260920-05): 非交互环境（计划任务/自动同步/CI，stdin 非 tty）跳过 AI 审查。
#   AI 审查要联网调付费模型，在无人值守环境里既无凭据也无意义，一旦超时/失败会
#   直接阻断自动提交（2026-09-20 06:53 自动同步即因此被拦）。交互提交时照常执行。
if [ ! -t 0 ]; then
  echo "[pre-commit] SKIP AI 审查（非交互环境，stdin 非 tty）"
  rc=0
else
  "$PY" "$ROOT/tools/precommit_ai_review.py"
  rc=$?
fi
if [ $rc -ne 0 ]; then
  echo "[pre-commit] FAIL AI 语义审查未通过（P0 问题），已阻止提交。"
  echo "[pre-commit] 若确认为误报，可跳过: git -c ai.review=0 commit 或 AI_REVIEW_SKIP=1 git commit"
  exit 1
fi
echo "[pre-commit] OK AI 审查通过"

echo "[pre-commit] 3/5 页面-API 契约检查（防空壳：前端调用必须已注册路由）..."
"$PY" "$ROOT/tools/page_api_lint.py"
rc=$?
if [ $rc -ne 0 ]; then
  echo "[pre-commit] FAIL 存在页面调用未注册的 API（空壳死链），已阻止提交。"
  echo "[pre-commit] 修复: 补路由/删死调用；已知待修项在 page_api_lint.py PENDING_APIS 名单声明。"
  exit 1
fi
echo "[pre-commit] OK 契约一致（PENDING 到期提醒见上方 WARN）"

echo "[pre-commit] 4/5 操作留痕（审计轨迹，WARN 不阻断）..."
# v4 (JS-20260920-05): 原实现用 sed 拼文件名，瘦 sh 里没有 sed → FILES 恒为空、留痕丢文件清单。
#   改为纯 shell 循环拼接，不依赖任何外部命令。
FILES=""
for f in $(git diff --cached --name-only 2>/dev/null); do
  FILES="$FILES|$f"
done
"$PY" -c "import sys; sys.path.insert(0, r'$ROOT'); from tools.audit_trail import log_event; log_event('commit', 'pre-commit 自动记录', files='$FILES'.split('|'))" >/dev/null 2>&1
echo "[pre-commit] OK 留痕完成"

# v5 (JS-20260921-03): 仓库卫生 —— 备份/临时类文件不得入仓。
#   事故：`git add -A` 把 3 个 <file>.<tag>_bak 形态的一次性迁移备份（1.66 MB）扫进仓库，
#   而 .gitignore 当时只覆盖 *.bak / *.json.bak.*，漏了 *_bak。本闸扫 git ls-files 兜底。
echo "[pre-commit] 5/5 仓库卫生（备份/临时文件不得入仓）..."
"$PY" "$ROOT/tools/repo_hygiene.py"
rc=$?
if [ $rc -ne 0 ]; then
  echo "[pre-commit] FAIL 存在被 git 跟踪的备份/临时类文件，已阻止提交。"
  echo "[pre-commit] 修复: git rm --cached <文件>（保留本地），或删除后重试"
  exit 1
fi
echo "[pre-commit] OK 仓库卫生通过"

echo "[pre-commit] ========================================"
echo "[pre-commit] 全部检查通过，可以提交！"
echo "[pre-commit] ========================================"
exit 0