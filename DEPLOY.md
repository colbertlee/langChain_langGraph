# AI Agent Console — 部署指南

本项目前后端彻底解耦：

| 角色      | 路径            | 技术栈                  | 运行时端口                |
|-----------|-----------------|-------------------------|---------------------------|
| 前端      | `web_console/`  | React + Vite + Tailwind | 开发 `5173` / 生产 `80`   |
| 后端      | `ai_agent/`     | Python 3.11 + FastAPI   | `8000`（仅内网，生产不对外） |

**生产环境下：**
- Nginx 容器（`frontend`，host:80）是唯一对外入口。
- FastAPI 容器（`backend`，8000）只提供 API，**不**托管任何前端静态文件或前端路由。
- 浏览器 → `:80` 拉静态资源 + 通过 `/api/*` 反代到后端。

---

## 1. 本地开发

### 1.1 启动后端（8000）

```bash
cd ai_agent
python -m pip install -r requirements.txt
cp .env.example .env          # 编辑填入 OPENAI_API_KEY / 其他 LLM Key
python app.py                 # 默认 0.0.0.0:8000
```

健康检查：

```bash
curl http://localhost:8000/api/health
# {"status":"ok","agent_ready":false,"timestamp":...}
```

### 1.2 启动前端（5173）

```bash
cd web_console
npm install
npm run dev                   # 默认 http://localhost:5173
```

前端会通过环境变量 `VITE_API_BASE`（默认 `/api`）访问后端。本地模式下，`/api` 走 vite 自身的解析 —— **生产构建**已用 `VITE_API_BASE_URL=/api` 硬编码进 bundle，由同源 nginx 反代。

如果需要本地直连后端（例如没有 nginx），可在 `web_console/.env.local` 中显式覆盖：

```ini
VITE_API_BASE=http://localhost:8000/api
VITE_API_BASE_URL=http://localhost:8000/api
```

### 1.3 同时启动（推荐）

开两个终端分别 `python app.py` 与 `npm run dev`，前端通过 `http://localhost:5173` 访问。

---

## 2. 生产部署（Docker Compose，一键构建并启动）

### 2.1 前置条件

- Docker Engine ≥ 24 + Docker Compose v2（`docker compose` 命令）。
- 复制并按需修改 `.env`：

  ```bash
  cp .env.example .env
  # 编辑：填入 OPENAI_API_KEY / DEEPSEEK_API_KEY / LangSmith 等凭据
  ```

### 2.2 启动

```bash
docker compose up -d --build
```

Compose 会：

1. 构建 `backend` 镜像（`ai_agent/Dockerfile`，python:3.11-slim + uvicorn）。
2. 构建 `frontend` 镜像（`web_console/Dockerfile`，node:20 → nginx:alpine，多阶段构建时 `VITE_API_BASE_URL=/api`）。
3. 启动两个容器，加入 `ai-agent-net` bridge 网络。
4. 仅把 `frontend` 的 `80` 端口映射到 host；`backend` 的 `8000` **不对外暴露**。

### 2.3 验证

```bash
# 浏览器访问
open http://localhost/                          # SPA 入口（应落到 /index.html）

# 健康检查
curl -s http://localhost/api/health             # 走 nginx → backend:8000

# 仅验证反代链路
docker compose exec backend curl -s http://localhost:8000/api/health

# 查看日志
docker compose logs -f frontend
docker compose logs -f backend
```

### 2.4 常用运维

```bash
docker compose ps                # 查看容器状态
docker compose restart backend   # 重启后端（拉取新依赖后）
docker compose down              # 停止（保留数据卷）
docker compose down -v           # 停止 + 删除数据卷（清空 SQLite / 上传 / 记忆）
```

### 2.5 反向代理 / HTTPS

- 当前 `frontend` 直接把 `80` 暴露给 host，**HTTPS / TLS 终止建议放在前置 LB（Nginx / Cloudflare / ALB）**。
- 容器内 nginx 仍只跑 80 端口（明文 HTTP）。生产环境不要把 8000 直接暴露公网。

---

## 3. 配置摘要

| 组件              | 关键文件                                          | 说明                                                                 |
|-------------------|---------------------------------------------------|----------------------------------------------------------------------|
| 前端 Dockerfile   | `web_console/Dockerfile`                          | Multi-Stage（node:20-alpine → nginx:1.27-alpine），`VITE_API_BASE_URL=/api` |
| 后端 Dockerfile   | `ai_agent/Dockerfile`                             | Python 3.11-slim，安装 `requirements.txt`，`uvicorn app:app --host 0.0.0.0 --port 8000` |
| 反向代理          | `nginx.conf`（项目根）                            | `/api/` 反代 `http://backend:8000/`，`proxy_buffering off` 支持 SSE  |
| 编排              | `docker-compose.yml`（项目根）                    | `frontend` + `backend`，同一 bridge，仅 host:80 对外                  |
| CORS              | `ai_agent/app.py` 中 `CORSMiddleware`             | 已允许 `*` 来源 + 凭据 + 全部方法/头                                 |
| 前端 API 路径     | `web_console/src/lib/api.ts`                       | 通过 `import.meta.env.VITE_API_BASE` 读取，默认 `/api`（相对路径）    |

---

## 4. 排错速查

| 现象                              | 可能原因 / 排查                                                                 |
|-----------------------------------|---------------------------------------------------------------------------------|
| 浏览器 502                        | 后端未就绪：等待 backend healthcheck 通过后，frontend 才被 Compose 启动         |
| `/api/...` 返回 404               | nginx.conf 与 docker-compose.yml 中服务名必须一致（`backend`）                |
| SSE 一直转圈、无 chunk           | 检查 nginx.conf 的 `proxy_buffering off` + `X-Accel-Buffering: no`            |
| 前端页面 404（刷新子路由）        | `try_files $uri $uri/ /index.html` 必须存在                                    |
| 前端 fetch 跨域                   | 同源 nginx 反代已规避；如直连 8000 端口，确认 `CORSMiddleware` 已启用          |
| 看不到 agent                      | `.env` 中 `OPENAI_API_KEY` 是占位符；填入真实 key 后重启 backend                |
| `npm run build` 报 API URL       | 确认 `web_console/Dockerfile` 中 `ENV VITE_API_BASE_URL=/api`                  |