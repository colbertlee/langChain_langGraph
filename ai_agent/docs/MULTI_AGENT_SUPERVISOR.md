# Milestone 2.2.3 — Multi-Agent Supervisor 架构设计文档

> LangGraph Supervisor Multi-Agent 模式 + 任务拆解协作
>
> 状态：已交付 / 质量门禁全绿（841 pytest passed + 0 TS 错误）

---

## 1. 目标与背景

在已存在的 **SqliteSaver Checkpointer + HITL + Local Chroma RAG** 基础上，引入 Supervisor Multi-Agent 架构，实现复杂任务的自主拆解与分发执行。

设计目标：
- 复杂任务自动拆分为"研究 / 代码 / 检索"三类子任务；
- Worker 子图独立构建，工具集最小授权；
- 全量保留 SqliteSaver Checkpointer 状态持久化与 HITL 审批能力；
- 前端可通过 SSE `event: agent_switch` 实时呈现"思考节点转换"。

---

## 2. 核心流程

```
                        ┌───────────────────────────────────────┐
                        │      SupervisorState（LangGraph）      │
                        │  messages / next_node / subtasks      │
                        └───────────────────────────────────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │   supervisor    │  ← 调用 LLM 决策
                              │  (RouterOutput) │  ← next_agent + reason
                              └─────────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │ add_conditional_edges  │                        │
              ▼                        ▼                        ▼
      ┌───────────────┐        ┌───────────────┐        ┌───────────────┐
      │research_worker│        │  code_worker  │        │  rag_worker   │
      │  (web_search) │        │(python_interp)│        │(knowledge_srch)│
      └───────────────┘        └───────────────┘        └───────────────┘
              │                        │                        │
              └──────────── add_edge(name, "supervisor") ───────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │   supervisor    │  ← 再次决策
                              └─────────────────┘
                                       │
                                  FINISH?
                                   │  │
                              是  │  │ 否（继续派 Worker）
                                   ▼  ▼
                              ┌─────┐  （回到循环）
                              │ END │
                              └─────┘
```

关键路径：
1. **START → supervisor**：所有请求从 Supervisor 入口进入。
2. **supervisor → worker**：根据 `RouterOutput.next_agent` 用 `add_conditional_edges` 路由到对应 Worker。
3. **worker → supervisor**：Worker 执行完必返回 Supervisor（强制收敛，避免孤立节点）。
4. **supervisor → END**：当 `next_agent == "FINISH"`，主图终止。

---

## 3. 状态定义

### 3.1 `SupervisorState`（TypedDict + `add_messages` reducer）

```python
class SupervisorState(TypedDict, total=False):
    messages: Annotated[List[Any], add_messages]   # 自动追加
    next_node: WorkerName                          # 路由目标
    subtasks: List[Dict[str, Any]]                 # 已派发的子任务审计
```

字段说明：

| 字段 | 类型 | 用途 |
|---|---|---|
| `messages` | `Annotated[List, add_messages]` | LangGraph 标准消息列表，Worker 返回的 `ToolMessage` / `AIMessage` 由 reducer 自动追加 |
| `next_node` | `Literal["research_worker", "code_worker", "rag_worker", "FINISH"]` | Supervisor 决策结果，供 `add_conditional_edges` 读取 |
| `subtasks` | `List[Dict]` | 审计追踪，记录每次 Supervisor 决策的 `(agent, task, thought)` |

### 3.2 `RouterOutput`（Pydantic BaseModel）

```python
class RouterOutput(BaseModel):
    next_agent: WorkerName                  # 下一个 Worker（含 FINISH）
    task_description: Optional[str]         # 派给 Worker 的子任务
    thought_process: str                    # 思考过程 → SSE agent_switch.reason
```

### 3.3 `WorkerName`

```python
WorkerName = Literal["research_worker", "code_worker", "rag_worker", "FINISH"]
```

---

## 4. 三个核心文件

### 4.1 [supervisor_state.py](../supervisor_state.py)

| 导出符号 | 职责 |
|---|---|
| `SupervisorState` | 主图状态 TypedDict |
| `RouterOutput` | Supervisor 结构化输出模型 |
| `WorkerName` | 字面量联合类型 |
| `parse_router_output(text)` | 容错 JSON 解析（严格JSON → 嵌入段 → 正则 → 关键字兜底 → FINISH） |
| `build_agent_switch_event(next_agent, thought)` | SSE `agent_switch` 帧构造器 |

### 4.2 [agent_workers.py](../agent_workers.py)

| 导出符号 | 职责 |
|---|---|
| `WorkerState` | Worker 子图统一状态 |
| `build_research_worker()` | 仅加载 `web_search` 的研究子图 |
| `build_code_worker()` | 加载 `python_interpreter` 的代码子图（HITL 包裹由 `v21_tools` 的 `requires_approval=True` 自动生效） |
| `build_rag_worker()` | 加载 `knowledge_search`（Session 隔离 ChromaDB）的 RAG 子图 |
| `build_default_workers()` | 一次性返回三 Worker 字典 |

每个 Worker 内部结构：
```
START → worker_node（加载工具 + 执行 + 包装 ToolMessage）→ END
```

子图完成后返回控制权给 Supervisor 主图（`add_edge(name, "supervisor")`）。

### 4.3 [supervisor_agent.py](../supervisor_agent.py)

| 导出符号 | 职责 |
|---|---|
| `make_supervisor_node(llm, on_agent_switch)` | 构造 Supervisor 节点：调用 LLM → 解析 `RouterOutput` → 推 `agent_switch` → 返回 `Command(goto=...)` |
| `build_supervisor_workflow(llm, workers, *, checkpointer, on_agent_switch)` | 装配 `StateGraph(SupervisorState)` 主图，注入 3 个 Worker 子图 + `add_conditional_edges` 路由 + `SqliteSaver` Checkpointer |
| `default_supervisor_llm()` | 默认 LLM（FakeListLLM 兜底，避免生产环境无 key 时崩溃） |
| `stream_supervisor(workflow, ...)` | 流式执行包装（`workflow.stream(...)`） |
| `SUPERVISOR_PROMPT` | Supervisor 决策用的系统提示 |

`build_supervisor_workflow` 关键行为：
- `checkpointer=None` 时 fallback 到 `MemorySaver`；
- path_map **动态生成**（只包含图中实际存在的 Worker），允许测试只注入部分 Worker；
- 未知 `next_agent` → 自动降级为 `FINISH`（fail-fast）。

---

## 5. SSE 事件增强（app.py）

新增端点：**`POST /api/chat/supervisor/stream`**

事件序列：
1. `event: start` → `{type: "start", mode: "supervisor"}`
2. `event: agent_switch` → `{type: "agent_switch", agent: "<worker|FINISH>", reason: "<thought>"}`
3. `event: update` → LangGraph 原生 `updates` 流
4. `event: complete` / `event: end` → 收尾

前端 UI 监听 `agent_switch` 即可在 thinking 节点转换时显示当前由哪个 Worker 执行任务。

---

## 6. 测试覆盖

测试文件：[tests/test_multi_agent_supervisor.py](../tests/test_multi_agent_supervisor.py)（共 **32 个测试**，全绿）

| 类别 | 测试数 | 覆盖点 |
|---|---|---|
| `TestRouterOutputParsing` | 8 | 严格JSON / 嵌入 JSON / Markdown 包裹 / FINISH 字面 / 未知 agent 兜底 / 别名兼容（researcher→research_worker）/ 空输入 / 乱码 |
| `TestSupervisorStateShape` | 3 | State 字段形状 / RouterOutput 必填 / `agent_switch` 事件构造 |
| `TestWorkerSubgraphs` | 5 | 三个 Worker 独立 compile / `build_default_workers` 完整性 / Worker 单独 invoke |
| `TestSupervisorMultiStepLoop` | 5 | FINISH 终止 / research → FINISH / **rag + code + FINISH 复合循环** / 未知 worker 降级 / state 持久化 |
| `TestSupervisorHITLClosedLoop` | 3 | python_interpreter 必须 `requires_approval=True` / HITLStore request + approve / **code_worker 触发 HITL → 审批 → 回到 Supervisor → FINISH 闭环** |
| `TestAgentSwitchEventContract` | 2 | 事件必有字段 / JSON 可序列化（含中文 / 特殊字符） |
| `TestSupervisorWorkflowBuild` | 3 | 空 workers 抛错 / 未知 worker 名抛错 / default LLM 可解析 |
| `TestSupervisorCheckpointPersistence` | 1 | SqliteSaver / MemorySaver 持久化（`cp.list(thread_id)`） |
| `TestHITLCompat` | 2 | HITL resolve_after_decision approved / rejected 流程不退化 |

---

## 7. 关键设计决策

1. **RouterOutput 容错解析** — LLM 输出不一定严格 JSON，按优先级逐级兜底；同时 alias 兼容老版命名（`researcher / coder / reviewer`）。

2. **Worker 子图独立可测** — 三个 Worker 都能脱离 Supervisor 单独 `invoke`（便于隔离测试与未来的能力扩展）。

3. **HITL 闭环** — `python_interpreter` 在 `v21_tools.TOOL_REGISTRY` 仍标记 `requires_approval=True`，HITL 拦截链路完全沿用既有 `HITLStore.request_approval → approve → resolve_after_decision`；Supervisor 模式下脚本 LLM 验证 `code_worker → supervisor → FINISH` 完整闭环。

4. **path_map 动态生成** — `add_conditional_edges` 的 path_map 只包含图中实际存在的 Worker，允许只注入部分 Worker 用于测试。

5. **Checkpointer 兼容** — SqliteSaver 生产路径保留；测试用 `MemorySaver`；传递 `None` 时自动 fallback 到内存。

6. **状态字段语义清晰** — `messages` 用 `add_messages` reducer 自动追加，避免整段替换；`subtasks` 仅追加不重写，便于审计。

---

## 8. 与既有架构的关系

| 既有组件 | 复用方式 |
|---|---|
| `langgraph.checkpoint.sqlite.SqliteSaver` | 主图 `compile(checkpointer=...)` 全量保留 |
| `hitl_langgraph.HITLStore` | `code_worker` 通过 `requires_approval=True` 自动走同一审批管线 |
| `v21_tools.web_search` / `python_interpreter` / `knowledge_search` | Worker 子图按需加载，最小授权 |
| `RAGModule` / Chroma | `rag_worker` 走 Session 隔离的 knowledge_search |
| `agent.py` 的 `_HITLWrappedTool` | 自动应用到 code_worker 的工具调用（无需 Supervisor 重复实现） |

---

## 9. 后续演进

- **并行 Worker**：当前为顺序 Supervisor → Worker；可扩展为 `add_conditional_edges` 返回 `Send` 实现多 Worker 并行。
- **HITL 工具调用恢复**：当前 HITL 拦截发生在 Worker 内部；可升级为 Supervisor 主图层面直接处理 `pending_approval`（更显式的状态机）。
- **动态 Worker 注册**：通过 LangGraph 的 `add_node` 动态注入（目前为静态三 Worker）。