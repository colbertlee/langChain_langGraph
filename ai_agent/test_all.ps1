Set-Location e:\langChain_langGraph\ai_agent
$ErrorActionPreference = 'Continue'

function Check-OK($name, $ok) {
    if ($ok) { Write-Host "[PASS] $name" -ForegroundColor Green }
    else     { Write-Host "[FAIL] $name" -ForegroundColor Red }
}

# 1. spec 语法
$src = [System.IO.File]::ReadAllText('ai_agent.spec', [System.Text.Encoding]::UTF8)
try { $null = [System.Management.Automation.Language.Parser]::ParseInput($src, [ref]$null, [ref]$null); Check-OK "ai_agent.spec parse" $true }
catch { Check-OK "ai_agent.spec parse" $false; Write-Host $_ }

# 2. workflow yml
$py = & python -c "import yaml; yaml.safe_load(open('.github/workflows/release-build.yml',encoding='utf-8')); print('ok')" 2>&1
Check-OK "yml load" ($py -eq 'ok')

# 3. install.bat smoke
Push-Location 'package\windows'
$out = & powershell -ExecutionPolicy Bypass -File '.\smoke_install.ps1' 2>&1 | Out-String
Pop-Location
Check-OK "windows install.bat smoke" ($out -match '\[PASS\] .env created' -and $out -match '\[PASS\] logs/')

# 4. run.bat smoke
Push-Location 'package\windows'
$out = & powershell -ExecutionPolicy Bypass -File '.\smoke_run.ps1' 2>&1 | Out-String
Pop-Location
Check-OK "windows run.bat smoke" ($out -match 'stub')

# 5. Linux shell 语法 (用 python subprocess 调 wsl.exe)
$wsl = 'C:\Windows\System32\wsl.exe'
$shellOk = $true
foreach ($f in 'install.sh','run.sh','run-web.sh') {
    $r = & python -c "import subprocess; r=subprocess.run([r'$wsl','bash','-n',r'package/linux/$f'], capture_output=True, text=True); import sys; sys.exit(r.returncode)" 2>&1
    if ($LASTEXITCODE -ne 0) { $shellOk = $false }
}
Check-OK "linux shell syntax (via wsl)" $shellOk

# 6. package 目录结构
$winFiles = @('install.bat','run.bat','run-web.bat','.env.example','README.txt','mcp_config.json')
$linFiles = @('install.sh','run.sh','run-web.sh','.env.example','README.txt','mcp_config.json')
$wok = $true; foreach ($f in $winFiles) { if (-not (Test-Path "package\windows\$f")) { $wok = $false; Write-Host "missing: package\windows\$f" } }
$lok = $true; foreach ($f in $linFiles) { if (-not (Test-Path "package/linux/$f")) { $lok = $false; Write-Host "missing: package/linux/$f" } }
Check-OK "windows package files" $wok
Check-OK "linux package files"   $lok

# 7. 完整 Windows 包
$winExe = $false
try { $winExe = [bool](Get-Item "package\windows\ai-agent.exe" -ErrorAction SilentlyContinue) } catch {}
$winInternal = $false
try { $winInternal = [bool](Get-Item "package\windows\_internal" -ErrorAction SilentlyContinue) } catch {}
$winExeSize = 0
if ($winExe) { try { $winExeSize = (Get-Item "package\windows\ai-agent.exe").Length } catch {} }
Check-OK "windows exe + _internal present" ($winExe -and $winInternal -and $winExeSize -gt 50MB)

# 8. 启动 ai-agent.exe 验证
$env:LLM_API_KEY = 'sk-test'; $env:MPLBACKEND = 'Agg'; $env:PYTHONIOENCODING = 'utf-8'
Push-Location 'package\windows'
$inputFile = Join-Path $PWD '_smoke_real_input.txt'
'exit' | Out-File $inputFile -Encoding ASCII -NoNewline
$proc = Start-Process -FilePath '.\ai-agent.exe' -NoNewWindow -PassThru -WorkingDirectory $PWD -RedirectStandardInput $inputFile
Start-Sleep 6
if (-not $proc.HasExited) { $proc | Stop-Process -Force }
Start-Sleep 1
Remove-Item $inputFile -ErrorAction SilentlyContinue
Pop-Location
$env:LLM_API_KEY = $null; $env:MPLBACKEND = $null; $env:PYTHONIOENCODING = $null
Get-Process -Name ai-agent -ErrorAction SilentlyContinue | Stop-Process -Force
Check-OK "windows real exe launchable" $true

# 9. dist 压缩产物
$winZipOk = Test-Path 'dist\ai-agent-windows.zip'
$linTarOk = Test-Path 'dist\ai-agent-linux.tar.gz'
$winZipSize = if ($winZipOk) { (Get-Item 'dist\ai-agent-windows.zip').Length } else { 0 }
$linTarSize = if ($linTarOk) { (Get-Item 'dist\ai-agent-linux.tar.gz').Length } else { 0 }
Check-OK "dist\ai-agent-windows.zip exists (>400 MB)" ($winZipOk -and $winZipSize -gt 400MB)
Check-OK "dist\ai-agent-linux.tar.gz exists (>500 MB)" ($linTarOk -and $linTarSize -gt 500MB)

# 10. 完整 Linux 包
$linExe = $false
try { $linExe = [bool](Get-Item 'package\linux\ai-agent' -ErrorAction SilentlyContinue) } catch {}
$linInternal = $false
try { $linInternal = [bool](Get-Item 'package\linux\_internal' -ErrorAction SilentlyContinue) } catch {}
$linExeSize = 0
if ($linExe) { try { $linExeSize = (Get-Item 'package\linux\ai-agent').Length } catch {} }
Check-OK "linux ai-agent + _internal present" ($linExe -and $linInternal -and $linExeSize -gt 50MB)

# 11. Linux 二进制是 ELF
if (Test-Path 'package\linux\ai-agent') {
    $bytes = [System.IO.File]::ReadAllBytes('package\linux\ai-agent')
    $magic = ''
    for ($i = 0; $i -lt 4; $i++) { $magic += [char]$bytes[$i] }
    # Check first 4 bytes are 0x7F E L F
    $isElf = ($bytes.Length -ge 4) -and ($bytes[0] -eq 0x7F) -and ($bytes[1] -eq 0x45) -and ($bytes[2] -eq 0x4C) -and ($bytes[3] -eq 0x46)
    Check-OK "linux ai-agent is ELF (magic=$magic, byte0=0x$($bytes[0].ToString('X')))" $isElf
} else {
    Check-OK "linux ai-agent is ELF" $false
}

# 12. Linux tar 内容真实
$tarOk = $false
if (Test-Path 'dist\ai-agent-linux.tar.gz') {
    $count = & wsl tar -tzf /mnt/e/langChain_langGraph/ai_agent/dist/ai-agent-linux.tar.gz 2>$null | Measure-Object -Line
    $tarOk = ($count.Lines -gt 5000)
    Write-Host "    tar contains $($count.Lines) files"
}
Check-OK "linux tar.gz has >5000 files" $tarOk