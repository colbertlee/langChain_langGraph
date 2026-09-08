<#
.SYNOPSIS
    Restart the AI Agent backend (app.py / uvicorn) on port 8000.

.DESCRIPTION
    1) Stops any process holding -Port (default 8000) via stop-app.ps1 logic.
    2) Starts `python app.py` in this directory in a new PowerShell window.
       Stdout/stderr are tee'd to logs\app-<timestamp>.log so the GUI window
       can be closed without killing the server.

.PARAMETER Port
    Backend port. Default 8000 (matches ai_agent/api.py default).

.PARAMETER NoStart
    Stop only; do not relaunch. Useful before a manual `python app.py`.

.EXAMPLE
    .\restart-app.ps1
    .\restart-app.ps1 -Port 8000
    .\restart-app.ps1 -NoStart
#>

[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# 1) Stop existing instance, if any.
& (Join-Path $scriptDir 'stop-app.ps1') -Port $Port
if ($LASTEXITCODE -ne 0) {
    Write-Error "[restart-app] Stop step failed (exit $LASTEXITCODE). Aborting."
    exit $LASTEXITCODE
}

if ($NoStart) {
    Write-Host "[restart-app] -NoStart specified; exiting." -ForegroundColor Cyan
    exit 0
}

# 2) Start in a new PowerShell window (non-blocking).
$logDir = Join-Path $scriptDir 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logPath = Join-Path $logDir "app-$stamp.log"

$env:PORT = $Port

$startCmd = "cd `"$scriptDir`"; " +
            "`$env:PORT=$Port; " +
            "python app.py 2>&1 | Tee-Object -FilePath `"$logPath`""

Write-Host "[restart-app] Launching in new window. Logs: $logPath" -ForegroundColor Green
Write-Host "             Open http://127.0.0.1:$Port/api/health to verify."

Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-NoExit", "-Command", $startCmd `
    -WorkingDirectory $scriptDir `
    -WindowStyle Normal

# 3) Wait until /api/health responds (max ~15s).
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}

if ($ok) {
    Write-Host "[restart-app] Backend is up at http://127.0.0.1:$Port/" -ForegroundColor Green
    exit 0
} else {
    Write-Warning "[restart-app] Backend did not respond on /health within 15s. Tail the log: $logPath"
    exit 2
}
