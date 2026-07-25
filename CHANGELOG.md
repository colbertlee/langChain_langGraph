# 更新日志

所有重要的项目更新都将记录在此文件中。

---

## [v2.0.0] - 2026-07-25

### Migration Guide · 从 v1.x 升级

**数据兼容性**:✅ 向后兼容。`context_memory.db` / `memory.db` / `chroma_db` 全部可直接复用,无需迁移工具。

**配置变更**:
| 变量 | v1.x | v2.0 |
|---|---|---|
| `MODEL_PROVIDER` 默认值 | `openai` | 不变 |
| 新增 `EMBEDDING_MODEL_TYPE` | — | `openai / zhipu / minimax / jina` |
| 新增 `AI_AGENT_DISABLE_PLACEHOLDER_CHECK` | — | `1`(不传占位符 Key 时短路 LLM 初始化) |
| 移除 `LEGACY_API_PORT` | 有 | 已删除,统一 `PORT=8000` |

**端点兼容**:
- `/api/chat`、`/api/chat/stream`、`/api/models`、`/api/memory/*`、`/api/prompts/*`、`/api/hitl/*` 全部保持原签名
- 新增:`/api/context/*`、`/api/permission/enforce`、`/api/user-prompts/export`、`/api/user-prompts/import`

**前端兼容**:
- 单文件 HTML 主界面(端口 8765)继续可用
- React 控制台(端口 5173 / 8000)正式成为推荐入口

**桌面二进制**:
- v1.x 桌面包无法热更新到 v2.0(因为 `_internal/` 体积与依赖变化),需卸载后重新下载
- 卸载步骤见 [DISTRIBUTION.md §10](file:///e:/langChain_langGraph/DISTRIBUTION.md)

**破坏性变更**:
- `web_ui:run` 的端口绑定从 `0.0.0.0:8000` 调整为 `127.0.0.1:8000`(安全);如需对外暴露,用 `HOST=0.0.0.0` 显式声明。
- `agent.log` 默认级别从 `INFO` → `WARNING`(减少噪声);需要详细日志请设 `LOG_LEVEL=INFO`。

### 新增
- **多渠道分发**:PyPI(PEP 740 OIDC)、Docker GHCR、Scoop、Homebrew、GitHub Release 全链路打通。
- **桌面二进制打包**:`build_windows.ps1` / `build_linux.sh` / `package_dist.ps1` 自动产出三平台 PyInstaller 单文件可执行包。
- **React 控制台(web_console)**:React 19 + Vite 5 + TypeScript 5 + Tailwind 3 + Zustand 4 + assistant-ui;8 个页面 Chat/Agents/Approval/Observability/Tools/Settings/Prompts/Memory。
- **多阶段 Docker 镜像**:`web_console/Dockerfile` 把前端构建产物嵌入到 `python:3.11-slim`,`docker compose up -d` 一键起前后端。
- **GitHub Actions 流水线**:`backend-ci.yml`(pytest + 3 层安全扫描)、`ci.yml`(前端 vitest + e2e + 视觉基线)、`release.yml`(PyPI + GHCR + Release)、`release-build.yml`(三平台桌面打包)、`weekly-upgrades.yml`。
- **GHCR / Pages / Branch Protection 文档**:完整发版 runbook。

### 修复与改进
- React 控制台侧栏折叠按钮无障碍焦点 → `aria-expanded`。
- Vite dev 代理偶发 502 → 长连接空闲超时调高。
- Tailwind 深色主题背景缺失 → `globals.css` 补齐深空黑令牌。
- 会话列表在长上下文下卡顿 → Zustand 选择器细粒度订阅。
- 桌面二进制体积优化:`package/EXCLUDES` 排除 torch/onnxruntime 等大依赖,Windows 包 ~470 MB。

---

## [v1.1.0] - 2026-07-22

### 新增功能

#### 1. 多级容错机制 (llm_reliability.py)

**五层容错栈**：
- **Timeout 层**：LLM 调用超时控制
- **RetryPolicy 层**：指数退避 + 抖动重试策略
- **FallbackChain 层**：多 Provider 自动切换（OpenAI → DeepSeek → Qwen → Moonshot → 智谱 → MiniMax）
- **CircuitBreaker 层**：单 Provider 熔断器（连续失败自动熔断，60秒后恢复）
- **GracefulDegradation 层**：全部 Provider 失败时基于记忆/上下文生成骨架回答

**新增组件**：
- `ResilientLLMInvoker`：容错栈总入口，同步/流式调用
- `FailLogRepository`：失败日志持久化（SQLite），支持错误聚合
- `PrimaryStandbyConfig`：主备模型声明式配置
- `StandbyWarmupService`：Standby 模型后台预热服务

#### 2. 结构化上下文管理 (context_manager.py)

**核心组件**：
- `EntityExtractor`：自动提取 ETF 代码、城市、日期、动作、查询类型等实体
- `ContextBuilder`：智能构建 LLM 上下文（摘要 → 实体 → 工具 → 偏好 → 对话历史）
- `AutoSummarizer`：会话自动摘要生成
- `ContextManager`：上下文管理器主入口

**特性**：
- 上下文缓存（基于输入内容哈希）
- 按重要性权重分配 token 预算
- 自动滚动归档旧消息（避免数据库膨胀）
- Token 计数使用 0.35 系数（中英混合优化）

#### 3. 统一记忆存储 (memory_store.py)

**记忆类型**：
- `WORKING`：工作记忆（当前交互）
- `EPISODIC`：情景记忆（会话片段）
- `SEMANTIC`：语义记忆（知识沉淀）
- `PROCEDURAL`：程序记忆（操作流程）

**核心组件**：
- `MemoryDatabase`：记忆数据库（SQLite，支持向量存储）
- `ShortTermMemory`：短期记忆（注意力聚焦 + 衰减机制）
- `LongTermMemory`：长期记忆（语义检索 + 向量相似度）
- `MemoryConsolidator`：记忆整合器（短期→长期迁移，含去重）
- `UnifiedMemoryStore`：统一记忆存储单例

**特性**：
- 记忆重要性分级（LOW/MEDIUM/HIGH/CRITICAL）
- 记忆衰减机制（decay_factor）
- 语义向量检索（支持 numpy fallback）
- 自动记忆整合（每 5 轮触发）

#### 4. 多 Agent 编排 (multi_agent.py)

**编排模式**：
- `SUPERVISOR`：Supervisor 模式（主 Agent 协调专业 Agent）
- `PARALLEL`：并行模式（多 Agent 同时执行）
- `SEQUENTIAL`：顺序模式（Agent 按序执行）
- `HIERARCHICAL`：层次模式（多层 Agent 协同）
- `FANOUT`：扇出模式（一任务分发给多 Agent）

**核心组件**：
- `AgentOrchestrator`：多 Agent 编排器
- `WorkerAgent`：工作 Agent
- `Task`：任务定义（含依赖关系）
- `Workflow`：工作流定义

#### 5. 协商与竞争机制 (negotiation.py)

**协商系统**：
- `NegotiationParticipantMixin`：协商参与者 Mixin
- `NegotiationManager`：协商管理器
- `Proposal`：协商提议（含 utility 评分）

**竞价/拍卖系统**：
- `AuctionManager`：拍卖管理器
- `AuctionStrategy`：拍卖策略（第一价格/第二价格/英式/荷兰式/综合评分）
- `Bid`：竞价记录

#### 6. 可靠性机制 (reliability.py)

**组件**：
- `RetryPolicy`：重试策略（Fixed/Linear/Exponential/Exp_Jitter）
- `CircuitBreaker`：三态熔断器（Closed/Half-Open/Open）
- `DeadLetterQueue`：死信队列（失败消息缓冲）
- `ReliabilityLayer`：可靠性层总控

#### 7. 能力注册中心 (capability.py)

- `CapabilityRegistry`：能力注册表
- `WorkerProfile`：Worker 能力画像
- `WorkerMetrics`：Worker 指标统计
- `LoadBalancer`：负载均衡器（RoundRobin/Random/LeastLoaded）

#### 8. 消息协议与总线 (message_protocol.py, message_bus.py, distributed_bus.py)

**消息协议**：
- `Message`：消息基类
- `TaskMessage`：任务消息
- `MessageType`：消息类型枚举
- `MessagePriority`：消息优先级

**消息总线**：
- `MessageBus`：消息总线
- `BaseAgent`：Agent 基类
- `DistributedMessageBus`：分布式消息总线（Redis 集成）
- `PubSubScenarios`：发布订阅场景

#### 9. 增强工具集

**新增 MCP 工具 (mcp_tools.py)**：
- 文件操作：`file_read`、`file_write`、`directory_list`
- 网络工具：`http_request`、`curl`
- 开发工具：`git_status`、`git_log`、`docker_ps`
- 系统工具：`whoami`、`system_info`、`process_list`
- 数据工具：`json_parse`、`json_query`
- 工具类：`current_time`、`timestamp_convert`

**增强 ETF 工具 (tools.py)**：
- `get_etf_info`：ETF 基本信息
- `get_etf_price`：实时行情
- `get_etf_history`：历史行情
- `get_etf_knowledge`：ETF 知识库
- `compare_etfs`：多 ETF 对比
- `etf_analysis`：综合分析与预测

#### 10. 安全增强 (security.py)

- 输入安全检查（危险命令拦截）
- 输出脱敏（敏感信息过滤）
- 工具执行确认
- 意图检测（query/compare/analysis/calculate/greeting/command）

#### 11. 可观测性 (observability.py)

- 性能指标收集
- 上下文缓存
- 监控仪表板

#### 12. 其他新增模块

- `ab_testing.py`：A/B 测试框架
- `adaptive_threshold.py`：自适应阈值
- `human_in_loop.py`：人机交互
- `multimodal.py`：多模态支持
- `planner.py`：任务规划器
- `plugin_manager.py`：插件管理器
- `sandbox.py`：沙箱环境
- `state_manager.py`：状态管理器
- `streaming.py`：流式处理
- `task_intent.py`：任务意图识别
- `task_scheduler.py`：任务调度器

### 功能增强

#### Agent 核心 (agent.py)

- **多 Provider 支持**：OpenAI、DeepSeek、Qwen、Moonshot、智谱、MiniMax、百度、讯飞
- **Sub-Agent 系统**：轻量级子任务委派
- **主备模型切换**：自动故障切换 + 手动切换
- **结构化上下文注入**：基于 EntityExtractor + ContextBuilder
- **记忆增强**：短期/长期记忆统一管理
- **流式容错**：流式模式下的 fallback 处理

#### API 服务 (api.py)

- WebSocket 流式响应
- API Key 动态配置
- 会话管理 API
- 健康检查端点

#### Web UI (web/)

- 现代化聊天界面
- 设置面板（API Key 配置）
- 消息流式显示
- 错误提示

### Bug 修复

- **W1/W6**：实体关系创建时的空 ID 防御
- **W2**：Token 阈值触发摘要（避免长消息预算失控）
- **W3/W4**：上下文构建的 token 预算分配优化
- **W5**：消息滚动归档（防止数据库膨胀）
- **C2**：记忆存储重置时缓存清理
- **C4**：向量维度一致性检查
- **C5**：记忆整合去重优化（N×SQL → 批量）
- **C7**：记忆整合候选筛选职责分离
- **C8**：记忆整合触发时机修复
- **F1**：错误指纹聚合优化（去掉变量尾部）

### 性能优化

- 上下文构建缓存（基于内容哈希）
- 记忆整合批量处理
- Token 预算智能分配
- 流式输出差分更新

---

## [v1.0.0] - 2026-07-18

### 初始发布

#### 新增

- AI Agent 核心模块 (`agent.py`)
- LangChain 工具集 (`tools.py`)
  - `get_current_time` - 获取当前时间
  - `calculate` - 数学计算
  - `search_web` - 网络搜索
  - `query_knowledge_base` - 知识库查询
  - `load_knowledge_base` - 加载文档
  - `read_file` - 读取文件
  - `write_file` - 写入文件
  - `list_files` - 列出文件
  - `run_code` - 执行代码
  - `get_weather` - 查询天气
  - `github_search` - GitHub 搜索
  - `generate_chart` - 生成图表
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
