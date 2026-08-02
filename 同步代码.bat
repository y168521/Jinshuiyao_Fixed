@echo off
chcp 936 >nul
title 代码同步中...
cd /d "%~dp0"

echo ========== 正在同步代码 ==========

REM 自动检测 git 路径
set GITCMD=git
where git >nul 2>nul
if %errorlevel% neq 0 set GITCMD=E:\Git\cmd\git.exe

REM 先下载远程更新（自动暂存本地修改）
echo [1/3] 下载远程更新...
%GITCMD% pull --rebase --autostash
if %errorlevel% neq 0 (
    echo × 下载失败，可能有冲突
    pause
    exit /b
)

REM 再上传本地修改
echo [2/3] 提交本地修改...
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