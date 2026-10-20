# AI Agent 运维 SOP

> 适用版本:**v2.5.0**(LangChain × LangGraph AI Agent 运维手册)
>
> 面向对象:**SRE / 运维 / 部署负责人**。
>
> 如果你只想"用 AI Agent",请看 [USER_MANUAL.md](USER_MANUAL.md);开发者请看 [README.md](README.md) / [docs/API.md](docs/API.md) / [ai_agent/README.md](ai_agent/README.md)。

---

## 目录

- [1. 部署形态选择](#1-部署形态选择)
- [2. 部署前置检查](#2-部署前置检查)
- [3. 五种部署模式](#3-五种部署模式)
  - [3.1 Docker Compose(推荐生产)](#31-docker-compose推荐生产)
  - [3.2 裸机 uvicorn](#32-裸机-uvicorn)
  - [3.3 桌面二进制(内网单机)](#33-桌面二进制内网单机)
  - [3.4 PyPI pip install](#34-pypi-pip-install)
  - [3.5 Scoop / Homebrew](#35-scoop--homebrew)
- [4. v2.5.0 升级路径(从 v1.x / v2.0.x)](#4-v250-升级路径从-v1x--v20x)
- [5. 健康检查与监控](#5-健康检查与监控)
  - [5.1 Liveness / Readiness](#51-liveness--readiness)
  - [5.2 Prometheus + Grafana](#52-prometheus--grafana)
  - [5.3 24h Staging 监控探针](#53-24h-staging-监控探针)
  - [5.4 Fail Log](#54-fail-log)
  - [5.5 事件流 / Trace](#55-事件流--trace)
- [6. 数据持久化与备份恢复](#6-数据持久化与备份恢复)
- [7. 回滚操作](#7-回滚操作)
- [8. 灰度发布与 A/B](#8-灰度发布与-ab)
- [9. 安全加固](#9-安全加固)
- [10. 常见故障与处理](#10-常见故障与处理)
- [11. 容量与性能调优](#11-容量与性能调优)
- [12. 联系与升级链路](#12-联系与升级链路)

---

## 1. 部署形态选择

| 形态 | 适用 | 监听端口 | 推荐度 |
|---|---|---|---|
| Docker Compose | 生产(前后端一体) | 8000 | ⭐⭐⭐⭐⭐ |
| 裸机 uvicorn + Nginx | 已有 K8s / VM 集群 | 8000(内部) / 443(Nginx) | ⭐⭐⭐⭐ |
| 桌面包(PyInstaller) | 内网单机 / 给最终用户 | CLI / 8000 | ⭐⭐⭐ |
| PyPI(`pip install ai-agent`) | 嵌入式 / 脚本调用 | 8000 | ⭐⭐ |
| Scoop / Homebrew | 桌面 CLI 用户 | CLI | ⭐⭐ |

> v2.5.0 起,**`AIAgent_LEGACY` 环境变量已彻底忽略**;`config.LEGACY_MODE` 恒为 `False`;`v2_slim/*_legacy.py` 已物理删除。**不要在 systemd unit / docker-compose / k8s manifest 中再设 `AIAgent_LEGACY=true`**(设了也不会生效)。

---

## 2. 部署前置检查

### 2.1 资源

| 资源 | 最小 | 推荐 | 说明 |
|---|---|---|---|
| CPU | 2 vCPU | 4+ vCPU | Embedding / Rerank 时 CPU 重要 |
| 内存 | 2 GB | 4+ GB | PyInstaller 桌面包需 ~1.2 GB 解压 |
| 磁盘 | 3 GB | 10+ GB | Chroma 索引 + 上传文件 + 日志 |
| Python | 3.11+ | 3.12 | CI 测 3.11 + 3.12 |
| Node | — | 20 LTS / 22 LTS | 仅 React 控制台 dev / e2e 需要 |
| Docker | 24+ | 最新 | 含 docker compose v2 |
| 浏览器 | Chrome 120+ | 最新 | React 控制台 + 主界面 |

### 2.2 端口清单

| 端口 | 服务 | 命令 |
|---|---|---|
| 8000 | FastAPI 后端 / 单文件 HTML 主界面 / Web 控制台 | `python app.py` |
| 8765 | 单文件 HTML 主界面(独立静态服务器) | `python -m http.server 8765` |
| 5173 | React 控制台 Vite dev | `npm run dev` |
| 9090 | Prometheus 自身 UI | (Prom 安装时确定) |
| 3000 | Grafana UI | (Grafana 安装时确定) |

### 2.3 环境变量(.env 完整清单)

```env
# ==== LLM Provider(任选一家) ====
OPENAI_API_KEY=sk-...
DEEPSEEK_API_KEY=sk-...         # 国产首选
QWEN_API_KEY=sk-...             # 中文最强
ZHIPU_API_KEY=...
MOONSHOT_API_KEY=sk-...
MINIMAX_API_KEY=...
BAIDU_API_KEY=...
BAIDU_SECRET_KEY=...
SPARK_APP_ID=...
SPARK_API_KEY=...
SPARK_SECRET_KEY=...
DOUBAO_API_KEY=...
HUNYUAN_API_KEY=...
SILICONFLOW_API_KEY=...
GLM_API_KEY=...                 # ZHIPU_API_KEY 别名

# ==== 主备模型 ====
MODEL_PROVIDER=deepseek
MODEL_NAME=deepseek-chat

# ==== RAG Embedding ====
EMBEDDING_API_KEY=              # 默认复用 OPENAI_API_KEY
EMBEDDING_MODEL_TYPE=openai     # openai / zhipu / minimax / jina

# ==== 第三方 ====
SERPAPI_API_KEY=                # search_web 工具
GITHUB_PERSONAL_ACCESS_TOKEN=   # github MCP 工具
GITEE_TOKEN=                    # gitee MCP 工具

# ==== 运行时 ====
PORT=8000
HOST=0.0.0.0
LOG_LEVEL=INFO
AI_AGENT_DISABLE_PLACEHOLDER_CHECK=1   # 0=关闭占位符短路,LLM 真初始化
MEMORY_SUMMARY_CHARS=500               # 上下文截断字符预算(v2.5.0+)
AI_AGENT_INMEM_CHECKPOINT=             # 1=true=SqliteSaver 失败回退 MemorySaver(测试环境)

# ==== 已废弃(忽略即可) ====
# AIAgent_LEGACY=true            # v2.5.0+ 完全无效,保留仅为兼容监控
```

### 2.4 端口/磁盘/进程 检查

```bash
# 端口
ss -tlnp | grep -E ':(8000|5173|8765)' || echo "ports clear"

# 磁盘
df -h /path/to/ai_agent      # 至少 3 GB 可用

# 进程占位
pgrep -f "uvicorn app:app"   # 应为空,首次部署
```

---

## 3. 五种部署模式

### 3.1 Docker Compose(推荐生产)

仓库根目录已配 `docker-compose.yml`(多阶段:Node 构建前端 → python:3.11-slim 运行 uvicorn)。

```bash
# 仓库根目录
cp .env.example .env          # 填 LLM_API_KEY
docker compose up -d --build  # 自动构建前后端

# 验证
curl http://localhost:8000/api/health
# → {"status":"ok","runtime_flavor":"v2_slim",...}

# 实时日志
docker compose logs -f ai_agent

# 停机(保留数据)
docker compose down

# 完全清理(⚠️ 会删数据)
docker compose down -v
```

**关键 docker-compose 配置**(已就绪):
- `healthcheck`:每 30s 探 `/api/health`
- `restart: unless-stopped`
- `volumes`:`ai_agent_data / ai_agent_uploads / ai_agent_chroma`
- `TZ: Asia/Shanghai`

### 3.2 裸机 uvicorn

```bash
# 系统级
sudo useradd -r -s /bin/false aiagent
sudo -u aiagent git clone https://github.com/colbertlee/langChain_langGraph /opt/ai-agent
cd /opt/ai-agent/ai_agent
sudo -u aiagent python -m venv .venv
sudo -u aiagent .venv/bin/pip install -r requirements.txt
sudo -u aiagent cp .env.example .env
sudo -u aiagent vi .env    # 填 LLM_API_KEY

# systemd unit(/etc/systemd/system/ai-agent.service)
[Unit]
Description=AI Agent FastAPI
After=network.target

[Service]
Type=simple
User=aiagent
WorkingDirectory=/opt/ai-agent/ai_agent
EnvironmentFile=/opt/ai-agent/ai_agent/.env
ExecStart=/opt/ai-agent/ai_agent/.venv/bin/python app.py
Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target

# 启用
sudo systemctl daemon-reload
sudo systemctl enable --now ai-agent
sudo systemctl status ai-agent
```

**Nginx 反代 + TLS**(参考 `nginx-ssl.conf`):

```nginx
server {
  listen 443 ssl;
  server_name ai.example.com;
  ssl_certificate     /etc/letsencrypt/live/ai.example.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/ai.example.com/privkey.pem;

  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;       # SSE 长连接
    proxy_buffering off;           # 关闭缓冲
  }
}
```

### 3.3 桌面二进制(内网单机)

Windows:
```bat
cd package\windows
install.bat            :: 第一次:生成 .env、建 logs/uploads/data
notepad .env           :: 填 LLM_API_KEY
run.bat                :: 启动 CLI
run-web.bat            :: 启动 Web 服务(:8000)
```

Linux / macOS:
```bash
cd package/linux
chmod +x ai-agent install.sh run.sh run-web.sh
./install.sh
nano .env
./run.sh          # CLI
./run-web.sh      # Web(:8000)
```

**优势**:零 Python 依赖(~470 MB 含 Python 运行时 + LangChain + LangGraph + ChromaDB)。
**适用**:内网单机 / 给非技术同事 / 离线场景。

### 3.4 PyPI pip install

```bash
pip install ai-agent
# 启动 Web 服务
ai-agent
# 或别名
ai-agent-server
```

CI 走 OIDC + PEP 740 provenance;详见 `web_console/.github/PYPI_PUBLISHING.md`。

### 3.5 Scoop / Homebrew

```powershell
# Windows
scoop bucket add colbertlee https://github.com/colbertlee/scoop-bucket
scoop install ai-agent
```

```bash
# macOS / Linux
brew tap colbertlee/tap
brew install ai-agent
```

详见 `web_console/.github/SCOOP_BREW_TAP_SETUP.md`。

---

## 4. v2.5.0 升级路径(从 v1.x / v2.0.x)

### 4.1 v1.x → v2.5.0

```bash
git fetch origin
git checkout master
git pull

# 数据兼容:✅ 直接复用(无需迁移)
# context_memory.db / memory.db / chroma_db/ 全部可继续用

# 如果从 v2.0.x 之前迁过来:不需要 migrate_memory_v1_to_v2.py
# (该脚本只对 v2.0.x 内部的 v1/v2 记忆模型迁移有用)

# 重启服务
sudo systemctl restart ai-agent
# 或
docker compose restart

# 验证
curl http://your-host:8000/api/health
# → runtime_flavor: "v2_slim"
```

### 4.2 v2.0.x → v2.5.0

无 breaking change,**直接 `git pull && restart`**。

> ⚠️ **关键**:删除所有 `AIAgent_LEGACY=true` 的环境变量配置(v2.0.10 起该 env 完全无效)。

### 4.3 v2.0.10 之前 → v2.5.0(LEGACY 用户必看)

```bash
# 1. 移除所有部署清单里的 AIAgent_LEGACY=true
grep -r "AIAgent_LEGACY" /etc/systemd /opt/ai-agent/docker-compose.yml
# 手动删除

# 2. 拉新版本
git pull

# 3. 重启
sudo systemctl restart ai-agent

# 4. 验证 v2.5.0 真在跑
curl http://your-host:8000/api/health | jq .
# "runtime_flavor" 必须为 "v2_slim"
```

> 如果你之前依赖 `AIAgent_LEGACY=true` 绕过某个 v2 slim 问题,需手动验证该问题在 v2.5.0 是否已修;若仍存在,参考 [§7 回滚](#7-回滚操作)。

---

## 5. 健康检查与监控

### 5.1 Liveness / Readiness

| 端点 | 用途 | 期望 |
|---|---|---|
| `GET /api/health` | Liveness + 运行时 flavor | 200,`status: ok`,`runtime_flavor: v2_slim` |
| `GET /api/version` | 版本号 | 200,`version: 2.5.0` |
| `GET /` | 主界面可达 | 200 HTML |
| `GET /metrics` | Prometheus 抓取 | 200 文本 |

**K8s probe 示例**:

```yaml
livenessProbe:
  httpGet: { path: /api/health, port: 8000 }
  initialDelaySeconds: 10
  periodSeconds: 30
readinessProbe:
  httpGet: { path: /api/version, port: 8000 }
  initialDelaySeconds: 5
  periodSeconds: 10
```

### 5.2 Prometheus + Grafana

#### 抓取配置(`prometheus.yml`)

```yaml
scrape_configs:
  - job_name: ai_agent
    metrics_path: /metrics
    static_configs:
      - targets: ['ai-agent.internal:8000']
    scrape_interval: 15s
```

仓库根目录已含 `monitoring/prometheus.yml` 模板。

#### Grafana Dashboard

仓库根目录 `monitoring/grafana/provisioning/dashboards/ai-agent-console/overview.json` 已就绪。导入步骤:

1. Grafana → Dashboards → Import
2. 上传 `overview.json` 或填 URL
3. 选 Prometheus 数据源
4. 完成 → 看到 Token 用量 / 错误率 / LLM 调用次数 / Tool 调用次数面板

#### 关键 PromQL 查询

```promql
# 1. LLM 调用成功率(按 provider)
sum by (provider) (rate(ai_agent_llm_calls_total{status="success"}[5m]))
  / sum by (provider) (rate(ai_agent_llm_calls_total[5m]))

# 2. Fallback 触发率
rate(ai_agent_llm_fallback_total[5m])

# 3. p95 LLM 延迟
histogram_quantile(0.95, rate(ai_agent_llm_latency_ms_bucket[5m]))

# 4. Token 消耗速率(按 provider)
sum by (provider) (rate(ai_agent_tokens_total[5m]))

# 5. 5xx 错误率
rate(ai_agent_http_requests_total{status=~"5.."}[5m])
```

### 5.3 24h Staging 监控探针

跑 `tests/test_staging_monitor.py`(15 个探针):

```bash
cd ai_agent
pytest tests/test_staging_monitor.py -v --no-cov
# 期望:15 passed
```

**24h 循环**(`scripts/staging_monitor_loop.py` 已就绪):

```bash
# 启动后台循环(每 5 分钟一次)
nohup python ai_agent/scripts/staging_monitor_loop.py > /var/log/ai_agent/staging.log 2>&1 &

# 探针维度:
# 1. TelemetrySink 自检(5 项)
# 2. 11 Provider 路由(2 项)
# 3. 7 事件 schema 漂移(2 项)
# 4. 五层容错模块自检(2 项)
# 5. v2 slim 双重入口(1 项)
# 6. LEGACY 兜底(1 项,已被 frozen 占位)
# 7. frozen 模块正确性(1 项)
# 8. migration 模块(1 项)
# 9. 综合健康报告(1 项)
```

#### 探针失败告警映射

| 探针 | 等级 | 影响 |
|---|---|---|
| `test_telemetry_*` | **P0** | TelemetrySink schema 漂移(核心闭环) |
| `test_provider_base_url_*` | P1 | 11 Provider 路由失效 |
| `test_seven_event_types_*` | **P0** | run_stream 事件 schema 漂移 |
| `test_event_types_no_drift` | **P0** | 出现未知事件类型(typo) |
| `test_fault_tolerance_*` | P1 | 五层容错模块导入失败 |
| `test_fail_log_*` | P2 | FailLog 不可写 |
| `test_v2_slim_double_entry_import` | P1 | v2_slim 双重入口失效 |
| `test_frozen_modules_raise_not_implemented` | **P0** | frozen 模块静默成功(破坏冻结) |

详见 `ai_agent/docs/STAGING_MONITORING.md`。

### 5.4 Fail Log

`FailLogRepository` 自动持久化 LLM 失败记录(SQLite),聚合摘要:

```bash
curl http://your-host:8000/api/fail-log/summary | jq .
# {
#   "by_provider": {
#     "openai": {"errors": 0, "last_error": null},
#     "deepseek": {"errors": 2, "last_error": "timeout after 30s"}
#   },
#   "by_fingerprint": [
#     {"fp": "TimeoutError-deepseek-chat", "count": 2}
#   ],
#   "degradation_count_24h": 5
# }
```

**告警建议**:`degradation_count_24h > 10` → Slack/邮件告警。

### 5.5 事件流 / Trace

```bash
# 实时事件(过去 1h 全部 LLM 调用 / Tool 调用 / Fallback / Memory Recall)
curl 'http://your-host:8000/api/events?limit=200' | jq '.events[] | {ts, type, data}'

# 最近 Trace(嵌套调用树)
curl 'http://your-host:8000/api/traces?limit=20' | jq .
```

前端:`/insights` 页直接看。

---

## 6. 数据持久化与备份恢复

### 6.1 数据落盘清单

| 数据 | 路径 | 大小量级 |
|---|---|---|
| 对话消息(SqliteSaver) | `ai_agent/memory.db` | KB / session |
| 结构化上下文 | `ai_agent/context_memory.db` | KB ~ MB |
| 长期记忆 | 同上,合并存储 | KB ~ MB |
| RAG 向量 | `ai_agent/chroma_db/` | MB ~ GB |
| 上传文件 | `ai_agent/uploads/` | 用户决定 |
| 日志 | `ai_agent/agent.log` | MB / day |
| 失败日志 | `ai_agent/fail_log.db` | KB |
| 可观测事件 | `ai_agent/observability.db` | KB ~ MB |
| 用户 Profile | `ai_agent/context_memory.db` | KB |

### 6.2 备份脚本

```bash
#!/bin/bash
# /opt/ai-agent/scripts/backup.sh — cron 每日 1 次
set -euo pipefail
BACKUP_DIR=/var/backups/ai-agent
INSTALL_DIR=/opt/ai-agent
TS=$(date +%Y%m%d-%H%M)

mkdir -p "$BACKUP_DIR"
tar czf "$BACKUP_DIR/ai-agent-$TS.tar.gz" \
  -C "$INSTALL_DIR/ai_agent" \
  *.db uploads chroma_db agent.log

# 保留 14 天
find "$BACKUP_DIR" -name "ai-agent-*.tar.gz" -mtime +14 -delete
```

### 6.3 恢复

```bash
systemctl stop ai-agent
tar xzf /var/backups/ai-agent/ai-agent-20260908-0100.tar.gz \
  -C /opt/ai-agent/ai_agent/
systemctl start ai-agent
curl http://localhost:8000/api/health
```

### 6.4 容器部署的卷

`docker-compose.yml` 已配:
```yaml
volumes:
  - ai_agent_data:/opt/ai-agent/ai_agent  # db + uploads
  - ai_agent_chroma:/opt/ai-agent/ai_agent/chroma_db
```

```bash
# 备份容器卷
docker run --rm -v ai_agent_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/ai-agent-data-$(date +%F).tar.gz -C /data .
```

---

## 7. 回滚操作

### 7.1 Git revert(推荐)

```bash
# 1. 找出要回滚的 commit
git log --oneline -20

# 2. revert
git revert <sha>            # 创建一个反向 commit
# 或
git revert <sha1>..<sha2>   # 批量 revert

# 3. 推送(若有直推权限)
git push origin master

# 4. 重启服务
sudo systemctl restart ai-agent
# 或
docker compose up -d --build
```

### 7.2 Tag 回滚(更稳)

```bash
# 1. 找到上一个稳定 tag
git tag --sort=-v:refname | head -10
# 例:v2.0.10 v2.0.9 v2.0.7-cleanup-verified

# 2. 切到 tag(创建 hotfix 分支)
git checkout -b hotfix/v2.0.10 v2.0.10

# 3. 部署 hotfix 分支
sudo systemctl restart ai-agent
```

### 7.3 数据回滚(谨慎)

> ⚠️ **如果新版本升级时改了 SQLite schema,数据回滚可能不兼容**。建议先备份再升级。

```bash
# 1. 停服
systemctl stop ai-agent

# 2. 恢复昨天的 db 备份
cp /var/backups/ai-agent/ai-agent-yesterday.db /opt/ai-agent/ai_agent/memory.db

# 3. 回滚代码 + 重启
git checkout v2.0.10 -- ai_agent/
systemctl start ai-agent

# 4. 验证
curl http://localhost:8000/api/health
```

### 7.4 v2.5.0 LEGACY 用户回滚

如果你必须依赖老 `tools.py / memory_store.py / multi_agent.py`(LEGACY 实现):

```bash
# v2.5.0 已彻底删除 LEGACY 模块,无法回退到 LEGACY 运行时
# 唯一选择:git checkout v2.0.9 -- ai_agent/
git checkout v2.0.9 -- ai_agent/
# 然后重新部署 v2.0.9
```

---

## 8. 灰度发布与 A/B

### 8.1 蓝绿部署

```bash
# v2.5.0(蓝)与 v2.0.10(绿)并存
# Nginx upstream 切换
upstream ai_agent_blue  { server 127.0.0.1:8001; }  # v2.5.0
upstream ai_agent_green { server 127.0.0.1:8000; }  # v2.0.10

# 切 10% 流量到蓝
split_clients $request_id $backend {
  10%     ai_agent_blue;
  *       ai_agent_green;
}
```

### 8.2 Prompt A/B

`/admin?tab=prompts` → 注册新版本(如 v3.0.0) → 选择性切换:
- 全部用户:激活版本切到 v3.0.0
- 部分用户:用 `/api/prompts/rollback` + 自定义 endpoint 按 user_id 分流

### 8.3 模型 A/B

```python
from ai_agent.ab_testing import ABTest
test = ABTest(
    name="deepseek-vs-qwen",
    variants={
        "deepseek": {"provider": "deepseek", "model": "deepseek-chat"},
        "qwen":     {"provider": "qwen", "model": "qwen-turbo"},
    },
    metric="user_satisfaction",
)
test.run(question="...", n=200)
print(test.report())
```

---

## 9. 安全加固

### 9.1 文件 / 进程权限

```bash
# 1. 跑 Agent 的用户用最小权限
sudo useradd -r -s /bin/false aiagent

# 2. ai_agent/ 目录禁止 world-write
chmod -R o-w /opt/ai-agent

# 3. 日志 / 数据目录单独 owner
chown -R aiagent:aiagent /opt/ai-agent/ai_agent/{*.db,uploads,chroma_db,logs}
chmod 600 /opt/ai-agent/ai_agent/.env  # .env 仅 aiagent 可读

# 4. systemd 加 ProtectSystem=strict / PrivateTmp=true / NoNewPrivileges=true
```

### 9.2 API Key 管理

- `.env` 仅 600 权限
- 不在 Git 里(`.gitignore` 已含 `.env`)
- 不进日志(`security.redact_output` 自动脱敏)
- 不在前端 React 控制台持久化

### 9.3 输入输出安全

| 防护 | 实现 |
|---|---|
| 危险命令拦截 | `security.py`(`rm -rf` / `del /f` / `format c:` / `shutdown` / `os.system`) |
| 上级目录访问 | 阻止 `..` 和绝对路径 |
| 代码执行安全 | AST 白名单 + 仅数学表达式 |
| 输出脱敏 | `sk-` / `Bearer` / `password` 替换为 `***` |
| Prompt Injection 检测 | 正则 + 关键词匹配(`ignore previous instructions` 等) |
| HITL 二次确认 | `requires_approval=True` 工具(`python_interpreter` 等) |
| RBAC | `permission.py`(agent × tool × worker 三维) |

### 9.4 网络隔离

```bash
# 1. LLM API 出站白名单(防火墙)
/sbin/iptables -A OUTPUT -p tcp -d api.deepseek.com -j ACCEPT
/sbin/iptables -A OUTPUT -p tcp -d api.openai.com -j ACCEPT
/sbin/iptables -A OUTPUT -p tcp --dport 443 -j DROP  # 其他 https 出站禁止

# 2. 入口仅 443(Nginx)
/sbin/iptables -A INPUT -p tcp --dport 8000 -j DROP  # 直接 8000 不暴露
```

### 9.5 HTTPS / Let's Encrypt

仓库根目录 `scripts/init-letsencrypt.sh` 已就绪:

```bash
sudo ./scripts/init-letsencrypt.sh ai.example.com admin@ai.example.com
# 自动申请 + Nginx 配置 + 续期 cron
```

`scripts/renew-cert.sh` 配合 cron。

---

## 10. 常见故障与处理

### 10.1 启动失败

| 现象 | 排查 |
|---|---|
| `ModuleNotFoundError: langchain_core` | `pip install -r requirements.txt`;venv 已激活 |
| `OPENAI_API_KEY not set` | `.env` 填真 Key,或 Web 设置页填 |
| `placeholder key` 跳过初始化 | 设 `AI_AGENT_DISABLE_PLACEHOLDER_CHECK=0` |
| 端口 8000 被占 | `PORT=9000 python app.py` |
| `SqliteSaver Checkpoint store unavailable` | 检查 `ai_agent/memory.db` 目录权限;或设 `AI_AGENT_INMEM_CHECKPOINT=1` 启用 MemorySaver 降级 |
| Windows 中文乱码 | `run.bat` 已 `chcp 65001`;CLI 入口 `main.py` 已 `stdout.reconfigure(encoding='utf-8')` |
| matplotlib 报错 | 已自动 `MPLBACKEND=Agg` |

### 10.2 模型相关

| 现象 | 排查 |
|---|---|
| DeepSeek 返回空 | `MODEL_NAME=deepseek-chat` 或 `deepseek-reasoner`;`https://api.deepseek.com/v1` |
| Qwen DashScope 401 | Key 必须 `sk-` 开头;用 `QWEN_API_KEY` 而非 `DASHSCOPE_API_KEY` |
| GLM 报 endpoint 错 | `ZHIPU_API_KEY` 或 `GLM_API_KEY` 任一;`https://open.bigmodel.cn/api/paas/v4` |
| 切换模型不生效 | 调 `/api/model/switch` 或重启;前端刷新 |
| 全部 Provider 不可用 | 五层容错会触发 L5 降级;查 `fail_log` |

### 10.3 桌面包/打包

| 现象 | 排查 |
|---|---|
| PyInstaller `ModuleNotFound` | `ai_agent.spec` 的 `hiddenimports` 补 |
| Linux 二进制缺失 `.so` | 必须 Linux 主机 / Docker 编译;`package/linux/BUILD_ON_LINUX.md` |
| Windows Defender 警告 | 未签名 exe 常见;"More info → Run anyway"或代码签名证书 |
| 包太大 (~470 MB) | 正常;已排除 torch / onnxruntime |

### 10.4 监控告警

| 告警 | 处理 |
|---|---|
| `probe_pass_rate_24h < 100%` | 查 `/var/log/ai_agent/staging/probe.log` |
| `degradation_count_24h > 10` | 查 `/api/fail-log/summary` 找错误指纹 |
| `breaker_open_count_24h > 10` | Provider 不稳定,考虑主备切换 |
| `5xx > 1%` | 查 `agent.log` + `/api/events?type=error` |
| 磁盘 > 80% | 备份 + 清旧 `agent.log.*` + 缩 Chroma 索引 |

### 10.5 CI/发版(若自己跑 GitHub Actions)

| 现象 | 排查 |
|---|---|
| PyPI 403 OIDC | PyPI 项目 → Publishing → pending publisher 配置 |
| Docker push 失败 | Settings → Actions → General → Workflow permissions → Read and write |
| e2e 失败 | 本地 `npm run e2e` 复现;首次需 `npm run e2e:install` |
| Slack/Discord 没收到 | 检查 `SLACK_WEBHOOK_URL` / `DISCORD_WEBHOOK_URL` Secret |
| `.github/workflows/*.yml` push 失败 | PAT 缺 `workflow` scope;workaround:用 `release_cli.py` 手动 |

---

## 11. 容量与性能调优

### 11.1 上下文 Token 预算

`.env` 加 `MEMORY_SUMMARY_CHARS=1000`(默认 500;增大 → 上下文更完整但 token 多)。

### 11.2 LLM 调用并发

- 默认单进程单 worker;生产用 `uvicorn --workers 4` 起 4 个 worker
- 每个 worker 独立 SqliteSaver + MemoryStore;Redis 模式见 `distributed_bus.py`

### 11.3 Embedding 缓存

`rag.py` 已带 Chroma 持久化;若换 Embedding 模型,删 `ai_agent/chroma_db/` 重建。

### 11.4 监控成本

```bash
# 过去 24h token 消耗
curl 'http://your-host:8000/api/context/stats' | jq .

# 高消耗 session 排行
curl 'http://your-host:8000/api/context/analytics' | jq '.top_sessions'
```

按需调:`MEMORY_SUMMARY_CHARS` / `MAX_HISTORY_LENGTH`(默认 10)/ `TEMPERATURE`。

---

## 12. 联系与升级链路

- **GitHub**:https://github.com/colbertlee/langChain_langGraph
- **Gitee**:https://gitee.com/colbertlee/langChain_langGraph
- **Issues**:GitHub Issues 模板 `bug_report.yml` / `feature_request.yml` / `question.yml`
- **Security**:`SECURITY.md`(私密漏洞请发 maintainer,不要公开 issue)
- **发版 SOP**:[docs/VERSION_MANAGEMENT.md](docs/VERSION_MANAGEMENT.md)
- **Incident retro**:[docs/INCIDENT_REPORT_v2.0.7.md](docs/INCIDENT_REPORT_v2.0.7.md)
- **Release notes**:`release_notes/v2.0.10.md` / `release_notes/v2.0.11-patch.md` / 当前 `v2.5.0`(如有)

### 升级 Checklist(贴到 change ticket)

```markdown
- [ ] 备份 ai_agent/*.db、uploads/、chroma_db/
- [ ] git fetch && git pull
- [ ] grep -r "AIAgent_LEGACY" /etc/systemd /opt/ai-agent — 移除所有命中
- [ ] pip install -r ai_agent/requirements.txt(若有依赖变更)
- [ ] npm ci(若前端变更)
- [ ] 重启服务(systemctl restart / docker compose up -d --build)
- [ ] curl /api/health → runtime_flavor: "v2_slim"
- [ ] 跑 24h staging 探针(无 FAIL)
- [ ] 看 /metrics / /api/fail-log/summary(降级次数)
- [ ] 通知用户新版本
```

---

> 文档维护:**AI Agent 运维团队**
> 最近更新:**2026-09-08**(v2.5.0)
> 适用版本:**v2.5.0**