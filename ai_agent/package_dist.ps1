# ============================================================
#  Package the two complete distribution bundles
#  Output: dist/ai-agent-windows.zip  +  dist/ai-agent-linux.tar.gz
# ============================================================
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$distDir = Join-Path $PSScriptRoot 'dist'
New-Item -ItemType Directory -Path $distDir -Force | Out-Null

# ---- Windows zip (PowerShell ZipFile) ----
$winZip = Join-Path $distDir 'ai-agent-windows.zip'
if (Test-Path $winZip) { Remove-Item $winZip -Force }
Add-Type -AssemblyName 'System.IO.Compression.FileSystem'
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    (Join-Path $PSScriptRoot 'package\windows'),
    $winZip
)
Write-Host "[OK] $winZip" -ForegroundColor Green
Write-Host ("     size = {0:N1} MB" -f ((Get-Item $winZip).Length / 1MB))

# ---- Linux tar.gz (only build if not already present) ----
# Windows tar cannot handle Linux .so files; we rely on WSL or an out-of-band build
# (e.g. run ./build_linux.sh on a Linux host, or have CI do it).
$linTar = Join-Path $distDir 'ai-agent-linux.tar.gz'
$linuxSrc = Join-Path $PSScriptRoot 'package\linux'
$needsBuild = $true
if (Test-Path $linTar) {
    $existing = (Get-Item $linTar).Length
    $expected = 500 * 1024 * 1024   # 500 MB threshold for "real" Linux tarball
    if ($existing -gt $expected) {
        $needsBuild = $false
        Write-Host "[OK] $linTar (existing, $([math]::Round($existing/1MB,1)) MB)" -ForegroundColor Green
    } else {
        Write-Host "[WARN] existing $linTar is only $([math]::Round($existing/1MB,1)) MB - rebuilding" -ForegroundColor Yellow
        Remove-Item $linTar -Force
    }
}
if ($needsBuild) {
    # try WSL
    $wslOk = $false
    try {
        $wslExe = 'C:\Windows\System32\wsl.exe'
        if (-not (Test-Path $wslExe)) { $wslExe = "$env:SystemRoot\System32\wsl.exe" }
        if (Test-Path $wslExe) {
            $wslLinuxSrc = $linuxSrc -replace '\\', '/' -replace '^([A-Za-z]):', { '/mnt/' + $_.Groups[1].Value.ToLower() }
            $wslLinTar   = $linTar   -replace '\\', '/' -replace '^([A-Za-z]):', { '/mnt/' + $_.Groups[1].Value.ToLower() }
            & $wslExe tar -czf $wslLinTar -C $wslLinuxSrc . 2>$null
            if ((Test-Path $linTar) -and ((Get-Item $linTar).Length -gt 100MB)) {
                $wslOk = $true
                Write-Host "[OK] $linTar (via WSL)" -ForegroundColor Green
            }
        }
    } catch {}
    if (-not $wslOk) {
        Write-Host "[WARN] WSL not available, writing a STUB tarball" -ForegroundColor Yellow
        Write-Host "       (the .so files cannot be packaged by Windows tar)" -ForegroundColor Yellow
        Write-Host "       To get a real tarball: run on Linux or push a v* tag for CI" -ForegroundColor Yellow
        $tmpTar = Join-Path $distDir '_ai-agent-linux.tar'
        if (Test-Path $tmpTar) { Remove-Item $tmpTar -Force }
        & tar -cf $tmpTar -C $linuxSrc '.' 2>$null
        $src = [System.IO.File]::OpenRead($tmpTar)
        $dst = [System.IO.File]::Create($linTar)
        $gz = New-Object System.IO.Compression.GZipStream($dst, [System.IO.Compression.CompressionLevel]::Optimal)
        $src.CopyTo($gz); $gz.Close(); $src.Close(); $dst.Close()
        Remove-Item $tmpTar -Force
    }
}
if (Test-Path $linTar) {
    Write-Host ("     size = {0:N1} MB" -f ((Get-Item $linTar).Length / 1MB))
}
