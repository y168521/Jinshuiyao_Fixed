#!/bin/sh
# 金水谣 pre-commit 钩子（仓库可跟踪规范源）
# 安装方式: py -3.14 tools/install_hooks.py
# 绕过方式: git commit --no-verify

PY="py -3.14"
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "$(cd "$(dirname "$0")/../.." && pwd)")

echo "[pre-commit] ========================================"
echo "[pre-commit] 金水谣 · 提交前检查"
echo "[pre-commit] ========================================"

# 1. AST 语法检查
echo "[pre-commit] 1/3 AST 语法检查..."
$PY "$ROOT/Jinshuiyao_Fixed/tools/gate.py" --ast --quick
if [ $? -ne 0 ]; then
    echo "[pre-commit] FAIL AST 语法检查未通过！"
    exit 1
fi
echo "[pre-commit] OK AST 通过"

# 2. 跨文档一致性审计
echo "[pre-commit] 2/3 跨文档一致性审计..."
$PY "$ROOT/Jinshuiyao_Fixed/tools/gate.py" --audit
if [ $? -ne 0 ]; then
    echo "[pre-commit] FAIL 审计未通过！"
    exit 1
fi
echo "[pre-commit] OK 审计通过"

# 3. 收工门禁（交接中心/经验收集箱/总索引三件套）
echo "[pre-commit] 3/3 收工门禁..."
$PY "$ROOT/Jinshuiyao_Fixed/tools/closeout_gate.py"
if [ $? -ne 0 ]; then
    echo "[pre-commit] FAIL 收工三件套不全！"
    exit 1
fi
echo "[pre-commit] OK 收工门禁通过"

# 4. 操作留痕
echo "[pre-commit] 4/4 操作留痕..."
FILES=$(git diff --cached --name-only | tr '\n' ' ')
$PY -c "
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname('$0'), '..'))
from tools.audit_trail import log_event
files = '$FILES'.split()
log_event('commit', 'pre-commit auto-log', files=files)
"
echo "[pre-commit] OK 留痕记录"

echo "[pre-commit] ========================================"
echo "[pre-commit] 全部检查通过，可以提交！"
echo "[pre-commit] ========================================"
exit 0
