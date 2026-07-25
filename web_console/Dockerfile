# ─────────────── 前端构建阶段 ───────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/web_console

# 只 copy 依赖文件以利用 cache
COPY web_console/package*.json ./
RUN npm ci --no-audit --no-fund

# 复制源码并构建
COPY web_console/ ./
RUN npm run build

# ─────────────── 后端运行阶段 ───────────────
FROM python:3.11-slim AS backend

WORKDIR /app

# 系统依赖（sqlite + curl 用于 healthcheck）
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 curl gcc && \
    rm -rf /var/lib/apt/lists/*

# 先装 Python 依赖
COPY ai_agent/requirements.txt /app/ai_agent/
RUN pip install --no-cache-dir -r /app/ai_agent/requirements.txt

# 复制后端代码
COPY ai_agent/ /app/ai_agent/

# 复制前端 dist（由 frontend-builder 构建）
COPY --from=frontend-builder /app/web_console/dist /app/web_console/dist

# 数据 / 上传目录
RUN mkdir -p /app/data /app/ai_agent/uploads

# 环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    UPLOAD_ROOT=/app/ai_agent/uploads \
    DATA_ROOT=/app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "ai_agent.web_ui:app", "--host", "0.0.0.0", "--port", "8000"]