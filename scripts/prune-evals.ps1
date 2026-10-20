<#
.SYNOPSIS
  归档 evals/runs/ 下"非白名单"的旧 run 目录（仅 Move-Item，不删）。
  设计意图：保留所有数据，但减少工作树噪声。

.DESCRIPTION
  白名单（保留不动）：
    - harness_*            harness/ci/eval 相关
    - rag_*                RAG 维度对比相关
    - *_real_smoke         真实 API 烟测
    - *_smoke*             烟测
    - *_demo               demo
    - *_obs_fix            修复回归
    - *_ci                 CI 触发

  其余视为可归档。
  默认 dry-run；-Apply 才会真正 Move-Item。

.PARAMETER Apply
  真正移动；不带则仅打印计划。

.EXAMPLE
  pwsh -File scripts/prune-evals.ps1                # dry-run
  pwsh -File scripts/prune-evals.ps1 -Apply         # 真归档
#>

[CmdletBinding()]
param(
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$RunsRoot = 'e:\langChain_langGraph\ai_agent\evals\runs'
$Archive  = Join-Path $RunsRoot 'archive'

if (-not (Test-Path $RunsRoot)) {
    throw "runs dir not found: $RunsRoot"
}

$keepPatterns = @(
    '^harness_',
    '^rag_',
    '_real_smoke$',
    '_smoke',
    '_demo$',
    '_obs_fix$',
    '_ci$'
)

function Test-Keep([string]$Name) {
    foreach ($p in $keepPatterns) {
        if ($Name -match $p) { return $true }
    }
    return $false
}

$all = Get-ChildItem -Path $RunsRoot -Directory -ErrorAction SilentlyContinue
if (-not $all) {
    Write-Host '[info] runs 目录为空或不可读' -ForegroundColor DarkGray
    return
}

$toArchive = @()
$toKeep    = @()
foreach ($d in $all) {
    if ($d.Name -eq 'archive') { continue }
    if (Test-Keep $d.Name) { $toKeep += $d } else { $toArchive += $d }
}

Write-Host ("[info] 总目录数：{0}" -f $all.Count)
Write-Host ("[keep] {0} 个" -f $toKeep.Count) -ForegroundColor Green
foreach ($d in $toKeep) {
    Write-Host ("  + {0}" -f $d.Name)
}
Write-Host ("[archive] {0} 个" -f $toArchive.Count) -ForegroundColor Yellow
foreach ($d in $toArchive) {
    Write-Host ("  ~ {0}" -f $d.Name)
}

if ($toArchive.Count -eq 0) {
    Write-Host '[info] 无可归档目录' -ForegroundColor DarkGray
    return
}

if (-not $Apply) {
    Write-Host ''
    Write-Host '[dry-run] 上面是要归档的目录。带 -Apply 真执行 Move-Item。' -ForegroundColor Cyan
    return
}

if (-not (Test-Path $Archive)) {
    New-Item -ItemType Directory -Force -Path $Archive | Out-Null
}

$ok = 0
$fail = 0
foreach ($d in $toArchive) {
    $dest = Join-Path $Archive $d.Name
    if (Test-Path $dest) {
        Write-Host ("[skip] 目标已存在：{0}" -f $dest) -ForegroundColor DarkYellow
        continue
    }
    try {
        Move-Item -LiteralPath $d.FullName -Destination $dest -Force
        Write-Host ("[ok] {0} -> {1}" -f $d.Name, 'archive/')
        $ok++
    }
    catch {
        Write-Host ("[fail] {0}: {1}" -f $d.Name, $_.Exception.Message) -ForegroundColor Red
        $fail++
    }
}
Write-Host ''
Write-Host ("[done] 成功 {0}，失败 {1}，归档目录：{2}" -f $ok, $fail, $Archive)
