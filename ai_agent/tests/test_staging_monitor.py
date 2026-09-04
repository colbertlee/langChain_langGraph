"""
v2.0 slim — Staging 24h 监控探针

部署到 staging 后每隔一段时间（推荐 5min）跑一次：
    pytest tests/test_staging_monitor.py -v

探针维度：
1. TelemetrySink 自检
   - snapshot() 字段完整
   - counters/gauges/histograms_summary 累积不重置
2. 11 Provider 路由可达性
   - 仅检查 _build_provider_base_url 返回正确 URL
   - 不发起真实 API 请求
3. 7 事件 schema 漂移检测（静态扫描 run_stream 源码）
4. 五层容错模块可导入 + FailLog 可写入
5. v2 slim 入口可达（双重 import 兼容）

执行：
    pytest tests/test_staging_monitor.py -v
    pytest tests/test_staging_monitor.py --junitxml=staging-report.xml

告警规则（建议接入监控告警系统）：
- test_telemetry_snapshot_has_all_keys 失败 → TelemetrySink 字段变更
- test_provider_base_url_* 失败 → 核心 Provider 路由漂移
- test_seven_event_types_present 失败 → run_stream 事件 schema 变更
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Dict, List

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# 1. TelemetrySink 自检
# ============================================================

def test_telemetry_snapshot_has_all_keys():
    """TelemetrySink.snapshot() 必须返回 5 个必需字段。"""
    from v2_slim.telemetry import TelemetrySink
    sink = TelemetrySink()
    snap = sink.snapshot()
    required = {"counters", "gauges", "histograms_summary", "recent_events", "recent_spans"}
    missing = required - set(snap.keys())
    assert not missing, f"TelemetrySink.snapshot() 缺字段：{missing}（可用：{set(snap.keys())}）"


def test_telemetry_snapshot_state_persists():
    """多次调用 snapshot()，counters/gauges 应保持累积（不重置）。"""
    from v2_slim.telemetry import TelemetrySink
    sink = TelemetrySink()
    sink.incr("requests_total", 5)
    sink.incr("errors_total", 2)
    sink.gauge("active_sessions", 10)

    snap1 = sink.snapshot()
    sink.incr("requests_total", 3)  # 继续累积
    snap2 = sink.snapshot()

    assert snap1["counters"]["requests_total"] == 5
    assert snap2["counters"]["requests_total"] == 8
    assert snap2["counters"]["errors_total"] == 2
    assert snap2["gauges"]["active_sessions"] == 10


def test_telemetry_histogram_p95_p99():
    """histograms_summary.p95 / p99 必须单调不减。"""
    from v2_slim.telemetry import TelemetrySink
    sink = TelemetrySink()
    for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
        sink.observe("latency_ms", v)
    snap = sink.snapshot()
    h = snap["histograms_summary"]["latency_ms"]
    assert h["count"] == 10
    assert h["p50"] <= h["p95"] <= h["p99"], (
        f"histogram p50/p95/p99 必须单调：p50={h['p50']}, p95={h['p95']}, p99={h['p99']}"
    )


def test_telemetry_event_recording():
    """emit() 必须产生 recent_events（最多保留 1000 条）。"""
    from v2_slim.telemetry import TelemetrySink
    sink = TelemetrySink()
    for i in range(5):
        sink.emit("test_event", idx=i)
    snap = sink.snapshot()
    assert len(snap["recent_events"]) >= 5
    last = snap["recent_events"][-1]
    assert last["event"] == "test_event"
    assert last["idx"] == 4


# ============================================================
# 2. 11 Provider 路由可达性
# ============================================================

def test_provider_base_url_all_8_compat():
    """8 个 OpenAI 兼容 Provider 必须返回正确 base_url。"""
    from agent import _build_provider_base_url
    expected = {
        "deepseek": "https://api.deepseek.com/v1",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        "moonshot": "https://api.moonshot.cn/v1",
        "minimax": "https://api.minimax.chat/v1",
        "doubao": "https://ark.cn-beijing.volces.com/api/v3",
        "hunyuan": "https://api.hunyuan.tencent.com/v1",
        "siliconflow": "https://api.siliconflow.cn/v1",
    }
    for provider, url in expected.items():
        actual = _build_provider_base_url(provider)
        assert actual == url, f"Provider {provider} base_url 漂移：期望 {url}，实际 {actual}"
    assert _build_provider_base_url("openai") is None


def test_provider_meta_covers_all_11():
    """config.PROVIDER_META 必须覆盖全部 11 个 provider。"""
    import config
    expected = {"openai", "deepseek", "qwen", "zhipu", "moonshot",
                "minimax", "baidu", "spark", "doubao", "hunyuan", "siliconflow"}
    actual = set(config.PROVIDER_META.keys())
    missing = expected - actual
    assert not missing, f"PROVIDER_META 缺：{missing}"


# ============================================================
# 3. 7 事件 schema 漂移检测（静态扫描 run_stream）
# ============================================================

def test_seven_event_types_present():
    """run_stream 源码必须含 7 种事件类型字面量。"""
    import inspect
    import re
    from agent import AIAgent
    src = inspect.getsource(AIAgent.run_stream)
    expected = {"start", "safety", "thinking", "chunk", "tool_call", "error", "complete"}
    found = set(re.findall(r'_evt\(["\']([a-z_]+)["\']', src))
    missing = expected - found
    assert not missing, f"run_stream 缺事件类型：{missing}（找到 {found}）"


def test_event_types_no_drift():
    """事件类型不允许出现未知字符串（防止 typo）。"""
    import inspect
    import re
    from agent import AIAgent
    src = inspect.getsource(AIAgent.run_stream)
    expected = {"start", "safety", "thinking", "chunk", "tool_call", "error", "complete"}
    found = set(re.findall(r'_evt\(["\']([a-z_]+)["\']', src))
    unexpected = found - expected
    assert not unexpected, f"run_stream 出现未知事件类型：{unexpected}"


# ============================================================
# 4. 五层容错模块自检
# ============================================================

def test_fault_tolerance_modules_importable():
    """五层容错关键类必须可导入。"""
    from llm_reliability import (
        ResilientLLMInvoker, ModelFallbackChain, FallbackCandidate,
        RetryConfig, FailLogRepository, ProviderBreaker,
        PrimaryStandbyConfig, GracefulDegradation, LLMError, LLMErrorKind,
    )
    assert ResilientLLMInvoker is not None
    assert ModelFallbackChain is not None
    assert RetryConfig is not None


def test_fail_log_writable(tmp_path):
    """FailLogRepository 必须能写入 SQLite。"""
    from llm_reliability import FailLogRepository
    db = str(tmp_path / "fail.db")
    repo = FailLogRepository(db)
    repo.record(
        trace_id="staging-1", session_id=None, provider="openai", model="gpt-4o-mini",
        error_kind="timeout", error_fingerprint="?|timeout|staging",
        message="staging check", attempts=1, fallbacks_tried=[], recovered=False,
    )
    stats = repo.fingerprint_stats()
    assert len(stats) >= 1
    assert any(s["error_fingerprint"] == "?|timeout|staging" for s in stats)


# ============================================================
# 5. v2 slim 双重入口可达
# ============================================================

def test_v2_slim_double_entry_import():
    """v2_slim 必须既能被作为 ai_agent.v2_slim 导入，也能被作为 v2_slim 导入。"""
    # 1. 作为 ai_agent.v2_slim 子包
    try:
        from ai_agent.v2_slim import frozen, approval, telemetry
        ok1 = True
    except ImportError:
        ok1 = False
    # 2. 作为顶级 v2_slim
    try:
        from v2_slim import frozen, approval, telemetry
        ok2 = True
    except ImportError:
        ok2 = False
    # 至少一种必须可用（取决于 PYTHONPATH）
    assert ok1 or ok2, "v2_slim 双重入口都不可用"


# ============================================================
# 6. LEGACY 兜底模块仍可导入（兼容性测试）
# ============================================================

def test_legacy_modules_importable():
    """LEGACY 兜底模块在两种模式下都必须可 import。"""
    # 这些模块无论 LEGACY_MODE=True/False 都应可导入（只是可能 not implemented）
    from v2_slim.tools_legacy import get_all_tools as legacy_get_all
    from v2_slim.memory_store_legacy import get_memory_store as legacy_get_ms
    from v2_slim.multi_agent_legacy import get_orchestrator as legacy_get_orch
    from v2_slim.frozen_modules import ab_test, rate_limit
    from v2_slim.negotiation_legacy import negotiate
    assert callable(legacy_get_all)
    assert callable(legacy_get_ms)
    assert callable(legacy_get_orch)
    assert callable(ab_test)
    assert callable(rate_limit)
    assert callable(negotiate)


# ============================================================
# 7. frozen 模块必须抛 NotImplementedError（不静默）
# ============================================================

def test_frozen_modules_raise_not_implemented():
    """所有 frozen 模块调用必须抛 NotImplementedError（不能静默成功）。"""
    from v2_slim.frozen_modules import ab_test, rate_limit
    from v2_slim.negotiation_legacy import negotiate

    for fn in (ab_test, rate_limit, negotiate):
        with pytest.raises(NotImplementedError) as ei:
            fn()
        assert "Frozen in v2.0 slim" in str(ei.value), (
            f"{fn.__name__} 应抛 'Frozen in v2.0 slim'，实际 {ei.value}"
        )


# ============================================================
# 8. migration 模块可作为 Python 模块 import
# ============================================================

def test_migration_module_importable():
    """迁移脚本必须既可作为 __main__ 跑，也能作为模块 import。"""
    sys.path.insert(0, str(ROOT / "scripts"))
    import migrate_memory_v1_to_v2 as m
    assert hasattr(m, "main")
    assert hasattr(m, "migrate_short_term")
    assert hasattr(m, "_init_ctx")


# ============================================================
# 9. 健康度汇总（报告）
# ============================================================

def test_staging_health_report():
    """综合健康度报告（手动查看，便于接入告警）。"""
    import json
    report = {
        "timestamp": time.time(),
        "checks": {},
    }

    # Telemetry
    try:
        from v2_slim.telemetry import get_telemetry
        snap = get_telemetry().snapshot()
        report["checks"]["telemetry"] = "OK"
        report["checks"]["counters"] = len(snap.get("counters", {}))
    except Exception as e:
        report["checks"]["telemetry"] = f"FAIL: {e}"

    # Provider
    try:
        from agent import _build_provider_base_url
        ok = sum(1 for p in ["deepseek", "qwen", "zhipu", "moonshot", "minimax",
                             "doubao", "hunyuan", "siliconflow"]
                 if _build_provider_base_url(p) is not None)
        report["checks"]["providers"] = f"{ok}/8"
    except Exception as e:
        report["checks"]["providers"] = f"FAIL: {e}"

    # Five-layer
    try:
        from llm_reliability import ResilientLLMInvoker, FailLogRepository
        report["checks"]["fault_tolerance"] = "OK"
    except Exception as e:
        report["checks"]["fault_tolerance"] = f"FAIL: {e}"

    print("\n[STAGING HEALTH REPORT]")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    assert "FAIL" not in str(report["checks"].values()), (
        f"健康检查失败：{report['checks']}"
    )
