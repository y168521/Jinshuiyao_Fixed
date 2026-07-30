@echo off
chcp 65001 >nul
echo ========== 从 GitHub 下载更新 ==========
git pull
if %errorlevel%==0 (
    echo ✓ 下载完成！
) else (
    echo × 失败，尝试用完整路径...
    "E:\Git\cmd\git.exe" pull
)
echo ====================================
pause