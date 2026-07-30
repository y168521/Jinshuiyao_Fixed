@echo off
chcp 65001 >nul
REM Jinshuiyao Watchdog Task Installer
REM Creates an hourly Windows scheduled task to monitor the Jinshuiyao service.
REM If not running as admin, this script will automatically request elevation.

REM Check admin rights
net session >nul 2>&1
if %errorlevel% == 0 goto run

REM No admin rights: use PowerShell to relaunch this batch with UAC elevation
powershell -Command "Start-Process -FilePath '%~f0' -Verb runAs"
exit /b

:run
cd /d "%~dp0"
"..\..\venv_314\Scripts\python.exe" install_watchdog.py
pause
