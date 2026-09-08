# 更新日志

所有重要的项目更新都将记录在此文件中。

---

## [v2.0.11-patch] - 2026-09-08

**类型**: Hotfix · **SemVer**: PATCH（无 BREAKING）
**Commit**: `refactor(agent): 增强上下文结构化注入与防御栈 (P0/P1 修复闭环)`
**诊断依据**: 内部「Agent 自动化运行与状态验证」巡检（2026-09-08）→ 5 维诊断报告。

### 修复项（P0 / P1 全量闭环）

- **P0 — 上下文结构化 Message 隔离**：`_build_messages_payload` 新增，发送
  `[SystemMessage, HumanMessage]` 替代旧的「单条 HumanMessage 字符串拼接」。
  SystemMessage 仅承载 RAG 检索 + 历史记忆片段（标签 `【背景上下文与历史记忆】` /
  `【当前会话上下文】`），HumanMessage 仅承载经 `_apply_user_prompt_template` 安全
  重写后的纯净 user_input。彻底消除「上下文被当作用户问题覆盖 System Prompt」的
  多轮指令跟随退化。
- **P0 — Tool 工具异常防御栈**：
  - `v2_slim/tools_v2.py::web_search.search` 捕获 `requests.RequestException` /
    SerpAPI `results["error"]`，统一返回 `❌ 搜索服务暂时不可用: {msg}`，由 LLM
    决定降级路径，不再让 ToolMessage 让 LLM 误判为 fatal。
- **P1 — SQL 工具安全硬化**：
  - `v2_slim/tools_v2.py::data_query.sql` 引入 SQL 白名单（仅 `SELECT / WITH /
    PRAGMA / EXPLAIN`），捕获 `sqlite3.DatabaseError / OperationalError`，防止
    Agent 触发破坏性语句。
- **P1 — Checkpointer 安全降级开关**：
  - `_init_checkpointer` 重排为「先尝试 SqliteSaver → 失败再判 opt-in」：
    默认失败时直接 `raise RuntimeError("SqliteSaver Checkpoint store unavailable")`
    阻止静默降级；仅当调用参数 `memory_fallback=True` 或 env
    `AI_AGENT_INMEM_CHECKPOINT ∈ {1, true, yes, on}` 时才回退 `MemorySaver` 并
    打 `WARNING("Checkpointer 初始化失败，已显式降级为内存模式")`。
  - `tests/conftest.py` autouse fixture 注入 `AI_AGENT_INMEM_CHECKPOINT=1`，
    保证测试环境 SqliteSaver 不可用时仍能走 MemorySaver 路径，633 个用例不受影响。
- **P1 — Memory Token 预算限流**：
  - `memory_store.get_context(query, session_id, max_tokens=None)` 新增可选
    `max_tokens` 参数；agent.py 调用处统一追加 `max_tokens=1000`，与
    `context_manager._join_and_truncate` 字符预算策略对齐，超出截断并标记
    `[已截断]`，杜绝长对话 Token 预算溢出。
- **P1 — 降级路径同步加固**：
  - `_safe_memory_hint` 同步追加 `max_tokens=1000`，确保 LLM 异常降级路径同样
    受预算约束。

### 接口影响

- **新增**：`AIAgent._build_messages_payload(user_input, final_input) -> List[Any]`。
- **扩展**：`AIAgent._init_checkpointer(memory_fallback: Optional[bool] = None)`。
- **扩展**：`MemoryStore.get_context(query, session_id, max_tokens: Optional[int] = None)`。
- `_apply_user_prompt_template(user_input, enhanced_input) -> str` 签名 / 行为
  **完全保持向后兼容**，`prompt_registry` 与 `test_prompts_api.py` 接口不变。

### 测试

- `pytest --no-cov`（全量）：**633 passed / 0 failed / 2 deselected**（≈ 82.9s）。
- `_llm_agent_test.py` 沙箱：12 passed / 0 failed（含真实 minimax 端到端）。
- 退出码：0。

---

## [v2.0.10] - 2026-09-07

**类型**: Cleanup · **SemVer**: PATCH (含 1 个 BREAKING)
**Release Notes**: [release_notes/v2.0.10.md](release_notes/v2.0.10.md)
**SOP**: [docs/VERSION_MANAGEMENT.md](docs/VERSION_MANAGEMENT.md)

### ⚠️ BREAKING CHANGES

- **`AIAgent_LEGACY` 环境变量从 v2.0.10 起完全无效**。`config.LEGACY_MODE` 改为常量 `False`（不再读取 env），`v2_slim/*_legacy.py` 共 7 个文件已物理删除。如有运维脚本设置了 `AIAgent_LEGACY=true`，请删除该配置。回滚需 `git revert` 本次清理 commit。详见 [release_notes/v2.0.10.md §Breaking Changes](release_notes/v2.0.10.md#-breaking-changes)。

### Removed

- **7 个 `v2_slim/*_legacy.py` 模块**：`tools_legacy.py` / `memory_store_legacy.py` / `multi_agent_legacy.py` / `permission_legacy.py` / `human_in_loop_legacy.py` / `observability_legacy.py` / `negotiation_legacy.py`。
- **`config.LEGACY_MODE` 真回滚分支**（`agent.py` / `api.py` / `v2_slim/multi_agent_router.py` 三处的 `if LEGACY_MODE` 块）。
- **`v2_slim/multi_agent_router.py`** 的 `get_orchestrator()` / `reset_orchestrator()` 入口（仅 LEGACY 路径用）。
- **`tests/test_v2_slim_legacy_switch.py`** 整个文件（8 个 LEGACY 双路测试）。
- **前端死代码**：`web_console/src/pages/Chat.tsx`（老 assistant-ui runtime v1 页）+ `components/chat/SessionList.tsx` + `SessionList.test.tsx`。
- **调试一次性脚本**（共 57 个 .py + 数据/日志产物）：
  - `ai_agent/tests/legacy/` 整个目录（26 个历史 skip 测试）
  - `ai_agent/scripts/legacy_tests/` 整个目录（10 个旧测试脚本）
  - 顶层 `diag_*.py` × 14 + `_diag_*.py` × 5
  - 顶层 `_chart_*.png` × 8 + `_chart_raw.txt` / `_e2e_out.txt` / `_e2e_regression.py` / `_dataflow.py` / `_demo.txt` / `_products.json` / `_sales.csv`
  - 顶层调试 `test_*.py` × 15（`test_chart_*.py` / `test_sse*.py` / `test_tools*.py` / `test_endpoints.py` / `test_data.py` / `test_minimax_direct.py` / `test_fileops_code.py`）
  - `scripts/add-slow-markers.py`（已 no-op）

### Added

- **`ai_agent/scripts/real_api_smoke.py`** — 真实 LLM provider 冒烟脚本（manual-only，3 段 PASS/FAIL：hello + 工具直调 + 流式事件，artifact 落到 `evals/runs/<ts>_real_smoke/`）。
- **`ai_agent/.gitignore`** 新增 13 条规则覆盖上述调试产物与一次性脚本，防止同类积累。

### Changed

- **`ai_agent/agent.py`** — `_resolve_tools()` / `_resolve_memory_store()` 固定为 v2 slim；`__init__` 改用 `_resolve_tools()` 取代已删的 `get_all_tools()`。
- **`ai_agent/api.py`** — `_resolve_monitor()` 固定走 `v2_slim.telemetry`；删除 LEGACY_MODE telemetry 分支。
- **`ai_agent/v2_slim/multi_agent_router.py`** — 简化为 v2 slim only 入口；删除 LEGACY 入口函数。
- **`ai_agent/v2_slim/frozen.py` / `frozen_modules.py`** — 注释更新（去除 LEGACY_MODE 恢复误导）。
- **`ai_agent/tests/test_v2_slim_consistency.py`** — `test_legacy_mode_respects_env` 改写为 `test_legacy_env_var_is_ignored`（验证 env 被忽略）。
- **`ai_agent/tests/test_staging_monitor.py`** — 删 `test_legacy_modules_importable`，保留 frozen 测试。
- **`ai_agent/tests/test_v2_slim_tools.py`** — `test_legacy_modules_importable` 改写为 `test_v2_slim_modules_importable`。
- **`web_console/e2e/app.spec.ts`** — 修复 3 处过期断言：路由从 `/agents /tools` → `/admin?tab=xxx`、侧栏入口 6 → 8、"新建会话" → 主题切换按钮（v2 ChatPage 已不用 SessionList）。
- **`web_console/README.md`** §2.4 — 新增「联调实战」段（3 步自检 + 端口冲突表 + Playwright/real_api_smoke 命令速查）。
- **`docs/DIRECTORY_STRUCTURE.md`** — 删除 `legacy_tests/` 条目与 `add-slow-markers.py` 条目。
- **`ai_agent/docs/STAGING_DEPLOY_CHECKLIST.md`** — P2.1-P2.5 段标为「✅ 已完成（v2.10+）」。
- **`ai_agent/docs/STAGING_MONITORING.md`** — P2 任务清单标完成，回滚说明改为 `git revert`。
- **`ai_agent/README.md`** — `v2_slim/` 树注释去掉 `_legacy.py` 一行。
- **`ai_agent/scripts/migrate_memory_v1_to_v2.py`** — 完成日志「设置 env=false」改为「v2.10+ 无需切换」。

### Verification

| Check | Result |
|---|---|
| `pytest tests/ --collect-only` | 633/635 collected (2 deselected, 0 errors) |
| `pytest tests/{core,security,permission,skills,app_e2e,v2_slim*,staging}` | 219 passed in 47.47s |
| `npx playwright test e2e/app.spec.ts` | 9 passed in 17.5s |
| `npx vitest run` (web_console) | 37 passed (7 files) |
| `python scripts/real_api_smoke.py --skip-agent` | tools PASS in 54ms |

---

## [v2.0.9] - 2026-09-04

**类型**: Capability · **SemVer**: PATCH
**Release Notes**: [release_notes/v2.0.9.md](release_notes/v2.0.9.md)
**SOP**: [docs/VERSION_MANAGEMENT.md](docs/VERSION_MANAGEMENT.md)

### Added

- `ai_agent/v2_slim/` — slim runtime namespace merging 5 modules into 3 (`tools_v2.py` 6 composite `@tool` with `subcommand: Literal[...]`, `memory_store_v2.py` dual `ShortTermContext` + `LongTermKnowledge`, `multi_agent_v2.py` keeps only `SEQUENTIAL` + `SUPERVISOR`, `approval.py` unified `ApprovalGate` + RBAC `Policy`, `telemetry.py` single `TelemetrySink` facade). Opt-in via `AIAgent_LEGACY=true` fallback; default is slim.
- `ai_agent/harness.py` + `harness_runner.py` + `harness_storage.py` + `harness_cli.py` + `harness_observability.py` — Agent runtime facade with dependency injection, configurable planner/memory/observability/security/sandbox flags, and `Trace` dataclass replay.
- `ai_agent/scripts/migrate_memory_v1_to_v2.py` — collapse EPISODIC/PROCEDURAL records into ShortTerm/LongTerm layout.
- `ai_agent/scripts/staging_monitor_loop.py` — 24h staging probe loop driven by `test_staging_monitor.py`.
- `ai_agent/docs/HARNESS.md`, `STAGING_DEPLOY_CHECKLIST.md`, `STAGING_MONITORING.md` — Harness reference + staging gate runbooks.
- `ai_agent/evals/` — eval harness infra: `evals/sets/smoke_v1.jsonl` + `evals/runs/<ts>/{cases.jsonl,summary.json,metrics.json,report.md}` for every `harness_dry_*`, `harness_pr*_local`, `harness_smoke_*` run.
- `.github/workflows/release.yml` — tag-driven release pipeline (`v[0-9]+.[0-9]+.[0-9]+*`) wrapping `release_cli.py github`/`gitee` with sdist + wheel + source tarball. Closes A-3 from INCIDENT_REPORT_v2.0.7.
- `.github/workflows/pr-merge-label.yml` — applies `release` label + posts a comment on merged release PRs via `release_cli.py webhook`. Closes A-4 from INCIDENT_REPORT_v2.0.7.
- 11 new test modules (`test_harness*.py`, `test_staging_monitor.py`, `test_v2_slim_*.py`) — 613 passed in 89.14s on the slim profile.

### Changed

- `ai_agent/agent.py` — `init_agent()` honors runtime `LEGACY_MODE` toggle without restart.
- `ai_agent/app.py` — `/api/models` now respects `LEGACY_MODE` (single config knob).
- `ai_agent/api.py` — `/api/health` returns the runtime flavor (`v2_slim` vs `legacy`) for staging probes.
- `ai_agent/config.py` — adds `LEGACY_MODE` and `V2_SLIM_PACKAGE` env knobs.
- `ai_agent/web_ui.py` — entry point honors `LEGACY_MODE` for the web console launcher.
- `web_console/src/App.tsx` — reads runtime flavor from `/api/health` to surface in the UI footer.
- `ai_agent/pyproject.toml` — version `2.0.8` → `2.0.9`; registers `harness_runner / harness_storage / harness_cli` as `py-modules`.

### Migration

No breaking change. `v2_slim` is additive; existing imports continue to work. New code can opt into slim by leaving `AIAgent_LEGACY=false` (default) and importing from `ai_agent.v2_slim`. To fold legacy memory records:

```bash
python ai_agent/scripts/migrate_memory_v1_to_v2.py --src ai_agent/memory.db
```

To consume:

```bash
git fetch origin && git checkout master && git pull
```

### Known Caveats

- `.github/workflows/*.yml` are committed but not yet auto-active: requires PAT `workflow` scope (still TODO A-7). Until then, releases continue via `release_cli.py`.
- `tests/legacy/` (~280 cases) is skipped by default under the slim profile.
- `frozen("name")()` raises `NotImplementedError` immediately (PEP 318 semantics); this is intentional and tested by `test_v2_slim_fault_tolerance.py`.

---

## [v2.0.8] - 2026-09-04

**类型**: Tooling / Process · **SemVer**: PATCH
**Retro**: [docs/INCIDENT_REPORT_v2.0.7.md](docs/INCIDENT_REPORT_v2.0.7.md)
**SOP**: [docs/VERSION_MANAGEMENT.md](docs/VERSION_MANAGEMENT.md)

### Added

- `scripts/release/release_cli.py` — 跨平台统一发布 CLI(github / gitee / protect / cleanup / webhook / status 六子命令)
- `scripts/release/apply_branch_protection.{sh,ps1}` — 分支保护一键应用脚本
- `docs/VERSION_MANAGEMENT.md` — ~610 行完整发布 SOP,8 大节 + 2 附录
- `docs/INCIDENT_REPORT_v2.0.7.md` — v2.0.7 release 7 个 incident 复盘
- `.github/PULL_REQUEST_TEMPLATE/release.md` — release PR 模板(含 §7.6.4 checklist)
- `.gitattributes` — 强制 `.sh` LF / `.ps1` CRLF,避免 Windows EOL 损坏

### Changed

- `ai_agent/pyproject.toml` — version `0.1.0` → `2.0.8`(与 tag 同步)
- GitHub 远端 `master` 启用分支保护:enforce_admins=true,linear history,no force push,no branch deletion,conversation resolution
- GitHub 远端 `release/v2.0.7-cleanup-verified` 启用保护:enforce_admins=false,owner 直接 hotfix

### Fixed

- I-1:orphan `main` 分支无法删除 → §7.6.2 强制先 PATCH default_branch
- I-2:分支保护 PUT 返回 422 → payload 强制包含 `required_status_checks` 和 `restrictions`(即使为 null)
- I-3:单 owner 仓库 PR 死锁 → §7.5.2 拆分多人 / 单 owner 两套 payload
- I-4:`release_cli.py` 被 cleanup 误删 → 新增跨平台版本(100% stdlib)
- I-5:tag 在 local/remote 漂移 → §7.2 固化"remote wins, never force-push"
- I-6:cleanup backup 分支残留 → §7.6.3 明确 backup 分支保留 2 周后删除

### Known Caveats

- I-7:当前 PAT 缺少 `workflow` scope,`.github/workflows/*.yml` 未推送;release CLI 完全可用,workflows 是可选 accelerator。Permanent fix:重新生成含 `workflow` scope 的 PAT。
- 单 owner 仓库下 `required_approving_review_count=0`(为避免 self-merge 死锁);多人协作出现时切回 1。

### Migration

无 breaking change。打 tag `v2.0.8` 后:

```bash
git fetch origin && git checkout master && git pull
```

无需数据迁移、无需配置变更。

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
- v1.x 桌面版无法热更新到 v2.0(因为 `_internal/` 体积与依赖变化),需卸载后重新下载
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
