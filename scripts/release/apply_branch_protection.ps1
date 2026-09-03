# scripts/release/apply_branch_protection.ps1
# Enable GitHub branch protection for master / release/* branches (Windows PowerShell).
#
# Usage:
#   $env:GH_TOKEN = "ghp_xxx"
#   .\apply_branch_protection.ps1 master
#   .\apply_branch_protection.ps1 release/v2.0.7-cleanup-verified
#
# Prereq:
#   - GH_TOKEN must have repo scope
#   - target branch must already exist
#
# Ref: docs/VERSION_MANAGEMENT.md section 7.5

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Branch
)

$ErrorActionPreference = "Stop"

$Repo = if ($env:GH_REPO) { $env:GH_REPO } else { "colbertlee/langChain_langGraph" }

if (-not $env:GH_TOKEN) {
    Write-Error "GH_TOKEN env var is not set"
    exit 1
}

switch -Wildcard ($Branch) {
    "master" {
        # required_status_checks + restrictions MUST be present (even as null) per GitHub REST API.
        $Payload = @{
            required_status_checks           = $null
            enforce_admins                   = $true
            required_pull_request_reviews    = @{
                dismiss_stale_reviews          = $true
                require_code_owner_reviews     = $false
                required_approving_review_count = 1
                require_last_push_approval     = $true
            }
            restrictions                     = $null
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
            required_status_checks           = $null
            enforce_admins                   = $false
            required_pull_request_reviews    = $null
            restrictions                     = $null
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
        Write-Error "Unsupported branch '$Branch'. Supported: master | release/*"
        exit 1
    }
}

$Json = $Payload | ConvertTo-Json -Depth 10 -Compress
$Json | Set-Content -Path "$env:TEMP\gh_protect_payload.json" -Encoding UTF8 -NoNewline

$Url = "https://api.github.com/repos/$Repo/branches/$Branch/protection"
Write-Host ">>> Applying branch protection to ${Repo}@${Branch}..."

try {
    $Resp = Invoke-RestMethod -Method PUT `
        -Uri $Url `
        -Headers @{
            "Authorization" = "token $env:GH_TOKEN"
            "Accept"        = "application/vnd.github+json"
        } `
        -ContentType "application/json" `
        -Body (Get-Content "$env:TEMP\gh_protect_payload.json" -Raw)

    Write-Host "[OK] Branch protection enabled (HTTP 200)" -ForegroundColor Green
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
    Write-Error "[FAIL] HTTP $Code : $($Body.message)"
    exit 2
}
