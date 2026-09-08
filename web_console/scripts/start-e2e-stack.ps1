<#
.SYNOPSIS
    前端 + 后端 E2E 联调栈一键编排（Windows PowerShell 版本）。

.DESCRIPTION
    1. 后台启动前端 Vite dev server (5173) - 端口空闲才启动
    2. 后台启动后端 uvicorn app:app       (8000) - 端口空闲才启动
    3. 轮询等待两端端口就绪（最多 E2E_TIMEOUT 秒）
    4. 自动运行沙箱 E2E 脚本 web_console\e2e_no_browser.mjs
    5. 测试结束后优雅清理：先 Close-Gracefully，5s 后 Stop-Force

    日志写到 $env:TEMP\e2e-stack-{frontend,backend}.log
    通过 .pid 文件跟踪子进程 PID。

.PARAMETER FrontendPort
    前端 Vite 端口，默认 5173

.PARAMETER BackendPort
    后端 uvicorn 端口，默认 8000

.PARAMETER E2ETimeout
    端口就绪总超时（秒），默认 90

.PARAMETER KeepRunning
    脚本退出后保留后台服务（默认清理）

.PARAMETER SkipFrontend
    跳过前端启动与就绪等待

.PARAMETER SkipBackend
    跳过后端启动与就绪等待

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start-e2e-stack.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start-e2e-stack.ps1 -KeepRunning

.NOTES
    Exit codes:
      0  E2E 全部 PASS
      1  E2E 至少 1 项 FAIL
      2  端口就绪超时
      3  依赖缺失（node / npm / python / uvicorn）
#>

[CmdletBinding()]
param(
    [int]$FrontendPort = 5173,
    [int]$BackendPort  = 8000,
    [int]$E2ETimeout   = 90,
    [switch]$KeepRunning,
    [switch]$SkipFrontend,
    [switch]$SkipBackend
)

# ---- 0. 路径 ----
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot    = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$FrontendDir = Join-Path $RepoRoot "web_console"
$BackendDir  = Join-Path $RepoRoot "ai_agent"
$E2EScript   = Join-Path $FrontendDir "e2e_no_browser.mjs"

$LogDir          = $env:TEMP
$FrontendLog     = Join-Path $LogDir "e2e-stack-frontend.log"
$BackendLog      = Join-Path $LogDir "e2e-stack-backend.log"
$FrontendPidFile = Join-Path $LogDir "e2e-stack-frontend.pid"
$BackendPidFile  = Join-Path $LogDir "e2e-stack-backend.pid"

# 子进程（trap 清理）
$FrontendProc = $null
$BackendProc  = $null
$ExitCode     = 0

# ---- 1. 颜色输出 ----
function Info($msg)  { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Pass($msg)  { Write-Host "[PASS] $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Fail($msg)  { Write-Host "[FAIL] $msg" -ForegroundColor Red }

# ---- 2. 工具函数 ----
function Test-Port {
    param([string]$Host, [int]$Port)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect($Host, $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(2000, $false)
        if ($ok) {
            $client.EndConnect($iar)
            $client.Close()
            return $true
        }
        $client.Close()
        return $false
    } catch {
        return $false
    }
}

function Wait-Port {
    param([string]$Label, [string]$Host, [int]$Port)
    $deadline = (Get-Date).AddSeconds($E2ETimeout)
    Info "等待 $Label 端口 $Host`:$Port 就绪…"
    while ((Get-Date) -lt $deadline) {
        if (Test-Port -Host $Host -Port $Port) {
            Pass "$Label 端口就绪 ($Host`:$Port)"
            return $true
        }
        Start-Sleep -Seconds 1
    }
    Fail "$Label 端口在 ${E2ETimeout}s 内未就绪 ($Host`:$Port)"
    return $false
}

function Stop-Proc {
    param([System.Diagnostics.Process]$Proc, [string]$Sig)
    if ($null -ne $Proc -and -not $Proc.HasExited) {
        Info "停止 $($Proc.ProcessName) (pid=$($Proc.Id), SIG$Sig)"
        try {
            if ($Sig -eq "KILL") { $Proc.Kill() } else { $Proc.CloseMainWindow() | Out-Null; $Proc.Refresh() }
            if (-not $Proc.WaitForExit(5000)) { $Proc.Kill() }
        } catch {
            Warn "停止进程失败: $_"
        }
    }
}

# ---- 3. Trap 清理 ----
trap {
    if ($KeepRunning) {
        Info "KEEP_RUNNING：保留服务"
    } else {
        Stop-Proc -Proc $FrontendProc -Sig "TERM"
        Start-Sleep -Seconds 2
        Stop-Proc -Proc $FrontendProc -Sig "KILL"
        Stop-Proc -Proc $BackendProc  -Sig "TERM"
        Start-Sleep -Seconds 2
        Stop-Proc -Proc $BackendProc  -Sig "KILL"
        if ($ExitCode -eq 0) {
            Pass "E2E 栈已清理（日志: $FrontendLog / $BackendLog）"
        } else {
            Warn "E2E 栈已清理（退出码=$ExitCode）"
        }
    }
}

# ---- 4. 前置检查 ----
Info "仓库根目录: $RepoRoot"
Info "前端目录: $FrontendDir (port=$FrontendPort)"
Info "后端目录: $BackendDir (port=$BackendPort)"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Fail "node 未安装"; exit 3
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Fail "npm 未安装"; exit 3
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail "python 未安装"; exit 3
}

if (-not (Test-Path $E2EScript)) {
    Fail "E2E 脚本不存在: $E2EScript"; exit 3
}

# ---- 5. 启动前端 ----
if (-not $SkipFrontend) {
    if (Test-Port -Host "127.0.0.1" -Port $FrontendPort) {
        Pass "前端端口 $FrontendPort 已被占用，跳过启动"
    } else {
        if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
            Info "前端未安装依赖，执行 npm ci…"
            Push-Location $FrontendDir
            try { npm ci | Out-Null } catch { Fail "npm ci 失败"; exit 3 }
            Pop-Location
        }
        Info "启动前端: npm run dev (日志: $FrontendLog)"
        Push-Location $FrontendDir
        $FrontendProc = Start-Process -FilePath "npm.cmd" `
            -ArgumentList "run","dev","--","--port",$FrontendPort `
            -RedirectStandardOutput $FrontendLog `
            -RedirectStandardError  $FrontendLog `
            -WindowStyle Hidden `
            -PassThru
        Pop-Location
        # 备用 PID 文件（PowerShell Process 跟踪已够，但兼容 bash 脚本）
        Set-Content -Path $FrontendPidFile -Value $FrontendProc.Id -Encoding ASCII

        if (-not (Wait-Port -Label "frontend" -Host "127.0.0.1" -Port $FrontendPort)) {
            Fail "前端启动失败，尾部日志："
            Get-Content $FrontendLog -Tail 50 | ForEach-Object { Write-Host $_ }
            exit 2
        }
    }
} else {
    Info "SkipFrontend=1，跳过前端"
}

# ---- 6. 启动后端 ----
if (-not $SkipBackend) {
    if (Test-Port -Host "127.0.0.1" -Port $BackendPort) {
        Pass "后端端口 $BackendPort 已被占用，跳过启动"
    } else {
        Info "启动后端: uvicorn app:app (日志: $BackendLog)"
        Push-Location $BackendDir
        $BackendProc = Start-Process -FilePath "python" `
            -ArgumentList "-m","uvicorn","app:app","--host","127.0.0.1","--port",$BackendPort,"--log-level","info" `
            -RedirectStandardOutput $BackendLog `
            -RedirectStandardError  $BackendLog `
            -WindowStyle Hidden `
            -PassThru
        Pop-Location
        Set-Content -Path $BackendPidFile -Value $BackendProc.Id -Encoding ASCII

        if (-not (Wait-Port -Label "backend" -Host "127.0.0.1" -Port $BackendPort)) {
            Fail "后端启动失败，尾部日志："
            Get-Content $BackendLog -Tail 50 | ForEach-Object { Write-Host $_ }
            exit 2
        }
    }
} else {
    Info "SkipBackend=1，跳过后端"
}

# ---- 7. 运行 E2E ----
Info "运行 E2E: node $E2EScript"
Push-Location $FrontendDir
try {
    & node $E2EScript
    $ExitCode = $LASTEXITCODE
} catch {
    Fail "E2E 异常: $_"
    $ExitCode = 1
} finally {
    Pop-Location
}

if ($ExitCode -eq 0) {
    Pass "E2E 全部通过"
} else {
    Fail "E2E 退出码=$ExitCode（详见上方日志）"
}

exit $ExitCode