# web_console/Dockerfile — 前端 React/Vite 构建 + Nginx 镜像（前后端彻底解耦）
#
# Multi-Stage 构建：
#   Stage 1 (builder) : node:20-alpine  → npm ci + npm run build，产出 dist/
#   Stage 2 (runtime) : nginx:1.27-alpine → 仅放入 dist/ + 根目录 nginx.conf
#
# 关键点：
#   - VITE_API_BASE_URL=/api   生产构建时硬编码进前端 bundle（所有 fetch 走同源 /api/*）
#   - /api/* 在运行时由同容器 nginx 反代到 backend:8000（docker-compose 内的服务名）
#   - 该镜像不包含 Python/uvicorn；后端由独立的 backend 容器跑
#
# 安全加固：
#   - 通过 build-arg 注入版本/构建日期标签，运维/CI 可查；
#   - 加 `no-new-privileges` capability（compose 配 security_opt）；
#   - nginx 容器默认以 root 启动主进程，但 worker 由 master fork 为 nginx 用户，
#     这是 nginx 官方镜像的标准安全模型。

# ──────────────── build args ────────────────
ARG NODE_VERSION=20-alpine
ARG NGINX_VERSION=1.27-alpine

# ──────────────── Stage 1: 前端构建 ────────────────
FROM node:${NODE_VERSION} AS builder

WORKDIR /build/web_console

# 关键：生产环境下所有请求走同源 /api，不再硬编码 localhost:8000
ENV VITE_API_BASE_URL=/api \
    NODE_ENV=production \
    NPM_CONFIG_UPDATE_NOTIFIER=false

# 1) 先装依赖（利用 Docker layer cache）
COPY web_console/package.json web_console/package-lock.json* ./
RUN npm ci --no-audit --no-fund --prefer-offline

# 2) 复制源码并构建
COPY web_console/ ./
RUN npm run build \
    && echo "Build complete at $(date -u +%FT%TZ)" > dist/.buildinfo

# ──────────────── Stage 2: Nginx 镜像 ────────────────
FROM nginx:${NGINX_VERSION} AS runtime

# 替换默认 server 配置
RUN rm -f /etc/nginx/conf.d/default.conf

# 拷贝项目根目录的 nginx.conf（前后端彻底解耦版）
COPY nginx.conf /etc/nginx/nginx.conf

# 拷贝前端构建产物到 nginx 静态目录
COPY --from=builder /build/web_console/dist /usr/share/nginx/html

# 写入版本与构建时间（运维/CI 拉镜像可查）
ARG BUILD_VERSION=unknown
ARG BUILD_DATE=unknown
RUN echo "${BUILD_VERSION} ${BUILD_DATE}" > /usr/share/nginx/html/.version

# 健康检查（alpine 默认带 wget）
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/api/health || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
