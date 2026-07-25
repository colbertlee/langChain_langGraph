@echo off
REM ============================================================
REM  AI Agent Windows - Web service launcher
REM  After launch open http://127.0.0.1:8000
REM  Requires spec to be re-packed with app.py as entry.
REM ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".env" (
    if exist "install.bat" call install.bat
)

set MPLBACKEND=Agg
set HOST=0.0.0.0
set PORT=8000

echo ===========================================================
echo   AI Agent (Web) starting on http://127.0.0.1:%PORT%/
echo   Press Ctrl+C to stop
echo ===========================================================

ai-agent.exe web
if errorlevel 1 (
    echo.
    echo Launch failed. If the exe was packed from main.py, re-pack with app.py entry.
    pause
)
endlocal
