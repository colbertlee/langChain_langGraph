@echo off
REM ============================================================
REM  AI Agent Windows - Restart script
REM  1) Stop any process on port 8000
REM  2) Start `ai-agent.exe web` in a new console window
REM     (or python app.py fallback when exe is missing)
REM ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set PORT=8000
if not "%1"=="" set PORT=%1

echo ===========================================================
echo   AI Agent - restarting backend on port %PORT%
echo ===========================================================

call "%~dp0stop-app.bat" %PORT%
if errorlevel 1 (
    echo [restart] Stop step failed. Aborting.
    pause
    exit /b 1
)

set MPLBACKEND=Agg
set HOST=0.0.0.0
set PORT=%PORT%

if exist "ai-agent.exe" (
    echo [restart] Launching ai-agent.exe web in new window...
    start "AI Agent Web" cmd /k "ai-agent.exe web"
) else (
    echo [restart] ai-agent.exe not found, falling back to `python app.py`.
    where python >nul 2>&1
    if errorlevel 1 (
        echo [restart] python is not on PATH. Install Python 3.10+ first.
        pause
        exit /b 1
    )
    start "AI Agent Web" cmd /k "python app.py"
)

echo [restart] Launched. Waiting for /health ...
powershell -NoProfile -Command ^
  "$ok=$false;" ^
  "for ($i=0; $i -lt 30; $i++) {" ^
  "  try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/health' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop;" ^
  "        if ($r.StatusCode -eq 200) { $ok=$true; break } } catch {};" ^
  "  Start-Sleep -Milliseconds 500" ^
  "};" ^
  "if ($ok) { Write-Host '[restart] Backend is up at http://127.0.0.1:%PORT%/' -ForegroundColor Green }" ^
  "else { Write-Host '[restart] Backend did not respond within 15s. Check the new window for errors.' -ForegroundColor Yellow }"

echo.
echo [restart] Done. Open http://127.0.0.1:%PORT% in your browser.
endlocal
