# scripts/release/apply_branch_protection.ps1
# 为 master / release/* 分支一键启用 GitHub 分支保护规则(Windows PowerShell 版)。
#
# 用法:
#   $env:GH_TOKEN = "ghp_xxx"
#   .\apply_branch_protection.ps1 master
#   .\apply_branch_protection.ps1 release/v2.0.7-cleanup-verified
#
# 前置条件:
#   - GH_TOKEN 需包含 repo scope
#   - 目标分支已存在并与本地一致
#
# 参考:docs/VERSION_MANAGEMENT.md §7.5

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Branch
)

$ErrorActionPreference = "Stop"

$Repo = if ($env:GH_REPO) { $env:GH_REPO } else { "colbertlee/langChain_langGraph" }

if (-not $env:GH_TOKEN) {
    Write-Error "错误:GH_TOKEN 环境变量未设置"
    exit 1
}

# 根据分支名选择 payload
switch -Wildcard ($Branch) {
    "master" {
        $Payload = @{
            enforce_admins                   = $true
            required_pull_request_reviews    = @{
                dismiss_stale_reviews          = $true
                require_code_owner_reviews     = $false
                required_approving_review_count = 1
                require_last_push_approval     = $true
            }
            required_linear_history          = $true
            allow_force_pushes               = $false
            allow_deletions                  = $false
            block_creations                  = $false
            required_conversation_resolution = $true
            lock_branch                      = $false
            allow_fork_syncing               = $false
        }
    }
    "release/*" {
        $Payload = @{
            enforce_admins                   = $false
            required_pull_request_reviews    = $null
            required_linear_history          = $false
            allow_force_pushes               = $false
            allow_deletions                  = $false
            block_creations                  = $false
            required_conversation_resolution = $false
            lock_branch                      = $false
            allow_fork_syncing               = $false
        }
    }
    default {
        Write-Error "错误:不支持的分支 '$Branch'`n支持的模式:master | release/*"
        exit 1
    }
}

$Json = $Payload | ConvertTo-Json -Depth 10 -Compress
$Json | Set-Content -Path "$env:TEMP\gh_protect_payload.json" -Encoding UTF8 -NoNewline

$Url = "https://api.github.com/repos/$Repo/branches/$Branch/protection"
Write-Host ">>> 正在为 ${Repo}@${Branch} 应用分支保护..."

try {
    $Resp = Invoke-RestMethod -Method PUT `
        -Uri $Url `
        -Headers @{
            "Authorization" = "token $env:GH_TOKEN"
            "Accept"        = "application/vnd.github+json"
        } `
        -ContentType "application/json" `
        -Body (Get-Content "$env:TEMP\gh_protect_payload.json" -Raw)

    Write-Host "✓ 分支保护已启用 (HTTP 200)" -ForegroundColor Green
    Write-Host "  enforce_admins:           $($Resp.enforce_admins.enabled)"
    Write-Host "  required_linear_history:  $($Resp.required_linear_history.enabled)"
    Write-Host "  allow_force_pushes:       $($Resp.allow_force_pushes.enabled)"
    Write-Host "  allow_deletions:          $($Resp.allow_deletions.enabled)"
    if ($Resp.required_pull_request_reviews) {
        Write-Host "  required_reviews:         $($Resp.required_pull_request_reviews.required_approving_review_count)"
    }
}
catch {
    $Code = $_.Exception.Response.StatusCode.value__
    $Body = $_.Exception.Response | ConvertFrom-Json -ErrorAction SilentlyContinue
    Write-Error "✗ 启用失败 (HTTP $Code): $($Body.message)"
    exit 2
}
