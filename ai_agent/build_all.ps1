# ============================================================
#  在 Windows 上交叉验证：用 Docker 起一个 ubuntu 容器打 Linux 包
#  （可选；不强制要求）
# ============================================================
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host "==> 在 Docker 内打 Linux 包" -ForegroundColor Cyan
docker run --rm -v "${PWD}:/work" -w /work/ai_agent python:3.11-slim bash -c "
  apt-get update &&
  apt-get install -y --no-install-recommends binutils patchelf libpython3-dev &&
  pip install --no-cache-dir -r requirements.txt pyinstaller &&
  pyinstaller ai_agent.spec --clean --noconfirm &&
  cp -r dist/ai-agent/. package/linux/ &&
  chmod +x package/linux/ai-agent package/linux/install.sh package/linux/run.sh &&
  echo 'Linux build OK'
"
