@echo off
chcp 936 >nul
title 金水谣 · DeepSeek 备用代码助手
set "PY="
if not defined PY (for /f "delims=" %%i in ('where py 2^>nul') do @if not defined PY set "PY=%%i")
if not defined PY if exist "%LocalAppData%\Programs\Python\Python314\python.exe" set "PY=%LocalAppData%\Programs\Python\Python314\python.exe"
if not defined PY if exist "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python38\python.exe" set "PY=%LocalAppData%\Programs\Python\Python38\python.exe"
if not defined PY if exist "C:\Users\Administrator\AppData\Local\Programs\Python\Python38\python.exe" set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python38\python.exe"
if not defined PY if exist "C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PY=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not defined PY (for /f "delims=" %%i in ('where python 2^>nul') do @if not defined PY (echo %%i | findstr /i "WindowsApps" >nul || set "PY=%%i"))
if not defined PY (
  echo 没有找到 Python，请先安装 Python 3.8 或以上版本。
  echo 下载地址：https://www.python.org/downloads/
  pause
  exit /b 1
)
cd /d "%~dp0"
"%PY%" "deepseek_coder.py"
if errorlevel 1 pause
