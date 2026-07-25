param([string]$Here = $PSScriptRoot)
Write-Host "Here=$Here"

# 清理
if (Test-Path "$Here\.env") { Remove-Item "$Here\.env" }
foreach ($d in 'logs','uploads','data') { if (Test-Path "$Here\$d") { Remove-Item -Recurse -Force "$Here\$d" } }

# 写一个 wrapper bat：set SMOKE=1 && install.bat
$wrapper = Join-Path $Here '_run_install.bat'
$bat = @"
@echo off
set SMOKE=1
cd /d "$Here"
call install.bat
exit /b %ERRORLEVEL%
"@
[System.IO.File]::WriteAllText($wrapper, $bat, [System.Text.UTF8Encoding]::new($false))

$outFile = Join-Path $Here '_install_out.txt'
$errFile = Join-Path $Here '_install_err.txt'
if (Test-Path $outFile) { Remove-Item $outFile }
if (Test-Path $errFile) { Remove-Item $errFile }

$proc = Start-Process -FilePath "$env:ComSpec" `
    -ArgumentList @('/d','/c', $wrapper) `
    -NoNewWindow -Wait -PassThru `
    -WorkingDirectory $Here `
    -RedirectStandardOutput $outFile `
    -RedirectStandardError $errFile
Write-Host "exit=$($proc.ExitCode)"

if (Test-Path $outFile) { Write-Host "---- out ----"; Get-Content $outFile }
if (Test-Path $errFile) { Write-Host "---- err ----"; Get-Content $errFile }

Remove-Item $wrapper, $outFile, $errFile -ErrorAction SilentlyContinue

# 验证
if (Test-Path "$Here\.env")   { Write-Host "[PASS] .env created" -ForegroundColor Green } else { Write-Host "[FAIL] .env missing" -ForegroundColor Red }
foreach ($d in 'logs','uploads','data') {
    if (Test-Path "$Here\$d") { Write-Host "[PASS] $d/" -ForegroundColor Green } else { Write-Host "[FAIL] $d missing" -ForegroundColor Red }
}
