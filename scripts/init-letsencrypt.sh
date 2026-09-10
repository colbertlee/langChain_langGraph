#!/usr/bin/env bash
# P2-4 — Let's Encrypt 证书初始化
#
# 用法：
#   DOMAIN=ai.example.com EMAIL=admin@example.com ./scripts/init-letsencrypt.sh
#
# 流程：
#   1) 准备 certbot webroot + conf 目录
#   2) 启动临时 nginx（仅 80 端口 + ACME challenge）
#   3) 用 certbot certonly --webroot 签证书（http-01 challenge）
#   4) 重启主 docker compose 让 frontend 加载 https nginx.conf
#   5) certbot 加入 cron（每天 3:00 检查续期）
#
# 注意：
#   - 域名必须已指向本机公网 IP（A 记录）
#   - 80 / 443 端口必须能从公网访问
#   - 首次运行需要 sudo / root

set -euo pipefail

DOMAIN="${DOMAIN:-}"
EMAIL="${EMAIL:-}"
STAGING="${STAGING:-0}"   # 1 = 用 Let's Encrypt staging（避免生产限额）
WEBROOT="/var/www/certbot"

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo "Usage: DOMAIN=ai.example.com EMAIL=admin@example.com $0" >&2
    exit 1
fi

echo "==> Domain: $DOMAIN"
echo "==> Email:  $EMAIL"
echo "==> Staging: $STAGING"

# ──────────────── 1) 准备目录 ────────────────
mkdir -p ./certbot/conf
mkdir -p ./certbot/www

# ──────────────── 2) 下载推荐参数 ────────────────
if [ ! -f "./certbot/conf/options-ssl-nginx.conf" ]; then
    echo "==> 下载 recommended-ssl-nginx.conf"
    curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf > ./certbot/conf/options-ssl-nginx.conf
fi
if [ ! -f "./certbot/conf/ssl-dhparams.pem" ]; then
    echo "==> 下载 ssl-dhparams.pem (2048-bit DH params)"
    curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem > ./certbot/conf/ssl-dhparams.pem
fi

# ──────────────── 3) 临时 nginx：仅 80 端口 + ACME ────────────────
echo "==> 启动临时 certbot-only nginx"
cat > /tmp/certbot-only.conf <<EOF
events { worker_connections 1024; }
http {
    server {
        listen 80;
        server_name $DOMAIN;
        location /.well-known/acme-challenge/ {
            root $WEBROOT;
        }
        location / {
            return 200 'OK';
        }
    }
}
EOF
docker run --rm -d --name certbot-only-nginx \
    -p 80:80 \
    -v /tmp/certbot-only.conf:/etc/nginx/nginx.conf:ro \
    -v $(pwd)/certbot/www:$WEBROOT \
    nginx:alpine

# ──────────────── 4) 签证书 ────────────────
echo "==> 用 certbot 签证书"
STAGING_ARG=""
if [ "$STAGING" = "1" ]; then
    STAGING_ARG="--staging"
fi

docker run --rm \
    -v $(pwd)/certbot/conf:/etc/letsencrypt \
    -v $(pwd)/certbot/www:$WEBROOT \
    certbot/certbot certonly \
    --webroot --webroot-path=$WEBROOT \
    --email "$EMAIL" \
    --agree-tos --no-eff-email \
    --force-renewal \
    $STAGING_ARG \
    -d "$DOMAIN"

# ──────────────── 5) 停临时 nginx ────────────────
echo "==> 停临时 nginx"
docker stop certbot-only-nginx 2>/dev/null || true

# ──────────────── 6) 替换 nginx-ssl.conf 里的 <DOMAIN> ────────────────
echo "==> 替换 nginx-ssl.conf 中的 <DOMAIN> 占位符"
sed -i "s|<DOMAIN>|$DOMAIN|g" nginx-ssl.conf

# ──────────────── 7) 提示启用 HTTPS ────────────────
echo ""
echo "✅ 证书签发完成"
echo ""
echo "下一步："
echo "  1) 编辑 docker-compose.yml frontend service:"
echo "       volumes:"
echo "         - ./nginx-ssl.conf:/etc/nginx/nginx.conf:ro"
echo "         - ./certbot/conf:/etc/letsencrypt:ro"
echo "         - ./certbot/www:/var/www/certbot:ro"
echo "       ports:"
echo "         - \"80:80\""
echo "         - \"443:443\""
echo ""
echo "  2) 重启 frontend:"
echo "       docker compose up -d --force-recreate frontend"
echo ""
echo "  3) 验证:"
echo "       curl -I https://$DOMAIN/api/health"
echo ""
echo "  4) 设置自动续期 cron（每天 03:00 检查）："
echo "       0 3 * * * cd $(pwd) && bash scripts/renew-cert.sh >> /var/log/certbot-renew.log 2>&1"
