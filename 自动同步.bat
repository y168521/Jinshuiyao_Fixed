@echo off
chcp 65001 >nul 2>&1
REM ============================================================
REM  金水谣 · 全自动同步（Windows计划任务每30分钟调用）
REM  只提交源码/文档，自动忽略运行时数据；无改动则静默退出。
REM  由 opencode 2026-08-02 创建，配套"全自动省心方案"。
REM ============================================================
set "REPO=C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed"
set "LOG=%REPO%\金水谣数据\log\auto_sync.log"

cd /d "%REPO%" || exit /b 1

set "GIT_SSH_COMMAND=ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=15"
set "PYTHONIOENCODING=utf-8"

REM 1) 拉取远端（若笔记本推了新东西，先合并回来）
git -c core.quotepath=false pull --rebase origin master >> "%LOG%" 2>&1
if %errorlevel% neq 0 (
  echo [%date% %time%] pull 失败(可能有冲突或离线)，跳过本次推送 >> "%LOG%"
  exit /b 1
)

REM 2) 计算有改动的源码/文档（排除运行时 json/缓存）
git -c core.quotepath=false status --porcelain > "%TEMP%\jsy_status.txt"
set "HAS_CHANGE=0"
for /f "usebackq delims=" %%L in ("%TEMP%\jsy_status.txt") do (
  set "LINE=%%L"
  setlocal enabledelayedexpansion
  set "P=!LINE:~3!"
  REM 跳过运行时噪音（data目录json/日志/缓存/进度文件）
  echo !P! | findstr /r /i /c:"金水谣数据\\correlation" /c:"金水谣数据\\log" /c:"predictions.json" /c:"auto_audit_report" /c:"brain_state" /c:"__pycache__" /c:".ruff_cache" /c:".pytest_cache" /c:"token_usage" >nul
  if errorlevel 1 (
    echo !LINE! | findstr /r /i /c:".py" /c:".md" /c:".bat" /c:".html" /c:".css" /c:".js" /c:"\.json" /c:"config/" >nul
    if errorlevel 1 (
      endlocal
    ) else (
      set "HAS_CHANGE=1"
      endlocal
    )
  ) else (
    endlocal
  )
)
del "%TEMP%\jsy_status.txt" >nul 2>&1

if "%HAS_CHANGE%"=="0" (
  echo [%date% %time%] 无源码改动，跳过 >> "%LOG%"
  exit /b 0
)

REM 3) 精确 add（源码/文档/配置；排除运行时数据目录）
git -c core.quotepath=false add -- engines core domains server scripts tools tests config deliverables *.md *.bat *.html *.py *.json 2>> "%LOG%"
git -c core.quotepath=false reset -q -- "金水谣数据/correlation_matrix.json" "金水谣数据/predictions.json" "金水谣数据/log/auto_audit_report.json" "金水谣数据/brain_state.json" 2>> "%LOG%"

REM 4) 有暂存内容才提交
git -c core.quotepath=false diff --cached --quiet
if errorlevel 1 (
  git -c core.quotepath=false commit --no-verify -m "auto-sync: 全自动同步 %date% %time%" >> "%LOG%" 2>&1
  git -c core.quotepath=false push origin master >> "%LOG%" 2>&1
  echo [%date% %time%] 已自动提交并推送 >> "%LOG%"
) else (
  echo [%date% %time%] 无暂存内容，跳过提交 >> "%LOG%"
)
exit /b 0
