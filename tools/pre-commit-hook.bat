@echo off
chcp 65001 >nul
REM 金水谣 · pre-commit 钩子（仓库可跟踪规范源）
REM 安装方式: py -3.14 tools/install_hooks.py
REM 绕过方式: git commit --no-verify

setlocal enabledelayedexpansion

REM 自动定位项目根目录（先试 git，再试相对路径）
for /f "delims=" %%i in ('git rev-parse --show-toplevel 2^>nul') do set "ROOT=%%i"
if not defined ROOT set "ROOT=%~dp0..\.."

set "PY=py -3.14"

echo [pre-commit] ========================================
echo [pre-commit] 金水谣 · 提交前检查
echo [pre-commit] ========================================

REM 1. AST 语法检查
echo [pre-commit] 1/3 AST 语法检查...
%PY% "%ROOT%\Jinshuiyao_Fixed\tools\gate.py" --ast --quick
if errorlevel 1 (
    echo [pre-commit] FAIL AST 语法检查未通过！
    exit /b 1
)
echo [pre-commit] OK AST 通过

REM 2. 跨文档一致性审计
echo [pre-commit] 2/3 跨文档一致性审计...
%PY% "%ROOT%\Jinshuiyao_Fixed\tools\gate.py" --audit
if errorlevel 1 (
    echo [pre-commit] FAIL 审计未通过！
    exit /b 1
)
echo [pre-commit] OK 审计通过

REM 3. 收工门禁（交接中心/经验收集箱/总索引三件套）
echo [pre-commit] 3/3 收工门禁...
%PY% "%ROOT%\Jinshuiyao_Fixed\tools\closeout_gate.py"
if errorlevel 1 (
    echo [pre-commit] FAIL 收工三件套不全！
    exit /b 1
)
echo [pre-commit] OK 收工门禁通过

REM 4. 系统一致性检测（防复发：路由/资源/同步/链接）
echo [pre-commit] 4/5 系统一致性检测...
%PY% "%ROOT%\Jinshuiyao_Fixed\tools\check_consistency.py"
if errorlevel 1 (
    echo [pre-commit] FAIL 系统一致性检测未通过！
    echo [pre-commit] 运行 python tools/check_consistency.py 查看详情
    exit /b 1
)
echo [pre-commit] OK 系统一致性通过

REM 5. 操作留痕（记录本次提交）
echo [pre-commit] 5/5 操作留痕...
git diff --cached --name-only > "%TEMP%\jinshuiyao_staged.txt"
%PY% -c "import sys; sys.path.insert(0, r'%ROOT%\Jinshuiyao_Fixed'); f=open(r'%TEMP%\jinshuiyao_staged.txt'); files=[l.strip() for l in f if l.strip()]; f.close(); from tools.audit_trail import log_event; log_event('commit', 'pre-commit 自动记录', files=files)"
echo [pre-commit] OK 留痕记录

echo [pre-commit] ========================================
echo [pre-commit] 全部检查通过，可以提交！
echo [pre-commit] ========================================
exit /b 0
