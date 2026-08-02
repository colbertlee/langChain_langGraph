# Web UI 上线指南（Day 16）

AI Agent 提供两类 Web UI：

1. **主控制台**（含聊天 / 模型切换 / 记忆 / Prompts / 监控 等全功能）
2. **Doctor 面板**（仅环境与回归诊断，单独端口隔离）

本文说明如何"上线"，含端口、安全、CI。

---

## 一、端口与路由

### 主控制台（默认 `8000`）

由 `app.py` 启动，FastAPI：

| 路径 | 用途 |
|------|------|
| `/` | 单页前端入口（`web/index.html`） |
| `/dashboard` | 监控仪表板（`web/dashboard.html`） |
| `/legacy` | 老版本 web UI（向后兼容） |
| `/diagnose` | Doctor 别名 / 页面 |
| `/api/index` | 侧栏导航清单（JSON） |
| `/api/health` | 简易存活检查 |
| `/api/doctor` | Doctor JSON |
| `/api/evals/run` | 触发回归（POST） |
| `/api/evals/history` | 回归历史（GET） |

启动：
```bash
uvicorn app:app --host 0.0.0.0 --port 8000
# 或 ai-agent
```

### Doctor 面板（独立 `8088`）

**只暴露诊断面（doctor / health / evals history）**，不暴露 agent runtime。
适合"给 SRE / 监控 / 审计" 独立部署。

启动：
```bash
python scripts/serve_diagnose.py
# 或 DOCTOR_PORT=9090 python scripts/serve_diagnose.py
```

访问：
- 页面：`http://<host>:8088/web/doctor`
- JSON：`http://<host>:8088/api/doctor`
- 历史：`http://<host>:8088/api/evals/history?limit=20`

---

## 二、安全建议

### 主控制台（8000）

- **绑 0.0.0.0 + 反向代理 + TLS**：直接暴露在公网危险。务必走 nginx/caddy。
- **鉴权**：当前不带鉴权，假设仅内网访问。若需外网，加：
  - OAuth 代理（如 oauth2-proxy）
  - HTTP Basic（`uvicorn ... --ssl-keyfile ... --ssl-certfile ...`）
  - 网关层 JWT
- **CORS**：默认已开启 `allow_origins=["*"]`（开发友好），生产改为具体域名。

### Doctor 面板（8088）

- 给监控 / 审计专用即可 —— **无需鉴权**，但**禁止绑 0.0.0.0**（除非走反向代理）：
  ```bash
  # 仅内网
  DOCTOR_HOST=127.0.0.1 python scripts/serve_diagnose.py
  ```
- 因为它能跑 evals、读 `/api/doctor`（含 token 占位符信息），开放公网等于泄密。
- 推荐做法：
  ```bash
  # nginx 把 /diagnose 路径转发到 8088
  location /diagnose/ {
      proxy_pass http://127.0.0.1:8088/;
      allow 10.0.0.0/8;     # 公司内网
      deny all;
  }
  ```

---

## 三、CI / Docker 场景

### Docker

```dockerfile
EXPOSE 8000 8088
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port 8000 & \
     python scripts/serve_diagnose.py & \
     wait"]
```

### Kubernetes

```yaml
ports:
  - name: ui
    containerPort: 8000
  - name: diagnose
    containerPort: 8088
livenessProbe:
  httpGet: { path: /api/health, port: 8000 }
readinessProbe:
  httpGet: { path: /api/doctor, port: 8088 }
```

### CI / nightly

- 主控制台的 `8000` 不必总在；nightly-evals 直接通过 `python -m doctor --json` 跑结果。
- Doctor 面板 8088 可选，便于临时调试。

---

## 四、端点 Quick Reference

| 路径 | 方法 | 用途 |
|------|------|------|
| `/` | GET | 单页前端 |
| `/dashboard` | GET | 监控面板 |
| `/diagnose` | GET | Doctor 页面 |
| `/web/doctor` | GET | Doctor 页面（同 /diagnose） |
| `/api/index` | GET | 路由清单 |
| `/api/health` | GET | 存活检查 |
| `/api/doctor` | GET | Doctor JSON `{exit_code, checks, summary}` |
| `/api/evals/run` | POST | 触发回归 `{all: true}` 或 `{case: "safety"}` |
| `/api/evals/history?limit=N` | GET | 最近 N 次回归 |

---

## 五、FAQ

### Q: 直接访问 `/web/doctor` 报错 404

答: `doctor.html` 不存在。检查 web 目录：
```bash
ls web/doctor.html
```

### Q: `/api/doctor` 返回 exit_code=1，但实际没问题

答: 可能是 doctor 检查太严。比如当前环境没配 API Key，doctor 报 FAIL 是预期的；
若想只看 warning → 改为：
```python
ok_count, fail_count = summary["ok"], summary["fail"]
if fail_count == 0:
    # 视为健康
    pass
```

### Q: 8088 端口被占用

```bash
DOCTOR_PORT=9090 python scripts/serve_diagnose.py
```

### Q: 想把 evals 触发做成"点击 → 跑 → 自动跳结果"

参考 web/doctor.html 中 `runEvals()` 函数（已实现 fetch + alert 完成）。

### Q: 想自动打开浏览器？

启动后：
```bash
python scripts/serve_diagnose.py &
sleep 2
python -m webbrowser "http://localhost:8088/web/doctor"
```
