# CONVENTIONS.md · 本仓库代码实际约定（从代码读出来的规律）

> **本文件的定位**：只记录**代码里真实存在的做法**，每条尽量附 `file:///` 行号证据。
> 写代码/改代码前先读本文件；发现本文件与代码不一致时，**以代码为准并修正本文件**。
>
> **与另外两份文件的分工**：
> | 文件 | 管什么 | 面向 |
> |---|---|---|
> | 本文件 | 代码**长什么样**（风格、结构、落点、校验命令） | 写代码时 |
> | [`AGENT_RULES.md`](file:///e:/langChain_langGraph/AGENT_RULES.md) | AI **怎么干活**（证据、权限、红线、回滚） | 干活时 |
> | [`CONTRIBUTING.md`](file:///e:/langChain_langGraph/CONTRIBUTING.md) | 人**怎么提 PR**（流程、分支、评审） | 提交时 |
>
> 冲突处理见 [§7](#7-与-contributingmd-的偏差清单待用户裁决)。
> 行为红线（禁止伪造 / 禁止顺手重构等）见 [`AGENT_RULES.md` §7](file:///e:/langChain_langGraph/AGENT_RULES.md#L114-L126)，本文件不重复。

---

## 0. 仓库形态速览

| 项 | 事实 | 证据 |
|---|---|---|
| 后端 | Python **扁平模块**：`ai_agent/` 根下平铺 `.py`（不是包层级） | [pyproject.toml#L142-L146](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L142-L146) 注释明写「ai_agent 是 flat module（所有 .py 在 ai_agent/ 根）」 |
| 前端 | React SPA，独立 npm 包 `ai-agent-console`（`private: true`，`type: module`） | `web_console/package.json` |
| 后端 Python 要求 | `>=3.11` | [pyproject.toml#L5](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L5) |
| 版本声明 | **三处不一致**，见 [§7 D5](#7-与-contributingmd-的偏差清单待用户裁决) | — |

---

## 1. 后端 Python 约定

### 1.1 格式化与 lint：ruff（**没有 black**）

| 项 | 值 | 证据 |
|---|---|---|
| line-length | **120** | [pyproject.toml#L259](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L259) |
| target-version | `py311` | [pyproject.toml#L260](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L260) |
| `lint.select` | `["E","F","W","I","N","UP","B","C4","SIM","RUF"]`（含 `I`=isort 导入排序、`N`=pep8-naming） | [pyproject.toml#L264-L265](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L264-L265) |
| `lint.ignore` | `E501`（超长行）、`B008`（FastAPI `Depends` 模式）、`RUF002`/`RUF003`（中文 docstring 全角字符）、`UP032`（遗留 `format()`） | [pyproject.toml#L266-L272](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L266-L272) |
| `per-file-ignores` | `tests/**/*.py` → `F401,F811,B011`；`cli.py` → `F401`（脚本入口允许） | [pyproject.toml#L274-L278](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L274-L278) |
| format | `quote-style="double"`、`indent-style="space"`、`line-ending="lf"`、`docstring-code-format=true` | [pyproject.toml#L280-L287](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L280-L287) |

**推论（含中文 docstring 的明确要求）**：
- 配置注释原文：「排除业务代码里的大量中文 docstring 全角字符（避免噪音）」+「**注意：新增文件请保留中文 docstring（用半角字符）**」——[pyproject.toml#L261-L262](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L261-L262)。
- 即：**docstring 继续写中文**，只是标点用半角，避免触发 `RUF002`。

### 1.2 mypy：类型注解**不强制**

```toml
python_version = "3.11"
ignore_missing_imports = true
disallow_untyped_defs = false      # ← 未强制全量注解
warn_unused_ignores = true
```
— [pyproject.toml#L289-L293](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L289-L293)

**推论**：新代码仍应写注解（与 `CONTRIBUTING.md` §4.1 一致），但**缺失注解不会导致 CI 失败**。

### 1.3 命名

| 类别 | 约定 | 实例证据 |
|---|---|---|
| 模块 | `snake_case` | `json_log.py`、`multi_agent_integration.py` |
| 类 | `PascalCase` | `AIAgent`、`JsonFormatter`、`ChatRequest` — [json_log.py#L38](file:///e:/langChain_langGraph/ai_agent/json_log.py#L38)、[api.py#L51](file:///e:/langChain_langGraph/ai_agent/api.py#L51) |
| 常量 | `UPPER_SNAKE`；私有常量同样大写 | `MODEL_PROVIDER` — [config.py#L6-L43](file:///e:/langChain_langGraph/ai_agent/config.py#L6-L43)；`_PLACEHOLDER_MARKERS`、`_UPLOAD_ROOT` — [app.py#L52-L62](file:///e:/langChain_langGraph/ai_agent/app.py#L52-L62) |
| 私有函数/变量 | `_` 前缀 | `_is_real_api_key` — [agent.py#L68](file:///e:/langChain_langGraph/ai_agent/agent.py#L68)；`_resolve_monitor` — [api.py#L21](file:///e:/langChain_langGraph/ai_agent/api.py#L21) |
| 分区注释 | `# ===== 分区名 =====` / `# ─── 中文 ───` | [app.py#L49-L51](file:///e:/langChain_langGraph/ai_agent/app.py#L49-L51) |

### 1.4 docstring：中文为主（风格不统一，见 §7 D1）

模块级 docstring 常带「设计原则」「背景」「使用示例」段落 — [agent.py#L1-L13](file:///e:/langChain_langGraph/ai_agent/agent.py#L1-L13)、[json_log.py#L1-L18](file:///e:/langChain_langGraph/ai_agent/json_log.py#L1-L18)、[app.py#L1-L11](file:///e:/langChain_langGraph/ai_agent/app.py#L1-L11)。

> 注：[config.py#L1-L9](file:///e:/langChain_langGraph/ai_agent/config.py#L1-L9) 是例外——纯常量模块，用 `#` 注释块而非 docstring。

### 1.5 `from __future__ import annotations`

- **新代码加**：`app.py` L12、`cli.py` L40、`json_log.py` L19、`conftest.py` L22 等较新模块都有。
- **老顶层模块没有**：`agent.py` L15 直接 `import json`、`api.py` L1 直接 `from fastapi import`、`config.py` L1、`tools.py` L1 同样没有（[agent.py#L15-L21](file:///e:/langChain_langGraph/ai_agent/agent.py#L15-L21)、[api.py#L1-L7](file:///e:/langChain_langGraph/ai_agent/api.py#L1-L7)）。

→ **约定**：新文件加这一行；**不要**为了统一而去给老文件补（属 `AGENT_RULES.md` §7 R3「顺手重构」）。

### 1.6 类型注解风格：新旧两派

| 派别 | 风格 | 代表 |
|---|---|---|
| 老代码 | `typing` 传统泛型 + `Optional`：`Dict` / `List` / `Optional[dict]` | [agent.py#L21](file:///e:/langChain_langGraph/ai_agent/agent.py#L21)、[tools.py#L41-L46](file:///e:/langChain_langGraph/ai_agent/tools.py#L41-L46) |
| 新代码 | PEP 585/604：`list[str]` / `str \| None` | [cli.py#L60](file:///e:/langChain_langGraph/ai_agent/cli.py#L60)、[cli.py#L107](file:///e:/langChain_langGraph/ai_agent/cli.py#L107)、[tests/conftest.py#L52](file:///e:/langChain_langGraph/ai_agent/tests/conftest.py#L52) |

→ **约定**：新代码用现代写法；改老文件时**跟随所在文件的既有风格**，不做全仓统一。

### 1.7 日志：三套机制并存

| 机制 | 用在哪 | 证据 |
|---|---|---|
| `logging.getLogger(__name__)` | **库模块与 Web 层默认** | `logger = logging.getLogger(__name__)` — [agent.py#L100](file:///e:/langChain_langGraph/ai_agent/agent.py#L100)；`logging.basicConfig(...)` 只在 [app.py#L45-L46](file:///e:/langChain_langGraph/ai_agent/app.py#L45-L46) 出现一次 |
| `print()` | **CLI / 脚本入口**（`main.py`、`harness_cli.py`、`start_mcp.py`、`scripts/`） | [main.py#L19](file:///e:/langChain_langGraph/ai_agent/main.py#L19)、[harness_cli.py#L45](file:///e:/langChain_langGraph/ai_agent/harness_cli.py#L45)、[rag.py#L208](file:///e:/langChain_langGraph/ai_agent/rag.py#L208) `print("[WARN] Fallback to OpenAI Embedding")` |
| 自定义 JSON 日志 | 可选结构化路径 | `json_log.py` 提供 `JsonFormatter` / `configure_json_logging()` / `get_logger()` — [json_log.py#L38-L69](file:///e:/langChain_langGraph/ai_agent/json_log.py#L38-L69) |

→ **约定**：库代码用 `logger`；CLI/脚本入口用 `print` 允许。

### 1.8 异常处理：防御性降级是刻意设计

「不让 ReAct loop 抛异常死掉」是明确写进模块 docstring 的设计原则 — [agent.py#L5](file:///e:/langChain_langGraph/ai_agent/agent.py#L5)。

主流写法 `except Exception as e` + 返回可读错误串 — [tools.py#L67-L69](file:///e:/langChain_langGraph/ai_agent/tools.py#L67-L69) `return f"❌ 知识库检索失败: {e}"`；[app.py#L3006-L3007](file:///e:/langChain_langGraph/ai_agent/app.py#L3006-L3007) 降级为 `logger.warning`。

裸 `except:` 属少数（集中在 `context_db.py` / `mcp_tools.py` / `state_manager.py` 等），**新代码不要新增裸 except**。

覆盖率配置显式排除容错分支：`exclude_lines` 含 `except ImportError:` — [pyproject.toml#L312-L332](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L312-L332)。

### 1.9 异步：路由层 async，内部同步

- FastAPI 路由用 `async def`（`app.py` L981 `root()`、L1104 `chat()`、L1115 `chat_stream_sse()`、L1512 `chat_stream_ws()`）；
- 工厂/单例获取保持同步（`app.py` L696 `get_agent()`、L727 `get_proxy()`）；
- `main.py`（CLI REPL）**完全同步 + print**，无 async。

→ **约定**：新端点写 `async def`；新工具/工厂函数写同步 `def`，除非内部需要 await。

### 1.10 导入降级：三种固定模式

| 模式 | 实例 |
|---|---|
| 布尔哨兵 + 降级分支 | `context_manager.py`：`except ImportError: MONITOR_AVAILABLE = False; get_monitor = None` |
| 延迟导入（避免循环依赖） | `@tool` 函数体内 `from rag_service import ...` — [tools.py#L59](file:///e:/langChain_langGraph/ai_agent/tools.py#L59)、[tools.py#L76](file:///e:/langChain_langGraph/ai_agent/tools.py#L76)；`cli.py` L46-L52 延迟导入 `argcomplete` |
| 转成显式业务错误 | `agent.py`：`except ImportError as e: raise RuntimeError("sub-agent 依赖 multi_agent.WorkerAgent...")` |

测试中则转 `pytest.skip` — `tests/test_basic_endpoints.py`：`except ImportError as e: pytest.skip(...)`。

### 1.11 包边界：`__init__.py` 极简

`ai_agent/__init__.py` 仅 9 行：中文说明「模块顶层不应放任何重逻辑（避免循环引用 + 导入成本）」+ `__version__`，**无 import、无 `__all__`**。唯一做重导出的是 `observability/__init__.py`（从 4 个子模块导入并用 `__all__` 列出 16 项）。

→ **约定**：不要往 `__init__.py` 里塞重逻辑或 re-export。

---

## 2. 前端 TS / React 约定

### 2.1 tsconfig

| 项 | 值 | 证据 |
|---|---|---|
| `strict` | **true** | [tsconfig.json#L14](file:///e:/langChain_langGraph/web_console/tsconfig.json#L14) |
| `noUnusedLocals` / `noUnusedParameters` | **false**（明确关闭） | [tsconfig.json#L15-L16](file:///e:/langChain_langGraph/web_console/tsconfig.json#L15-L16) |
| 别名 | `@/*` → `src/*`（**唯一别名**） | [tsconfig.json#L18-L21](file:///e:/langChain_langGraph/web_console/tsconfig.json#L18-L21) |
| 测试文件 | **被 `exclude` 排除出主 tsconfig** | [tsconfig.json#L24](file:///e:/langChain_langGraph/web_console/tsconfig.json#L24) |
| target / module | `ES2020` / `ESNext`，`moduleResolution: bundler` | [tsconfig.json#L3-L8](file:///e:/langChain_langGraph/web_console/tsconfig.json#L3-L8) |

→ 导入用 `@/lib/xxx`、`@/types/api`，**不用相对路径 `../../`**。

### 2.2 导出与命名

- **具名导出为主**：`export function cn(...)`、`export function formatTime(...)` — [utils.ts#L3-L11](file:///e:/langChain_langGraph/web_console/src/lib/utils.ts#L3-L11)；`export function TokenUsageWidget()`。
- 类型用 `import type { ... }` 单独导入 — `src/lib/api.ts` L1-L9。
- 组件 Props 用 `XxxProps` interface：`ResumeDrawerProps`、`ApprovalCardProps`、`AgentExecutionGraphProps`。
- 函数式组件 + Hooks（`CONTRIBUTING.md` §4.2 亦如此要求）。
- 部分组件同时具名导出与 `export default`（`ResumeDrawer.tsx`）——**跟随所在文件的既有写法**。

### 2.3 样式：Tailwind + `cn()`，无组件库依赖

- `cn()` 定义在 `src/lib/utils.ts`：`export function cn(...inputs: ClassValue[]) { return clsx(inputs); }` — [utils.ts#L1-L5](file:///e:/langChain_langGraph/web_console/src/lib/utils.ts#L1-L5)。
- 颜色 token 全部由 CSS 变量驱动，`tailwind.config.js` 的 `colors` 做桥接（`bg0/bg1/bg2`、`fg0/fg1/fg2`、`accent1/accent2`、`danger/success/warn` → `var(--bg-0)` 等），变量定义在 `src/styles/globals.css` L4-L40。
- `package.json` 依赖中**没有** `@radix-ui` / `cva`，即**未真正引入 shadcn/ui 组件库**（`globals.css` 只保留兼容 token 注释）。

→ **约定**：UI 手写 Tailwind class，不引入新的组件库依赖（除非先说明理由）。

### 2.4 状态管理：Zustand

| 约定 | 内容 | 证据 |
|---|---|---|
| 创建 | `export const useXxxStore = create<XxxState>(...)` | `src/stores/agentStore.ts` L36；`uiStore.ts` L6-L22 |
| 命名 | `useXxxStore`（全 5 个 store 一致） | `src/stores/` |
| 结构 | state + actions 合并在同一个 `interface` 内，不拆 slice | `agentStore.ts` L14-L34 |
| 持久化 | `persist` + `createJSONStorage(() => localStorage)`，带 `name` / `version` / `partialize` / `migrate` | `uiStore.ts` L22-L52；`chatStore.ts`；`workflowStore.ts`；`credentialsStore.ts` |
| 例外 | `agentStore` **不用** persist | `agentStore.ts` L10 |
| 测试 | 提供 `resetForTests()` action | `agentStore.ts` L33/L36 |

### 2.5 流式（SSE）分层

| 层 | 文件 | 导出 |
|---|---|---|
| 无状态解析 | `src/lib/sseParser.ts` | `parseSseStream`、`isTerminalSseEvent`、`friendlyError`、类型 `SseEvent` |
| 控制器 + 重试 + 指标 | `src/lib/runAgentStream.ts` | `runAgentStream(...)`、`AgentStreamController`、`StreamMetrics`、测试钩子 `_resetActiveStreamIdForTests` |
| 续生成 | `src/lib/agentStreamResume.ts` | — |
| 重试策略 | `src/lib/agentStreamRetry.ts` | `decideRetry` / `sleep` / `DEFAULT_RETRY_OPTIONS` |

`sseParser.ts` 的 docstring 明确「此函数是无状态的」——**解析逻辑放这里，不要塞进组件**。

---

## 3. 测试约定（后端）

### 3.1 pytest 配置

| 项 | 值 | 证据 |
|---|---|---|
| `testpaths` | `["tests"]` | [pyproject.toml#L134](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L134) |
| 收集规则 | `test_*.py` / `Test*` / `test_*` | [pyproject.toml#L135-L137](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L135-L137) |
| `addopts` | `-ra`、`--strict-markers`、`--tb=short`、`--cov=.`、`--cov-branch`、`--cov-fail-under=35`、`-m "not slow and not integration"` | [pyproject.toml#L137-L176](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L137-L176) |
| `markers` | `integration` / `network` / `slow`（**无 `legacy`**，P2-7 已移除） | [pyproject.toml#L177-L181](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L177-L181) |
| `asyncio_mode` | `"auto"` | [pyproject.toml#L182](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L182) |

⚠️ **注意 `--cov=.`**：因为是扁平布局，写 `--cov=ai_agent` 会找不到任何代码（[pyproject.toml#L142-L146](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L142-L146) 注释原文）。

### 3.2 覆盖率门禁：35%（不是 80%）

`--cov-fail-under=35` 写死在 `addopts`，CI 未显式传参，靠 `addopts` 生效。配置注释记录了阈值演进策略：当前 35% 留 2-3% 余量 → 每 2-3 个月 +5% → 目标 80%（需 1-2 年）—— [pyproject.toml#L164-L170](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L164-L170)。与 `CONTRIBUTING.md` §6 的「≥80%」有偏差，见 [§7 D2](#7-与-contributingmd-的偏差清单待用户裁决)。

### 3.3 测试文件命名：4 类前缀并存

| 类别 | 实例 |
|---|---|
| 按被测模块（主流） | `test_agent.py`、`test_rag.py`、`test_security.py`、`test_skills.py`、`test_harness.py`、`test_multi_agent.py` |
| 按版本/里程碑 | `test_v2_slim_{consistency,tools,run_pipeline,stream_events,migration,fault_tolerance}.py` |
| 按里程碑任务编号 | `test_p0_3_4_tools_and_rag.py`、`test_p1_2_5_hitl_resume_and_retry.py` |
| 按端点/协议 | `test_app_{e2e,sse,sse_abort,sse_isolation,ws,spa_fallback}.py` |

→ **约定**：新增测试默认按**被测模块**命名（`test_<模块名>.py`）；只有成组的版本回归测试才用 `test_v2_slim_*` 前缀。

### 3.4 共享 fixture（`ai_agent/tests/conftest.py`）

| fixture | 作用 | 行号 |
|---|---|---|
| `temp_dir` | `TemporaryDirectory` + `yield` | L51-L61 |
| `isolated_env` | 注入 5 个 fake API key + `OPENAI_API_BASE` | L64-L85 |
| `sample_messages` | 3 条 OpenAI 格式消息 | L88-L98 |
| `sample_upload_file` | 写 `test.txt` 到 `tmp_path` | L101-L109 |
| `_reset_agent_state_between_tests`（**autouse**） | 每测试**前后**重置 `app._agent_instance` / `app._proxy_instance` / `HITLStore.reset_instance()` | L115-L167 |
| 根级 `conftest.py` | `ai_agent_root()`（session 作用域）、`disable_llm_network(monkeypatch)` 设 `AI_AGENT_DISABLE_LLM=1` | [conftest.py#L38-L49](file:///e:/langChain_langGraph/ai_agent/conftest.py#L38-L49) |

**marker 双注册机制**（两处并存，勿删其一）：
1. `pytest_collection_modifyitems` 按 nodeid 自动打 `integration` / `network` 标记 — L170-L189；
2. `pytest_configure` 用 `addinivalue_line` 再注册一遍（消除 `PytestUnknownMarkWarning`）— L192-L201。

因 `--strict-markers` 已开，**未注册的 marker 会直接报错**。

### 3.5 异步测试

`asyncio_mode="auto"` 已开，但代码里仍大量显式写 `@pytest.mark.asyncio`（如 `test_agent_presets.py`、`test_agent_tools.py`）。→ **跟随所在文件的既有写法**，不强求统一。

---

## 4. 测试约定（前端）

| 项 | 事实 | 证据 |
|---|---|---|
| 框架 | Vitest + jsdom；`globals: false`（**必须显式 `import { describe, it }`**） | [vitest.config.ts#L19-L22](file:///e:/langChain_langGraph/web_console/vitest.config.ts#L19-L22) |
| 单测位置 | 与源码同目录 `*.test.ts(x)` / `*.spec.ts(x)` | [vitest.config.ts#L24-L26](file:///e:/langChain_langGraph/web_console/vitest.config.ts#L24-L26) |
| **实际生效的 setup** | `src/test-setup.ts` | [vitest.config.ts#L23](file:///e:/langChain_langGraph/web_console/vitest.config.ts#L23) |
| ⚠️ 另一个 setup | `src/test/setup.ts` **并存但未被引用**（含 localStorage 清理 + matchMedia mock） | 文件存在；`vitest.config.ts` 未引用 |
| E2E | Playwright，`testDir: ./e2e`，`testIgnore: ['**/visual.spec.ts']`，chromium only，`workers: 1` | [playwright.config.ts#L16-L52](file:///e:/langChain_langGraph/web_console/playwright.config.ts#L16-L52) |
| 覆盖率阈值 | 按目录分组：`src/lib/**` 60/30/60/45、`src/stores/**` 40/35/40/20、`src/types/**` 100/100/100/100；`src/components/**` 与 `src/hooks/**` 为 0 | [vitest.config.ts#L86-L124](file:///e:/langChain_langGraph/web_console/vitest.config.ts#L86-L124) |

→ **约定**：新增工具函数放 `src/lib/` 并写测试（该目录有 60% 行覆盖门槛）；纯展示组件放 `src/components/` 无需强测。

---

## 5. 校验命令（**实际会被检查的**）

### 5.1 后端 CI（[.github/workflows/ci.yml](../.github/workflows/ci.yml)）

```bash
pip install -e ".[dev]"
python -m pytest --no-header --tb=short -q \
  --cov-report=term-missing --cov-report=xml:coverage.xml \
  --cov-report=json:coverage.json --junitxml=test-results.xml
```
— [ci.yml#L60-L75](file:///e:/langChain_langGraph/.github/workflows/ci.yml#L60-L75)

⚠️ **CI 不跑 `ruff check` / `ruff format --check` / `mypy`**（实测 5 个 job：`backend-tests`、`frontend-tests`、`frontend-e2e`、`docker-build`、`actionlint`，均无 lint 步骤）。→ 风格靠本地 `ai-agent-lint` + review 保证，**不要以为 CI 会拦风格问题**。

### 5.2 前端 CI（[web_console/.github/workflows/ci.yml](../web_console/.github/workflows/ci.yml)）

去重后实际执行的命令：`npm ci --no-audit --no-fund`、`npm run lint:workflows`（actionlint）、`npm run check`（`tsc --noEmit`）、`npx tsc -p tsconfig.e2e.json`、`npm test`（vitest）、`npm run test:coverage`、`npm run e2e`（playwright）、`npm run build`（`tsc -b && vite build`）。

⚠️ **没有 ESLint / Prettier 步骤**（`package.json` 里也没有独立 `lint` 脚本，只有 `lint:workflows`）。

### 5.3 本地开发入口（`CONTRIBUTING.md` §3.3 口径）

```bash
cd ai_agent && ai-agent-lint && ai-agent-format && ai-agent-test
cd web_console && npm run check && npm test && npm run lint:workflows
```

`ai-agent-test` / `ai-agent-lint` / `ai-agent-format` 是 `pyproject.toml [project.scripts]` 指向 `cli.py` 的 console_script。

---

## 6. 新增功能落点速查

| 要做什么 | 动哪些文件 | 证据 |
|---|---|---|
| 加 LLM Provider | `ai_agent/config.py` 的 `MODEL_VERSIONS` → 复用 `OpenAICompatibleClient` → 加 `ai_agent/tests/test_models_registry.py` → 更新 README §4.2 | [CONTRIBUTING.md#L169-L177](file:///e:/langChain_langGraph/CONTRIBUTING.md#L169-L177) |
| 加后端工具 | `ai_agent/tools.py` 用 `@tool` 装饰器 + docstring → 在 `get_all_tools()` 注册 → 加 `ai_agent/tests/test_agent_tools.py`（**注意不是 `test_tools.py`**，见 §7 D3） | [CONTRIBUTING.md#L181-L204](file:///e:/langChain_langGraph/CONTRIBUTING.md#L181-L204) |
| 加 API 端点 | `ai_agent/app.py`（主应用）或 `ai_agent/api.py` → 加 `ai_agent/tests/test_app_*.py` | [CONTRIBUTING.md#L158](file:///e:/langChain_langGraph/CONTRIBUTING.md#L158) |
| 加 Skill | `Skill(name=, description=, category=, prompt_template=, tools=)` → `registry.register()` → 加 `ai_agent/tests/test_skills.py` | [CONTRIBUTING.md#L208-L222](file:///e:/langChain_langGraph/CONTRIBUTING.md#L208-L222) |
| 加前端组件 | `web_console/src/components/<分组>/` → 同目录写 `*.test.tsx` | [vitest.config.ts#L24-L26](file:///e:/langChain_langGraph/web_console/vitest.config.ts#L24-L26) |
| 加前端状态 | `web_console/src/stores/useXxxStore.ts`，需要持久化则加 `persist` | `web_console/src/stores/uiStore.ts` L22-L52 |

---

## 7. 与 CONTRIBUTING.md 的偏差清单（待用户裁决）

> 以下 5 条是**实测发现的文档与代码不一致**。本文件按**代码实际**写；`CONTRIBUTING.md` 本轮**未改动**，等用户裁决后再同步。

| # | CONTRIBUTING.md 写的 | 代码实际 | 证据 |
|---|---|---|---|
| **D1** | docstring 用 Google 风格 `Args:`/`Returns:`（L68） | `tools.py` 用中文「参数:」「返回:」；`cli.py` 用 Google 风格 `Args:` —— **两种风格并存** | [CONTRIBUTING.md#L68](file:///e:/langChain_langGraph/CONTRIBUTING.md#L68) vs [tools.py#L47-L58](file:///e:/langChain_langGraph/ai_agent/tools.py#L47-L58) vs [cli.py#L92-L94](file:///e:/langChain_langGraph/ai_agent/cli.py#L92-L94) |
| **D2** | 覆盖率目标 ≥ 80%（§6） | `addopts` 写死 `--cov-fail-under=35`，注释说明 80% 需 1-2 年 | [CONTRIBUTING.md#L154-L165](file:///e:/langChain_langGraph/CONTRIBUTING.md#L154-L165) vs [pyproject.toml#L164-L170](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L164-L170) |
| **D3** | 「记得在 `tests/test_tools.py` 加用例」（§8） | 该文件**不存在**，实际为 `tests/test_agent_tools.py` | [CONTRIBUTING.md#L181-L204](file:///e:/langChain_langGraph/CONTRIBUTING.md#L181-L204) vs `ai_agent/tests/` 目录清单 |
| **D4** | 「所有新函数必须有参数与返回类型」（L67） | `mypy.disallow_untyped_defs = false`；且现存无注解函数如 `tools.set_rag_instance(rag)` | [CONTRIBUTING.md#L67](file:///e:/langChain_langGraph/CONTRIBUTING.md#L67) vs [pyproject.toml#L292](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L292) vs [tools.py#L16](file:///e:/langChain_langGraph/ai_agent/tools.py#L16) |
| **D5** | —— | 版本号三处不一致：`pyproject.toml` = `2.0.9`、`ai_agent/README.md` = `v2.5.0`、`__init__.py` = `2.0.0-slim` | [pyproject.toml#L3](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L3)、[ai_agent/README.md#L3](file:///e:/langChain_langGraph/ai_agent/README.md#L3)、[__init__.py#L1-L9](file:///e:/langChain_langGraph/ai_agent/__init__.py#L1-L9) |

### 附带发现（同样只记录，不擅自修）

| # | 发现 | 证据 |
|---|---|---|
| N1 | `pyproject.toml` L128-L131 注释声明「pytest-timeout 默认 60 秒超时」，但 `[tool.pytest.ini_options]` 中**无 `timeout` 配置项**；且 `pytest-timeout` 只在 `requirements-dev.txt`，不在 `pyproject.toml` 的 `dev` extra | 实读 [pyproject.toml#L128-L188](file:///e:/langChain_langGraph/ai_agent/pyproject.toml#L128-L188) |
| N2 | `ai_agent/.github/workflows/harness.yml` 位于**子目录**；GitHub Actions 只识别仓库根 `.github/workflows/` —— 该 workflow 是否生效**未找到证据**，需外部确认 | 文件存在于 `ai_agent/.github/workflows/` |
| N3 | `web_console/src/test/setup.ts` 与 `web_console/src/test-setup.ts` 并存，前者未被 `vitest.config.ts` 引用 | [vitest.config.ts#L23](file:///e:/langChain_langGraph/web_console/vitest.config.ts#L23) |

---

## 8. 证据指针

- 本文件引用的全部源文件（按章节）：
  - 后端：[`ai_agent/pyproject.toml`](file:///e:/langChain_langGraph/ai_agent/pyproject.toml)、[`agent.py`](file:///e:/langChain_langGraph/ai_agent/agent.py)、[`app.py`](file:///e:/langChain_langGraph/ai_agent/app.py)、[`api.py`](file:///e:/langChain_langGraph/ai_agent/api.py)、[`tools.py`](file:///e:/langChain_langGraph/ai_agent/tools.py)、[`config.py`](file:///e:/langChain_langGraph/ai_agent/config.py)、[`json_log.py`](file:///e:/langChain_langGraph/ai_agent/json_log.py)、[`cli.py`](file:///e:/langChain_langGraph/ai_agent/cli.py)、[`conftest.py`](file:///e:/langChain_langGraph/ai_agent/conftest.py)、[`tests/conftest.py`](file:///e:/langChain_langGraph/ai_agent/tests/conftest.py)、[`README.md`](file:///e:/langChain_langGraph/ai_agent/README.md)
  - 前端：[`tsconfig.json`](file:///e:/langChain_langGraph/web_console/tsconfig.json)、[`vitest.config.ts`](file:///e:/langChain_langGraph/web_console/vitest.config.ts)、[`playwright.config.ts`](file:///e:/langChain_langGraph/web_console/playwright.config.ts)、[`tailwind.config.js`](file:///e:/langChain_langGraph/web_console/tailwind.config.js)、[`src/lib/utils.ts`](file:///e:/langChain_langGraph/web_console/src/lib/utils.ts)、[`src/stores/`](file:///e:/langChain_langGraph/web_console/src/stores)、[`src/styles/globals.css`](file:///e:/langChain_langGraph/web_console/src/styles/globals.css)
  - CI：[`.github/workflows/ci.yml`](file:///e:/langChain_langGraph/.github/workflows/ci.yml)、[`web_console/.github/workflows/ci.yml`](file:///e:/langChain_langGraph/web_console/.github/workflows/ci.yml)
  - 规范：[`AGENT_RULES.md`](file:///e:/langChain_langGraph/AGENT_RULES.md)、[`CONTRIBUTING.md`](file:///e:/langChain_langGraph/CONTRIBUTING.md)、[`AGENTS.md`](file:///e:/langChain_langGraph/AGENTS.md)
- 本文件的 SHA256 基线留档在 [`output/MEMORY.md`](file:///e:/langChain_langGraph/output/MEMORY.md)（不写在本文件正文，避免每次编辑即失效）。
- 最后核对日期：2026-10-20。