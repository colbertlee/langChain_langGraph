# LangChain LangGraph AI Agent

基于 LangChain + LangGraph 构建的多功能 AI Agent 智能助手。

## 项目简介

本项目实现了一个基于 LangChain 1.x 和 LangGraph 的多功能 AI Agent，支持：
- 多轮对话记忆（SQLite 持久化）
- 18+ 工具调用
- MCP 协议支持
- RAG 知识库检索
- GitHub/Gitee API 集成
- ETF 金融分析

## 技术栈

| 组件 | 说明 |
|------|------|
| Python 3.10+ | 编程语言 |
| LangChain 1.x | AI Agent 开发框架 |
| LangGraph | 工作流编排引擎 |
| FastAPI | Web API 框架 |
| ChromaDB | 向量数据库 |

## 项目结构

```
langChain_langGraph/
├── ai_agent/                  # AI Agent 核心代码
│   ├── agent.py              # Agent 核心逻辑
│   ├── tools.py              # LangChain 工具定义
│   ├── rag.py                # RAG 知识库模块
│   ├── security.py           # 安全防护模块
│   ├── api.py                # FastAPI Web API
│   ├── main.py               # 命令行入口
│   ├── config.py             # 配置管理
│   ├── github_tools.py       # GitHub MCP 工具
│   ├── gitee_tools.py       # Gitee MCP 工具
│   ├── web/                  # Web UI
│   ├── knowledge_base/       # 知识库文档
│   ├── requirements.txt      # 依赖列表
│   └── .env.example          # 环境变量模板
└── README.md                 # 项目说明文档
```

## 快速开始

### 1. 安装依赖

```bash
cd ai_agent
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

### 3. 启动服务

**命令行模式：**
```bash
python main.py
```

**Web UI 模式：**
```bash
python api.py
# 访问 http://localhost:8000
```

## 功能特性

### 基础工具

| 工具 | 功能 |
|------|------|
| `get_current_time` | 获取当前时间 |
| `calculate` | 数学计算 |
| `search_web` | 网络搜索 |
| `query_knowledge_base` | 查询知识库 |
| `load_knowledge_base` | 加载文档 |
| `read_file` | 读取文件 |
| `write_file` | 写入文件 |
| `list_files` | 列出文件 |
| `run_code` | 执行代码 |
| `get_weather` | 查询天气 |
| `github_search` | GitHub 搜索 |
| `generate_chart` | 生成图表 |

### RAG 知识库

支持多种 Embedding 模型：
- OpenAI (默认)
- 智谱 AI (zhipu) - 中文优化
- MiniMax
- Jina AI (免费)

### GitHub/Gitee 集成

- 搜索仓库
- 查看仓库详情
- 操作 Issue
- 代码 Push

## 扩展开发

### 添加新工具

在 `tools.py` 中添加：

```python
@tool
def my_tool(param: str) -> str:
    """工具描述"""
    return result

# 在 get_all_tools() 中注册
```

### 配置 MCP 服务

编辑 `mcp_config.json` 配置外部 MCP 服务。

## 环境变量说明

```env
# LLM 配置
OPENAI_API_KEY=your_openai_api_key

# SerpAPI (可选)
SERPAPI_API_KEY=your_serpapi_key

# Embedding 配置
EMBEDDING_API_KEY=your_embedding_key
EMBEDDING_MODEL_TYPE=zhipu

# GitHub Token
GITHUB_PERSONAL_ACCESS_TOKEN=your_github_token
```

## 版本历史

### v1.0.0 (2026-07-18)
- 初始版本发布
- Agent 核心功能
- RAG 知识库
- MCP 工具集
- GitHub/Gitee 集成

## 许可证

MIT License

## 仓库地址

- GitHub: https://github.com/colbertlee/langChain_langGraph
- Gitee: https://gitee.com/colbertlee/langChain_langGraph
