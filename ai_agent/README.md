# AI Agent 智能助手

> 基于 LangChain 1.x + LangGraph 构建的多功能 AI Agent：多 Provider、容错、结构化记忆、多 Agent 编排、人机协同、Skill 框架、ETF 金融分析、MCP、安全、可观测性。可作为 Python 包 / FastAPI 服务 / PyInstaller 桌面二进制 / Docker 镜像使用。

[![Backend CI](https://img.shields.io/github/actions/workflow/status/colbertlee/langChain_langGraph/backend-ci.yml?branch=main&label=backend%20ci)](https://github.com/colbertlee/langChain_langGraph/actions/workflows/backend-ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![PyPI](https://img.shields.io/pypi/v/ai-agent.svg)](https://pypi.org/project/ai-agent/)
[![Docker Image](https://ghcr.io/colbertlee/ai-agent-console/badge)](https://ghcr.io/colbertlee/ai-agent-console)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

## 📚 文档导航

> 🎯 **一句话找文档**:
> - "我第一次用" → [`USAGE.md`](USAGE.md)
> - "我想升级版本" → [`UPGRADE.md`](UPGRADE.md)
> - "我想看最新发布说明" → [`RELEASE_NOTES.md`](RELEASE_NOTES.md)

| 文档 | 适合谁 | 阅读时长 | 难度 |
|---|---|---|---|
| 🆕 **[`USAGE.md`](USAGE.md)** | 最终用户 / 新手 | 25 分钟(速读 5 分钟) | ⭐ |
| 🆕 **[`UPGRADE.md`](UPGRADE.md)** | 运维 / 老用户 | 15 分钟(速读 5 分钟) | ⭐⭐⭐ |
| 🚀 **[`RELEASE_NOTES.md`](RELEASE_NOTES.md)** | 所有用户 | 8 分钟(速读 3 分钟) | ⭐⭐ |
| 📖 **[`FEATURES_GUIDE.md`](FEATURES_GUIDE.md)** | 想深入了解功能 | 30 分钟 | ⭐⭐⭐ |
| 🔧 **[`agent_middleware.md`](agent_middleware.md)** | 开发者 | 20 分钟 | ⭐⭐⭐⭐ |
| 📝 **[`CHANGELOG.md`](CHANGELOG.md)** | 所有用户 | 按需查阅 | - |
| 📋 **[`README.md`](README.md)** | 所有人 | 本文 | - |

> 💡 **建议阅读顺序**:新用户 `USAGE.md → README → FEATURES_GUIDE → agent_middleware`;老用户 `RELEASE_NOTES → UPGRADE → CHANGELOG`。

## 目录

- [项目简介](#项目简介)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [安装步骤](#安装步骤)
- [配置说明](#配置说明)
- [使用方法](#使用方法)
- [核心功能](#核心功能)
  - [多级容错机制](#多级容错机制)
  - [结构化上下文管理](#结构化上下文管理)
  - [统一记忆存储](#统一记忆存储)
  - [多 Agent 编排](#多-agent-编排)
  - [协商与竞价](#协商与竞价)
  - [可靠性机制](#可靠性机制)
  - [能力注册中心](#能力注册中心)
  - [Prompt 工程化](#prompt-工程化)
  - [Skill 系统](#skill-系统)
- [工具说明](#工具说明)
  - [LangChain 工具](#langchain-工具)
  - [MCP 工具](#mcp-工具)
  - [ETF 金融工具](#etf-金融工具)
- [安全功能](#安全功能)
- [可观测性与人机协同](#可观测性与人机协同)
- [Web UI 与 API](#web-ui-与-api)
- [桌面打包](#桌面打包)
- [PyPI 发版](#pypi-发版)
- [扩展指南](#扩展指南)
- [常见问题](#常见问题)
- [测试](#测试)
- [版本历史](#版本历史)

## 项目简介

`ai_agent/` 是 [LangChain × LangGraph AI Agent](../README.md) 的 Python 后端子项目。它把"一个能用的 Agent"升级成"一个能上线生产的 Agent"：

- **多轮对话记忆**：基于 LangGraph `SqliteSaver` 持久化，配合 `MemoryStore` 四类记忆统一管理。
- **多 Provider / 多模型**：内置 11 家 LLM 厂商、70+ 模型；可声明式主备切换 + Standby 预热。
- **五层容错**：任何 LLM 调用失败都不会让前端"空白或崩溃"。
- **结构化上下文**：自动实体提取 + 自动摘要 + 按重要性分配 token 预算。
- **多 Agent 编排**：Supervisor / Parallel / Sequential / Hierarchical / Fanout 五种模式。
- **人机协同（HITL）**：工具执行前可强制走人工审批，前端"审批中心"批准/拒绝。
- **Skill 框架**：可插拔技能（深度研究、代码文档、PPT 大纲、论文审阅、图表可视化）。
- **MCP 协议**：内置 14 个 MCP 工具，可一键接入 GitHub/Brave/Slack/SQLite 等官方 MCP Server。
- **RAG 知识库**：Chroma + 多 Embedding（OpenAI / 智谱 / MiniMax / Jina）。
- **ETF 金融分析**：7 个工具（信息 / 行情 / 历史 / 知识 / 对比 / 综合 / 图表）。
- **安全纵深**：Prompt Injection 检测 + AST 白名单表达式求值 + 危险命令拦截 + 输出脱敏 + RBAC 权限 + 沙箱。
- **可观测性**：事件流 + Trace + Prometheus 文本 + Fail Log + A/B 测试。
- **多渠道分发**：PyPI 包 / Docker 镜像 / Scoop / Homebrew / Windows+Linux+macOS PyInstaller 二进制。

返回总仓：[`README.md`](../README.md)。

## 技术栈

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.11+（推荐 3.12） | 编程语言 |
| LangChain | 0.2 / 1.x | AI Agent 开发框架 |
| LangGraph | 1.x | 工作流编排引擎 |
| langchain-openai | 0.1+ | OpenAI 兼容协议适配（覆盖 9/11 Provider） |
| langchain-chroma | 0.1+ | Chroma 向量库 |
| langchain-text-splitters | 0.2+ | 文档切分 |
| langgraph-checkpoint-sqlite | 0.2+ | SQLite 持久化 Checkpointer |
| ChromaDB | 0.4+ | 本地向量数据库 |
| FastAPI | 0.110+ | Web API |
| Uvicorn | 0.27+ | ASGI 服务器 |
| MCP SDK | 1.x | Model Context Protocol |
| SQLite3 | 内置 | 结构化数据存储 |
| pytest | 8+ | 测试框架 |
| ruff | 0.3+ | lint + format |

依赖完整列表：[`requirements.txt`](requirements.txt)、[`requirements-dev.txt`](requirements-dev.txt)。

## 项目结构

```
ai_agent/
├── agent.py                     # AIAgent 核心（多 Provider、Sub-Agent、主备切换）
├── app.py                       # 统一 FastAPI 入口（~40 端点，SSE + WebSocket）
├── api.py / web_ui.py           # 旧版 API（向后兼容，已合并进 app.py）
├── main.py                      # CLI 入口（双击 exe 进 REPL）
├── cli.py                       # console_script：ai-agent-test / ai-agent-lint / ai-agent-format
├── config.py                    # 11 家 Provider × 70+ 模型 + 全局配置
├── tools.py                     # LangChain 工具集（18+，含 7 个 ETF）
├── mcp_server.py / mcp_tools.py # MCP 协议 + 14 个内置 MCP 工具
├── skills.py                    # Skill 系统（5 个内置 Skill）
├── rag.py                       # RAG 知识库模块
├── security.py                  # 输入/输出安全 + Prompt Injection + AST 白名单
│
├── # ───────── 核心增强模块 ─────────
├── llm_reliability.py           # 五层容错 + 主备 + Standby 预热
├── context_manager.py           # 结构化上下文管理（实体 + 摘要 + token 预算）
├── memory_store.py              # 统一记忆存储（WORKING/EPISODIC/SEMANTIC/PROCEDURAL）
├── multi_agent.py               # 多 Agent 编排（5 模式）
├── negotiation.py               # 协商 + 拍卖（第一价格/第二价格/英式/荷兰式）
├── reliability.py               # RetryPolicy + CircuitBreaker + DeadLetterQueue
├── capability.py                # 能力注册中心 + 负载均衡
├── message_protocol.py          # 消息协议
├── message_bus.py               # 本地消息总线
├── distributed_bus.py           # 分布式消息总线（Redis）
├── pub_sub_scenarios.py         # Pub/Sub 场景
├── observability.py             # 可观测性（事件 / Trace / Prometheus）
├── monitor.py                   # 性能监控（token / 耗时 / 错误率）
│
├── # ───────── 辅助模块 ─────────
├── ab_testing.py                # A/B 测试框架
├── adaptive_threshold.py        # 自适应阈值
├── human_in_loop.py             # HITL 人机协同
├── multimodal.py                # 多模态
├── audio_pipeline.py / audio_streaming.py / audio_semantic.py / audio_feedback.py
├── planner.py                   # 任务规划器
├── plugin_manager.py            # 插件管理器
├── sandbox.py                   # 沙箱环境
├── state_manager.py             # 状态管理器
├── streaming.py                 # 流式处理
├── task_intent.py               # 任务意图识别
├── task_scheduler.py            # 任务调度器
├── permission.py                # 权限（RBAC）
├── prompt_registry.py           # System Prompt 模板注册 + 版本化 + 回滚
├── user_prompt_registry.py      # User Prompt 模板注册 + few-shot + 安全改写
├── sqlite_tools.py              # SQLite 工具
├── github_tools.py / gitee_tools.py  # GitHub / Gitee 集成
│
├── # ───────── 资源 ─────────
├── web/                         # Web UI（单文件 HTML 工作台 + 测试中心）
├── prompts/                     # Prompt 模板目录（打包后置 _internal）
├── knowledge_base/              # 内置 RAG 文档（python_intro.txt）
│
├── # ───────── 测试 ─────────
├── tests/                       # pytest 全量测试（~96 用例）
│   ├── test_agent.py / test_agent_run.py / test_multi_agent.py
│   ├── test_prompt_registry.py / test_prompts_api.py
│   ├── test_user_prompt_registry.py / test_user_prompts_api.py
│   ├── test_stream_events.py / test_app_sse.py / test_app_ws.py
│   ├── test_models_registry.py
│   ├── test_skills.py / test_mcp_tools.py / test_sqlite_tools.py
│   ├── test_rag.py / test_memory_store.py / test_permission.py
│   ├── test_security.py / test_basic_endpoints.py / test_upload.py
│   ├── test_audio_pipeline.py / test_audio_extended.py
│   ├── test_respx_example.py / test_akshare_respx.py
│   └── legacy/                  # 历史迁移用例
│
├── # ───────── 文档 ─────────
├── docs/
│   ├── AGENT_ARCHITECTURE_ROADMAP.md
│   ├── SPEC_CONTEXT_PERSISTENCE.md
│   └── STAGE_A_DELIVERY.md
│
├── # ───────── 桌面分发 ─────────
├── package/
│   ├── windows/                 # 完整 Windows 桌面包（ai-agent.exe + .bat + 内置 KB）
│   └── linux/                   # 完整 Linux 桌面包（ai-agent + .sh + 内置 KB）
│
├── # ───────── 产物 / 构建脚本 ─────────
├── htmlcov/ / coverage.xml      # pytest-cov 覆盖率产物
├── ai_agent.spec                # PyInstaller 跨平台 spec（同一份 spec 三端通用）
├── build_windows.ps1            # Windows 一键打包
├── build_linux.sh               # Linux 一键打包
├── build_all.ps1                # 在 Docker 内交叉打 Linux 包（可选）
├── package_dist.ps1             # 把 package/{windows,linux} 打成 zip / tar.gz
├── test_package.ps1 / test_package.sh  # 单平台端到端冒烟
├── test_all.ps1                 # 全平台冒烟（spec 语法 / workflow lint / install.bat / run.bat / ELF / tar.gz 文件数）
│
├── # ───────── PyPI / Lint ─────────
├── pyproject.toml               # PyPI 元数据 + console_scripts + pytest + ruff + semantic-release
├── requirements.txt / requirements-dev.txt
├── .env.example / mcp_config.json
│
├── # ───────── 文档 ─────────
├── README.md                    # 本文件
├── FEATURES_GUIDE.md            # 功能用户指南
├── CHANGELOG.md                 # 项目更新日志
├── RELEASE_NOTES.md / RELEASE_SUMMARY.md / INSPECTION_REPORT.md
│
└── homebrew-tap-ai-agent.rb / scoop-bucket-ai-agent.json  # Tap / Bucket 模板
```

## 安装步骤

### 1. 进入目录

```bash
cd ai_agent
```

### 2. 创建虚拟环境（推荐）

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt

# 可选：装开发依赖
pip install -r requirements-dev.txt
# 或
pip install -e ".[dev]"
```

### 4. 准备环境变量

```bash
cp .env.example .env
# 编辑 .env，至少填一个 LLM_API_KEY（详见下方"配置说明"）
```

### 5. 验证

```bash
python -c "from agent import AIAgent; print('import ok')"
python app.py   # 监听 http://localhost:8000
# 浏览器访问 http://localhost:8000/api/health
```

## 配置说明

### 环境变量配置

`ai_agent/.env.example` 已经列全所有可配项。下表为常用关键变量（完整 11 家 Provider 的 base URL 见 [`config.py`](config.py)）：

```env
# ============ LLM Provider（任选一家填一个 Key 即可） ============
OPENAI_API_KEY=your_openai_api_key
DEEPSEEK_API_KEY=your_deepseek_key        # 推荐国产首选，性价比
QWEN_API_KEY=your_qwen_key                # 中文最强
ZHIPU_API_KEY=your_zhipu_key              # GLM-5.2 / 推理 Z1
MOONSHOT_API_KEY=your_moonshot_key        # Kimi K3 / 长上下文
MINIMAX_API_KEY=your_minimax_key          # MiniMax-M3
BAIDU_API_KEY=your_baidu_key              # 文心一言（需 secret key）
BAIDU_SECRET_KEY=your_baidu_secret
SPARK_APP_ID=your_spark_app_id            # 讯飞星火（需 app_id + secret）
SPARK_API_KEY=your_spark_api_key
SPARK_SECRET_KEY=your_spark_secret
DOUBAO_API_KEY=your_doubao_key            # 字节豆包（火山方舟 ARK）
HUNYUAN_API_KEY=your_hunyuan_key          # 腾讯混元
SILICONFLOW_API_KEY=your_siliconflow_key  # 硅基流动（聚合多模型）

# ============ 模型选择 ============
MODEL_PROVIDER=deepseek                   # openai / deepseek / qwen / zhipu / moonshot ...
MODEL_NAME=deepseek-chat                  # 具体模型名；不填用各 Provider 默认

# ============ RAG Embedding ============
EMBEDDING_API_KEY=                        # 默认复用 OPENAI_API_KEY
EMBEDDING_MODEL_TYPE=openai               # openai / zhipu / minimax / jina

# ============ MCP / 第三方 ============
GITHUB_PERSONAL_ACCESS_TOKEN=             # GitHub MCP（仓库 / Issue / PR）
SERPAPI_API_KEY=                          # search_web 工具

# ============ 运行时 ============
PORT=8000
LOG_LEVEL=INFO
AI_AGENT_DISABLE_PLACEHOLDER_CHECK=1      # 0=关闭占位符短路，让 LLM 真的初始化
```

详细 Provider base_url 与模型清单：[`config.py`](config.py) `MODEL_VERSIONS` + `PROVIDER_META`。

## 使用方法

### 方法 1 · FastAPI Web 服务（推荐）

```bash
python app.py          # 默认 0.0.0.0:8000
PORT=9000 python app.py
```

打开浏览器：
- `http://localhost:8000/` —— 内嵌主界面（`ai_agent/web/index.html`）
- `http://localhost:8000/dashboard` —— 仪表板（如果有 dashboard.html）
- `http://localhost:8000/legacy` —— 兼容入口

> 主界面是单文件 HTML；想看 React 控制台版本，去仓库根的 `web_console/`（详见 [../README.md §2.4 选项 B](../README.md#24-选择前端推荐先看主界面)）。

### 方法 2 · CLI

```bash
python main.py
# 或打包后的桌面二进制
./ai-agent        # Linux / macOS
ai-agent.exe      # Windows
```

CLI 内置命令：`exit`、`quit`、`clear`、`help`、`tools`、`history`、`version`。

### 方法 3 · 编程调用

```python
from agent import AIAgent

agent = AIAgent()
agent.init_agent()

# 同步
print(agent.run("你好"))

# 流式
for chunk in agent.run_stream("你好"):
    print(chunk, end="")
```

### 方法 4 · 桌面二进制（最终用户）

```bash
# Windows
cd package\windows
install.bat        # 第一次生成 .env
notepad .env       # 填 OPENAI_API_KEY
run.bat            # 启动 CLI
run-web.bat        # 启动 Web 服务

# Linux / macOS
cd package/linux
chmod +x ai-agent install.sh run.sh
./install.sh
nano .env          # 填 LLM_API_KEY
./run.sh           # 启动 CLI
./run-web.sh       # 启动 Web
```

> 不需要 Python 环境。所有依赖（LangChain / LangGraph / MCP / ChromaDB / numpy 等）都已打入 `_internal/`。

### 方法 5 · 容器

```bash
docker pull ghcr.io/colbertlee/ai-agent-console:latest
docker run -d -p 8000:8000 -e OPENAI_API_KEY=sk-xxx ghcr.io/colbertlee/ai-agent-console:latest
```

或本仓库根 `docker compose up -d --build`。

## 核心功能

### 多级容错机制

五层容错栈确保任何 LLM 调用失败都不导致空白或崩溃：

| 层级 | 组件 | 功能 |
|---|---|---|
| 1 | Timeout | LLM 调用超时控制 |
| 2 | RetryPolicy | 指数退避 + 抖动重试 |
| 3 | FallbackChain | 多 Provider 自动切换 |
| 4 | CircuitBreaker | 单 Provider 熔断（连续失败熔断 60s） |
| 5 | GracefulDegradation | 全部失败时基于记忆/上下文生成骨架回答 |

**默认 Fallback 顺序**：OpenAI → DeepSeek → Qwen → Moonshot → 智谱 → MiniMax → 豆包 → Hunyuan → SiliconFlow。

**主备模型**：可声明 Primary + 多个 Standby，StandbyWarmupService 后台预热，故障自动切换。

```python
# 示例：获取容错状态
agent = AIAgent()
print(agent.get_fail_log_summary())
print(agent.get_standby_status())

# 自定义主备
agent.set_primary_standby(
    primary={"provider": "openai", "model": "gpt-4o-mini"},
    standbys=[
        {"provider": "deepseek", "model": "deepseek-chat"},
        {"provider": "qwen", "model": "qwen-turbo"},
    ],
    enable_warmup=True,
)
```

详见 [`llm_reliability.py`](llm_reliability.py)。

### 结构化上下文管理

自动从对话中提取实体并构建上下文：

**实体类型**：
- ETF 代码（6 位数字）
- 城市名称
- 日期和时间
- 动作关键词
- 查询类型

**上下文构建顺序**：
1. 会话摘要
2. 相关实体
3. 工具调用历史
4. 用户偏好
5. 对话历史

**特性**：
- 基于内容哈希的上下文缓存
- 按重要性权重分配 token 预算
- 自动滚动归档旧消息
- Token 计数使用 0.35 系数（中英混合优化）

```python
agent = AIAgent()
print(agent.get_session_analytics())
print(agent.get_context_summary())
print(agent.get_entities(entity_type="etf"))
```

详见 [`context_manager.py`](context_manager.py) 和 [`docs/SPEC_CONTEXT_PERSISTENCE.md`](docs/SPEC_CONTEXT_PERSISTENCE.md)。

### 统一记忆存储

四层记忆体系：

| 类型 | 说明 | 特点 |
|---|---|---|
| WORKING | 工作记忆 | 当前交互，衰减机制 |
| EPISODIC | 情景记忆 | 会话片段归档 |
| SEMANTIC | 语义记忆 | 向量检索 |
| PROCEDURAL | 程序记忆 | 操作流程沉淀 |

**重要性分级**：LOW / MEDIUM / HIGH / CRITICAL

**自动整合**：`MemoryConsolidator` 每 5 轮触发，把短期记忆去重后写入长期。

```python
agent.memory_store.add(
    content="用户偏好低风险投资",
    session_id=agent.current_session_id,
    importance=MemoryImportance.HIGH.value,
)
```

Web 端极简接口：`POST /api/memory/add`（只需 content，scope=global）+ `GET /api/memory/list` + `DELETE /api/memory/{id}`。

详见 [`memory_store.py`](memory_store.py)。

### 多 Agent 编排

| 模式 | 说明 | 适用场景 |
|---|---|---|
| SUPERVISOR | 主 Agent 协调专业 Agent | 任务需要分类派发 |
| PARALLEL | 多 Agent 同时跑，取最优 | 多视角分析 |
| SEQUENTIAL | 顺序执行 | 流水线（先检索再总结） |
| HIERARCHICAL | 多层 Agent 协同 | 复杂项目分解 |
| FANOUT | 一任务分发给多 Agent | 投票 / 投票式评测 |

```python
agent.register_sub_agent(capability="summarize", name="摘要专家")
agent.register_sub_agent(capability="code_review", name="代码审查员")
result = agent.delegate_subtask("summarize", "请总结这段文字...")
```

详见 [`multi_agent.py`](multi_agent.py) 和 [`multi_agent_integration.py`](multi_agent_integration.py)。

### 协商与竞价

**协商系统**：多 Agent 通过提议/反提议达成共识。
- `NegotiationParticipantMixin`
- `NegotiationManager`
- `Proposal`（含 utility 评分）

**竞价系统**：多 Worker 出价竞争任务执行权。
- `AuctionManager`
- `AuctionStrategy`：第一价格 / 第二价格（Vickrey）/ 英式 / 荷兰式 / 综合评分
- `Bid`

```python
from negotiation import AuctionStrategy
strategy = AuctionStrategy.SECOND_PRICE  # Vickrey 拍卖
```

详见 [`negotiation.py`](negotiation.py)。

### 可靠性机制

| 组件 | 功能 |
|---|---|
| `RetryPolicy` | 固定 / 线性 / 指数 / 抖动 退避 |
| `CircuitBreaker` | 三态熔断（Closed / Half-Open / Open） |
| `DeadLetterQueue` | 失败消息缓冲 |
| `ReliabilityLayer` | 可靠性层总控 |

详见 [`reliability.py`](reliability.py)。

### 能力注册中心

- `CapabilityRegistry`：能力注册表
- `WorkerProfile`：Worker 能力画像
- `WorkerMetrics`：Worker 指标统计
- `LoadBalancer`：RoundRobin / Random / LeastLoaded

详见 [`capability.py`](capability.py)。

### Prompt 工程化

System Prompt + User Prompt 全部支持**模板注册 + 版本化 + 回滚**：

```python
from prompt_registry import PromptTemplate, get_prompt_registry

reg = get_prompt_registry()
reg.register(PromptTemplate(
    name="default",
    version="2.0.0",
    author="me",
    changelog="强化 CoT",
    system_block="...",
    role_block="...",
    tool_block_template="...",
    cot_instructions="复杂任务必须先输出 ## 思考 ##",
))
# 回滚
reg.rollback("default", "1.0.0")
```

`run_stream` 改为产出结构化事件：`start / thinking / chunk / tool_call / safety / error / complete`，前端可绘制工具调用时间线 + 思考过程折叠面板。

Web 端：
- `GET /api/prompts` / `POST /api/prompts/rollback`（System Prompt）
- `GET /api/user-prompts` / `POST /api/user-prompts/{register,rollback,render,export,import}`（User Prompt）

详见 [`prompt_registry.py`](prompt_registry.py)、[`user_prompt_registry.py`](user_prompt_registry.py)、[`docs/STAGE_A_DELIVERY.md`](docs/STAGE_A_DELIVERY.md)。

### Skill 系统

| 技能 | 分类 | 功能 |
|---|---|---|
| `deep_research` | research | 深度研究报告生成 |
| `code_documentation` | development | 自动生成代码文档 |
| `ppt_generation` | productivity | PPT 大纲生成 |
| `paper_review` | academic | 学术论文审阅 |
| `chart_visualization` | data | 数据可视化图表 |

```python
from skills import get_skill_manager
manager = get_skill_manager()
prompt = manager.get_skill_prompt("deep_research", topic="人工智能发展趋势")
```

详见 [`skills.py`](skills.py)。

## 工具说明

### LangChain 工具（tools.py）

| 工具 | 功能 |
|---|---|
| `get_current_time` | 获取当前时间 |
| `calculate` | 数学计算（支持 sin / cos / sqrt / ^ 等，AST 白名单） |
| `search_web` | 网络搜索（SerpAPI） |
| `query_knowledge_base` | 查询知识库 |
| `load_knowledge_base` | 加载文档到知识库 |
| `read_file` | 读取文件 |
| `write_file` | 写入文件 |
| `list_files` | 列出目录文件 |
| `run_code` | 执行简单 Python 代码 |
| `get_weather` | 查询天气 |
| `github_search` | 搜索 GitHub 仓库 |
| `generate_chart` | 生成数据可视化图表 |

### MCP 工具（mcp_tools.py）

| 分类 | 工具 | 功能 |
|---|---|---|
| **file** | `file_read` | 读取文件 |
|  | `file_write` | 写入文件 |
|  | `directory_list` | 列出目录 |
| **web** | `http_request` | HTTP 请求 |
| **development** | `git_status` | Git 状态 |
|  | `git_log` | Git 日志 |
|  | `docker_ps` | Docker 容器 |
| **system** | `whoami` | 用户信息 |
|  | `system_info` | 系统信息 |
|  | `process_list` | 进程列表 |
| **data** | `json_parse` | JSON 解析 |
|  | `json_query` | JSON 查询 |
| **utility** | `current_time` | 当前时间 |
|  | `timestamp_convert` | 时间戳转换 |

外部 MCP Server（默认配置，需要时可启用）：

| 服务 | 来源 |
|---|---|
| `github` | `@modelcontextprotocol/server-github` |
| `filesystem` | `@modelcontextprotocol/server-filesystem` |
| `brave-search` | `@modelcontextprotocol/server-brave-search` |
| `slack` | `@modelcontextprotocol/server-slack` |
| `sqlite` | `@modelcontextprotocol/server-sqlite` |

详见 [`mcp_tools.py`](mcp_tools.py) 与 [`mcp_config.json`](mcp_config.json)。

### 自建 MCP Server（stdio 模式）

项目内自带两个 Python stdio MCP server，位于 [`mcp_servers/`](mcp_servers/)：

| Server | 作用 | 提供工具 |
|---|---|---|
| `demo_server` | 学习 / 测试 MCP 协议的最小示例 | `echo` / `reverse_text` / `sha256_hash` / `random_number` / `word_count` |
| `agent_bridge_server` | 把 ai_agent 现有能力反向暴露给外部 MCP 客户端 | `list_capabilities` / `list_skills` / `run_etf_info` / `query_knowledge` |

二者均已在 [`mcp_config.json`](mcp_config.json) 的 `external_servers` 中注册（`demo` 默认 enabled，`agent-bridge` 默认 disabled，需要时手动打开）。

**手动启动（用于调试）**：

```bash
# 必须把仓库根目录加进 PYTHONPATH 才能 import ai_agent.* 包
cd e:\langChain_langGraph
python -m ai_agent.mcp_servers.demo_server
python -m ai_agent.mcp_servers.agent_bridge_server
```

启动后 server 监听 stdin/stdout 上的 newline-delimited JSON-RPC，可用 [MCP Inspector](https://github.com/modelcontextprotocol/inspector) 或任意 MCP 客户端连接。

**接入 Claude Desktop / Cursor**：

在 `claude_desktop_config.json`（Windows：`%APPDATA%\Claude\claude_desktop_config.json`，macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`）里加：

```json
{
  "mcpServers": {
    "ai-agent-demo": {
      "command": "python",
      "args": ["-m", "ai_agent.mcp_servers.demo_server"],
      "cwd": "e:\\langChain_langGraph",
      "env": {
        "PYTHONPATH": "e:\\langChain_langGraph"
      }
    },
    "ai-agent-bridge": {
      "command": "python",
      "args": ["-m", "ai_agent.mcp_servers.agent_bridge_server"],
      "cwd": "e:\\langChain_langGraph",
      "env": {
        "PYTHONPATH": "e:\\langChain_langGraph"
      }
    }
  }
}
```

> ⚠️ `cwd` / `PYTHONPATH` 必须指向仓库根目录，否则 `ai_agent.mcp_servers.*` 找不到模块。

**协议注意点**：

- stdio 模式用 **newline-delimited JSON**（每条消息以 `\n` 结尾），**不是** LSP 风格的 `Content-Length:` 头。
- `initialize` 之后必须立刻发 `notifications/initialized` 通知，否则 server 会拒收后续请求。

详见 [`tests/test_demo_mcp_server.py`](tests/test_demo_mcp_server.py)（完整 stdio JSON-RPC 握手示例，可直接抄）。

### ETF 金融工具（tools.py）

| 工具 | 功能 |
|---|---|
| `get_etf_info` | ETF 基本信息（名称、规模、净值等） |
| `get_etf_price` | 实时行情（价格、涨跌幅等） |
| `get_etf_history` | 历史行情（最近 N 天） |
| `get_etf_knowledge` | ETF 知识库（基础 / 类型 / 购买 / 风险） |
| `compare_etfs` | 多 ETF 对比分析 |
| `etf_analysis` | 综合分析与预测（波动率、趋势等） |
| `generate_chart` | 生成数据可视化图表 |

## 安全功能

### 输入安全

- 危险命令拦截：`rm -rf`、`del /f`、`format c:`、`shutdown`、`restart`、`os.system`、`subprocess.call` 等。
- 上级目录访问阻止（`..` / 绝对路径）。
- 代码执行安全过滤（仅允许数学表达式 + AST 白名单）。

### 输出脱敏

- API Key / Token / 密码等敏感信息过滤。
- 日志脱敏处理。

### 意图检测

- `query` 查询、搜索
- `compare` 比较、对比
- `analysis` 分析、预测
- `calculate` 计算
- `greeting` 问候
- `command` 命令执行
- `general` 通用

### Prompt Injection 检测

正则 + 关键词命中以下攻击模式即视为可疑输入：

- `ignore previous instructions` / `忽略之前的指令`
- `system: you are` 假冒 system role
- `<|im_start|>` / `<|im_end|>` 特殊 token
- `reveal/show/print your prompt`
- `jailbreak` / `DAN mode` / `developer mode`

详见 [`security.py`](security.py)。

## 可观测性与人机协同

### 可观测性

| 端点 | 用途 |
|---|---|
| `GET /api/events?limit=50` | 最近事件流（按级别过滤） |
| `GET /api/traces?limit=30` | 最近 Trace span 列表 |
| `GET /api/metrics/prometheus` | Prometheus 文本（直接给 Prom 抓） |
| `GET /api/load_stats` | 多 Agent / Worker 负载 |
| `GET /api/capabilities` | 能力注册表 + Task 类型 |
| `GET /api/agents` | Worker profile + 状态 |

A/B 测试框架 [`ab_testing.py`](ab_testing.py)、自适应阈值 [`adaptive_threshold.py`](adaptive_threshold.py)。

### 人机协同（HITL）

```python
from human_in_loop import HITLPolicy, get_hitl_guard

guard = get_hitl_guard()
# HookPoint 策略：PASS / ASK / BLOCK
guard.set_default_policy(HITLPolicy.ASK)
guard.set_hook_policy("BEFORE_TOOL_CALL", HITLPolicy.ASK)
guard.set_hook_policy("FINAL_ANSWER", HITLPolicy.PASS)
```

Web 端：
- `GET /api/hitl/pending` —— 待审批列表
- `POST /api/hitl/decide` —— 提交决议（批准 / 拒绝 + 备注）
- `GET /api/hitl/history` —— 历史
- `POST /api/hitl/policy` —— 设置 Hook 策略

详见 [`human_in_loop.py`](human_in_loop.py)。

### 权限（RBAC）

```python
from permission import get_permission_guard, Policy, Role

guard = get_permission_guard()
guard.add_policy(Policy(
    agent_id="agent-1",
    roles=[Role.OPERATOR],
    capabilities=["etf_query", "knowledge_query"],
    allowed_tools=["get_etf_info", "query_knowledge_base"],
))
# 强制开启
guard.enable_enforce(True)
```

详见 [`permission.py`](permission.py)。

## Web UI 与 API

### 主界面（推荐，零依赖）

```bash
cd ai_agent/web
python -m http.server 8765
# 浏览器打开 http://localhost:8765/
```

主界面单文件 HTML，5 个 tab：设置 / 工具 / 记忆 / 计划 / 运维/观测。

测试中心：
- `http://localhost:8765/home.html` —— 10 个面板 + 实时测试反馈
- `http://localhost:8765/test_dashboard.html` —— 测试报告只读
- `http://localhost:8765/test_lab.html` —— 单功能测试实验台

> React 控制台版本在仓库根 `web_console/`（开发中，功能逐步对齐主界面），[../README.md §2.4](../README.md#24-选择前端推荐先看主界面)。

### 统一 API（app.py）

端点速查：

| 类别 | 端点 |
|---|---|
| 健康 | `GET /api/health`、`GET /api/version` |
| 聊天 | `POST /api/chat`、`POST /api/chat/stream`（SSE）、`WS /api/chat/stream` |
| 模型 | `GET /api/models`、`GET /api/api-key/status`、`POST /api/api-key`、`POST /api/model/switch` |
| 工具 | `GET /api/tools` |
| Agent | `GET /api/agents`、`GET /api/capabilities`、`GET /api/load_stats` |
| 权限 | `GET /api/policies`、`POST /api/policy`、`POST /api/permission/enforce` |
| HITL | `GET /api/hitl/pending`、`POST /api/hitl/decide`、`GET /api/hitl/history`、`GET /api/hitl/stats`、`POST /api/hitl/policy` |
| 计划 | `POST /api/plan/create`、`POST /api/plan/research`、`POST /api/plan/code`、`POST /api/plan/run` |
| 记忆 | `POST /api/memory/add`、`GET /api/memory/list`、`DELETE /api/memory/{id}`、`POST /api/memory/remember`、`GET /api/memory/recall`、`GET /api/memory/search`、`POST /api/memory/save`、`POST /api/memory/load`、`GET /api/memory/stats` |
| Prompt | `GET /api/prompts`、`POST /api/prompts/rollback`、`GET /api/user-prompts`、`POST /api/user-prompts/rollback`、`POST /api/user-prompts/register`、`POST /api/user-prompts/render`、`GET /api/user-prompts/export`、`POST /api/user-prompts/import` |
| 观测 | `GET /api/events`、`GET /api/traces`、`GET /api/metrics/prometheus` |
| 上传 | `POST /api/upload`、`GET /api/files/{name}` |
| 上下文 | `GET /api/context/sessions`、`POST /api/context/sessions`、`GET /api/context/sessions/{sid}`、`GET /api/context/sessions/{sid}/summary`、`GET /api/context/sessions/{sid}/entities`、`GET /api/context/sessions/{sid}/messages`、`GET /api/context/analytics`、`GET /api/context/search`、`GET /api/context/stats`、`GET /api/context/performance`、`POST /api/context/performance/reset` |

> 旧版 [`api.py`](api.py) 和 [`web_ui.py`](web_ui.py) 仍保留向后兼容，建议新代码统一走 `app.py`。

## 桌面打包

### 快速打包

```bash
# Windows
cd ai_agent
.\build_windows.ps1            # 产物：dist\ai-agent\ai-agent.exe
.\package_dist.ps1             # 产物：dist\ai-agent-windows.zip（约 470 MB / 解压 1.16 GB）

# Linux / WSL
./build_linux.sh               # 产物：dist/ai-agent/ai-agent
./package_dist.ps1             # 产物：dist/ai-agent-linux.tar.gz（≥ 500 MB）

# 在 Windows 上交叉打 Linux 包（可选）
.\build_all.ps1                # 内部用 python:3.11-slim docker 镜像编译
```

### 详细步骤

1. `pip install -r requirements.txt pyinstaller`
2. `pyinstaller ai_agent.spec --clean --noconfirm`
3. 拷贝 `dist/ai-agent/*` 到 `package/{windows,linux}/`
4. 拷贝 `knowledge_base / prompts / mcp_config.json / .env.example / run.{bat,sh} / install.{bat,sh} / README.txt`
5. 加可执行权限（Linux / macOS）
6. 压缩成 zip / tar.gz

### Spec 关键点（ai_agent.spec）

- 入口：`main.py`（CLI）。要打 Web 版把 `main.py` 改为 `app.py` 重新打包。
- 同一份 spec 三端通用，已剔除 Windows 专属参数。
- `hiddenimports` 显式收 langchain / langgraph / mcp / chromadb / uvicorn / fastapi。
- `EXCLUDES` 已剔除 `tkinter / matplotlib.tests / onnxruntime / torch`（体积优化）。

### Smoke 测试

```bash
# 完整冒烟（含 spec 语法 / install.bat / run.bat / ELF / tar.gz 文件数）
cd ai_agent
./test_all.ps1
./test_package.sh
```

详见 [`package/README.md`](package/README.md) 和 [`package/linux/BUILD_ON_LINUX.md`](package/linux/BUILD_ON_LINUX.md)。

## PyPI 发版

```bash
cd ai_agent

# 1. 干净构建
rm -rf build dist *.egg-info
python -m build

# 2. 包检查
python -m twine check dist/*

# 3. 上传
python -m twine upload --repository testpypi dist/*   # 先 TestPyPI 验证
python -m twine upload dist/*                        # 再正式 PyPI

# 或 CI 自动：release.yml 在打 tag 时自动跑（详见 ../.github/RELEASE_PIPELINE.md）
```

安装后命令：

```bash
pip install ai-agent
ai-agent              # 启动 Web 服务（默认监听 8000）
ai-agent-server       # 同上别名
ai-agent-test         # 跑 pytest
ai-agent-lint         # ruff check
ai-agent-format       # ruff format
```

详见 [`pyproject.toml`](pyproject.toml) 与 [`../web_console/.github/PYPI_PUBLISHING.md`](../web_console/.github/PYPI_PUBLISHING.md)。

## 扩展指南

### 添加新工具

```python
# ai_agent/tools.py
from langchain_core.tools import tool

@tool
def my_new_tool(param: str) -> str:
    """工具描述（用于 LangChain tool schema）"""
    # 实现逻辑
    return result

# 注册到 get_all_tools()
```

### 添加新 Skill

```python
# ai_agent/skills.py · _load_builtin_skills
def _register_my_skill(self):
    skill = Skill(
        name="my_skill",
        description="技能描述",
        category="my_category",
        prompt_template="提示词模板，{param}",
        tools=["tool1", "tool2"],
    )
    self.registry.register(skill)
```

### 添加新 MCP 工具

```python
# ai_agent/mcp_tools.py
from mcp_server import MCPTool

def my_handler(args: dict) -> str:
    return "..."

registry.register(MCPTool(
    name="my_mcp_tool",
    description="...",
    handler=my_handler,
    schema={"type": "object", "properties": {"x": {"type": "string"}}},
))
```

### 配置主备模型

```python
agent.set_primary_standby(
    primary={"provider": "openai", "model": "gpt-4o-mini"},
    standbys=[
        {"provider": "deepseek", "model": "deepseek-chat"},
        {"provider": "qwen", "model": "qwen-turbo"},
        {"provider": "doubao", "model": "doubao-pro-32k"},
    ],
    enable_warmup=True,
)
```

### 编写新的 A/B 测试

```python
from ab_testing import ABTest, get_ab_framework

framework = get_ab_framework()
test = ABTest(
    name="prompt_v2",
    variants={"v1": "你是一个有帮助的助手。", "v2": "你是一个有帮助的助手，先思考再回答。"},
    metric="user_satisfaction",
)
framework.register(test)
```

## 常见问题

> 更多排错详见顶层 [`README.md §8`](../README.md#8-常见问题与故障排除)。

| 现象 | 排查 |
|---|---|
| 运行时提示缺少 API Key | 创建 `.env` 并填入 `OPENAI_API_KEY`（或 DeepSeek / Qwen 任一） |
| Embedding 模型无法使用 | 检查 `EMBEDDING_API_KEY`；免费可设 `EMBEDDING_MODEL_TYPE=jina` |
| GitHub API 访问失败 | 检查 `GITHUB_PERSONAL_ACCESS_TOKEN` 与代理；可改用 Gitee |
| 文件操作报错 | 路径含 `..` 或绝对路径会被安全层拒绝；改用相对路径 |
| 代码执行被拦截 | `run_code` 不允许 `import` / `exec` / `eval`；仅数学表达式 |
| 全部模型不可用 | 五层容错栈会自动降级；查看 `/api/fail-log/summary` 与 `agent.log` |
| Windows 桌面版中文乱码 | `run.bat` 已 `chcp 65001`；CLI 入口 `main.py` 已 `stdout.reconfigure(encoding='utf-8')` |
| `ai-agent` 命令找不到 | `pip install -e .` 装包后才有；或直接 `python app.py` / `python main.py` |
| PyInstaller 报 `ModuleNotFound` | 在 `ai_agent.spec` 的 `hiddenimports` 补 |
| Linux 二进制缺 `.so` | 必须 Linux 主机 / Docker 编译；详见 `package/linux/BUILD_ON_LINUX.md` |

## 测试

### 跑测试

```bash
# 仅测试 FastAPI 端点（不需 LangChain / LLM）
py -3.11 -m pytest tests/ -v

# 带覆盖率
py -3.11 -m pytest tests/ --cov=. --cov-report=html
# 打开 htmlcov/index.html
```

### 当前覆盖情况

| 测试文件 | 通过用例 |
|---|---|
| `test_agent.py`（核心回归） | 55+ |
| `test_prompt_registry.py` | 10 |
| `test_stream_events.py` | 7 |
| `test_prompts_api.py` | 4 |
| `test_user_prompt_registry.py` | 13 |
| `test_user_prompts_api.py` | 4 |
| `test_models_registry.py` | 20 |
| `test_app_sse.py` / `test_app_ws.py` | 2 |
| `test_basic_endpoints.py` | 4 |
| `test_upload.py` | 9 |
| `test_skills.py` / `test_mcp_tools.py` / `test_sqlite_tools.py` | 各若干 |
| `test_security.py` / `test_permission.py` / `test_memory_store.py` / `test_rag.py` | 各若干 |
| `tests/` 总计 | ~96 passed（不含 slow / network / integration） |

CI 自动跑测试 + 上传覆盖率报告到 Actions artifact。

## 版本历史

- **v0.3.0**（2026-07-23）：阶段 B，新增 4 个国产模型 Provider（豆包 / Hunyuan / SiliconFlow / MiniMax），扩充老 Provider 最新模型，分组化 Provider 元数据。
- **v0.2.0**（2026-07-23）：阶段 A，`prompt_registry.py` + `run_stream` 结构化事件 + `/api/prompts` 回滚 + 前端工具调用时间线 + 思维链折叠面板 + 安全横幅。
- **v0.1.0**：初版。
- **v1.1.0**（顶层仓库，2026-07-22）：多级容错 / 结构化上下文 / 统一记忆 / 多 Agent / 协商竞价 / 可靠性 / 能力注册 / 分布式总线 / ETF / 安全 / 11 Provider。
- **v1.0.0**（顶层仓库，2026-07-18）：LangChain 1.x + LangGraph 基础、12 个工具、RAG、MCP、GitHub/Gitee、Web UI + CLI。

详细变更：[`CHANGELOG.md`](CHANGELOG.md)，顶层 [`../CHANGELOG.md`](../CHANGELOG.md)。

## 许可证

MIT License。详见顶层 `LICENSE`。