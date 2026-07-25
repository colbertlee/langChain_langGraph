@echo off
REM ============================================================
REM  AI Agent Windows - install / first-run setup
REM  Usage: double-click install.bat
REM  Automation:  set SMOKE=1 ^&^& install.bat   (skips pause)
REM ============================================================
setlocal
chcp 65001 >nul

echo ===========================================================
echo        AI Agent (Windows) First-Run Setup
echo ===========================================================
echo.

REM 1) .env
if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
        echo [1/3] .env created (from .env.example)
    ) else (
        echo [1/3] WARNING: .env.example not found
    )
) else (
    echo [1/3] .env already exists, skip
)

REM 2) runtime dirs
if not exist "logs"    mkdir logs
if not exist "uploads" mkdir uploads
if not exist "data"    mkdir data
echo [2/3] created logs/ uploads/ data/

REM 3) prompt user
echo [3/3] Open .env with Notepad and fill in your LLM_API_KEY
echo.
echo   notepad .env
echo.
echo ===========================================================
echo  Setup complete. Run:  run.bat
echo ===========================================================
if defined SMOKE exit /b 0
pause
endlocal
