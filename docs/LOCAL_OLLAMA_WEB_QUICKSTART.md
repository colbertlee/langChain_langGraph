# 本地 Ollama + Web 端 5 分钟极速联调指南

> 目标：用 5 分钟把 **本地 Ollama 小模型** + **web_console** + **FastAPI Agent** 三者打通，
> 并通过 3 个 Case 验证"简单对话 / 工具调用 / Checkpointer 状态恢复"完整链路。

适用：硬件资源有限、希望在本地反复测试 Agent 行为的开发者。

---

## 0. 准备（≤1 分钟）

确认已安装：

| 依赖 | 版本建议 | 检查命令 |
|---|---|---|
| Python | ≥ 3.10 | `python --version` |
| Node.js | ≥ 18 | `node --version` |
| Ollama | ≥ 0.3 | `ollama --version` |
| 8GB+ 显存（或 CPU 推理） | — | — |

确认目录结构（关键路径）：

```
langChain_langGraph/
├─ ai_agent/                  ← FastAPI 后端
│  ├─ app.py
│  └─ config.py
├─ web_console/               ← React 前端（Vite）
│  └─ src/pages/v2/ChatPage.tsx
└─ scripts/
   └─ verify_local_web.py     ← 本联调脚本
```

---

## 1. 启动 Ollama 并加载指定模型（≤1 分钟）

```bash
# 后台启动 Ollama（如已运行可跳过）
ollama serve

# 拉取小模型（任选其一；推荐 3B 级别，CPU 也能跑）
ollama pull qwen2.5:3b          # 中文友好
ollama pull llama3.2:3b         # Meta 3B
ollama pull gemma2:2b           # Google 2B

# 验证模型可推理
ollama run qwen2.5:3b "你好，用一句话自我介绍"
```

> ⚠️ 模型名要记住，后面切换模型时会用到。

---

## 2. 一键构建前端 + 启动 FastAPI（≤3 分钟）

### 2.1 配置后端 `.env`（首次需要）

```bash
cd ai_agent
cp .env.example .env       # 若 .env 已存在可跳过
```

`.env` 关键字段（Ollama 路径）：

```ini
# 本地 Ollama：OPENAI 兼容端点 + 不校验的占位 key
OPENAI_API_KEY=sk-placeholder-for-tests
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_API_KEY=ollama

# 切到 ollama 作为默认 provider
MODEL_PROVIDER=ollama
MODEL_NAME=qwen2.5:3b
```

### 2.2 构建 web_console

```bash
cd ../web_console
npm install                # 首次需要
npm run build              # 输出到 web_console/dist
```

### 2.3 启动 FastAPI

```bash
cd ../ai_agent
python app.py              # 默认监听 0.0.0.0:8000
```

启动日志关键行（应能看到）：

```
web_console dist mounted at /console from .../web_console/dist
Using small-model prompt template (v3.0.0)   ← Ollama 自动切换
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 2.4 打开 Web

浏览器访问：

- **http://localhost:8000/console/** ← Vite 构建产物（推荐）
- **http://localhost:8000/** ← 兼容老版 web/index.html
- **http://localhost:8000/api/health** ← 健康检查

看到 ChatPage 即联调成功。

---

## 3. 三个 Case 一键验证

```bash
cd ..
python scripts/verify_local_web.py
```

预期输出（精简版）：

```
==== verify_local_web.py · target=http://localhost:8000 ====
✓ FastAPI 健康检查通过 (HTTP 200)

[Case 1] 简单对话 (POST /api/chat)
  ✓ HTTP 200, assistant len=128 preview='Qwen2.5 3B：我是...'
[Case 2] SSE 流式聊天 (POST /api/chat/stream)
  events=12 types={'chunk':4, 'complete':1, 'end':1} chunks=4 dt=8.3s ...
[Case 3] Checkpointer 恢复 (同 session_id 两次对话)
  turn2 preview='你刚才让我记住的数字是 7421。'

RESULT: 4/4 cases passed
```

### Case 1 — 简单对话

- **目的**：验证 Ollama → FastAPI → Web 端最基础的链路。
- **手动验证**：
  1. 打开 `/console/`；
  2. 输入框写："你好，自我介绍一句话" → 回车；
  3. 期望：看到流式打字机效果（逐字生成），不是一次性吐整段。

### Case 2 — 工具调用（SSE）

- **目的**：验证 LangGraph 的 tool_calls 事件能流到前端。
- **手动验证**：
  1. 输入："用一句话总结 LangChain 的核心设计"；
  2. 右侧 "工具调用时间线" 应出现调用（如 `python_exec` / `summarize` 等）；
  3. 鼠标悬停工具名 → 可展开查看 Arguments / Result。

### Case 3 — Checkpointer 状态恢复

- **目的**：验证 LangGraph SqliteSaver checkpointer 是否生效。
- **手动验证**：
  1. 第一轮输入："请记住数字 7421"；
  2. 第二轮输入："刚才那个数字是多少？"；
  3. 期望：模型回答包含 "7421"。
  4. 顶部点 **重置** → 重复上面两步 → 期望第二次答不出"7421"（checkpointer 已清）。

> 想在不同会话间对比：
> - **新会话** = 仅前端换 sessionId（checkpointer 数据各自隔离）
> - **重置** = 清前端 + 清后端 checkpointer + 重建 session

---

## 常见问题

### Q1: Ollama 报 "connection refused"
检查 `OLLAMA_BASE_URL` 是否正确，默认 `http://localhost:11434/v1`。
Linux/macOS 一般 OK；Windows WSL2 里要换成 `http://localhost:11434/v1` 或宿主 IP。

### Q2: 模型吐字很慢 / 时间长
- 3B 模型 CPU 推理 ≈ 5-15 token/s，正常。
- 想更快：拉 2B 模型（如 `gemma2:2b`），或在 .env 里改 `MODEL_NAME`。
- Tools 页 → 模型 chip 可热切换。

### Q3: 工具调用没出现
- 小模型对工具调用 JSON 模式遵循度低，会"忘记"调用。
- 已在 prompt v3.0.0 里**关闭强制 CoT**，但工具调用本身依赖 LLM。
- 想要更稳的工具调用：把 `MODEL_NAME` 换成 `qwen2.5-coder:7b` 或换云端模型（GPT-4o-mini）。

### Q4: 前端 401 / API Key 报错
- 检查 `OPENAI_API_KEY` 是否仍是占位符（`sk-placeholder` / `your_`）。
- `app.py` 默认启用 placeholder 短路 → 未配置时 agent 不初始化 → 前端走降级提示。
- 在 .env 填真实 key 后 **重启** `python app.py`。

### Q5: Checkpointer 测试"通过"了但回答明显没上下文
- 可能走了 fallback → 没有真正调 LLM（key 是占位符）。
- 后端日志搜 `Agent initialized with ollama/...`：成功才会有这一行。

---

## 调试小抄

| 想看什么 | 怎么做 |
|---|---|
| 后端实时日志 | `tail -f ai_agent/agent.log` 或 FastAPI 控制台 stdout |
| 前端 SSE 原始流 | DevTools → Network → /api/chat/stream → EventStream tab |
| Checkpointer 内容 | `sqlite3 ai_agent/memory.db ".schema"`，再 `SELECT * FROM checkpoints LIMIT 5;` |
| Prompt 当前版本 | `curl http://localhost:8000/api/prompts` 看 `active_version`；用 `?prompts/rollback` 切换 |
| 强制 v2.0.0 prompt | `export AI_AGENT_PROMPT_VERSION=2.0.0` 后重启后端 |
| 强制 v3.0.0 (默认小模型) | `export AI_AGENT_PROMPT_VERSION=3.0.0` 或不设（Ollama 自动选） |

---

## 5 分钟复盘

✅ 第 1 分钟：装好 Ollama + 拉模型
✅ 第 2 分钟：配 `.env` + `npm run build`
✅ 第 3 分钟：起 `python app.py`
✅ 第 4 分钟：浏览器开 `/console/` + 简单对话
✅ 第 5 分钟：跑 `verify_local_web.py` → 4/4 PASS

如果 Case 1 失败 → 大概率是 Ollama 未启动或 `.env` 没切到 `MODEL_PROVIDER=ollama`。
如果 Case 3 失败 → 大概率是 `OPENAI_API_KEY` 仍是占位符，agent 没真正初始化。
