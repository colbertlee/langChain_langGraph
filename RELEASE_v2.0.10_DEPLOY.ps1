<#
.SYNOPSIS
  v2.0.10 本地发布执行脚本（运维在本地有 gh + GH_TOKEN 环境运行）

.DESCRIPTION
  本脚本封装 v2.0.10 release 的全部步骤:
    1. pre-flight check
    2. 创建并 push tag
    3. 创建 GitHub Release（含 release notes）
    4. Gitee 镜像（可选）
    5. post-publish verification

.PARAMETER SkipGitee
  跳过 Gitee 镜像（如果不需要 Gitee mirror）

.PARAMETER DryRun
  仅打印将执行的命令，不实际执行；可逐条确认

.EXAMPLE
  # 标准发布
  .\RELEASE_v2.0.10_DEPLOY.ps1

  # 只发 GitHub 不发 Gitee
  .\RELEASE_v2.0.10_DEPLOY.ps1 -SkipGitee

  # dry-run 看清楚要执行什么
  .\RELEASE_v2.0.10_DEPLOY.ps1 -DryRun

.NOTES
  前置条件:
    1. 已 git clone 此仓库，cd 到仓库根目录
    2. 已 git fetch --tags
    3. 当前分支是 master（或 main），且与 origin 同步
    4. 已设 $env:GH_TOKEN = "<github_personal_access_token>"
       (token 需要 repo scope；或 $env:GITHUB_TOKEN 也可)
    5. release CLI 的依赖已装（urllib/Python stdlib；gh 可选）
#>

param(
    [switch]$SkipGitee,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ==================== 颜色 ====================
function Write-Section($msg) {
    Write-Host ""
    Write-Host "=" * 60 -ForegroundColor Cyan
    Write-Host $msg -ForegroundColor Cyan
    Write-Host "=" * 60 -ForegroundColor Cyan
}

function Write-Step($n, $msg) {
    Write-Host ""
    Write-Host "[$n] $msg" -ForegroundColor Yellow
}

function Run-Cmd($cmd) {
    if ($DryRun) {
        Write-Host "  [DRY-RUN] Would run: $cmd" -ForegroundColor Magenta
        return $null
    }
    Write-Host "  > $cmd" -ForegroundColor Gray
    return Invoke-Expression $cmd
}

# ==================== Pre-flight ====================
Write-Section "v2.0.10 release deploy script"

# === STEP 0.1: 当前目录与分支 ===
Write-Step "0.1" "verify CWD and branch"
Run-Cmd "git rev-parse --abbrev-ref HEAD"
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne "master" -and $branch -ne "main") {
    Write-Error "Current branch is '$branch', expected 'master' or 'main'. Aborting."
    exit 1
}

# === STEP 0.2: 工作树 clean ===
Write-Step "0.2" "verify clean worktree"
Run-Cmd "git status --short"
$status = git status --short
if ($status -and -not $DryRun) {
    Write-Warning "Worktree has uncommitted changes:"
    Write-Host $status
    $confirm = Read-Host "Continue anyway? (y/N)"
    if ($confirm -ne "y") {
        Write-Error "Aborted by user."
        exit 1
    }
}

# === STEP 0.3: 9 commits present ===
Write-Step "0.3" "verify 9 v2.0.10 commits"
Run-Cmd "git log --oneline -9"
$expectedTopCommit = "5122bb9"  # chore: prompts tweak + release runbook + residual report
$topCommit = (git rev-parse --short HEAD).Trim()
if ($topCommit -ne $expectedTopCommit -and -not $DryRun) {
    Write-Warning "Top commit is $topCommit, expected $expectedTopCommit"
    $confirm = Read-Host "Continue anyway? (y/N)"
    if ($confirm -ne "y") {
        Write-Error "Aborted by user."
        exit 1
    }
}

# === STEP 0.4: pytest + playwright（可选，但推荐）===
Write-Step "0.4" "run pytest + playwright (verification, optional)"
$runTests = Read-Host "Run full pytest + playwright before publish? (Y/n)"
if ($runTests -ne "n") {
    Run-Cmd "cd ai_agent; py -3.11 -m pytest tests/ --no-cov -q --timeout=120"
    Run-Cmd "cd web_console; npx playwright test e2e/app.spec.ts --reporter=line"
}

# === STEP 0.5: GH_TOKEN check ===
Write-Step "0.5" "verify GH_TOKEN"
if (-not $env:GH_TOKEN -and -not $env:GITHUB_TOKEN) {
    Write-Error "Neither GH_TOKEN nor GITHUB_TOKEN is set."
    Write-Host "  Export before running:" -ForegroundColor Yellow
    Write-Host '    $env:GH_TOKEN = "ghp_..."' -ForegroundColor Yellow
    exit 1
}
$env:GH_TOKEN = if ($env:GH_TOKEN) { $env:GH_TOKEN } else { $env:GITHUB_TOKEN }
Write-Host "  GH_TOKEN length: $($env:GH_TOKEN.Length) chars" -ForegroundColor Green

# ==================== STEP 1: Push tag + GitHub Release ====================
Write-Section "STEP 1: Push tag + GitHub Release"

Write-Step "1.1" "create annotated tag v2.0.10"
Run-Cmd "git tag -a v2.0.10 -m 'release: v2.0.10'"

Write-Step "1.2" "push tag to origin"
Run-Cmd "git push origin v2.0.10"

Write-Step "1.3" "create GitHub Release via release_cli.py"
Run-Cmd "python scripts/release/release_cli.py github 2.0.10 --title 'v2.0.10 — Cleanup: LEGACY removal (BREAKING)' --body release_notes/v2.0.10.md"

# ==================== STEP 2: Gitee 镜像（可选）===================
if (-not $SkipGitee) {
    Write-Section "STEP 2: Gitee mirror"
    Write-Step "2.1" "create Gitee mirror release"
    Run-Cmd "python scripts/release/release_cli.py gitee 2.0.10 --create-release --body release_notes/v2.0.10.md"
} else {
    Write-Section "STEP 2: Gitee mirror (skipped)"
}

# ==================== STEP 3: post-publish verification ====================
Write-Section "STEP 3: post-publish verification"

Write-Step "3.1" "verify tag on GitHub"
Run-Cmd "git ls-remote origin 'refs/tags/v2.0.10*'"

Write-Step "3.2" "verify Release on GitHub via REST API"
$ghApiUrl = "https://api.github.com/repos/colbertlee/langChain_langGraph/releases/tags/v2.0.10"
$headers = @{
    "Authorization" = "token $env:GH_TOKEN"
    "Accept"        = "application/vnd.github+json"
    "User-Agent"    = "release-deploy-script"
}
if ($DryRun) {
    Write-Host "  [DRY-RUN] Would curl $ghApiUrl with GH_TOKEN" -ForegroundColor Magenta
} else {
    try {
        $resp = Invoke-RestMethod -Uri $ghApiUrl -Headers $headers -Method Get
        Write-Host "  Tag:     $($resp.tag_name)" -ForegroundColor Green
        Write-Host "  Name:    $($resp.name)" -ForegroundColor Green
        Write-Host "  Draft:   $($resp.draft)" -ForegroundColor Green
        Write-Host "  Body:    $($resp.body.Length) chars" -ForegroundColor Green
        Write-Host "  URL:     $($resp.html_url)" -ForegroundColor Green
    } catch {
        Write-Warning "Could not verify release via API: $_"
    }
}

# ==================== STEP 4: 收尾 ====================
Write-Section "STEP 4: Done"

Write-Host @"

🚀 v2.0.10 release 完成！

接下来的动作（人工执行）：
1. 访问 https://github.com/colbertlee/langChain_langGraph/releases/tag/v2.0.10 确认 Release 内容
2. 通知团队
3. 部署到 staging → 跑 smoke test → 部署到 production
4. 监控 24h（参考 docs/STAGING_MONITORING.md）

Slack/邮件公告草稿见 [RELEASE_v2.0.10_RUNBOOK.md §5](RELEASE_v2.0.10_RUNBOOK.md#5-announce)。

回滚方案：[RELEASE_v2.0.10_RUNBOOK.md §1 回滚段](RELEASE_v2.0.10_RUNBOOK.md#1-push-tag--github-release)
"@ -ForegroundColor Cyan
