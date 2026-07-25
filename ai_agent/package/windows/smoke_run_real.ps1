param([string]$Here)
if (-not $Here) { $Here = (Get-Location).Path }
Write-Host "Here=$Here"
Copy-Item -Force "$Here\.env.example" "$Here\.env"
Add-Content "$Here\.env" "`nLLM_API_KEY=sk-test-dummy`nMPLBACKEND=Agg`nPYTHONIOENCODING=utf-8"
Remove-Item "$Here\_smoke_out.txt","$Here\_smoke_err.txt" -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath "$Here\ai-agent.exe" -ArgumentList @('1>"_smoke_out.txt"','2>"_smoke_err.txt"') -NoNewWindow -PassThru -WorkingDirectory $Here
Start-Sleep -Seconds 8
if (-not $proc.HasExited) { $proc | Stop-Process -Force } else { Write-Host "exited early code=$($proc.ExitCode)" }
Start-Sleep -Seconds 2
Write-Host "---- out ----"
if (Test-Path "$Here\_smoke_out.txt") { Get-Content "$Here\_smoke_out.txt" | Select-Object -First 40 }
Write-Host "---- err ----"
if (Test-Path "$Here\_smoke_err.txt") { Get-Content "$Here\_smoke_err.txt" | Select-Object -First 20 }
$all = (Get-Content "$Here\_smoke_out.txt","$Here\_smoke_err.txt" -ErrorAction SilentlyContinue) -join "`n"
if ($all -match '\[OK\] Agent initialized') { Write-Host "[PASS]" -ForegroundColor Green } else { Write-Host "[FAIL]" -ForegroundColor Red }
Remove-Item "$Here\.env","$Here\_smoke_out.txt","$Here\_smoke_err.txt" -ErrorAction SilentlyContinue