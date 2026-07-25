#!/usr/bin/env bash
# ============================================================
#  Linux 端到端验证脚本
# ============================================================
set -e
cd "$(dirname "$0")"

echo "==> [1/5] 清理"
rm -rf build dist

echo "==> [2/5] 安装依赖"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

echo "==> [3/5] 单元 smoke 测试"
python -c "import agent, app, api; print('imports ok')"
python -c "from agent import AIAgent; a = AIAgent(); print('agent ok, tools=', len(a.get_tools_list()))"

echo "==> [4/5] PyInstaller 打包"
python -m PyInstaller ai_agent.spec --clean --noconfirm

PKG="package/linux"
echo "==> [5/5] 拷贝产物到 $PKG"
cp -r dist/ai-agent/. "$PKG/"
chmod +x "$PKG/ai-agent" "$PKG/install.sh" "$PKG/run.sh"

echo "==> 启动测试"
export MPLBACKEND=Agg
export LLM_API_KEY="sk-smoke-test"
"$PKG/ai-agent" --version 2>&1 | head -n 6

echo "==> 全部通过"
