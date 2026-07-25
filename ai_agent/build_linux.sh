#!/usr/bin/env bash
# ============================================================
#  Linux 一键打包脚本（PyInstaller，跨平台 spec）
#  与 Windows 共用同一份 ai_agent.spec
#  用法：在 ai_agent 目录下执行
#         chmod +x build_linux.sh && ./build_linux.sh
# ============================================================
set -e

echo "==> 清理旧的 build / dist"
rm -rf build dist

echo "==> 检查 / 安装 PyInstaller"
if ! python -m PyInstaller --version >/dev/null 2>&1; then
    python -m pip install --upgrade pip
    python -m pip install pyinstaller
fi

echo "==> 准备运行时依赖"
if [ -f requirements.txt ]; then
    python -m pip install -r requirements.txt
fi

echo "==> 触发 PyInstaller 打包（跨平台 spec）"
python -m PyInstaller ai_agent.spec --clean --noconfirm

EXE="dist/ai-agent/ai-agent"
if [ -x "$EXE" ]; then
    echo "==> 打包成功：$EXE"
    file "$EXE" || true
    echo "    （可整体打包分发： tar -czf ai-agent-linux.tar.gz dist/ai-agent）"
else
    echo "!! 打包失败，请检查上方日志"
    exit 1
fi
