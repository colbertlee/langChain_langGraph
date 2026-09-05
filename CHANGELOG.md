# 更新日志

所有重要的项目更新都将记录在此文件中。

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
- I-5:tag 在 local/remote 漂移 → §7.2 固化“remote wins, never force-push”
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