@echo off
REM ============================================================
REM  AI Agent Windows - Stop script
REM  Kills whichever process is bound to port 8000 (the uvicorn
REM  backend started by ai-agent.exe web / python app.py).
REM ============================================================
setlocal
chcp 65001 >nul

set PORT=8000
if not "%1"=="" set PORT=%1

echo ===========================================================
echo   AI Agent - stopping backend on port %PORT% ...
echo ===========================================================

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$conn = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1;" ^
  "if (-not $conn) { Write-Host '[stop] Port %PORT% is free.' -ForegroundColor DarkGray; exit 0 }" ^
  "$pid = $conn.OwningProcess;" ^
  "Write-Host \"[stop] Killing PID $pid holding port %PORT%...\" -ForegroundColor Yellow;" ^
  "Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue;" ^
  "Start-Sleep -Milliseconds 800;" ^
  "$left = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue;" ^
  "if ($left) { Write-Host '[stop] Port still occupied.' -ForegroundColor Red; exit 1 }" ^
  "else { Write-Host '[stop] Port %PORT% released.' -ForegroundColor Green; exit 0 }"

set RC=%errorlevel%
if not "%RC%"=="0" (
    echo.
    echo [stop] Failed. Try running this bat as Administrator.
    pause
)
endlocal & exit /b %RC%
