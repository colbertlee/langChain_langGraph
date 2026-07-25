#!/usr/bin/env bash
# ============================================================
#  AI Agent Linux 安装 / 初始化脚本
#  用法：./install.sh
# ============================================================
set -e

cd "$(dirname "$0")"

echo "==========================================================="
echo "       AI Agent (Linux) 首次配置"
echo "==========================================================="

# 1) .env
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "[1/3] 已生成 .env（基于 .env.example）"
    else
        echo "[1/3] 警告：未找到 .env.example，请手动创建 .env"
    fi
else
    echo "[1/3] .env 已存在，跳过复制"
fi

# 2) 目录
mkdir -p logs uploads data
echo "[2/3] 已创建 logs / uploads / data 目录"

# 3) 可执行权限
chmod +x ai-agent 2>/dev/null || true
chmod +x run.sh   2>/dev/null || true

echo "[3/3] 请使用编辑器打开 .env，填入 LLM_API_KEY 等参数："
echo "       nano .env   或   vim .env"
echo
echo "==========================================================="
echo "  初始化完成。运行程序请执行： ./run.sh"
echo "==========================================================="
