param([string]$Here = $PSScriptRoot)
if (-not $Here) { $Here = Split-Path -Parent $MyInvocation.MyCommand.Path }

# 拷贝 run.bat -> stub 版本
$tmp = Join-Path $Here '_run_smoke.bat'
$content = [System.IO.File]::ReadAllText((Join-Path $Here 'run.bat'), [System.Text.UTF8Encoding]::new($false))
$stub = $content `
    -replace '(?m)^\s*ai-agent\.exe\s*$', 'echo [stub] ai-agent.exe would start here' `
    -replace '(?m)^\s*pause\s*$', 'exit /b 0'
[System.IO.File]::WriteAllText($tmp, $stub, [System.Text.UTF8Encoding]::new($false))

$outFile = Join-Path $Here '_smoke_out.txt'
if (Test-Path $outFile) { Remove-Item $outFile }

$proc = Start-Process -FilePath 'cmd.exe' `
    -ArgumentList '/d','/c', $tmp `
    -NoNewWindow -Wait -PassThru `
    -WorkingDirectory $Here `
    -RedirectStandardOutput $outFile

Write-Host "exit=$($proc.ExitCode)"
if (Test-Path $outFile) {
    $out = Get-Content $outFile -Raw
    if ($out -match '\[stub\]') { Write-Host "[PASS] run.bat stub invoked" -ForegroundColor Green }
    else { Write-Host "[FAIL] stub line not found. Output:" -ForegroundColor Red; Write-Host $out }
}
Remove-Item $tmp, $outFile -ErrorAction SilentlyContinue
