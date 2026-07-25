# ============================================================
#  Windows 端到端验证脚本
#  1) 跑 PyInstaller
#  2) 拷贝产物到 package\windows
#  3) 启动 smoke 测试
# ============================================================
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host "==> [1/5] 清理" -ForegroundColor Cyan
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

Write-Host "==> [2/5] 安装依赖" -ForegroundColor Cyan
python -m pip install --upgrade pip | Out-Null
python -m pip install -r requirements.txt pyinstaller | Out-Null

Write-Host "==> [3/5] 单元 smoke 测试" -ForegroundColor Cyan
python -c "import agent, app, api; print('imports ok')"
python -c "from agent import AIAgent; a = AIAgent(); print('agent ok, tools=', len(a.get_tools_list()))"

Write-Host "==> [4/5] PyInstaller 打包" -ForegroundColor Cyan
python -m PyInstaller ai_agent.spec --clean --noconfirm

$pkg = "package\windows"
Write-Host "==> [5/5] 拷贝产物到 $pkg" -ForegroundColor Cyan
Copy-Item -Recurse -Force dist\ai-agent\* $pkg\

Write-Host "==> 启动测试" -ForegroundColor Cyan
$env:MPLBACKEND = "Agg"
$env:LLM_API_KEY = "sk-smoke-test"
& "$pkg\ai-agent.exe" --version 2>&1 | Select-Object -First 6
if ($LASTEXITCODE -ne 0) {
    Write-Host "!! 启动失败" -ForegroundColor Red; exit 1
}
Write-Host "==> 全部通过" -ForegroundColor Green
