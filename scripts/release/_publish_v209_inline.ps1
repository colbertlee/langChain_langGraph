# scripts/release/_publish_v209_inline.ps1
# 一次性脚本:用 GH_TOKEN 直接调 GitHub REST API 创建 Release v2.0.9,
# 跳过 git push(已经在 release/v2.0.9 分支全量推到 GitHub,target_commitish 指向 commit SHA)。
#
# 用法(在本仓库根目录的 PowerShell 里执行):
#   $env:GH_TOKEN = "ghp_xxx"
#   .\scripts\release\_publish_v209_inline.ps1
#   $env:GH_TOKEN = $null        # 用完立刻清空

[CmdletBinding()]
param()

if (-not $env:GH_TOKEN) {
    Write-Error "GH_TOKEN env var is not set"
    exit 1
}

$REPO = "colbertlee/langChain_langGraph"
$TAG = "v2.0.9"
$TARGET = "9928ff1c7ba81fdfed85610ceff717d59d19144f"
$TITLE = "AI Agent v2.0.9 — Harness + v2.0 slim runtime"
$NOTES = Get-Content "release_notes/v2.0.9.md" -Raw -Encoding UTF8

$payload = @{
    tag_name         = $TAG
    target_commitish = $TARGET
    name             = $TITLE
    body             = $NOTES
    draft            = $false
    prerelease       = $false
} | ConvertTo-Json -Depth 10

Write-Host "==> POST https://api.github.com/repos/$REPO/releases" -ForegroundColor Cyan

try {
    $resp = Invoke-RestMethod -Method POST `
        -Uri "https://api.github.com/repos/$REPO/releases" `
        -Headers @{
            "Authorization" = "token $env:GH_TOKEN"
            "Accept"        = "application/vnd.github+json"
            "User-Agent"    = "release-publisher"
        } `
        -ContentType "application/json" `
        -Body $payload
    Write-Host "[OK] Release created: $($resp.html_url)" -ForegroundColor Green
    Write-Host "     tag_name: $($resp.tag_name)"
    Write-Host "     target_commitish: $($resp.target_commitish)"
    Write-Host "     name: $($resp.name)"
}
catch {
    $code = $_.Exception.Response.StatusCode.value__
    $msg = ($_.Exception.Response | ConvertFrom-Json -ErrorAction SilentlyContinue).message
    if (-not $msg) { $msg = $_.Exception.Message }
    Write-Error "[FAIL] HTTP $code : $msg"
    exit 2
}