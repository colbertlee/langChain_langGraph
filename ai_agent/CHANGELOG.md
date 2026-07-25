# Changelog

AI Agent 项目更新记录。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

<!-- bumpversion placeholder -->

## v0.3.0 (2026-07-23) — 阶段 B：国内主流模型 Provider

### Added
- 新增 4 个国产模型 provider：
  - **doubao**（字节豆包 / 火山方舟 ARK）
  - **hunyuan**（腾讯混元）
  - **siliconflow**（硅基流动：一站式聚合 Qwen/DeepSeek/GLM 等）
  - **minimax**（MiniMax 01 / abab7）
- 原 deepseek / qwen / zhipu / moonshot 等老 provider 扩充最新模型：
  - deepseek 新增 `deepseek-reasoner`（R1 推理模型）
  - qwen 新增 `qwen3-max` 等
  - zhipu 拆出 `glm-z1-*` 推理模型
  - moonshot 新增 `kimi-k2-0711-preview`
- 新增 `PROVIDER_META` 元信息（中文 label / group / desc），前端按 provider 分组展示
- `app.py /api/models` 返回新结构：`providers` 数组（每个含 `configured` 字段）
- `web/index.html`：模型下拉改为 `<optgroup>` 分组；未配置 Key 的 provider 选项标灰禁用

### Changed
- `config.py`：新增 4 个 API Key 环境变量（DOUBAO_API_KEY / HUNYUAN_API_KEY / SILICONFLOW_API_KEY / GLM_API_KEY 别名）
- `agent.py`：`_build_provider_base_url` / `_api_key_for_provider` / `_get_model` 补全 4 个新 provider（统一走 ChatOpenAI）
- Fallback chain 加入新 provider，跨 provider 容错更稳健

### Tests
- `tests/test_models_registry.py` — 20 个新用例
- 既有 76 个测试全过（无回归）

总计 96 个测试 ✅

## v0.2.0 (2026-07-23) — 阶段 A：流式中间状态 + Prompt 工程化

### Added
- `prompt_registry.py`：提示词模板化与版本化管理，支持 system / role / tool 三段拼接 + CoT 注入
- `run_stream` 改为产出结构化事件：`start / thinking / chunk / tool_call / safety / error / complete`
- 新增 `/api/prompts` 与 `/api/prompts/rollback` 两个端点
- 前端 `web/index.html`：
  - 工具调用时间线（pill 形式）
  - 思维链折叠面板（`## 思考 ##`）
  - 安全提示横幅
  - 设置面板新增"Prompt 版本管理"

### Tests
- `tests/test_prompt_registry.py` — 10 个用例
- `tests/test_stream_events.py` — 7 个用例
- `tests/test_prompts_api.py` — 4 个用例
- 既有 55 个 `test_agent.py` 用例全部通过（向后兼容）

## v0.1.0 (2025-01-XX)

### Added
- 初始版本
- FastAPI + React 全栈 AI Agent 控制台
- 6 个页面：Chat / Agents / Approval / Observability / Tools / Settings
- 后端 LangChain / LangGraph / MCP 集成
- GitHub Actions CI（7 jobs）+ Docker Compose + GHCR 发布
