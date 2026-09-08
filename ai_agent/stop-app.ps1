<#
.SYNOPSIS
    Stop the AI Agent backend (app.py / uvicorn) bound to port 8000.

.DESCRIPTION
    Finds the process owning local port 8000 (default) or -Port, prints its PID +
    command line, then force-terminates it. Idempotent: no-op when the port is free.

.EXAMPLE
    .\stop-app.ps1
    .\stop-app.ps1 -Port 8000
#>

[CmdletBinding()]
param(
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'

function Get-PortOwner {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $conn) { return $null }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
    [pscustomobject]@{
        Pid     = $conn.OwningProcess
        Command = if ($proc) { $proc.CommandLine } else { '(unknown)' }
    }
}

$owner = Get-PortOwner -Port $Port
if (-not $owner) {
    Write-Host "[stop-app] Port $Port is free. Nothing to do." -ForegroundColor DarkGray
    exit 0
}

Write-Host "[stop-app] Port $Port is held by PID $($owner.Pid):" -ForegroundColor Yellow
Write-Host "    $($owner.Command)"
Write-Host "[stop-app] Stopping PID $($owner.Pid)..." -ForegroundColor Yellow

try {
    Stop-Process -Id $owner.Pid -Force -ErrorAction Stop
} catch {
    Write-Error "[stop-app] Failed to stop PID $($owner.Pid): $_"
    exit 1
}

# Wait briefly for the socket to be released.
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Milliseconds 300
    if (-not (Get-PortOwner -Port $Port)) {
        Write-Host "[stop-app] Port $Port released." -ForegroundColor Green
        exit 0
    }
}

Write-Warning "[stop-app] Port $Port still occupied after 3s. Check PID $($owner.Pid) manually."
exit 1
