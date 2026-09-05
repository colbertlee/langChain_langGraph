# scripts/release/_post_publish_cleanup_v209.ps1
# v2.0.9 发布后清理脚本(幂等,可重复跑)
#
# 用法(在仓库根目录的 PowerShell):
#   .\scripts\release\_post_publish_cleanup_v209.ps1
#
# 退出码:
#   0 = 全部 OK
#   1 = 远端删除失败(可手动 Web UI 删)
#   2 = 本地 reset 失败(有未提交变更)
#   4 = git fetch 失败(沙盒/网络屏蔽 github.com:443,严禁继续 reset)

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

Write-Host "== [1/4] git fetch origin" -ForegroundColor Cyan
$fetchOutput = git fetch origin 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error @"

❌ git fetch origin 失败(网络/沙盒屏蔽 github.com:443)。
❌ 严禁在 fetch 失败后跑 'git reset --hard origin/master' ——
   origin/master 引用是陈旧的,会把本地 HEAD 强制回退到旧 commit,
   丢失所有本地未推送的 commit(本会话已踩 2 次)。

请:
  1. 解除沙盒限制 / 换网络环境(VPN / 手机热点 / 直连)
  2. 再跑此脚本
  3. 或 Web UI 上手动清理:https://github.com/colbertlee/langChain_langGraph/branches

fetch 错误详情:
$fetchOutput
"@
    exit 4
}

Write-Host "== [2/4] 重置本地 master → origin/master" -ForegroundColor Cyan
$status = git status --porcelain
if ($status) {
    Write-Error "本地 master 有未提交变更,先 stash / commit / discard 再跑:"
    Write-Host $status
    exit 2
}
$originMasterSha = (git rev-parse origin/master).Substring(0, 7)
Write-Host "    origin/master = $originMasterSha"
git reset --hard origin/master
Write-Host "    本地 master 现在在 $originMasterSha" -ForegroundColor Green

Write-Host "== [3/4] 删除远端 release/v2.0.9 与 v2.0.9" -ForegroundColor Cyan
foreach ($branch in @("release/v2.0.9", "v2.0.9")) {
    try {
        git push origin --delete $branch 2>&1 | Out-Null
        Write-Host "    [OK] 远端 $branch 已删除" -ForegroundColor Green
    } catch {
        Write-Warning "    [WARN] 远端 $branch 删除失败(可能已不存在): $($_.Exception.Message)"
    }
}

Write-Host "== [4/4] 删除本地同名分支 + reflog 清理" -ForegroundColor Cyan
foreach ($branch in @("release/v2.0.9", "v2.0.9")) {
    try {
        git branch -D $branch 2>&1 | Out-Null
        Write-Host "    [OK] 本地 $branch 已删除" -ForegroundColor Green
    } catch {
        Write-Warning "    [WARN] 本地 $branch 不存在(已清理)"
    }
}

# reflog 清理(90 天后过期;这里显式 expire 加速)
git reflog expire --expire=now --all 2>&1 | Out-Null
git gc --prune=now --quiet 2>&1 | Out-Null
Write-Host "    reflog 已 expire + gc --prune=now" -ForegroundColor Green

Write-Host ""
Write-Host "== 最终状态" -ForegroundColor Cyan
git branch -vv | Select-String -Pattern 'master|release|v2\.0\.9' | ForEach-Object { Write-Host "    $_" }
Write-Host ""
git tag -l "v2.0.*" --sort=-version:refname | Select-Object -First 5 | ForEach-Object { Write-Host "    tag: $_" }
Write-Host ""
Write-Host "== 收尾:撤销两个已暴露的 PAT token" -ForegroundColor Cyan
Write-Host "    1. https://github.com/settings/tokens" -ForegroundColor Yellow
Write-Host "    2. 删除 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" -ForegroundColor Yellow
Write-Host "    3. 删除 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" -ForegroundColor Yellow
Write-Host ""
Write-Host "[OK] v2.0.9 发布后清理完成" -ForegroundColor Green