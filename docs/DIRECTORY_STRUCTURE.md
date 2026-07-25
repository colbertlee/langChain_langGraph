# 目录结构 · Repository Layout

> 仓库的全量目录结构与每个目录 / 关键文件的用途说明。
>
> **本文件是项目的"地图",**配合 [README.md §附录 Documentation Map](../README.md) 使用。
>
> **过滤说明**:为简洁起见,本文档**省略**了以下自动生成 / 第三方目录:
> - `_internal/`(PyInstaller 解压的 Python 运行时,Windows / Linux 包内)
> - `htmlcov/`(pytest-cov HTML 报告)
> - `playwright-report/`、`test-results/`(Playwright 测试产物)
> - `*.pytest_cache/`、`*.egg-info/`、`build/`、`dist/`
> - `__pycache__/`、`*.db-shm`、`*.db-wal`
> - `node_modules/`、`.vite/`、所有 `*.dist-info/`

---

## 0. 总览

```
langChain_langGraph/
├── 顶层文件 (根目录)
├── .github/          顶层 GitHub 配置
├── .trae/            产品与技术文档(被引用)
├── ai_agent/         后端 Python 包(后端 + 桌面包源)
├── docs/             跨子项目共享文档
├── scripts/          顶层小工具
└── web_console/      React 前端控制台
```

---

## 1. 顶层文件

| 文件 | 用途 |
|---|---|
| [README.md](../README.md) | 项目首页 · 架构 / 快速开始 / 部署 / FAQ |
| [QUICKSTART.md](../QUICKSTART.md) | 5 分钟起步 |
| [DISTRIBUTION.md](../DISTRIBUTION.md) | 7 种分发渠道 + 卸载 |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | 贡献指南 |
| [CHANGELOG.md](../CHANGELOG.md) | 版本变更 + 迁移指南 |
| [docker-compose.yml](../docker-compose.yml) | Docker 一键编排 |
| [.dockerignore](../.dockerignore) | Docker 构建排除 |
| [.gitignore](../.gitignore) | Git 排除 |
| [smoke.ps1](../smoke.ps1) | 顶层冒烟脚本 |

---

## 2. `.github/`(顶层 GitHub 配置)

| 路径 | 用途 |
|---|---|
| `ISSUE_TEMPLATE/` | bug_report / feature_request / question / config 四类 issue 模板(YAML) |
| `CODEOWNERS` | 自动指派 reviewer |
| `PULL_REQUEST_TEMPLATE.md` | PR 模板 |
| `SECURITY.md` | 安全策略与漏洞报告渠道 |

---

## 3. `.trae/documents/`

| 文件 | 用途 |
|---|---|
| `PRD.md` | 产品需求文档 |
| `TECHNICAL_ARCHITECTURE.md` | 技术架构详细文档 |

> 这两个文档不在 `docs/` 内是因为属于 AI IDE 工作区产物,被 README 通过相对链接引用。

---

## 4. `ai_agent/`(后端)

### 4.1 目录树
```
ai_agent/
├── .github/workflows/
├── docs/                  # 架构 / 设计 / 阶段交付
├── knowledge_base/        # 内置 RAG 文档
├── package/               # 桌面包产物(Win / Linux / macOS)
├── prompts/               # User Prompt 模板
├── scripts/               # 脚本(legacy_tests / dry-run)
├── tests/                 # pytest 全量测试
├── web/                   # 单文件 HTML 主界面
├── *.py                   # ~50 个 Python 模块
├── *.ps1 / *.sh           # 打包 / 测试 / 运行脚本
├── *.md                   # 文档
├── *.json / *.rb          # 包分发 manifest / formula
├── *.spec                 # PyInstaller spec
├── pyproject.toml         # PyPI 元数据 + pytest + ruff
├── requirements*.txt      # 依赖锁定
└── .env.example           # 环境变量模板
```

### 4.2 Python 模块清单(`ai_agent/*.py`)

#### 4.2.1 入口与配置
| 文件 | 职责 |
|---|---|
| `agent.py` | AIAgent 核心(多 Provider / Sub-Agent / 主备 / 容错注入) |
| `app.py` | **统一 FastAPI 入口**(40+ 端点,SSE / WS / Upload / Context / Observability / Approval) |
| `api.py` | 旧版 API(向后兼容) |
| `web_ui.py` | 旧版 Web UI(向后兼容) |
| `main.py` | CLI 入口(双击 exe 进 REPL) |
| `cli.py` | console_scripts:`ai-agent` / `ai-agent-server` / `ai-agent-test` / `ai-agent-lint` / `ai-agent-format` |
| `config.py` | 11 家 Provider × 70+ 模型配置 + base_url |
| `models_registry.py` | 模型注册表(供前端 `/api/models` 调用) |

#### 4.2.2 工具
| 文件 | 职责 |
|---|---|
| `tools.py` | 18+ LangChain 工具(含 7 个 ETF) |
| `mcp_server.py` | MCP 协议服务端 |
| `mcp_tools.py` | 14 个 MCP 工具(文件 / 网络 / 开发 / 系统 / 数据) |
| `sqlite_tools.py` | SQLite 数据库工具 |
| `github_tools.py` | GitHub MCP 工具 |
| `gitee_tools.py` | Gitee MCP 工具 |
| `sandbox.py` | 沙箱执行环境 |
| `plugin_manager.py` | 插件管理器 |

#### 4.2.3 核心引擎
| 文件 | 职责 |
|---|---|
| `llm_reliability.py` | **五层容错栈** + 主备模型 + Standby 预热 |
| `context_manager.py` | 实体提取 + 上下文构建 + 自动摘要 + token 预算分配 |
| `memory_store.py` | **四类记忆**(WORKING/EPISODIC/SEMANTIC/PROCEDURAL)+ 整合 + 衰减 |
| `memory.py` | 旧版记忆(兼容) |
| `multi_agent.py` | **多 Agent 编排 5 模式**(SUPERVISOR/PARALLEL/SEQUENTIAL/HIERARCHICAL/FANOUT) |
| `multi_agent_examples.py` | 多 Agent 示例 |
| `multi_agent_integration.py` | 多 Agent 集成胶水代码 |
| `negotiation.py` | 协商 + 拍卖(第一价格 / 第二价格 / 英式 / 荷兰式) |
| `planner.py` | 任务规划器 |
| `task_intent.py` | 任务意图识别 |
| `task_scheduler.py` | 任务调度器 |
| `state_manager.py` | 状态管理 |

#### 4.2.4 可观测与可靠性
| 文件 | 职责 |
|---|---|
| `observability.py` | 事件流 + Trace + 缓存 |
| `monitor.py` | Prometheus 指标 |
| `ab_testing.py` | A/B 测试框架 |
| `adaptive_threshold.py` | 自适应阈值 |
| `reliability.py` | RetryPolicy + CircuitBreaker + DeadLetterQueue |
| `rate_limit.py` | 进程内令牌桶 |
| `json_log.py` | 结构化 JSON 日志 |

#### 4.2.5 Prompt 工程
| 文件 | 职责 |
|---|---|
| `prompt_registry.py` | System/Role/Tool 三段注册 + 版本化 + 回滚 |
| `user_prompt_registry.py` | User Prompt 模板 + few-shot + 安全改写 |
| `prompts/user_prompts.json` | 用户 Prompt 数据 |

#### 4.2.6 协作与权限
| 文件 | 职责 |
|---|---|
| `message_protocol.py` | Message / TaskMessage / MessageType / Priority |
| `message_bus.py` | 本地消息总线 + BaseAgent |
| `distributed_bus.py` | 分布式消息总线(Redis) |
| `pub_sub_scenarios.py` | 发布订阅场景 |
| `capability.py` | Worker 能力注册 + 负载均衡 |
| `permission.py` | Agent × Tool × Worker 三维 RBAC |
| `human_in_loop.py` | HITL HookPoint(PASS/ASK/BLOCK) |

#### 4.2.7 记忆 / 上下文 / RAG
| 文件 | 职责 |
|---|---|
| `context_db.py` | 结构化上下文持久化(SQLite) |
| `rag.py` | Chroma + 多 Embedding(OpenAI / 智谱 / MiniMax / Jina) |
| `knowledge_base/python_intro.txt` | 内置 RAG 文档 |

#### 4.2.8 多模态与音频
| 文件 | 职责 |
|---|---|
| `multimodal.py` | 多模态支持 |
| `audio_pipeline.py` | 音频处理管线 |
| `audio_semantic.py` | 音频语义 |
| `audio_streaming.py` | 音频流式 |
| `audio_feedback.py` | 音频反馈 |

#### 4.2.9 安全与质量
| 文件 | 职责 |
|---|---|
| `security.py` | 输入过滤 + 输出脱敏 + Prompt Injection 检测 + AST 白名单 |
| `hallucination.py` | 幻觉检测 |
| `skills.py` | Skill 框架(深度研究 / 代码文档 / PPT / 论文 / 图表) |

#### 4.2.10 启动与运行
| 文件 | 职责 |
|---|---|
| `start_mcp.py` | MCP 服务启动入口 |
| `run_all_tests.py` | 跑所有测试的入口 |

#### 4.2.11 脚本与打包
| 文件 | 职责 |
|---|---|
| `ai_agent.spec` | PyInstaller 跨平台 spec |
| `build_windows.ps1` | Windows 桌面打包 |
| `build_linux.sh` | Linux 桌面打包 |
| `build_all.ps1` | 三平台打包 |
| `package_dist.ps1` | 把 PyInstaller 产物移到 `package/windows/` 并打 zip |
| `test_all.ps1` | Windows 端到端验证 |
| `test_package.ps1` | Windows 桌面包冒烟 |
| `test_package.sh` | Linux 桌面包冒烟 |
| `dry-run-release.py` | 发布预演(不真发) |

#### 4.2.12 文档
| 文件 | 用途 |
|---|---|
| `README.md` | 后端详细文档 |
| `FEATURES_GUIDE.md` | 任务导向 + 功能罗列 |
| `CHANGELOG.md` | 后端版本变更 |
| `RELEASE_NOTES.md` | 发布说明 |
| `RELEASE_SUMMARY.md` | 发布摘要 |
| `INSPECTION_REPORT.md` | 自检报告 |

#### 4.2.13 分发 Manifest
| 文件 | 用途 |
|---|---|
| `pyproject.toml` | PyPI 元数据 + pytest + ruff + semantic-release |
| `requirements.txt` | 运行依赖 |
| `requirements-dev.txt` | 开发依赖 |
| `scoop-bucket-ai-agent.json` | Scoop manifest |
| `homebrew-tap-ai-agent.rb` | Homebrew formula |
| `.env.example` | 环境变量模板(11 家 Provider 全部示例) |
| `mcp_config.json` | MCP 服务端配置 |

### 4.3 子目录

#### `ai_agent/docs/`(架构 / 设计 / 阶段交付)
| 文件 | 用途 |
|---|---|
| `AGENT_ARCHITECTURE_ROADMAP.md` | Agent 架构路线图 |
| `SPEC_CONTEXT_PERSISTENCE.md` | 上下文持久化设计 |
| `STAGE_A_DELIVERY.md` | 阶段 A 交付记录 |
| `screenshot_*.png` | 主界面截图 |
| `take_*.ps1` | 截图生成脚本 |

#### `ai_agent/tests/`(pytest 全量)
| 路径 | 内容 |
|---|---|
| `conftest.py` | pytest fixtures |
| `__init__.py` | 包标识 |
| `test_*.py` | 27 个新用例文件(agent / app / tools / memory / streaming / security / skills / rag / permission / prompts / models 等) |
| `legacy/` | 旧版用例(已弃用,但保留) |

#### `ai_agent/web/`(单文件 HTML 主界面)
| 文件 | 用途 |
|---|---|
| `index.html` | **主入口**(5 个 tab:设置 / 工具 / 记忆 / 计划 / 运维) |
| `dashboard.html` | 仪表板 |
| `home.html` | 测试中心(10 个面板) |
| `test_dashboard.html` | 测试报告(只读) |
| `test_lab.html` | 单功能实验台 |
| `preview_*.html` | 预览快照 |

#### `ai_agent/scripts/`
| 文件 | 用途 |
|---|---|
| `legacy_tests/test_*.py` | 旧版测试脚本(已弃用) |
| `dry-run-release.py` | 发布预演 |

#### `ai_agent/prompts/`
| 文件 | 用途 |
|---|---|
| `user_prompts.json` | User Prompt 模板 |

#### `ai_agent/knowledge_base/`
| 文件 | 用途 |
|---|---|
| `python_intro.txt` | 内置 RAG 文档(供"加载知识库"工具使用) |

#### `ai_agent/.github/workflows/`
| 文件 | 用途 |
|---|---|
| `release-build.yml` | 桌面三平台(Win/Linux/macOS)打包 CI |

#### `ai_agent/package/`(桌面包产物)

| 子目录 | 用途 | 用户脚本 |
|---|---|---|
| `package/windows/` | Windows 桌面包(包含 `ai-agent.exe` + `_internal/`) | `install.bat` → `run.bat` / `run-web.bat` |
| `package/linux/` | Linux 桌面包(包含 `ai-agent` + `_internal/`) | `install.sh` → `run.sh` / `run-web.sh` |
| `package/macos/` | macOS 用户文档(`README.txt`) | 见 README.txt |

**用户级 README**:
- `package/README.md`(总览)
- `package/windows/README.txt`
- `package/linux/README.txt`
- `package/linux/BUILD_ON_LINUX.md`(如何在 Linux 重新构建)
- `package/macos/README.txt`

每个平台包内部还含:
- `.env.example`(环境变量模板)
- `mcp_config.json`(MCP 服务端配置)
- `smoke_install.*` / `smoke_run.*`(开发者冒烟脚本)
- `_internal/`(PyInstaller 解压出的 Python 运行时 + 所有依赖,**已从本文档过滤**)

---

## 5. `docs/`(跨子项目共享文档)

| 文件 | 用途 |
|---|---|
| `API.md` | API 参考(40+ 端点完整 curl + JSON 示例) |

---

## 6. `scripts/`(顶层小工具)

| 文件 | 用途 |
|---|---|
| `add-slow-markers.py` | 给慢测试打 `@pytest.mark.slow` 标记 |
| `validate-compose.py` | docker-compose.yml 校验 |

---

## 7. `web_console/`(React 前端控制台)

### 7.1 目录树
```
web_console/
├── .github/
│   ├── homebrew-tap/
│   ├── scoop/
│   ├── workflows/                # 8 个 CI workflow
│   └── *.md                      # 发版 / 分支 / 容器 / Pages / PyPI / Tap 文档
├── e2e/                          # Playwright 测试
├── scripts/                      # 升级检查 / 创建 tap / 视觉基线
├── src/
│   ├── components/               # 组件
│   ├── hooks/                    # 自定义 Hooks
│   ├── lib/                      # api / utils / 适配器
│   ├── pages/                    # 8 个路由页面
│   ├── stores/                   # Zustand stores
│   ├── styles/                   # 全局样式
│   ├── test/                     # 测试配置
│   ├── types/                    # API 类型契约
│   └── App.tsx / main.tsx
├── Dockerfile                    # 多阶段:Node 20 构建 → python:3.11 运行
├── package.json / package-lock.json
├── tsconfig*.json
├── vite.config.{ts,d.ts,js} / vitest.config.ts
├── tailwind.config.js / postcss.config.js
├── playwright.config.ts
├── index.html
└── CHANGELOG.md / QUICKSTART.md / README.md
```

### 7.2 路由页面
| Path | 文件 | 作用 |
|---|---|---|
| `/` | `pages/Chat.tsx` | 流式对话 + 附件 + 工具调用可视化 |
| `/agents` | `pages/Agents.tsx` | 多 Agent 列表 / 启动 / 编排模式 |
| `/approval` | `pages/Approval.tsx` | HITL 审批中心 |
| `/observability` | `pages/Observability.tsx` | 事件流 + Trace + 指标 |
| `/tools` | `pages/Tools.tsx` | MCP 工具注册表 |
| `/settings` | `pages/Settings.tsx` | LLM / 模型 / Embedding / 容错配置 |
| `/prompts` | `pages/Prompts.tsx` | Prompt 模板管理 |
| `/memory` | `pages/Memory.tsx` | 记忆查看 |

### 7.3 Stores
| Store | 用途 |
|---|---|
| `chatStore` | 会话列表 + 流式订阅 + 附件元数据 |
| `uiStore` | 主题 + 侧栏折叠 + 后端健康灯 + Toast |

### 7.4 文档
| 文件 | 用途 |
|---|---|
| `README.md` | 前端详细文档(技术栈 / 快速开始 / 路由 / 开发) |
| `QUICKSTART.md` | 前端 5 分钟 |
| `CHANGELOG.md` | 前端版本变更 |

### 7.5 `.github/workflows/`
| 文件 | 触发 | 作用 |
|---|---|---|
| `ci.yml` | push/PR | 前端 type-check + vitest + e2e + visual + build |
| `backend-ci.yml` | push/PR | 后端 pytest + 3 层安全扫描 |
| `release.yml` | push tag | PyPI(OIDC) + GHCR + GitHub Release |
| `release-build.yml` | push tag | PyInstaller 三平台打包 |
| `docker-ci.yml` | Dockerfile 变更 | Docker 镜像 CI |
| `release-please.yml` | push | 自动开 Release PR |
| `release-drafter.yml` | push | 自动维护 Draft Release |
| `weekly-upgrades.yml` | 每周 | 依赖升级检查 + 通知 |

### 7.6 `.github/` 文档
| 文件 | 用途 |
|---|---|
| `RELEASE.md` | 发版总览 |
| `RELEASE_PIPELINE.md` | 完整发布流水线 |
| `FIRST_RELEASE_RUNBOOK.md` | 首次发版 runbook |
| `BRANCH_PROTECTION_SETUP.md` | 分支保护设置 |
| `GITHUB_PAGES_SETUP.md` | GitHub Pages / S3 部署 |
| `PYPI_PUBLISHING.md` | PyPI 发版 |
| `GHCR_SETUP.md` | GitHub Container Registry |
| `SCOOP_BREW_TAP_SETUP.md` | Scoop / Homebrew tap |
| `PACKAGE_DISTRIBUTION.md` | 分发渠道总览 |
| `dependabot.yml` | Dependabot 配置 |
| `release-drafter.yml` / `release-please-config.json` | 自动发版配置 |
| `.release-please-manifest.json` | release-please 版本清单 |

---

## 8. 关键文件 1-1 表

| 用途 | 路径 |
|---|---|
| **应用主入口** | [ai_agent/app.py](../ai_agent/app.py) |
| **Agent 核心** | [ai_agent/agent.py](../ai_agent/agent.py) |
| **配置中心** | [ai_agent/config.py](../ai_agent/config.py) |
| **5 层容错** | [ai_agent/llm_reliability.py](../ai_agent/llm_reliability.py) |
| **记忆存储** | [ai_agent/memory_store.py](../ai_agent/memory_store.py) |
| **多 Agent 编排** | [ai_agent/multi_agent.py](../ai_agent/multi_agent.py) |
| **HITL** | [ai_agent/human_in_loop.py](../ai_agent/human_in_loop.py) |
| **Prompt 注册** | [ai_agent/prompt_registry.py](../ai_agent/prompt_registry.py) |
| **RAG** | [ai_agent/rag.py](../ai_agent/rag.py) |
| **打包 spec** | [ai_agent/ai_agent.spec](../ai_agent/ai_agent.spec) |
| **Dockerfile** | [web_console/Dockerfile](../web_console/Dockerfile) |
| **前端入口** | [web_console/src/App.tsx](../web_console/src/App.tsx) |
| **Docker 编排** | [docker-compose.yml](../docker-compose.yml) |

---

## 9. 体积数据(参考)

| 项 | 大小 |
|---|---|
| Windows 桌面包(zip) | ~470 MB |
| Windows 桌面包(解压) | ~1.16 GB |
| Linux 桌面包 | ~520 MB |
| Docker 镜像(web_console) | ~1.5 GB |
| PyPI wheel | ~30 MB |
| 后端测试覆盖率(HTML) | ~3 MB |

---

## 10. 相关文档

| 主题 | 路径 |
|---|---|
| 项目首页 | [README.md](../README.md) |
| 5 分钟起步 | [QUICKSTART.md](../QUICKSTART.md) |
| 分发渠道 | [DISTRIBUTION.md](../DISTRIBUTION.md) |
| 贡献 | [CONTRIBUTING.md](../CONTRIBUTING.md) |
| API 参考 | [docs/API.md](API.md) |
| 后端详细 | [ai_agent/README.md](../ai_agent/README.md) |
| 前端详细 | [web_console/README.md](../web_console/README.md) |
| 桌面包总览 | [ai_agent/package/README.md](../ai_agent/package/README.md) |
| 文档地图 | [README.md §附录 Documentation Map](../README.md) |