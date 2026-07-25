# ============================================================
#  Windows 一键打包脚本（PyInstaller，跨平台 spec）
#  用法：在 ai_agent 目录下执行
#        powershell -ExecutionPolicy Bypass -File build_windows.ps1
# ============================================================
$ErrorActionPreference = 'Stop'

Write-Host "==> 清理旧的 build / dist" -ForegroundColor Cyan
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

Write-Host "==> 检查 / 安装 PyInstaller" -ForegroundColor Cyan
python -m PyInstaller --version 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    python -m pip install --upgrade pip
    python -m pip install pyinstaller
}

Write-Host "==> 准备运行时依赖" -ForegroundColor Cyan
if (Test-Path requirements.txt) {
    python -m pip install -r requirements.txt
}

Write-Host "==> 触发 PyInstaller 打包（跨平台 spec）" -ForegroundColor Cyan
python -m PyInstaller ai_agent.spec --clean --noconfirm

$exe = "dist\ai-agent\ai-agent.exe"
if (Test-Path $exe) {
    Write-Host "==> 打包成功：$exe" -ForegroundColor Green
    & $exe --help 2>$null | Out-Null
    Write-Host "    （已生成 dist\ai-agent\ 完整目录，可整体压缩分发）" -ForegroundColor Green
} else {
    Write-Host "!! 打包失败，请检查上方日志" -ForegroundColor Red
    exit 1
}
