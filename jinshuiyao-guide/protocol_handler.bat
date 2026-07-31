@echo off
chcp 65001 >nul 2>&1

:: 天枢自定义协议处理器
:: 接收 jinshuiyao://文件路径 参数，直接打开对应文件
set "BASE=c:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed"

:: URL格式: jinshuiyao://run.bat 或 jinshuiyao://knowledge/mirofish_gui.py
set "URL=%~1"
set "REL=%URL:jinshuiyao://=%"

:: 去除可能的斜杠
set "REL=%REL:/=\%"

:: 去除开头和结尾的斜杠
if "%REL:~0,1%"=="\" set "REL=%REL:~1%"
if "%REL:~-1%"=="\" set "REL=%REL:~0,-1%"

set "FULL=%BASE%\%REL%"

:: 检查是否是文件夹
if exist "%FULL%\*" (
    start "" explorer "%FULL%"
    exit /b 0
)

:: .html文件用默认浏览器打开
echo "%FULL%" | findstr /i ".html" >nul
if %errorlevel%==0 (
    start "" "%FULL%"
    exit /b 0
)

:: .py文件用pythonw运行（不弹黑窗口）—— 使用绝对路径避免裸 pythonw 找不到解释器
echo "%FULL%" | findstr /i ".py" >nul
if %errorlevel%==0 (
    start "" "D:\python38\pythonw.exe" "%FULL%"
    exit /b 0
)

:: .bat文件直接运行
echo "%FULL%" | findstr /i ".bat" >nul
if %errorlevel%==0 (
    start "" cmd /c "%FULL%"
    exit /b 0
)

:: 其他文件(.json .txt .log等)用记事本打开
start "" notepad "%FULL%"
exit /b 0
