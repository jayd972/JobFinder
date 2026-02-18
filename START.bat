@echo off
echo ========================================
echo   JobFinder Application Launcher
echo ========================================
echo.

REM Check if Python is available
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found in PATH
    echo Using direct path to Python...
    "C:\Users\darji\AppData\Local\Programs\Python\Python312\python.exe" app.py
) else (
    echo Starting JobFinder...
    python app.py
)

echo.
echo ========================================
echo   Application Stopped
echo ========================================
pause
