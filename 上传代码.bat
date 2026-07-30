@echo off
chcp 65001 >nul
echo ========== 上传代码到 GitHub ==========
"E:\Git\cmd\git.exe" add -A
"E:\Git\cmd\git.exe" commit -m "自动同步 %date% %time%"
"E:\Git\cmd\git.exe" push
if %errorlevel%==0 (
    echo ✓ 上传成功！
) else (
    echo × 失败，可能是没有新的更改
)
echo ====================================
pause