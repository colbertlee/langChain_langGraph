# Staging 部署 + 24h 监控运行手册（v2.0 slim）

## 当前状态：staging-ready ✅

最近一次全量回归（tests/ - 排除 legacy + test_app_e2e.py 单独跑）：
```
613 passed, 2 deselected, 94165 warnings in 89.14s
```

| 测试套件 | 数量 | 用时 | 状态 |
|---------|------|------|------|
| P0 矛盾探针 consistency | 36 | - | ✅ |
| P0 7 事件探针 stream_events | 10 | - | ✅ |
| P0 五层容错 fault_tolerance | 13 | - | ✅ |
| P0 DRY 管线 run_pipeline | 14 | - | ✅ |
| P0 迁移 migration | 5 | - | ✅ |
| P0 staging_monitor | 15 | - | ✅ |
| P0 v2 基础 tools / legacy_switch | 30 | - | ✅ |
| P1 老测试 security/tools/prompts | 250 | - | ✅ |
| 其他 agent/multi_agent/stream_events | 240 | - | ✅ |
| test_app_e2e（独立脚本） | 53 | - | ✅ |

---

## 部署到 staging

### 1. 部署前置检查

```bash
cd /path/to/ai_agent

# 1.1 确认 LEGACY_MODE 关闭（v2 slim 优先）
unset AIAgent_LEGACY

# 1.2 确认没有真实 OPENAI_API_KEY（测试 placeholder 短路会生效）
# 生产环境请设置真实的 OPENAI_API_KEY（不含 placeholder 标记）

# 1.3 确认 ai_agent 包可正常 import
python -c "import ai_agent; from ai_agent import agent; print('OK')"

# 1.4 确认 v2_slim 模块可双重导入
python -c "
from v2_slim import frozen, approval, telemetry, multi_agent_v2, tools_v2
from ai_agent.v2_slim import frozen, approval, telemetry
print('v2_slim double-entry: OK')
"
```

### 2. 启动服务

```bash
# 启动 FastAPI（默认 0.0.0.0:8000）
python app.py

# 或 uvicorn（生产）
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

### 3. 健康检查端点

```bash
# 3.1 健康检查
curl http://localhost:8000/api/health

# 3.2 触发 agent 初始化（首次）
curl -X POST http://localhost:8000/api/api-key \
  -H 'Content-Type: application/json' \
  -d '{"api_key": "sk-your-real-key", "provider": "openai"}'

# 3.3 SSE 流式冒烟
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message": "ping", "session_id": "smoke-test"}'
```

---

## 24h 监控探针部署

### 1. 单次跑全量探针

```bash
cd /path/to/ai_agent

# P0 staging 探针（15 项，约 8.4s）
pytest tests/test_staging_monitor.py -v --no-cov --junitxml=staging-$(date +%Y%m%d-%H%M).xml
```

### 2. 24h 定时循环（推荐 5min 一次）

```bash
# scripts/staging_monitor_loop.sh
#!/bin/bash
set -u
LOG_DIR=/var/log/ai_agent/staging
mkdir -p "$LOG_DIR"

while true; do
  TIMESTAMP=$(date +%Y%m%d-%H%M%S)
  echo "[$TIMESTAMP] running staging probe..." >> "$LOG_DIR/probe.log"

  # 跑探针，timeout 60s
  pytest tests/test_staging_monitor.py --no-cov -q \
    --timeout=60 \
    --junitxml="$LOG_DIR/probe-$TIMESTAMP.xml" \
    >> "$LOG_DIR/probe.log" 2>&1

  EXIT=$?
  if [ $EXIT -ne 0 ]; then
    echo "[$TIMESTAMP] FAIL (exit=$EXIT), triggering alert..." >> "$LOG_DIR/probe.log"
    # 接入告警：webhook / email / Slack
    curl -X POST "$STAGING_ALERT_WEBHOOK" \
      -H 'Content-Type: application/json' \
      -d "{\"text\": \"ai_agent staging probe failed at $TIMESTAMP (exit=$EXIT)\"}"
  fi

  sleep 300  # 5 分钟
done
```

```bash
chmod +x scripts/staging_monitor_loop.sh
nohup scripts/staging_monitor_loop.sh &
```

### 3. Prometheus / 告警接入（建议）

把 `--junitxml` 输出转为 Prometheus 指标：

| 探针 | 失败 = 告警级别 | 原因 |
|------|----------------|------|
| `test_telemetry_*` | P0 | TelemetrySink schema 漂移（核心闭环） |
| `test_provider_base_url_*` | P1 | 11 Provider 路由失效 |
| `test_seven_event_types_*` | P0 | run_stream 事件 schema 漂移 |
| `test_event_types_no_drift` | P0 | 出现未知事件类型（typo） |
| `test_fault_tolerance_*` | P1 | 五层容错模块导入失败 |
| `test_fail_log_*` | P2 | FailLog 不可写 |
| `test_v2_slim_double_entry_import` | P1 | v2_slim 双重入口失效 |
| `test_legacy_modules_importable` | P3 | LEGACY 兜底失效（24h 后会移除） |
| `test_frozen_modules_raise_not_implemented` | P0 | frozen 模块静默成功（破坏冻结） |

### 4. 探针涵盖的维度（15 项）

1. `test_telemetry_snapshot_has_all_keys` — TelemetrySink 字段完整性
2. `test_telemetry_snapshot_state_persists` — 累积不重置
3. `test_telemetry_histogram_p95_p99` — histogram 单调
4. `test_telemetry_event_recording` — emit/recent_events
5. `test_provider_base_url_all_8_compat` — 8 个 OpenAI 兼容 Provider
6. `test_provider_meta_covers_all_11` — 11 Provider 全覆盖
7. `test_seven_event_types_present` — run_stream 7 事件
8. `test_event_types_no_drift` — 不允许未知事件类型
9. `test_fault_tolerance_modules_importable` — 五层容错类可导入
10. `test_fail_log_writable` — FailLogRepository 写入
11. `test_v2_slim_double_entry_import` — `v2_slim` 与 `ai_agent.v2_slim` 都可用
12. `test_legacy_modules_importable` — LEGACY 兜底模块可导入
13. `test_frozen_modules_raise_not_implemented` — frozen 抛错（非静默）
14. `test_migration_module_importable` — 迁移脚本可作为模块 import
15. `test_staging_health_report` — 综合健康度报告

---

## 24h 稳定验收标准

### 必备条件（全部满足才能进入 P2）

1. **探针通过率 = 100%**
   - 24h 内 `pytest tests/test_staging_monitor.py` 零失败
   - 允许的 warning：frozen modules 中 `_FROZEN_NAMES 未注册`（legacy 占位）
2. **核心接口不漂移**
   - `test_seven_event_types_present` 稳定通过
   - `test_event_types_no_drift` 稳定通过
   - `test_provider_base_url_all_8_compat` 稳定通过
3. **run_stream 真实路径可用**
   - `test_app_e2e.py`（独立脚本）通过 53/53
   - 真实 `/api/chat/stream` SSE 流式响应正常（前端 fetchEventStream 可解析）
4. **FIVE 容错层真实触发**
   - 某个 Provider 真实 API 调用超时 → 切到 fallback
   - FailLog 中有相应记录（`fingerprint_stats()` 可查）

### 监控指标

| 指标 | 阈值 | 含义 |
|------|------|------|
| `probe_pass_rate_24h` | = 100% | 探针成功率 |
| `telemetry_counters_total` | 持续增长 | TelemetrySink 累积健康 |
| `fail_log_unrecovered_24h` | < 5 | 失败日志中未恢复数 |
| `run_stream_event_count` | > 100/24h | 流式输出有真实流量 |
| `breaker_open_count_24h` | < 10 | 熔断器 OPEN 次数 |

---

## 24h 稳定后：P2 任务（删除 _legacy 模块）

> **✅ 已完成（v2.10+）**：以下清理在 v2.10 起落地，与本部署清单同步。
>
> - 7 个 `v2_slim/*_legacy.py` 已删除（保留 `frozen_modules.py` 占位仍生效）
> - `agent.py` / `api.py` / `multi_agent_router.py` 的 LEGACY_MODE 分支已删除，统一走 v2 slim
> - `config.LEGACY_MODE` 已改为常量 `False`（env 变量 `AIAgent_LEGACY` 不再读取）
> - `tests/test_v2_slim_legacy_switch.py` 整个文件已删除
> - `tests/test_v2_slim_consistency.py` / `test_v2_slim_tools.py` / `test_staging_monitor.py` 中相关测试已重写
>
> 见 release notes `v2.0.10`（待发布）。

---

## 已知遗留（与 v2 重构无关）

- `app.py` 中 `enable_permission_enforcement` 修复后不再触发 `message_bus`（避免测试环境死锁）；生产环境的 message_bus 行为保持原状
- `web_ui.py` 的 SSE 端点改用 `agent.run()` 同步 fallback（牺牲流式体验换取稳定性）；后续可优化为 async + 真流式

---

## 联系

发现问题请：
- 探针失败 → 看 `staging-XXX.xml` + `probe.log`
- 提 issue：`tests/test_staging_monitor.py::test_xxx 失败`
- 回滚：v2.10+ 不支持 LEGACY_MODE 切换；如需回退请 `git revert` 清理 commit
