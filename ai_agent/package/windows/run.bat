@echo off
REM ============================================================
REM  AI Agent Windows - launcher (CLI mode)
REM  Double-click to run.
REM  For Web service mode, use run-web.bat (requires re-pack with app.py entry).
REM ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set MPLBACKEND=Agg

if not exist ".env" (
    if exist "install.bat" call install.bat
)

echo ===========================================================
echo   AI Agent (CLI) starting...
echo   Type 'exit' or Ctrl+C to quit
echo ===========================================================
echo.

ai-agent.exe
if errorlevel 1 (
    echo.
    echo Launch failed. Make sure ai-agent.exe is in this directory.
    pause
)
endlocal
