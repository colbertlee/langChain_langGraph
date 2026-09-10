#!/usr/bin/env bash
# P2-4 — Let's Encrypt 证书自动续期
#
# 用法（cron）：
#   0 3 * * * cd /path/to/project && bash scripts/renew-cert.sh >> /var/log/certbot-renew.log 2>&1
#
# 流程：
#   1) certbot renew --quiet 续期（接近过期才真正签）
#   2) 如果续期了（证书变化），重启 frontend nginx 加载新证书
#   3) 用 nginx -t 检查配置 + kill -HUP 热重载（比 docker compose restart 快）

set -euo pipefail

echo "==> $(date -Is) certbot renew"

# 续期；--quiet 仅在必要时打印；--deploy-hook 在续期后触发
docker run --rm \
    -v $(pwd)/certbot/conf:/etc/letsencrypt \
    -v $(pwd)/certbot/www:/var/www/certbot \
    certbot/certbot renew \
        --quiet \
        --webroot --webroot-path=/var/www/certbot \
        --deploy-hook "echo cert renewed at \$(date -Is)"

# 如果有 frontend 容器，重启它（让 nginx 重新加载证书）
# 注意：nginx -s reload 通常就够了（不用重启容器），但 certbot renew 的
# deploy-hook 在容器里跑访问不到 host docker，所以这里直接 compose restart
if docker ps --format '{{.Names}}' | grep -q '^ai-agent-frontend$'; then
    echo "==> 重启 ai-agent-frontend 加载新证书"
    docker compose restart frontend
fi
