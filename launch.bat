@echo off
chcp 936 >nul 2>&1
setlocal EnableDelayedExpansion

:: ============================================================
::  金水谣助手 启动器 v3.0（与 ensure_runtime 配合）
::  职责：找到任意可用 Python → 交给 launch_jinshuiyao.py
::  venv创建/依赖安装/路径修复 全部由 ensure_runtime() 自动完成
::  换电脑零配置，双击即用
:: ============================================================

set "PY="

:: ─── 策略0：本机专用 venv（2026-07-28 由 venv_314 迁移至本地盘 Project_Env\jinshuiyao_env；盘符随机器：台式D/笔记本E，自动扫描）───
if not defined PY (
    for %%d in (C D E F G H) do (
        if not defined PY if exist "%%d:\Project_Env\jinshuiyao_env\Scripts\python.exe" (
            "%%d:\Project_Env\jinshuiyao_env\Scripts\python.exe" --version >nul 2>&1 && set "PY=%%d:\Project_Env\jinshuiyao_env\Scripts\python.exe"
        )
    )
)

:: ─── 策略1：Windows Python Launcher（最可靠，装Python时自动注册） ───
:: 注意：py 返回的 python 路径必须真实存在且可运行，否则宁可不采用（避免指向旧机坏路径）
if not defined PY (
    for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
        if exist "%%i" (
            "%%i" --version >nul 2>&1 && set "PY=%%i"
        )
    )
)

:: ─── 策略2：PATH中的python（排除WindowsApps商店占位符） ───
if not defined PY (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        if not defined PY (
            echo %%i | findstr /i "WindowsApps" >nul || (
                "%%i" --version >nul 2>&1 && set "PY=%%i"
            )
        )
    )
)

:: ─── 策略3：常见安装位置（覆盖各种盘符） ───
if not defined PY (
    for %%d in (C D E F G) do (
        if not defined PY if exist "%%d:\下载\python.exe" set "PY=%%d:\下载\python.exe"
        if not defined PY if exist "%%d:\Python314\python.exe" set "PY=%%d:\Python314\python.exe"
        if not defined PY if exist "%%d:\Python313\python.exe" set "PY=%%d:\Python313\python.exe"
        if not defined PY if exist "%%d:\Python312\python.exe" set "PY=%%d:\Python312\python.exe"
        if not defined PY if exist "%%d:\python38\python.exe" set "PY=%%d:\python38\python.exe"
    )
)

:: ─── 策略4：用户AppData标准安装位置 ───
if not defined PY (
    for /f "delims=" %%u in ('echo %LocalAppData%') do (
        for %%v in (Python314 Python313 Python312 Python311 Python310) do (
            if not defined PY if exist "%%u\Programs\Python\%%v\python.exe" set "PY=%%u\Programs\Python\%%v\python.exe"
        )
    )
)

:: ─── 策略5：WorkBuddy内置Python ───
if not defined PY (
    for /d %%v in ("%UserProfile%\.workbuddy\binaries\python\versions\*") do (
        if not defined PY if exist "%%v\python.exe" set "PY=%%v\python.exe"
    )
)

if not defined PY (
    echo [错误] 未找到 Python。请安装 Python 3.10+ 后重试。
    echo         下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: ─── 清理占用18888端口的旧进程 ───
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr "LISTENING" ^| findstr ":18888"') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: ─── 禁止 Python 生成 .pyc 缓存（坚果云不支持忽略列表，从源头不产生缓存） ───
set "PYTHONDONTWRITEBYTECODE=1"

:: ─── 启动（独立窗口运行，避免 bat 等待导致服务被误关） ───
start "" "%PY%" "%~dp0launch_jinshuiyao.py"
exit /b 0
