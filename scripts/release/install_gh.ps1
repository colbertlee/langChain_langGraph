#!/usr/bin/env pwsh
#Requires -Version 5.1
<#
.SYNOPSIS
    一键安装 GitHub CLI (gh) 并完成认证。

.DESCRIPTION
    为 Windows PowerShell 用户提供 gh CLI 的安装与认证入口,与
    scripts/release/install_gh.sh 在功能上等价。

    安装器探测优先级:scoop > choco > winget > 直接下载 MSI (兜底)。

    参考:docs/VERSION_MANAGEMENT.md §4。

.PARAMETER Auth
    安装后立即触发 gh auth login。

.PARAMETER Token
    使用 PAT 直接认证 (跳过交互),需 PAT 含 'repo' scope (SOP §4.1 要求)。

.PARAMETER CheckOnly
    仅检查 gh 与认证状态,不修改系统。供其他脚本作为前置判断。
    退出码:0=就绪 / 3=未安装 / 4=未认证 / 1=其他错误。

.EXAMPLE
    .\install_gh.ps1

.EXAMPLE
    $env:GH_TOKEN = "ghp_xxx"
    .\install_gh.ps1 -Auth -Token $env:GH_TOKEN

.EXAMPLE
    .\install_gh.ps1 -CheckOnly
#>

[CmdletBinding()]
param(
    [switch]$Auth,
    [string]$Token,
    [switch]$CheckOnly,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'
$GH_Min_Version = [version]'2.40.0'
$Repo_Owner = 'colbertlee'
$Repo_Name  = 'langChain_langGraph'

function Log($msg) { Write-Host "[install_gh] $msg" }
function Warn($msg){ Write-Host "[install_gh] WARN: $msg" -ForegroundColor Yellow }
function Fail($msg, [int]$exitCode = 1) {
    Write-Host "[install_gh] FAIL: $msg" -ForegroundColor Red
    exit $exitCode
}

function Test-GhInstalled {
    try {
        $v = (& gh --version 2>$null) | Select-Object -First 1
        if ($LASTEXITCODE -ne 0) { return $false }
        if ($v -match 'gh\s+(\d+\.\d+\.\d+)') {
            $ver = [version]$Matches[1]
            return $true
        }
        return $false
    } catch { return $false }
}

function Get-GhVersion {
    (& gh --version 2>$null) | Select-Object -First 1
}

function Test-GhAuth {
    try {
        $null = gh auth status 2>&1
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Install-ViaScoop  { scoop install gh }
function Install-ViaChoco  { choco install gh --yes }
function Install-ViaWinget { winget install --id GitHub.cli --silent --accept-package-agreements --accept-source-agreements }
function Install-ViaDirectMsi {
    $arch = if ([Environment]::Is64BitOperatingSystem) { 'amd64' } else { '386' }
    $url  = "https://github.com/cli/cli/releases/latest/download/gh_${arch}_msi.zip"
    $tmp  = Join-Path $env:TEMP "gh-install"
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    Log "下载 gh MSI: $url"
    Invoke-WebRequest -Uri $url -OutFile (Join-Path $tmp 'gh.zip') -UseBasicParsing
    Expand-Archive -Path (Join-Path $tmp 'gh.zip') -DestinationPath $tmp -Force
    $msi = Get-ChildItem -Path $tmp -Filter '*.msi' -Recurse | Select-Object -First 1
    if (-not $msi) { Fail "未找到 MSI 安装包" 3 }
    Log "以管理员权限安装: $($msi.FullName)"
    Start-Process msiexec.exe -ArgumentList "/i `"$($msi.FullName)`" /qn" -Verb RunAs -Wait
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
}

function Install-Gh {
    $installer = $env:INSTALLER
    if (-not $installer) {
        if (Get-Command scoop -ErrorAction SilentlyContinue) { $installer = 'scoop' }
        elseif (Get-Command choco -ErrorAction SilentlyContinue) { $installer = 'choco' }
        elseif (Get-Command winget -ErrorAction SilentlyContinue) { $installer = 'winget' }
        else { $installer = 'direct-msi' }
    }
    Log "选择的安装器: $installer"
    switch ($installer) {
        'scoop'      { Install-ViaScoop }
        'choco'      { Install-ViaChoco }
        'winget'     { Install-ViaWinget }
        'direct-msi' { Install-ViaDirectMsi }
        default      { Fail "未知安装器: $installer" 1 }
    }
}

function Auth-WithToken {
    param([string]$t)
    Log "使用 PAT 直接认证 (跳过交互)"
    $t | gh auth login --hostname github.com --with-token
    if ($LASTEXITCODE -ne 0) { Fail "auth login 失败" 4 }
}

function Auth-Interactive {
    Log "启动 gh auth login 交互流程"
    gh auth login --hostname github.com
    if ($LASTEXITCODE -ne 0) { Fail "auth login 失败" 4 }
}

function Test-RepoAccess {
    Log "校验对 $Repo_Owner/$Repo_Name 的访问..."
    gh repo view "$Repo_Owner/$Repo_Name" --json nameWithOwner --jq '.nameWithOwner' | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "无法访问仓库 $Repo_Owner/$Repo_Name (PAT 权限不足?)" 4 }
}

function Show-Usage {
    $lines = @(
        'NAME',
        '    install_gh.ps1 - GitHub CLI 一键安装与认证',
        '',
        'SYNTAX',
        '    .\install_gh.ps1 [-Auth] [-Token <pat>] [-CheckOnly] [-Help]',
        '',
        '示例:',
        '    .\install_gh.ps1',
        '    $env:GH_TOKEN = "ghp_xxx"; .\install_gh.ps1 -Auth -Token $env:GH_TOKEN',
        '    .\install_gh.ps1 -CheckOnly'
    )
    $lines -join "`n"
}

# ============================================================
# Main
# ============================================================
if ($Help) { Show-Usage; exit 0 }

Log "=== gh CLI 安装与认证 ==="
Log "最低版本要求: $GH_Min_Version"
Log "目标仓库: $Repo_Owner/$Repo_Name"

# 仅检查模式
if ($CheckOnly) {
    if (Test-GhInstalled) { Log "OK gh 已安装: $(Get-GhVersion)" } else { Fail "gh 未安装" 3 }
    if (Test-GhAuth) { Log "OK gh 已认证" } else { Fail "gh 未认证" 4 }
    Test-RepoAccess
    Log "OK 可访问 $Repo_Owner/$Repo_Name"
    exit 0
}

# 安装阶段
if (Test-GhInstalled) {
    Log "OK gh 已存在,跳过安装: $(Get-GhVersion)"
} else {
    try {
        Install-Gh
        # 安装后强制刷新 PATH(同时刷新 Machine/User/Process 三层)
        $machine = [System.Environment]::GetEnvironmentVariable('Path','Machine')
        $user    = [System.Environment]::GetEnvironmentVariable('Path','User')
        $env:Path = '' + $machine + ';' + $user
        $env:Path = [System.Environment]::GetEnvironmentVariable('Path','Process')
        if (-not (Test-GhInstalled)) { Fail "安装成功但 gh 仍不可执行 (PATH 未刷新,请重启 shell)" 3 }
        Log "OK 安装成功: $(Get-GhVersion)"
    } catch {
        Fail "安装失败: $($_.Exception.Message)" 3
    }
}

# 认证阶段
if ($Auth) {
    if (-not (Test-GhAuth)) {
        if ($Token) {
            Auth-WithToken -t $Token
        } else {
            Auth-Interactive
        }
    } else {
        Log "OK gh 已处于已认证状态"
    }
    Test-RepoAccess
    Log "OK 对 $Repo_Owner/$Repo_Name 的 API 访问验证通过"
    gh auth status
}

Log "=== 完成 ==="
Log "后续可直接使用:"
Log '  gh pr create --base master --head <branch>'
Log '  python scripts/release/release_cli.py status'