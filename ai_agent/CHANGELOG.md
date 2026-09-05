# Changelog

AI Agent 项目更新记录。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

<!-- bumpversion placeholder -->

## v2.0.9 (2026-09-04) — Harness + v2.0 slim runtime

### Added
- `ai_agent/v2_slim/` — slim runtime namespace: 5 old modules collapsed into 3 (`tools_v2.py`, `memory_store_v2.py`, `multi_agent_v2.py`, `approval.py`, `telemetry.py`). Frozen names (`frozen("name")()`) raise `NotImplementedError`. Default: slim on (`AIAgent_LEGACY=false`).
- `ai_agent/harness.py` + `harness_runner.py` + `harness_storage.py` + `harness_cli.py` + `harness_observability.py` — Agent 运行时门面 + Eval Harness(JSONL 加载 + Keyword/Embed/Composite 评分 + `cases.jsonl`/`summary.json`/`metrics.json` 落盘)。
- `ai_agent/scripts/migrate_memory_v1_to_v2.py` — EPISODIC/PROCEDURAL 合入 ShortTerm/LongTerm。
- `ai_agent/scripts/staging_monitor_loop.py` — 24h staging 探针循环。
- `ai_agent/docs/HARNESS.md` + `STAGING_DEPLOY_CHECKLIST.md` + `STAGING_MONITORING.md` — Harness 参考 + staging 部署与监控 runbook。
- `ai_agent/evals/` — eval harness 基础(已有 harness_dry_* / harness_pr*_local / harness_smoke_* runs)。
- `.github/workflows/release.yml` — tag 驱动的 release 流水线(sdist + wheel + source tarball + release_cli.py github/gitee)。
- `.github/workflows/pr-merge-label.yml` — merged release PR 自动打 `release` label 并 comment。
- 11 个新 test 模块(`test_harness*.py`、`test_staging_monitor.py`、`test_v2_slim_*.py`) — slim profile 下 `613 passed in 89.14s`。

### Changed
- `agent.py` — `init_agent()` 运行时切换 LEGACY_MODE 不再需重启。
- `app.py` — `/api/models` 跟随 LEGACY_MODE。
- `api.py` — `/api/health` 返回运行时 flavor(`v2_slim` vs `legacy`)给 staging 探针。
- `config.py` — 新增 `LEGACY_MODE` 与 `V2_SLIM_PACKAGE` 环境变量。
- `web_ui.py` — Web 入口跟随 LEGACY_MODE。
- `pyproject.toml` — version `2.0.8` → `2.0.9`;新增 `harness_runner / harness_storage / harness_cli` py-modules。

### Tests
- `tests/test_harness.py` — CaseLoader / Scorerers / Runner / Storage / CLI dry-run。
- `tests/test_harness_facade.py` — Harness.run / run_stream + Trace shape。
- `tests/test_harness_observability.py` — Trace → observability 落盘回环。
- `tests/test_staging_monitor.py` — 15 个 staging 探针。
- `tests/test_v2_slim_*.py` × 6 — 双入口一致性 / frozen 抛错 / LEGACY 切换 / 迁移 / run pipeline / 7-event schema / 工具子命令路由。

总计 slim profile: 613 passed ✅(legacy `tests/legacy/` 280 用例 skip)

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