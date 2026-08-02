# Legacy Tests（Day 4-5 改造说明）

> **重要**：本目录的测试默认**被 pytest 跳过**，不会出现在常规 `pytest` 中。

## 为什么

`tests/legacy/` 下存放的是从 AI Agent 早期迁移来的"历史"测试用例：

- 部分使用老 API（如 `AgentExecutor`、旧的 web_ui.py）；
- 部分依赖外部服务（GitHub/Gitee MCP 真实连接）；
- 部分用例已经被新测试覆盖（`test_*.py` 顶级目录）。

如果默认运行，会带来两类问题：

1. **环境依赖**：CI runner 没装 GitHub token / Gitee token / 真 LLM Key 直接挂；
2. **覆盖噪音**：`pytest --cov` 把这些历史用例统计进 coverage，掩盖真实覆盖率。

## 如何运行

显式 opt-in：

```bash
# 跑所有 legacy 用例（CI 调试时使用）
pytest -m legacy

# 或环境变量开关
AI_AGENT_RUN_LEGACY=1 pytest
```

## 计划

后续每个 release 前清理一次：
- 已经有新版本对应的 → 删；
- 历史功能已删除的 → 删；
- 值得保留的 → 迁移到 `tests/` 顶级或 `tests/integration/`。

## 当前包含

```
test_basic.py                    # 早期基础工具测试
test_bug_fixes.py                # 历史 bug 修复回归
test_capability.py               # capability 注册中心
test_context.py                  # 上下文管理器
test_context_simple.py           # 上下文简单用例
test_full.py                     # 全功能端到端（需要 API Key）
test_full_system_integration.py  # 系统集成
test_github_mcp.py               # GitHub MCP（需 GITHUB_TOKEN）
test_github_push.py              # GitHub 推送（需 GITHUB_TOKEN）
test_hitl_webui.py               # HITL + WebUI（需起服务）
test_mcp.py                      # MCP 协议
test_memory_store.py             # 记忆存储
test_multi_agent.py              # 多 Agent（部分需 API Key）
test_negotiation.py              # 协商
test_negotiation_integration.py  # 协商集成
test_observability.py            # 可观测性
test_p2_extra.py                 # P2 阶段额外测试
test_p3_all.py                   # P3 阶段全量测试
test_planner_memory.py           # planner + memory
test_rag.py                      # RAG（需 OPENAI 等 Embedding）
test_reliability.py              # 容错机制
test_streaming_permission.py     # 流式 + 权限
test_task_intent.py              # 任务意图
test_tools_full.py               # 工具全量
test_zhipu_embedding.py          # 智谱 Embedding（需 ZHIPU_API_KEY）
```

> ⚠️ Legacy 目录不应再有新代码；新测试请写到 `tests/` 顶级或 `tests/integration/`。
