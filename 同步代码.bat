@echo off
chcp 936 >nul
title 自动同步代码...
cd /d "%~dp0"

echo ========== 自动同步代码 ==========

REM 自动选择 git 路径
set GITCMD=git
where git >nul 2>nul
if %errorlevel% neq 0 set GITCMD=E:\Git\cmd\git.exe

REM 下载远程更新，自动容忍版本修改
echo [1/3] 下载远程更新...
REM DNS波动容忍: pull失败自动重试(最多3次, 间隔5秒)
set RETRY=0
:RETRY_PULL
%GITCMD% pull --rebase --autostash
if %errorlevel% equ 0 goto PULL_OK
set /a RETRY+=1
if %RETRY% geq 3 goto PULL_FAIL
echo   同步失败, 5秒后自动重试 (%RETRY%/3)...
timeout /t 5 /nobreak >nul
goto RETRY_PULL
:PULL_FAIL
echo x 下载失败(重试3次仍失败), 可能有冲突
pause
exit /b
:PULL_OK

REM 提交本机修改
echo [2/3] 提交本机修改...
%GITCMD% add -A
%GITCMD% commit -m "自动同步 %date% %time%"
if %errorlevel% equ 0 (
    echo [3/3] 上传到 GitHub...
    %GITCMD% push
) else (
    echo - 没有新的修改需要上传
)

echo ========== 同步完成 ==========
timeout /t 3 /nobreak >nul
