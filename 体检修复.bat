@echo off
chcp 65001 >nul 2>&1
title 金水谣体检医生
setlocal EnableDelayedExpansion

:: ============================================================
::  金水谣体检医生 v3.0（doctor.py是纯标准库，任意Python即可运行）
:: ============================================================

set "PY="

:: ─── 策略1：Windows Python Launcher ───
if not defined PY (
    for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%i"
)

:: ─── 策略2：PATH中的python ───
if not defined PY (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        if not defined PY (
            echo %%i | findstr /i "WindowsApps" >nul || (
                "%%i" --version >nul 2>&1 && set "PY=%%i"
            )
        )
    )
)

:: ─── 策略3：常见安装位置 ───
if not defined PY (
    for %%d in (C D E F G) do (
        if not defined PY if exist "%%d:\下载\python.exe" set "PY=%%d:\下载\python.exe"
        if not defined PY if exist "%%d:\Python314\python.exe" set "PY=%%d:\Python314\python.exe"
        if not defined PY if exist "%%d:\python38\python.exe" set "PY=%%d:\python38\python.exe"
    )
)

:: ─── 策略4：用户AppData ───
if not defined PY (
    for /f "delims=" %%u in ('echo %LocalAppData%') do (
        for %%v in (Python314 Python313 Python312 Python311 Python310) do (
            if not defined PY if exist "%%u\Programs\Python\%%v\python.exe" set "PY=%%u\Programs\Python\%%v\python.exe"
        )
    )
)

if not defined PY (
    echo [错误] 找不到Python，无法运行体检。
    echo 请安装 Python 3.10+ 后重试。
    pause
    exit /b 1
)

"%PY%" "%~dp0tools\doctor.py"
pause
