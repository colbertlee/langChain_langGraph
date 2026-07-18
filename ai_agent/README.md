# AI Agent 智能助手

基于 LangChain + LangGraph 构建的多功能 AI Agent 智能助手，支持工具调用、知识库检索（RAG）、MCP 协议扩展、Skill 系统、ETF 金融分析等功能。

## 目录

- [项目简介](#项目简介)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [安装步骤](#安装步骤)
- [配置说明](#配置说明)
- [使用方法](#使用方法)
- [工具说明](#工具说明)
- [MCP 支持](#mcp-支持)
- [Skill 系统](#skill-系统)
- [安全功能说明](#安全功能说明)
- [记忆功能说明](#记忆功能说明)
- [RAG 知识库说明](#rag-知识库说明)
- [扩展指南](#扩展指南)
- [常见问题](#常见问题)

## 项目简介

本项目实现了一个基于 LangChain 1.x 和 LangGraph 的多功能 AI Agent 智能助手，具备以下核心能力：

- **多轮对话记忆**：基于 LangGraph 的 SqliteSaver 实现，对话历史持久化存储
- **工具自动调用**：支持 18+ 个工具，涵盖基础功能、扩展功能和金融分析
- **MCP 协议支持**：支持 Model Context Protocol，可连接外部服务和工具
- **Skill 系统**：可插拔的技能框架，支持深度研究、PPT 生成、代码文档等
- **RAG 知识库**：支持加载本地文档，基于向量检索回答问题
- **安全防护**：输入过滤、输出审查、危险命令拦截
- **流式输出**：逐字输出，提升交互体验
- **Web UI + API**：提供现代化聊天界面和 REST/WebSocket API
- **API Key 动态配置**：支持在 Web UI 中实时配置 OpenAI API Key
- **GitHub 集成**：支持 GitHub API，可搜索仓库、查看 Issue、代码 Push

## 技术栈

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ | 编程语言 |
| LangChain | 1.0+ | AI Agent 开发框架 |
| LangGraph | 1.0+ | 工作流编排引擎 |
| LangChain OpenAI | 1.0+ | OpenAI 模型集成 |
| LangChain Chroma | 1.0+ | Chroma 向量数据库集成 |
| LangChain Text Splitters | 1.0+ | 文档切分工具 |
| LangGraph Checkpoint SQLite | 1.0+ | SQLite 持久化存储 |
| ChromaDB | 1.0+ | 本地向量数据库 |
| FastAPI | 0.100+ | Web API 框架 |
| Uvicorn | 0.20+ | ASGI 服务器 |
| MCP SDK | 1.0+ | Model Context Protocol |

## 项目结构

```
ai_agent/
├── agent.py              # Agent 核心逻辑
├── tools.py              # LangChain 工具定义
├── mcp_server.py         # MCP 服务器核心
├── mcp_tools.py           # MCP 工具集（14个工具）
├── skills.py              # Skill 技能系统
├── rag.py                # RAG 知识库模块
├── security.py            # 安全防护模块
├── config.py             # 配置文件
├── main.py               # 命令行交互入口
├── api.py                # FastAPI Web API 服务
├── web/                  # Web UI 前端目录
│   └── index.html        # 聊天界面
├── mcp_config.json       # MCP 服务配置
├── requirements.txt       # Python 依赖列表
├── .env                  # 环境变量配置
├── knowledge_base/        # 知识库文档目录
├── memory.db             # SQLite 数据库（运行时）
├── agent.log             # 日志文件（运行时）
└── README.md             # 项目说明文档
```

### 文件说明

| 文件 | 职责 |
|------|------|
| `agent.py` | Agent 核心类，包含模型初始化、工具注册、对话逻辑 |
| `tools.py` | LangChain 工具定义（9个） |
| `mcp_server.py` | MCP 服务器核心实现 |
| `mcp_tools.py` | MCP 工具集（14个） |
| `skills.py` | Skill 技能系统（5个内置技能） |
| `rag.py` | RAG 模块，包含文档加载、切分、向量化、检索 |
| `security.py` | 安全防护模块 |
| `config.py` | 配置管理 |
| `api.py` | FastAPI Web API 服务 |

## 安装步骤

### 1. 进入项目目录

```bash
cd e:\langChain_langGraph\ai_agent
```

### 2. 创建虚拟环境（推荐）

```bash
python -m venv venv
.\venv\Scripts\Activate.ps1  # Windows
source venv/bin/activate     # macOS/Linux
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

## 配置说明

### 环境变量配置

创建 `.env` 文件：

```env
# LLM 模型配置
OPENAI_API_KEY=your_openai_api_key_here

# MCP 服务配置
GITHUB_PERSONAL_ACCESS_TOKEN=your_github_token_here

# Embedding 模型配置
EMBEDDING_API_KEY=your_embedding_api_key_here
EMBEDDING_MODEL_TYPE=zhipu  # openai/minimax/zhipu/jina
```

## 使用方法

### 方法 1：命令行交互

```bash
python main.py
```

### 方法 2：Web UI

```bash
python api.py
# 访问 http://localhost:8000
```

### 方法 3：编程调用

```python
from agent import AIAgent

agent = AIAgent()
result = agent.run("你好")
print(result)
```

## 工具说明

### LangChain 工具（tools.py）

| 工具 | 功能 |
|------|------|
| `get_current_time` | 获取当前时间 |
| `calculate` | 数学计算 |
| `search_web` | 网络搜索 |
| `query_knowledge_base` | 查询知识库 |
| `load_knowledge_base` | 加载文档到知识库 |
| `read_file` | 读取文件内容 |
| `write_file` | 写入文件内容 |
| `list_files` | 列出目录文件 |
| `run_code` | 执行简单 Python 代码 |

### MCP 工具（mcp_tools.py）

| 分类 | 工具 | 功能 |
|------|------|------|
| **file** | `file_read` | 读取文件 |
| | `file_write` | 写入文件 |
| | `directory_list` | 列出目录 |
| **web** | `http_request` | HTTP 请求 |
| **development** | `git_status` | Git 状态 |
| | `git_log` | Git 日志 |
| | `docker_ps` | Docker 容器 |
| **system** | `whoami` | 用户信息 |
| | `system_info` | 系统信息 |
| | `process_list` | 进程列表 |
| **data** | `json_parse` | JSON 解析 |
| | `json_query` | JSON 查询 |
| **utility** | `current_time` | 当前时间 |
| | `timestamp_convert` | 时间戳转换 |

## MCP 支持

### 支持的外部服务

| 服务 | 说明 | 配置 |
|------|------|------|
| **GitHub** | 仓库、Issue、PR 管理 | `GITHUB_PERSONAL_ACCESS_TOKEN` |

### 启动 MCP 服务

```bash
python start_mcp.py
```

## Skill 系统

### 内置技能（skills.py）

| 技能 | 分类 | 功能 |
|------|------|------|
| `deep_research` | research | 深度研究报告生成 |
| `code_documentation` | development | 自动生成代码文档 |
| `ppt_generation` | productivity | PPT 大纲生成 |
| `paper_review` | academic | 学术论文审阅 |
| `chart_visualization` | data | 数据可视化图表 |

### 使用技能

```python
from skills import get_skill_manager

manager = get_skill_manager()

# 获取技能提示词
prompt = manager.get_skill_prompt(
    "deep_research",
    topic="人工智能发展趋势"
)
```

## RAG 知识库说明

### 支持的 Embedding 模型

| 模型 | 类型 | 维度 | 说明 |
|------|------|------|------|
| `openai` | OpenAI | 1536 | 默认 |
| `zhipu` | 智谱 AI | 1024 | 中文优化 |
| `minimax` | MiniMax | 1024 | M2.5/M2.7 |
| `jina` | Jina AI | 1024 | 免费 |

### 配置 Embedding 模型

```env
EMBEDDING_MODEL_TYPE=zhipu
EMBEDDING_API_KEY=your_api_key_here
```

## 扩展指南

### 添加新工具

在 `tools.py` 中添加：

```python
@tool
def my_new_tool(param: str) -> str:
    """工具描述"""
    # 实现逻辑
    return result
```

### 添加新技能

在 `skills.py` 的 `_load_builtin_skills` 方法中添加：

```python
def _register_my_skill(self):
    skill = Skill(
        name="my_skill",
        description="技能描述",
        category="my_category",
        prompt_template="提示词模板，{param}",
        tools=["tool1", "tool2"]
    )
    self.registry.register(skill)
```

## 常见问题

### Q1: 运行时提示缺少 API Key

**解决**：创建 `.env` 文件并添加 `OPENAI_API_KEY=your_key_here`

### Q2: Embedding 模型无法使用

**解决**：确保 `EMBEDDING_API_KEY` 正确配置，或使用免费模型 `jina`

### Q3: GitHub API 访问失败

**解决**：检查网络代理设置，或使用 Gitee 作为替代

### Q4: 文件操作报错

**原因**：安全限制不允许访问上级目录或绝对路径

**解决**：使用相对路径，如 `README.md`

### Q5: 代码执行被拦截

**原因**：包含危险关键字（import、exec、eval）

**解决**：只执行安全的数学表达式

## 许可证

本项目使用 MIT 许可证。
