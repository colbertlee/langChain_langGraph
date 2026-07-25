# 生成 Playwright 视觉回归 baseline (PowerShell 版本)
#
# 用法：
#   pwsh scripts/generate-visual-baseline.ps1
#   $env:E2E_BASE_URL='https://staging'; pwsh scripts/generate-visual-baseline.ps1
#
# 效果：删除旧 baseline → 跑 visual.spec.ts → 产生新 baseline → 提示提交

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

Write-Host '🎨 Playwright visual baseline generation' -ForegroundColor Cyan
Write-Host '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━' -ForegroundColor Cyan

# 1. 检查 npx
if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
  Write-Host '❌ npx not found. Install Node.js 18+ first.' -ForegroundColor Red
  exit 1
}

# 2. 检查 Chromium
$cacheDir = Join-Path $env:USERPROFILE '.cache\ms-playwright'
if (-not (Test-Path $cacheDir)) {
  Write-Host '📦 Installing Chromium for Playwright...' -ForegroundColor Yellow
  npm run e2e:install
}

# 3. 删除旧 baseline
$snapshotDir = 'e2e\visual.spec.ts-snapshots'
if (Test-Path $snapshotDir) {
  Write-Host "🗑️  Removing old baseline at $snapshotDir\" -ForegroundColor Yellow
  Remove-Item -Recurse -Force $snapshotDir
}

# 4. 跑 visual.spec.ts 生成 baseline
Write-Host '📸 Generating baseline snapshots...' -ForegroundColor Cyan
Write-Host ''
$env:CI = '1'
npx playwright test visual.spec.ts --update-snapshots

Write-Host ''
Write-Host '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━' -ForegroundColor Cyan

if (Test-Path $snapshotDir) {
  $count = (Get-ChildItem -Path $snapshotDir -Filter '*.png' -Recurse | Measure-Object).Count
  Write-Host "✅ Generated $count baseline PNG file(s)." -ForegroundColor Green
  Write-Host ''
  Write-Host 'Next steps:' -ForegroundColor Yellow
  Write-Host "  git add $snapshotDir/"
  Write-Host "  git commit -m 'test: add visual regression baseline'"
  Write-Host '  git push'
} else {
  Write-Host '❌ Baseline directory not created. Check test output above.' -ForegroundColor Red
  exit 1
}
