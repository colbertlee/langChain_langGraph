# Staging 24h 监控运行手册

本文档说明如何在 staging 环境部署后跑 24h 监控探针。

## 探针来源

`tests/test_staging_monitor.py`（15 个探针）覆盖：

1. **TelemetrySink 自检**（5 项）
   - snapshot() 字段完整性
   - counters/gauges 累积不重置
   - histogram p50/p95/p99 单调
   - emit() recent_events 累积

2. **11 Provider 路由**（2 项）
   - 8 个 base_url 路由正确性
   - PROVIDER_META 全 11 覆盖

3. **7 事件 schema 漂移**（2 项）
   - run_stream 含 7 种事件类型
   - 不允许出现未知事件类型

4. **五层容错模块自检**（2 项）
   - ResilientLLMInvoker / FailLogRepository 等可导入
   - FailLog 可写入 SQLite

5. **v2 slim 双重入口**（1 项）
   - ai_agent.v2_slim 与 v2_slim 两种导入方式都可用

6. **LEGACY 兜底**（1 项）
   - 7 个 LEGACY 模块可 import

7. **frozen 模块正确性**（1 项）
   - frozen 模块调用必须抛 NotImplementedError（不静默）

8. **migration 模块**（1 项）
   - migrate_memory_v1_to_v2 可作为 Python 模块 import

9. **综合健康报告**（1 项）
   - 打印 JSON 健康报告并断言无 FAIL

## 部署到 staging

### 1. 单次跑全量探针

```bash
cd /path/to/ai_agent
pytest tests/test_staging_monitor.py -v --no-cov
```

### 2. 24h 定时跑（推荐 5min 一次）

`scripts/staging_monitor_cron.sh`（或 .ps1）：
```bash
#!/bin/bash
while true; do
  pytest tests/test_staging_monitor.py --no-cov -q --junitxml=staging-report-$(date +%Y%m%d-%H%M%S).xml
  sleep 300  # 5 min
done
```

### 3. 接 Prometheus / 告警

把 `--junitxml` 输出转为 Prometheus 指标：
- `tests/test_staging_monitor.py` 失败 → 触发 alert: "v2 slim 探针失败"
- `test_telemetry_snapshot_has_all_keys` 失败 → "TelemetrySink schema 漂移"
- `test_provider_base_url_*` 失败 → "核心 Provider 路由漂移"
- `test_seven_event_types_present` 失败 → "run_stream 事件 schema 漂移"

## 告警分级

| 等级 | 触发条件 | 响应时间 |
|------|---------|---------|
| P0 | telemetry / 7 events schema 漂移 | 立即 |
| P1 | 11 Provider 路由失效 | 5 min |
| P2 | FailLog 不可写 | 15 min |
| P3 | LEGACY 模块不可 import | 30 min |

## 24h 稳定指标

部署后 24h 内探针全部通过（0 failure），可执行：

1. **可选地移除 `_legacy` 模块**（P2 任务）
2. **关闭 staging 探针 cron**
3. **发布 v2.0.0**

## 已知遗留问题（与 v2 重构无关）

- `tests/test_app_sse.py / test_app_ws.py / test_app_e2e.py`：触发老 multi_agent auction 死锁
- 这些测试不在 24h 监控范围内（避免误报）

## 联系

发现问题请：
- 提 issue：`tests/test_staging_monitor.py::test_xxx 失败`
- 检查 v2 slim 文档：`docs/V2_SLIM.md`
- 回滚：`export AIAgent_LEGACY=true` 走老实现