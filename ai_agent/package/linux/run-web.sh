#!/usr/bin/env bash
# ============================================================
#  AI Agent Linux - Web 服务模式
#  启动后访问 http://127.0.0.1:8000
#  需要在 spec 里把 main.py 换成 app.py 重新打包
# ============================================================
set -e
cd "$(dirname "$0")"

if [ ! -f .env ] && [ -f install.sh ]; then
    ./install.sh
fi

export MPLBACKEND=${MPLBACKEND:-Agg}
export HOST=${HOST:-0.0.0.0}
export PORT=${PORT:-8000}

echo "==========================================================="
echo "  AI Agent (Web) 正在启动..."
echo "  访问 http://127.0.0.1:${PORT}/"
echo "  停止请按 Ctrl+C"
echo "==========================================================="

chmod +x ./ai-agent 2>/dev/null || true
./ai-agent web
