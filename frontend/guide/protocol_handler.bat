@echo off
chcp 936 >nul 2>&1

:: 金水谣 jinshuiyao:// 协议处理器
:: 由浏览器点 jinshuiyao://xxx 链接时调用

set "BASE=C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed"

:: URL格式: jinshuiyao://run.bat 或 jinshuiyao://knowledge/mirofish_gui.py
set "URL=%~1"
set "REL=%URL:jinshuiyao://=%"

:: 反斜杠归一化
set "REL=%REL:/=\%"

:: 去掉首尾反斜杠
if "%REL:~0,1%"=="\" set "REL=%REL:~1%"
if "%REL:~-1%"=="\" set "REL=%REL:~0,-1%"

set "FULL=%BASE%\%REL%"

:: 目录用资源管理器打开
if exist "%FULL%\*" (
    start "" explorer "%FULL%"
    exit /b 0
)

:: .html 用默认浏览器打开
echo "%FULL%" | findstr /i ".html" >nul
if %errorlevel%==0 (
    start "" "%FULL%"
    exit /b 0
)

:: .py 用 pythonw 后台运行(不弹黑窗口)
echo "%FULL%" | findstr /i ".py" >nul
if %errorlevel%==0 (
    start "" "D:\python38\pythonw.exe" "%FULL%"
    exit /b 0
)

:: .bat 用 cmd 运行
echo "%FULL%" | findstr /i ".bat" >nul
if %errorlevel%==0 (
    start "" cmd /c "%FULL%"
    exit /b 0
)

:: 其他(.json .txt .log等)用记事本打开
start "" notepad "%FULL%"
exit /b 0
