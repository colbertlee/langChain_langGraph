# P2-5 — 监控与 HTTPS 生产部署指南

本目录包含 Prometheus + Grafana 监控栈的全套配置。

## 目录结构

```
monitoring/
├── prometheus.yml             # Prometheus 主配置（采集 backend + grafana + 自定义）
├── alerting_rules.yml         # 告警规则（后端健康 / SSE / LLM 业务 / HITL）
├── targets/
│   └── example.json           # file_sd 自定义 target 示例
└── grafana/
    └── provisioning/
        ├── datasources/
        │   └── prometheus.yml # 自动加载 Prometheus 数据源
        └── dashboards/
            ├── default.yml     # provider 配置
            └── ai-agent-console/
                └── overview.json  # 主仪表盘（11 panels）
```

## 一键启动

```bash
# 启动 backend + frontend + prometheus + grafana
docker compose up -d

# 访问：
# - 应用：    http://localhost
# - Prometheus: http://localhost:9090
# - Grafana:    http://localhost:3000（admin / admin）
```

## Prometheus 关键指标说明

后端 `/metrics` 端点合并两套指标：

### 业务层（otel_exporter.py 维护）

| 指标 | 类型 | 用途 |
|---|---|---|
| `llm_token_usage_total{model, kind}` | Counter | LLM token 用量（按 model × kind 分类）|
| `agent_switch_latency_seconds` | Histogram | Agent 切换耗时 |
| `sandbox_execution_duration_seconds{tool, status}` | Histogram | 沙箱执行耗时 |
| `hitl_decisions_total{decision, tool}` | Counter | HITL 决策计数 |

### HTTP / SSE 协议层（prom_http_metrics 中间件维护）

| 指标 | 类型 | 用途 |
|---|---|---|
| `http_requests_total{method, route, status}` | Counter | 请求计数 |
| `http_request_duration_seconds{method, route}` | Histogram | 请求耗时分布 |
| `http_requests_in_progress{method, route}` | Gauge | 在途请求数 |
| `http_request_size_bytes` / `http_response_size_bytes` | Histogram | body 大小分布 |
| `sse_active_connections{route}` | Gauge | 活跃 SSE 连接数 |
| `sse_bytes_sent_total{route}` | Counter | SSE 已发字节 |
| `sse_events_sent_total{route, event_type}` | Counter | SSE 已发事件数 |
| `sse_connection_duration_seconds` | Histogram | SSE 连接时长 |

## Grafana 仪表盘

访问 http://localhost:3000 → Dashboards → AI Agent Console → Overview：

11 个 panel：
1. **Backend Status** —— `up{job="ai-agent-backend"}`（红/绿）
2. **SSE Active Connections** —— 活跃 SSE 总数
3. **5xx Error Rate (5m)** —— 错误率百分比
4. **P95 Latency (5m)** —— 全站 P95
5. **Request Rate by Route** —— 按路由分类的 req/s
6. **Request Latency by Route** —— p50/p95/p99 × route
7. **SSE Bytes Sent** —— SSE 吞吐
8. **SSE Active Connections by Route** —— 按路由活跃数
9. **LLM Token Usage Rate** —— token 消耗趋势
10. **Agent Switch Latency (P95)** —— Agent 切换延迟
11. **HITL Decisions** —— 决策计数

## 告警规则

`alerting_rules.yml` 定义了 10+ 告警：

| 严重度 | 规则 | 触发条件 |
|---|---|---|
| critical | BackendDown | scrape 失败 1min |
| critical | HighErrorRate | 5xx > 5% 持续 2min |
| warning | SlowRequests | P95 > 5s 持续 5min |
| warning | SSEConnectionsSpike | SSE > 100 持续 5min |
| warning | SSENoTraffic | SSE 字节吞吐为 0 但有 chat/stream 请求 10min |
| warning | LLMTokenSpike | token 消耗 > 100k/h 持续 15min |
| warning | HighAgentSwitchLatency | Agent 切换 P95 > 3s |
| warning | SandboxExecTimeout | 沙箱超时出现 |
| warning | HITLRejectSpike | HITL 拒绝率突增 |

启用告警：
1. 在 `prometheus.yml` 中取消注释 `rule_files: ["alerting_rules.yml"]`
2. 部署 Alertmanager（参考 docker-compose 加一个 alertmanager service）
3. 配 Slack webhook：`alertmanager.yml` 加 receivers

## 自定义 Target（file_sd）

往 `monitoring/targets/*.json` 扔一个 JSON：

```json
[
  {
    "targets": ["my-service:9090"],
    "labels": {
      "service": "my-service",
      "env": "staging"
    }
  }
]
```

Prometheus 每 30s 自动 reload。

## 持久化

- **prometheus_data**：30 天 TSDB 存储（默认）
- **grafana_data**：dashboard / 用户 / 凭证

调整保留期：`docker compose exec prometheus -- --storage.tsdb.retention.time=90d`（需重启）。

## 故障排查

```bash
# Prometheus 抓取目标状态
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'

# 实时查询
curl 'http://localhost:9090/api/v1/query?query=sse_active_connections'

# Grafana datasource health
curl -u admin:admin http://localhost:3000/api/datasources

# 查看 backend /metrics
curl http://localhost:8000/metrics | grep -E '^(http|sse)_'
```

## HTTPS 部署（P2-4）

详见 [nginx-ssl.conf](../nginx-ssl.conf) + [scripts/init-letsencrypt.sh](../scripts/init-letsencrypt.sh)。

简要步骤：
```bash
# 1) 签证书
DOMAIN=ai.example.com EMAIL=admin@example.com ./scripts/init-letsencrypt.sh

# 2) 启用 HTTPS
# 编辑 docker-compose.yml frontend service，挂载 nginx-ssl.conf + certbot 卷，加 443 端口
# 详见 scripts/init-letsencrypt.sh 输出

# 3) 重启
docker compose up -d --force-recreate frontend

# 4) 自动续期 cron
echo '0 3 * * * cd /path/to/project && bash scripts/renew-cert.sh >> /var/log/certbot-renew.log 2>&1' | sudo crontab -
```

## 生产强化建议

1. **TLS 强化**：TLSv1.2 + TLSv1.3（Mozilla Intermediate）；不要用 TLSv1.0/1.1
2. **CSP / HSTS**：nginx 已加 HSTS（6 个月）；CSP 可后续加
3. **Grafana 鉴权**：生产关掉 `GF_AUTH_ANONYMOUS_ENABLED`，用 SSO
4. **持久化**：prometheus_data / grafana_data 走云盘 / NFS，不要 local volume
5. **告警通道**：Slack / PagerDuty / Email 至少两个
6. **审计**：所有 Prometheus / Grafana 操作进 audit log
7. **网络隔离**：prometheus / grafana 不进 ai-agent-net（已配置 monitor-net）
