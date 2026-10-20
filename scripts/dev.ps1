<#
.SYNOPSIS
  开发期常用命令别名（audit / test-fast / lint-staged）。不动既有 build_*.ps1。

.DESCRIPTION
  设计意图：
  - 现有 `build_*.ps1` / `build_*.sh` 负责打包/分发，本脚本只覆盖"开发循环"动作。
  - 不引入新依赖：复用本仓库已有的 python / ruff / pytest / git。
  - 命令找不到时给出友好提示，不假装执行成功。
  - 所有动作幂等，可重复跑。

.PARAMETER Command
  audit | test-fast | lint-staged | build-pack | all
  省略时显示帮助。

.EXAMPLE
  pwsh -File scripts/dev.ps1 -Command audit
  pwsh -File scripts/dev.ps1 -Command test-fast
  pwsh -File scripts/dev.ps1 -Command lint-staged
  pwsh -File scripts/dev.ps1 -Command build-pack
  pwsh -File scripts/dev.ps1 -Command all
#>

[CmdletBinding()]
param(
    [ValidateSet('audit', 'test-fast', 'lint-staged', 'build-pack', 'all', 'help')]
    [string]$Command = 'help'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = 'e:\langChain_langGraph'
$OutDir      = Join-Path $ProjectRoot 'output\2026-10-20'

function Write-Banner([string]$Title) {
    Write-Host ''
    Write-Host "=== $Title ===" -ForegroundColor Cyan
}

function Test-Tool([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    return [bool]$cmd
}

function Invoke-Audit {
    Write-Banner 'audit'
    if (-not (Test-Path $OutDir)) {
        New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    }
    Push-Location $ProjectRoot
    try {
        python "$ProjectRoot\scripts\audit-deps-once.py"
        python "$ProjectRoot\scripts\audit-evals-once.py"
        python "$ProjectRoot\scripts\audit-b1-once.py"
        pwsh -NoProfile -File "$ProjectRoot\scripts\audit-activity-once.ps1"
    }
    finally {
        Pop-Location
    }
    Write-Host ("[ok] 报告落地：{0}" -f $OutDir) -ForegroundColor Green
}

function Invoke-TestFast {
    Write-Banner 'test-fast'
    if (-not (Test-Tool 'pytest')) {
        Write-Host '[warn] pytest 不可用，跳过测试。请先 `pip install -r ai_agent/requirements-dev.txt`' -ForegroundColor Yellow
        return
    }
    Push-Location "$ProjectRoot\ai_agent"
    try {
        # 跑快集：跳过 slow / integration，仅覆盖核心路径
        python -m pytest -q -m "not slow and not integration" --no-cov -x --tb=short
    }
    finally {
        Pop-Location
    }
}

function Invoke-LintStaged {
    Write-Banner 'lint-staged'
    if (-not (Test-Tool 'ruff')) {
        Write-Host '[warn] ruff 不可用，跳过 lint。请先 `pip install -r ai_agent/requirements-dev.txt`' -ForegroundColor Yellow
        return
    }
    Push-Location $ProjectRoot
    try {
        # 仅 lint 暂存变更的 .py；空集时给出空跑提示
        $staged = git diff --cached --name-only --diff-filter=ACMR | Where-Object { $_ -match '\.py$' }
        if (-not $staged) {
            Write-Host '[info] 当前无暂存 .py，跳过 lint-staged' -ForegroundColor DarkGray
            return
        }
        ruff check $staged
    }
    finally {
        Pop-Location
    }
}

function Invoke-BuildPack {
    Write-Banner 'build-pack'
    if (-not (Test-Path "$ProjectRoot\scripts\build-prompt-pack.ps1")) {
        Write-Host '[error] scripts/build-prompt-pack.ps1 不存在' -ForegroundColor Red
        return
    }
    Push-Location $ProjectRoot
    try {
        pwsh -NoProfile -File "$ProjectRoot\scripts\build-prompt-pack.ps1"
    }
    finally {
        Pop-Location
    }
}

function Show-Help {
    Write-Host '用法: pwsh -File scripts/dev.ps1 -Command <cmd>'
    Write-Host ''
    Write-Host '命令:'
    Write-Host '  audit        跑四个摸排脚本，输出到 output/<date>/audit-*.md'
    Write-Host '  test-fast    跑 pytest 核心集（-m "not slow and not integration"）'
    Write-Host '  lint-staged  ruff 检查暂存 .py（无暂存时空跑）'
    Write-Host '  build-pack   调 scripts/build-prompt-pack.ps1 重建 PROMPT-PACK §2'
    Write-Host '  all          按 audit → test-fast → lint-staged → build-pack 顺序跑'
    Write-Host '  help         显示本帮助'
}

switch ($Command) {
    'audit'       { Invoke-Audit }
    'test-fast'   { Invoke-TestFast }
    'lint-staged' { Invoke-LintStaged }
    'build-pack'  { Invoke-BuildPack }
    'all' {
        Invoke-Audit
        Invoke-TestFast
        Invoke-LintStaged
        Invoke-BuildPack
    }
    'help'        { Show-Help }
    default       { Show-Help }
}
