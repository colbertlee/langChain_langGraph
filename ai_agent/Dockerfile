# ai_agent/Dockerfile — FastAPI 后端镜像（仅 API，不托管前端）
#
# 镜像仅暴露 8000 端口；容器内通过 docker-compose 网络被前端 nginx 反代访问。
# 启动：python -m uvicorn ai_agent.app:app --host 0.0.0.0 --port 8000
#
# 安全加固：
#   - 以非 root (appuser, UID 10001) 运行；
#   - 添加 OCI labels (image.source / image.version / image.created)；
#   - 安装 tini 作为 PID 1（正确处理僵尸进程 + 信号转发）。
#
# 多阶段可选项（pip install 在同一 stage；如未来引入 C 扩展 / CUDA 等重型构建依赖，
#  可拆出 builder stage 用 gcc+wheel，最后到 runtime stage 仅 pip install --no-deps）。

# ──────────────── build args ────────────────
ARG PYTHON_VERSION=3.11-slim

FROM python:${PYTHON_VERSION}

ARG BUILD_VERSION=unknown
ARG BUILD_DATE=unknown

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # tini 路径（install 阶段已写入 /usr/local/bin/tini）
    TINI_SUBREAPER=true

# 系统依赖：
#   - sqlite3        部分工具落地 SQLite（如 HITL pending store）
#   - curl           健康检查
#   - gcc / libffi   编译部分 Python wheel
#   - tini           PID 1 进程管理器
RUN apt-get update && apt-get install -y --no-install-recommends \
        sqlite3 \
        curl \
        tini \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 1) 先装依赖（利用 layer cache）
COPY ai_agent/requirements.txt /app/ai_agent/requirements.txt
RUN pip install --no-cache-dir -r /app/ai_agent/requirements.txt

# 2) 复制后端代码
COPY ai_agent/ /app/ai_agent/

# 数据 / 上传目录
RUN mkdir -p /app/data /app/ai_agent/uploads

# ──────────────── 创建非 root 用户 ────────────────
# UID 10001 兼容 Kubernetes runAsNonRoot 安全上下文
RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid appuser --shell /bin/bash --create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

# OCI image labels（可被 docker inspect 读到）
LABEL org.opencontainers.image.title="ai-agent-backend" \
      org.opencontainers.image.description="AI Agent Console 后端（FastAPI + LangGraph + MCP）" \
      org.opencontainers.image.source="https://github.com/colbertlee/langChain_langGraph" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="MIT"

# 工作目录与 PYTHONPATH
WORKDIR /app
ENV PYTHONPATH=/app \
    DATA_ROOT=/app/data \
    UPLOAD_ROOT=/app/ai_agent/uploads \
    PATH="/home/appuser/.local/bin:${PATH}"

EXPOSE 8000

# 健康检查：直接拉后端自身的健康端点
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# tini 作为 PID 1：捕获信号 → 转发给 uvicorn；非 root 也能用（带 setcap 或 user namespace）
# 注意：tini 默认以 root 运行；这里我们用 tini -g 让它把信号转发到子进程组，
#       然后 exec 切换到 python（仍是 appuser）；信号处理保持一致。
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "uvicorn", "ai_agent.app:app", "--host", "0.0.0.0", "--port", "8000"]
