# 更新日志

所有重要的项目更新都将记录在此文件中。

## [v1.0.0] - 2026-07-18

### 初始发布

#### 新增
- AI Agent 核心模块 (`agent.py`)
- LangChain 工具集 (`tools.py`)
  - get_current_time - 获取当前时间
  - calculate - 数学计算
  - search_web - 网络搜索
  - query_knowledge_base - 知识库查询
  - load_knowledge_base - 加载文档
  - read_file - 读取文件
  - write_file - 写入文件
  - list_files - 列出文件
  - run_code - 执行代码
  - get_weather - 查询天气
  - github_search - GitHub 搜索
  - generate_chart - 生成图表
- RAG 知识库模块 (`rag.py`)
  - 支持多种 Embedding 模型 (OpenAI/智谱/MiniMax/Jina)
- 安全防护模块 (`security.py`)
- GitHub MCP 工具 (`github_tools.py`)
- Gitee MCP 工具 (`gitee_tools.py`)
- FastAPI Web 服务 (`api.py`)
- Web UI 界面 (`web/index.html`)
- 命令行入口 (`main.py`)
- 配置管理 (`config.py`)

#### 特性
- 多轮对话记忆 (SQLite 持久化)
- 流式输出响应
- 输入安全过滤
- 输出敏感信息脱敏
- Web UI + WebSocket 支持

---

## 如何贡献

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request
