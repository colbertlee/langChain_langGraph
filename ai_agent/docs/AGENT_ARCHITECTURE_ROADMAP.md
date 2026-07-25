# AIAgent 架构完善规划文档

> 本文档对照用户提出的"七大核心模块"逐项盘点当前实现，并按"补齐缺口 / 强化能力"两条主线给出**分阶段、可执行**的落地计划，便于一步步完善。

---

## 0. 现状速览

| 模块 | 已具备 | 主要缺口 |
|------|--------|----------|
| ① 核心大脑 | 多 Provider / 上下文管理（`context_manager.py`）/ 短期记忆（`memory_store.py`）/ 规划（`planner.py`）/ 多 Agent 编排（`multi_agent.py`）/ 容错（`llm_reliability.py`） | 提示词模板化与多版本管理 / CoT 显式注入 / Prompt 版本回滚 |
| ② 工具使用 | `tools.py` 18+ 内置工具 / MCP 协议（`mcp_server.py`）/ GitHub/Gitee 集成 / SQLite / 代码沙箱（`sandbox.py`） | 标准化 Schema（JSON-Schema 入参校验）/ 动态按需加载工具 / 沙箱策略分级 |
| ③ 记忆与存储 | Chroma 向量库（`rag.py`）/ SQLite（`context_db.py`）/ 长期记忆 + 语义检索（`memory_store.py`） | 知识库文档解析（PDF/Word）/ 多源知识库路由 / 记忆重要性衰减与召回评测 |
| ④ 多模态 IO | 流式 SSE/WebSocket（`app.py`）/ 输出脱敏（`security.py`）/ Trace 面板 | **流式中"思考过程 / 工具调用 / 错误"实时可视化** / 图片/附件解析（`multimodal.py` 待整合）/ 敏感词拦截前端联动 |
| ⑤ 编排与调度 | Supervisor / Parallel / Sequential（`multi_agent.py`）/ 协商竞价（`negotiation.py`）/ 状态机（`state_manager.py`）/ 任务调度（`task_scheduler.py`） | 主 Agent ↔ 上述调度器的统一接入 / 状态机驱动 LangGraph 节点显式转移 |
| ⑥ 运维与评测 | 可观测性（`observability.py`）/ 监控（`monitor.py`）/ FailLog（`llm_reliability.py`）/ A/B（`ab_testing.py`） | **Prompt 版本化与回滚** / Token 消耗面板 / 评测集与自动打分 |
| ⑦ 安全与权限 | 输入/输出安全（`security.py`）/ 危险命令拦截 / 权限（`permission.py`）/ HITL（`human_in_loop.py`）/ 沙箱（`sandbox.py`） | Prompt 注入对抗评测 / 工具级权限绑定 / HITL 在 Web 端的"批准/拒绝"闭环 |

整体评价：**七模块的基础全部存在**（仓库 v1.1.0 已具备相当完整的企业级骨架），本次重点是把"用户视角能直接感知的中间状态"、"Prompt 工程化"、"工具调用前后的人工把关"等几个薄弱处补齐。

---

## 1. 分阶段路线图

> 每个阶段都以"独立可交付、可验证"为单位，原则：
> - 不破坏现有 API；
> - 每步都加单测/集成测试；
> - 前端改动尽量走"渐进增强"（旧路径保留）。

### 阶段 A · Prompt 工程化 + 中间状态可视化（最贴近用户预期，建议先做）

| # | 任务 | 关键文件 | 验收 |
|---|------|----------|------|
| A1 | 抽出 `prompt_registry.py`：把硬编码的 `_build_system_prompt` 升级为 **System Prompt + Role Prompt + Tool Prompt** 三段可注册模板，支持变量注入 | `prompt_registry.py` (新增), `agent.py` 接入 | 单元测试：渲染结果与参数注入正确；同一角色 2 套 prompt 可热切换 |
| A2 | Prompt 版本化：每个模板带 `version`、`author`、`changelog`；支持 `agent.rollback_prompt(version)` | `prompt_registry.py`, `app.py` 新增 `/api/prompts` | UI 上能看到当前版本号与回滚按钮 |
| A3 | **流式中间状态可视化**：在 `run_stream` yield 时区分 `chunk / tool_call / reasoning / error` 四种事件类型，前端按"折叠面板"渲染"Agent 思考 / 调用了 X 工具 / 工具返回 Y" | `agent.py` (`run_stream` 返回结构化事件), `streaming.py` (`ChunkType` 已存在), `web/index.html` 新增时间线组件 | E2E：聊天时能在面板看到工具调用轨迹 |
| A4 | 显式 CoT 注入：在 system prompt 中追加"复杂任务必须先输出 ## 思考 ## 段落"指令；前端把"思考"段落折叠展示 | `prompt_registry.py`, `web/index.html` | 验证：回答前能看到折叠的"思考过程" |
| A5 | 把现有"输入前/输出后安全检查"事件接入流式通道，违规时前端弹提示并阻断 | `security.py`, `app.py` | E2E：触发敏感词立即中断且 UI 高亮 |

### 阶段 B · 工具调用工程化

| # | 任务 | 关键文件 | 验收 |
|---|------|----------|------|
| B1 | 工具入参 Schema 校验：用 `pydantic` / `jsonschema` 在 `tools.py` 注册层加 `input_schema` 校验，失败即返回结构化错误 | `tools.py` | 单测：参数缺失/类型错时返回可读错误 |
| B2 | **按需工具加载**：`ToolSelector` 根据意图动态筛选 top-K 工具（短期：基于关键词；长期：嵌入检索），避免 system prompt 过长 | `tool_selector.py` (新增) | token 消耗下降 30%+；命中无错 |
| B3 | 工具级权限绑定：把 `permission.PermissionGuard.check_tool(agent_id, tool_name)` 接入到工具执行前 | `permission.py`, `tools.py` | 单测：低权限 agent 调用高危工具被拒绝 |
| B4 | 沙箱分级策略：把 `sandbox.SandboxPolicy` 与"工具风险等级"绑定（LOW/MEDIUM/HIGH），代码/Shell 类工具默认进入 `SubprocessSandbox` | `sandbox.py`, `tools.py` | 单测：高风险代码执行被静态检查拦截 |
| B5 | 动态加载工具：实现"自然语言 → 工具调用"的兜底（已有 MCP，但补一个"通过 OpenAPI/JSON 描述自动注册工具"的接口） | `plugin_manager.py`（已有骨架） | 集成测试：动态加载一个示例 OpenAPI 工具 |

### 阶段 C · 记忆 / 知识库 强化

| # | 任务 | 关键文件 | 验收 |
|---|------|----------|------|
| C1 | 文档解析扩展：新增 PDF/Word/Markdown→结构化 chunk（`unstructured`/`pypdf`/`docx`） | `rag.py` | 单测：载入 PDF 后检索能命中 |
| C2 | 多知识库路由：不同用户/不同租户可挂多个 KB；按 session/role 选 KB | `rag.py`, `context_db.py` | 集成测试：两个 KB 互不污染 |
| C3 | 记忆衰减 + 重要性评分：在 `memory_store.MemoryItem` 加入 `decay_at`/`score`，检索时按"相关性 × 新鲜度"排序 | `memory_store.py` | 单测：老记忆权重降低 |
| C4 | 召回评测：内置一个 `eval/` 子模块，用固定问题集测检索准确率 | `eval/recall_eval.py` (新增) | CI 中可跑、可看分数 |

### 阶段 D · 编排层整合

| # | 任务 | 关键文件 | 验收 |
|---|------|----------|------|
| D1 | 把 `Planner` 与 `MultiAgent Orchestrator` 显式接入 AIAgent：`agent.run(complex_goal)` 自动选择"单 Agent 直答 / Planner 拆解" | `agent.py`, `multi_agent_integration.py` | E2E：复杂任务返回多步计划结果 |
| D2 | 状态机显式化：把 LangGraph 节点与 `state_manager.ConsistencyLevel` 对应，前端能"回到上一步" | `state_manager.py`, `web/index.html` | 演示：撤销一步工具调用 |
| D3 | 多 Agent 协作：内置 3 类 sub-agent（Coder / Reviewer / Researcher）作为开箱即用示例 | `multi_agent_examples.py`（已存在） | 单测：Supervisor 调度三类 sub-agent 完成代码生成+审查 |

### 阶段 E · 运维 & 评测

| # | 任务 | 关键文件 | 验收 |
|---|------|----------|------|
| E1 | **Token 消耗面板**：把每次 LLM 调用的 prompt/completion/total token 入库，前端 `/api/usage` 出趋势图 | `observability.py`, `app.py`, `web/index.html` | UI 折线图 |
| E2 | 死循环检测：同一 session 连续 N 次 fallback 或同一工具失败 K 次时，写告警 + 触发 HITL | `llm_reliability.py`, `human_in_loop.py` | 单测：模拟 3 次熔断后弹 HITL |
| E3 | **Prompt 版本回滚**：阶段 A2 的 UI 联动，后端要能 `apply_prompt(name, version)` | `prompt_registry.py`, `app.py` | UI 操作可逆 |
| E4 | Eval Harness：固定问题集 + 评分（关键词/Embedding 相似度/LLM-as-Judge），出分到 `observability` 指标 | `eval/eval_harness.py` (新增) | CI 中跑出基线分 |
| E5 | Tracing 导出 OpenTelemetry：让 `observability.Tracer` 支持 OTLP exporter，便于对接 Jaeger/Tempo | `observability.py` | 集成测试：导出 span 到 mock collector |

### 阶段 F · 安全纵深防御

| # | 任务 | 关键文件 | 验收 |
|---|------|----------|------|
| F1 | Prompt 注入对抗评测：`eval/prompt_injection_eval.py` 收录常见攻击模板，回归测试 | `eval/` (新增) | CI 通过基线 |
| F2 | 工具级 RBAC：每个工具声明 `risk_level`，`PermissionGuard` 按角色+风险级别决定是否需要审批 | `permission.py`, `tools.py` | 单测覆盖 4 个角色 |
| F3 | HITL Web 闭环：`BEFORE_TOOL_CALL` / `FINAL_ANSWER` 命中策略时，前端弹"批准/拒绝/修改"面板；决议回写 `ApprovalRequest` | `human_in_loop.py`, `web/index.html`, `app.py` | E2E 演示 |
| F4 | 输出审计：把"被拦截的输入/输出"统一写 `security_audit.log`，可检索 | `security.py` | 单测：审计接口可查 |
| F5 | 敏感操作二次确认：执行 `write_file`/`delete` 类工具前，HITL 默认 `ASK` | `permission.py`, `human_in_loop.py` | E2E 演示 |

---

## 2. 与七大模块的映射（执行完成度对照）

| 模块 | 阶段 | 完成后用户能看到的差异 |
|------|------|------------------------|
| ① 核心大脑 | A1 / A2 / A4 / D1 | 多套 prompt 可热切；复杂任务显示思考过程；多 Agent 调度自动生效 |
| ② 工具使用 | B1 / B2 / B3 / B4 | 工具入参更安全；按需加载；权限/沙箱统一约束 |
| ③ 记忆与存储 | C1 / C2 / C3 / C4 | PDF 等更多文档；多 KB；记忆带衰减；评测可量化 |
| ④ 多模态 IO | A3 / A5 / C1 | 流式展示 Agent 思考/工具调用；图片附件可被读入 |
| ⑤ 编排与调度 | D1 / D2 / D3 | 主 Agent 自动拆解；状态机可回退；多 Agent 协作示例 |
| ⑥ 运维与评测 | E1 / E2 / E3 / E4 / E5 | Token 趋势图、死循环告警、Prompt 回滚、Eval 自动化、OTel 导出 |
| ⑦ 安全与权限 | B3 / F1 / F2 / F3 / F4 / F5 | 注入评测、RBAC、HITL Web 闭环、审计日志、敏感操作确认 |

---

## 3. 推荐执行顺序（一次迭代一个完整阶段）

1. **第一波（最快出价值）**：阶段 A（A1+A3+A4+A5）  
   原因：直接补齐用户提到"流式思考过程 / 工具调用中间状态 / Prompt 工程化"，改动小、反馈快。

2. **第二波（补齐安全 + 工具治理）**：阶段 B + 阶段 F（F2/F3/F5）  
   原因：在工具层引入 Schema、权限、HITL，是企业化最缺的一环。

3. **第三波（补齐运维 & 评测）**：阶段 E（E1+E2+E3+E4）  
   原因：上线后才知道"该不该这么跑"，Token 面板和 Eval 是必备。

4. **第四波（深度优化）**：阶段 C + 阶段 D + 阶段 F（F1/F4）+ 阶段 E5  
   原因：知识库、规划、可观测生态属于长期能力建设。

---

## 4. 测试 & 验收策略

- 每个阶段提交必须含：
  1. **新增/修改的单元测试**（`pytest ai_agent/tests/`）；
  2. **E2E 用例**（如涉及 Web：放在 `web_console/e2e/` 或 `ai_agent/tests/test_app_*.py`）；
  3. **CHANGELOG 条目**；
  4. **FEATURES_GUIDE.md 更新**（面向最终用户）。
- 所有改动保留"开关"：通过 `config.py` 新增 feature flag，默认关闭 → 测试通过 → 灰度开启 → 全量。

---

## 5. 不在本轮范围的事项

- 多模态（语音、图片生成）端到端：只做"接口预留 + 数据通路"，不接入具体大模型。
- 跨进程分布式部署：当前 `distributed_bus.py` 已具备抽象，本轮不部署示例集群。
- 模型微调 / RLHF：与本规划无直接关系。

---

## 6. 提问给用户（确认优先级）

请确认下面三点以决定第一波具体范围：

1. **第一波是否聚焦"阶段 A"？**（A1/A3/A4/A5 是用户最直观的体感升级）
2. **是否同时开启"阶段 B + F2/F3/F5"的安全/工具治理？** 还是延后到第二波？
3. **是否在每阶段提交后要求"前端截图 + 演示脚本"？** 还是只跑测试即可。

---

> 文档维护：`ai_agent/docs/AGENT_ARCHITECTURE_ROADMAP.md`  
> 最近更新：2026-07-23