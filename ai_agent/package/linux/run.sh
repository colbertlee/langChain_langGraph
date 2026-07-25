#!/usr/bin/env bash
# ============================================================
#  AI Agent Linux 启动脚本
#  用法：./run.sh
# ============================================================
set -e
cd "$(dirname "$0")"

# matplotlib 无显示环境兼容
export MPLBACKEND=${MPLBACKEND:-Agg}

echo "==========================================================="
echo "  AI Agent 正在启动..."
echo "  退出请输入 exit 或按 Ctrl+C"
echo "==========================================================="

if [ ! -x ./ai-agent ]; then
    chmod +x ./ai-agent
fi

./ai-agent
