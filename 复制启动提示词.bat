@echo off
chcp 65001 >nul
cd /d "%~dp0"
type "启动提示词.txt" | clip
echo ✓ 启动提示词已复制到剪贴板！
echo 现在粘贴给任何 AI（Ctrl+V），即可开工。
echo ====================================
pause