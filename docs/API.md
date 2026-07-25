# API 参考 · API Reference

> 后端 FastAPI 暴露的所有端点。所有路径都以 `/api` 开头,默认监听 `http://localhost:8000`。
>
> **完整交互文档**:启动后端后访问 <http://localhost:8000/docs>(Swagger UI) 或 <http://localhost:8000/redoc>。
> **OpenAPI Schema**:<http://localhost:8000/openapi.json>(可导入 Postman / Insomnia / Apifox)。

---

## 目录
1. [健康 & 元信息](#1-健康--元信息)
2. [聊天 & 流式](#2-聊天--流式)
3. [模型 & API Key](#3-模型--api-key)
4. [Agent & 能力](#4-agent--能力)
5. [人机协同 HITL](#5-人机协同-hitl)
6. [规划 Plan](#6-规划-plan)
7. [记忆 Memory](#7-记忆-memory)
8. [Prompt 工程](#8-prompt-工程)
9. [上下文持久化](#9-上下文持久化)
10. [文件上传](#10-文件上传)
11. [可观测性](#11-可观测性)
12. [权限 Policy](#12-权限-policy)

---

## 通用约定
- 所有请求/响应均为 JSON,UTF-8。
- 流式端点使用 **SSE**(Server-Sent Events,`text/event-stream`)。
- 错误格式:
  ```json
  {"detail": "error message"}
  ```
  HTTP 状态码遵循 REST 惯例(200/201/204/400/401/403/404/409/422/500)。
- 鉴权:本地部署无需 token;生产环境建议前置 Nginx 反代 + BasicAuth 或 JWT(可由用户自行扩展)。

---

## 1. 健康 & 元信息

### `GET /api/health`
Liveness 检查。
```bash
curl http://localhost:8000/api/health
```
响应:
```json
{"status": "ok"}
```

### `GET /api/version`
```json
{"version": "2.0.0", "python": "3.12.4", "build": "2026-07-25"}
```

### `GET /`
返回单文件 HTML 主界面 `ai_agent/web/index.html`(若启用了 web_ui 集成)。

---

## 2. 聊天 & 流式

### `POST /api/chat`
非流式,返回完整回答。
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"你好","session_id":"s-1"}'
```
请求字段:
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `message` | string | ✓ | 用户输入 |
| `session_id` | string | ✗ | 会话 ID;不传则新建 |
| `stream` | bool | ✗ | false(本端点固定非流式) |

响应:
```json
{
  "session_id": "s-1",
  "reply": "你好!我是 AI Agent。",
  "tool_calls": [],
  "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
}
```

### `POST /api/chat/stream` (SSE)
流式输出,事件类型见下表。
```bash
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"分析一下 510300","session_id":"s-1"}'
```

SSE 事件类型:
| event | data 字段 | 含义 |
|---|---|---|
| `start` | `{"session_id":"s-1"}` | 流开始 |
| `thinking` | `{"text":"先查 ETF 信息..."}` | Agent 内部思考 |
| `chunk` | `{"text":"..."}` | 输出片段 |
| `tool_call` | `{"name":"get_etf_info","args":{"code":"510300"}}` | 工具调用 |
| `tool_result` | `{"name":"get_etf_info","result":{...}}` | 工具结果 |
| `safety` | `{"level":"warn|block","msg":"..."}` | 安全事件 |
| `error` | `{"message":"..."}` | 错误 |
| `complete` | `{"usage":{...},"session_id":"s-1"}` | 流结束 |

### `WebSocket /api/chat/stream`
双向流式连接,适合前端 assistant-ui。
```javascript
const ws = new WebSocket("ws://localhost:8000/api/chat/stream");
ws.send(JSON.stringify({message: "hi", session_id: "s-1"}));
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

### `POST /api/clear`
清空当前会话历史。
```bash
curl -X POST http://localhost:8000/api/clear \
  -H "Content-Type: application/json" \
  -d '{"session_id":"s-1"}'
```

---

## 3. 模型 & API Key

### `GET /api/models`
列出 11 家 Provider 的 70+ 模型(按 group 分组)。
```json
{
  "groups": [
    {"provider":"openai", "models":[{"id":"gpt-4o-mini","label":"GPT-4o mini"}, ...]},
    {"provider":"deepseek","models":[...]}
  ]
}
```

### `POST /api/api-key`
运行时设置 API Key(存内存,不写盘)。
```bash
curl -X POST http://localhost:8000/api/api-key \
  -H "Content-Type: application/json" \
  -d '{"provider":"deepseek","api_key":"sk-..."}'
```

### `GET /api/api-key/status`
查询当前 Key 是否配置(只返回是否设置,不返回 Key 本身)。
```json
{"providers": {"openai": true, "deepseek": false, ...}}
```

### `POST /api/model/switch`
切换主用 Provider + 模型(下一轮对话生效)。
```bash
curl -X POST http://localhost:8000/api/model/switch \
  -H "Content-Type: application/json" \
  -d '{"provider":"qwen","model":"qwen-turbo"}'
```

---

## 4. Agent & 能力

### `GET /api/agents`
列出已注册的 Sub-Agent。
```json
{"agents":[{"name":"summarize","capability":"summarize","status":"idle"}, ...]}
```

### `GET /api/capabilities`
工具能力清单(用于 Worker 注册与负载均衡)。
```json
{"tools":[{"name":"get_etf_info","category":"finance","risk":"low"}, ...]}
```

### `GET /api/load_stats`
负载均衡统计。
```json
{"round_robin": {...}, "random": {...}, "least_loaded": {...}}
```

---

## 5. 人机协同 HITL

### `GET /api/hitl/pending`
待审批列表。
```json
{"items":[{"id":"h-1","tool":"shell","args":{"cmd":"rm -rf /tmp/foo"},"risk":"high","created_at":"..."}]}
```

### `GET /api/hitl/history`
历史审批。

### `POST /api/hitl/decide`
批准 / 拒绝。
```bash
curl -X POST http://localhost:8000/api/hitl/decide \
  -H "Content-Type: application/json" \
  -d '{"id":"h-1","decision":"approve","reasoner":"user"}'
```

### `GET /api/hitl/stats`
审批统计。

### `POST /api/hitl/policy`
设置 HookPoint 策略。
```bash
curl -X POST http://localhost:8000/api/hitl/policy \
  -H "Content-Type: application/json" \
  -d '{"tool_pattern":"*shell*","action":"ASK"}'
```

---

## 6. 规划 Plan

### `POST /api/plan/create`
创建计划(Planner)。
```bash
curl -X POST http://localhost:8000/api/plan/create \
  -H "Content-Type: application/json" \
  -d '{"goal":"分析 510300 与 510500 的差异"}'
```

### `POST /api/plan/research` / `/api/plan/code`
直接调用 Research / Code 技能。

### `POST /api/plan/run`
按计划 ID 执行。
```bash
curl -X POST http://localhost:8000/api/plan/run \
  -H "Content-Type: application/json" \
  -d '{"plan_id":"p-1"}'
```

---

## 7. 记忆 Memory

### `POST /api/memory/remember`
写入记忆(用户视角,极简 API)。
```bash
curl -X POST http://localhost:8000/api/memory/remember \
  -H "Content-Type: application/json" \
  -d '{"content":"用户偏好 markdown 表格"}'
```

### `GET /api/memory/recall?session_id=s-1&limit=10`
召回最近记忆。

### `GET /api/memory/search?q=ETF&top_k=5`
语义检索。

### `DELETE /api/memory/forget?id=m-123`
删除指定记忆。

### `POST /api/memory/save` / `POST /api/memory/load`
手动持久化 / 加载记忆数据库(SQLite 文件)。

### `GET /api/memory/stats`
四类记忆统计。
```json
{"working":12, "episodic":34, "semantic":128, "procedural":5}
```

### `POST /api/memory/add`
直接添加(底层接口,带 type / scope)。

### `GET /api/memory/list`
列出所有记忆。

### `DELETE /api/memory/{memory_id}`
按 ID 删除。

---

## 8. Prompt 工程

### `GET /api/prompts`
列出所有 Prompt 模板 + 版本。
```json
{"prompts":[{"name":"default","versions":["1.0.0","2.0.0"],"active":"2.0.0"}]}
```

### `POST /api/prompts/rollback`
回滚到指定版本。
```bash
curl -X POST http://localhost:8000/api/prompts/rollback \
  -H "Content-Type: application/json" \
  -d '{"name":"default","version":"1.0.0"}'
```

### `GET /api/user-prompts` / `/api/user-prompts/rollback` / `/api/user-prompts/register` / `/api/user-prompts/render`
User Prompt 模板(few-shot / 安全改写)增删改查与渲染。

### `GET /api/user-prompts/export` (下载) / `POST /api/user-prompts/import` (上传)
模板导入导出,便于团队共享。

---

## 9. 上下文持久化

### `GET /api/context/sessions`
列出所有会话。

### `POST /api/context/sessions`
新建会话。
```bash
curl -X POST http://localhost:8000/api/context/sessions \
  -H "Content-Type: application/json" \
  -d '{"title":"我的项目"}'
```

### `GET /api/context/sessions/{session_id}`
获取会话元信息。

### `GET /api/context/sessions/{session_id}/summary`
获取自动摘要。

### `GET /api/context/sessions/{session_id}/entities`
提取的实体(ETF 代码 / 城市 / 日期 / 动作 / 查询类型)。

### `GET /api/context/sessions/{session_id}/messages`
原始消息列表。

### `GET /api/context/analytics`
上下文构建分析(token 预算分配、命中率)。

### `GET /api/context/search?q=...`
跨会话实体 / 消息检索。

### `GET /api/context/stats` / `/api/context/performance`
容量 / 性能指标。

### `POST /api/context/performance/reset`
清零性能指标。

---

## 10. 文件上传

### `POST /api/upload` (multipart/form-data)
```bash
curl -X POST http://localhost:8000/api/upload \
  -F "file=@README.md"
```
响应:
```json
{"name":"README.md","size":1234,"url":"/api/files/README.md","type":"text/markdown"}
```

### `GET /api/files/{name}`
下载 / 预览上传文件。

---

## 11. 可观测性

### `GET /api/events?limit=50`
事件流(JSON 数组)。
```json
{"events":[{"ts":"...","type":"llm_call","data":{"provider":"deepseek","latency_ms":420}}]}
```

### `GET /api/traces?limit=30`
链路追踪(嵌套调用树)。

### `GET /api/metrics/prometheus`
Prometheus 文本格式,可直接被 `prometheus.yml` 抓取。
```
# HELP ai_agent_llm_calls_total Total LLM invocations
# TYPE ai_agent_llm_calls_total counter
ai_agent_llm_calls_total{provider="deepseek",status="success"} 42
```

---

## 12. 权限 Policy

### `GET /api/policies`
列出所有权限策略。

### `POST /api/policy`
新增 / 更新策略。
```bash
curl -X POST http://localhost:8000/api/policy \
  -H "Content-Type: application/json" \
  -d '{"subject":"agent:default","tool":"*","action":"ALLOW"}'
```

### `POST /api/permission/enforce`
手动触发一次权限校验。

---

## 错误处理

所有端点统一返回:
```json
{"detail": "validation error: missing field 'message'"}
```
HTTP 状态码:
- `400` 参数错误
- `403` 权限拒绝
- `404` 资源不存在
- `409` 冲突(如回滚到非激活版本)
- `422` 请求体 / 参数校验失败
- `500` 内部错误(查看 `agent.log`)

---

## 示例脚本

### Python 一行调用
```python
import httpx, json
r = httpx.post("http://localhost:8000/api/chat/stream",
               json={"message":"你好"},
               timeout=30)
for line in r.iter_lines():
    if line.startswith("data:"):
        print(json.loads(line[5:]))
```

### JavaScript (浏览器 fetch + SSE)
```javascript
const es = new EventSource("/api/chat/stream", {withCredentials:true});
// 注:SSE 默认 GET,如需 POST 请用 fetch + ReadableStream 或 WebSocket 端点
```

### cURL 流式
```bash
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"上海天气"}'
```

---

## 速率限制

当前默认无全局速率限制(单机部署)。如需:
- 前置 Nginx `limit_req_zone`
- 或扩展 `ai_agent/rate_limit.py` 启用进程内令牌桶

---

## 版本兼容

| 后端版本 | API 兼容性 |
|---|---|
| v1.x → v2.0 | `/api/chat`、`/api/models`、`/api/chat/stream`、`/api/memory/*`、`/api/prompts/*`、`/api/hitl/*` 均向后兼容 |
| v2.0 新增 | `/api/context/*`、`/api/permission/enforce`、`/api/user-prompts/export` |

详细迁移指南见 [CHANGELOG.md](../CHANGELOG.md) 的 Migration Guide 章节。