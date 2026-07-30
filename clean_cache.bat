@echo off
echo ============================================
echo   Clean Python Cache (one-time)
echo ============================================
echo.

set COUNT=0

for /d /r "%~dp0" %%D in (__pycache__) do (
    echo   Removing: %%D
    rd /s /q "%%D"
    set /a COUNT+=1
)

echo.
echo ============================================
echo   Done! Removed %COUNT% cache folders
echo ============================================
echo.
pause
