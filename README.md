# LangChain LangGraph AI Agent

基于 LangChain + LangGraph 构建的多功能 AI Agent 智能助手。

## 项目简介

本项目支持：
- 多轮对话记忆
- 18+ 工具调用
- MCP 协议
- RAG 知识库
- GitHub/Gitee 集成
- ETF 金融分析

## 快速开始

```bash
cd ai_agent
pip install -r requirements.txt
cp .env.example .env
python main.py
```

## 功能特性

- get_current_time - 获取时间
- calculate - 数学计算
- search_web - 网络搜索
- query_knowledge_base - 知识库查询
- read_file - 读取文件
- get_weather - 查询天气
- github_search - GitHub 搜索

## 环境变量

- OPENAI_API_KEY
- SERPAPI_API_KEY
- EMBEDDING_API_KEY

## 版本历史

### v1.0.0 (2026-07-18)
- 初始版本发布

## 仓库地址

- GitHub: https://github.com/colbertlee/langChain_langGraph
- Gitee: https://gitee.com/colbertlee/langChain_langGraph

## 许可证

MIT License