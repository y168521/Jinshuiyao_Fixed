@echo off
chcp 65001 >nul
title 金水谣自动同步(完整链路)
cd /d "%~dp0"

REM ============================================================
REM 自动同步入口（计划任务 \Jinshuiyao自动同步 每小时调用本 bat）
REM 完整链路委托给 自动同步.ps1（pull+白名单提交+push+双副本+蒸馏+数据守卫+索引保鲜+vault）
REM 2026-08-12 修复：原 bat 仅 pull+add -A 全量提交（运行时数据入库）；现统一走 ps1 白名单通道
REM ============================================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0自动同步.ps1"
exit /b %errorlevel%