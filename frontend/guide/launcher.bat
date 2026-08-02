@echo off
chcp 936 >nul
cd /d "%~dp0"
set "BASE=c:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed"
if "%~1"=="" exit /b 1
set "REL=%~1"
set "FULL=%BASE%\%REL%"
if exist "%FULL%\*" (
    start "" explorer "%FULL%"
    exit /b 0
)
echo "%REL%" | findstr /i ".html" >nul
if %errorlevel%==0 (
    start "" "%FULL%"
    exit /b 0
)
echo "%REL%" | findstr /i ".py" >nul
if %errorlevel%==0 (
    start "" "D:\python38\pythonw.exe" "%FULL%"
    exit /b 0
)
echo "%REL%" | findstr /i ".bat" >nul
if %errorlevel%==0 (
    start "" cmd /c "%FULL%"
    exit /b 0
)
start "" notepad "%FULL%"
exit /b 0
