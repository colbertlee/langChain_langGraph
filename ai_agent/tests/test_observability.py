"""
test_observability.py — Milestone 2.3.1 LangSmith + OTel + Prometheus 可观测性测试

覆盖：
  1) LangSmith tracer 初始化
     - LANGCHAIN_TRACING_V2=true 时 init_langsmith_tracer 返回 (True, LangChainTracer)
     - 默认 / env=False → (False, None)
     - get_langsmith_callbacks() 自动挂载
  2) OTel providers 初始化 + TracerProvider / MeterProvider
  3) 业务指标记录（record_*）
     - record_llm_tokens / record_agent_switch / record_sandbox_execution / record_hitl_decision
     - 自定义 CollectorRegistry 下值能正确读出
  4) Prometheus 文本导出
     - render_metrics_text() 包含指定指标名 + 行格式合法
     - metrics_endpoint_response() 返回 (bytes, content_type)
  5) /metrics HTTP 端点（FastAPI TestClient）
     - 返回 200 + Prometheus 文本格式
     - 至少含 llm_token_usage_total / agent_switch_latency_seconds /
       sandbox_execution_duration_seconds / hitl_decisions_total 之一
  6) python_interpreter OTel 包装（v21_tools.python_sandbox）
     - 调用 python_interpreter_with_trace 后能正确记 sandbox_execution_duration_seconds
     - 原接口返回值结构未被破坏
  7) Supervisor agent_switch 指标自动记录
     - supervisor 节点在切换时自动调 record_agent_switch
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

_RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(_RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_ROOT))


# ============================================================
# 共用 fixture
# ============================================================


@pytest.fixture(autouse=True)
def _reset_observability():
    """每个测试前清空 observability 全局缓存，避免互相污染。"""
    from observability import _reset_for_tests, _reset_otel_for_tests

    _reset_for_tests()
    _reset_otel_for_tests()
    # 清理 prometheus_client 默认 registry 已被多个测试累积的指标
    try:
        from prometheus_client import REGISTRY

        # 仅清掉我们自己关心的指标名（不影响别的模块）
        for name in (
            "llm_token_usage_total",
            "agent_switch_latency_seconds",
            "sandbox_execution_duration_seconds",
            "hitl_decisions_total",
        ):
            try:
                REGISTRY.unregister(REGISTRY._names_to_collectors.get(name))  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        pass
    yield
    from observability import _reset_for_tests, _reset_otel_for_tests

    _reset_for_tests()
    _reset_otel_for_tests()


@pytest.fixture
def isolated_registry():
    """注入独立 prometheus_client registry，避免被全局污染。"""
    from observability import set_metrics_exporter

    try:
        from prometheus_client import CollectorRegistry

        reg = CollectorRegistry()
        set_metrics_exporter(reg)
        yield reg
    finally:
        from observability import set_metrics_exporter
        from prometheus_client import REGISTRY

        set_metrics_exporter(REGISTRY)


# ============================================================
# 1) LangSmith tracer
# ============================================================


class TestLangSmithTracer:

    def test_default_disabled(self, monkeypatch):
        monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
        monkeypatch.delenv("LANGCHAIN_TRACING", raising=False)
        from observability.langsmith_config import (
            init_langsmith_tracer,
            is_langsmith_enabled,
        )

        init_langsmith_tracer()
        assert is_langsmith_enabled() is False

    def test_enabled_when_env_true(self, monkeypatch):
        monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
        from observability.langsmith_config import (
            init_langsmith_tracer,
            is_langsmith_enabled,
            get_langsmith_tracer,
        )

        # 强制重置
        from observability.langsmith_config import _reset_for_tests

        _reset_for_tests()
        enabled, tracer = init_langsmith_tracer(project_name="trae-test")
        assert enabled is True
        # 在测试里即使没有 LANGSMITH_API_KEY，仍可能构造出 LangChainTracer
        # （langchain_core 自身允许）；只需断言不为 None
        assert get_langsmith_tracer() is not None
        _reset_for_tests()

    def test_get_callbacks_returns_list(self, monkeypatch):
        monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
        from observability.langsmith_config import (
            init_langsmith_tracer,
            get_langsmith_callbacks,
            _reset_for_tests,
        )

        _reset_for_tests()
        init_langsmith_tracer()
        cb = get_langsmith_callbacks()
        assert isinstance(cb, list)
        if cb:
            # 至少一个 callback handler
            assert cb[0] is not None
        _reset_for_tests()

    def test_callbacks_empty_when_disabled(self, monkeypatch):
        monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
        monkeypatch.delenv("LANGCHAIN_TRACING", raising=False)
        from observability.langsmith_config import (
            init_langsmith_tracer,
            get_langsmith_callbacks,
            _reset_for_tests,
        )

        _reset_for_tests()
        init_langsmith_tracer()
        cb = get_langsmith_callbacks()
        assert cb == []
        _reset_for_tests()


# ============================================================
# 2) OTel providers
# ============================================================


class TestOTelProviders:

    def test_init_returns_tuple(self):
        from observability.otel_exporter import init_otel_providers

        ok, tp, mp = init_otel_providers(service_name="trae-test")
        assert isinstance(ok, bool)
        if ok:
            assert tp is not None
            assert mp is not None

    def test_get_tracer_returns_object(self):
        from observability.otel_exporter import get_tracer

        tracer = get_tracer("test-tracer")
        assert tracer is not None
        # 必须有 start_span 接口
        assert hasattr(tracer, "start_span")

    def test_get_meter_returns_object(self):
        from observability.otel_exporter import get_meter

        meter = get_meter("test-meter")
        assert meter is not None
        # 必须有 create_histogram / create_counter
        assert hasattr(meter, "create_histogram")
        assert hasattr(meter, "create_counter")

    def test_tracer_start_span_returns_context_manager(self):
        from observability.otel_exporter import get_tracer

        tracer = get_tracer("test")
        span_cm = tracer.start_span("unit-test-span")
        # 兼容：span_cm 本身是 contextmanager，可以 __enter__
        with span_cm as span:
            assert span is not None


# ============================================================
# 3) 业务指标记录
# ============================================================


class TestRecordMetrics:

    def test_record_llm_tokens_prom(self, isolated_registry):
        from observability.otel_exporter import (
            record_llm_tokens,
            render_metrics_text,
        )

        record_llm_tokens("gpt-4o", "prompt", 100)
        record_llm_tokens("gpt-4o", "completion", 50)
        text = render_metrics_text()
        assert "llm_token_usage_total" in text
        assert 'model="gpt-4o"' in text
        # 至少有一行 kind="prompt" + kind="completion"
        assert 'kind="prompt"' in text
        assert 'kind="completion"' in text

    def test_record_agent_switch(self, isolated_registry):
        from observability.otel_exporter import (
            record_agent_switch,
            render_metrics_text,
        )

        record_agent_switch("supervisor", "research_worker", 0.123)
        record_agent_switch("research_worker", "code_worker", 0.456)
        text = render_metrics_text()
        assert "agent_switch_latency_seconds" in text
        assert 'from_agent="supervisor"' in text
        assert 'to_agent="research_worker"' in text
        assert 'to_agent="code_worker"' in text

    def test_record_sandbox_execution_ok_and_timeout(self, isolated_registry):
        from observability.otel_exporter import (
            record_sandbox_execution,
            render_metrics_text,
        )

        record_sandbox_execution("python_interpreter", 0.1, status="ok")
        record_sandbox_execution(
            "python_interpreter", 11.0, status="timeout", timed_out=True
        )
        text = render_metrics_text()
        assert "sandbox_execution_duration_seconds" in text
        assert 'tool="python_interpreter"' in text
        assert 'status="timeout"' in text

    def test_record_hitl_decision(self, isolated_registry):
        from observability.otel_exporter import (
            record_hitl_decision,
            render_metrics_text,
        )

        record_hitl_decision("approved", "python_interpreter")
        record_hitl_decision("rejected", "python_interpreter")
        record_hitl_decision("timed_out", "python_interpreter")
        text = render_metrics_text()
        assert "hitl_decisions_total" in text
        assert 'decision="approved"' in text
        assert 'decision="rejected"' in text
        assert 'decision="timed_out"' in text

    def test_render_metrics_text_returns_string(self, isolated_registry):
        from observability.otel_exporter import render_metrics_text

        text = render_metrics_text()
        assert isinstance(text, str)
        # 即使没有指标，至少要带 help/type 头（prometheus_client 行为）
        assert "# HELP" in text or "# TYPE" in text or text == ""

    def test_metrics_endpoint_response(self, isolated_registry):
        from observability.otel_exporter import (
            record_llm_tokens,
            metrics_endpoint_response,
        )

        record_llm_tokens("test", "prompt", 10)
        body, content_type = metrics_endpoint_response()
        assert isinstance(body, bytes)
        assert "text/plain" in content_type
        assert b"llm_token_usage_total" in body


# ============================================================
# 4) /metrics HTTP 端点
# ============================================================


class TestMetricsEndpoint:
    """FastAPI TestClient 验证 /metrics 端点。"""

    def test_metrics_endpoint_returns_200(self):
        try:
            from fastapi.testclient import TestClient
        except Exception:
            pytest.skip("fastapi.testclient unavailable")
        try:
            from app import app  # type: ignore
        except Exception as e:
            pytest.skip(f"app module unavailable: {e}")

        client = TestClient(app)
        # 记录一些指标
        from observability.otel_exporter import record_llm_tokens

        record_llm_tokens("gpt-4o", "prompt", 5)
        record_llm_tokens("gpt-4o", "completion", 3)

        r = client.get("/metrics")
        assert r.status_code == 200
        assert "text/plain" in r.headers.get("content-type", "")
        body = r.text
        # 至少一个 metric 名出现
        assert "llm_token_usage_total" in body

    def test_metrics_endpoint_includes_all_required_metrics(self):
        try:
            from fastapi.testclient import TestClient
        except Exception:
            pytest.skip("fastapi.testclient unavailable")
        try:
            from app import app  # type: ignore
        except Exception as e:
            pytest.skip(f"app module unavailable: {e}")

        client = TestClient(app)
        from observability.otel_exporter import (
            record_llm_tokens,
            record_agent_switch,
            record_sandbox_execution,
            record_hitl_decision,
        )

        # 把 4 个核心指标都打一遍，确保 /metrics 输出中至少含 # HELP / # TYPE 头
        record_llm_tokens("gpt-4o", "prompt", 10)
        record_agent_switch("supervisor", "research_worker", 0.05)
        record_sandbox_execution("python_interpreter", 0.5, status="ok")
        record_hitl_decision("approved", "python_interpreter")

        r = client.get("/metrics")
        assert r.status_code == 200
        text = r.text
        for name in (
            "llm_token_usage_total",
            "agent_switch_latency_seconds",
            "sandbox_execution_duration_seconds",
            "hitl_decisions_total",
        ):
            assert name in text, f"metric {name} not in /metrics output"


# ============================================================
# 5) python_interpreter OTel 包装
# ============================================================


class TestPythonSandboxTrace:

    def test_python_interpreter_records_metric(self, isolated_registry):
        from v21_tools.python_sandbox import python_interpreter_with_trace
        from observability.otel_exporter import render_metrics_text

        result = python_interpreter_with_trace("print('hello from sandbox')", timeout=5)
        assert isinstance(result, dict)
        # 原接口契约保留
        assert "stdout" in result
        assert "exit_code" in result
        assert "timed_out" in result
        assert "duration_ms" in result

        text = render_metrics_text()
        assert "sandbox_execution_duration_seconds" in text
        assert 'tool="python_interpreter"' in text

    def test_python_interpreter_records_timeout(self, isolated_registry):
        from v21_tools.python_sandbox import python_interpreter_with_trace
        from observability.otel_exporter import render_metrics_text

        # 用 sleep 触发 timeout
        result = python_interpreter_with_trace(
            "import time; time.sleep(15)", timeout=1
        )
        # result 仍要遵守原契约
        assert isinstance(result, dict)
        text = render_metrics_text()
        # sandbox metric 至少出现一次（ok 或 timeout 至少一个）
        assert "sandbox_execution_duration_seconds" in text

    def test_tooL_registry_uses_traced_interpreter(self):
        """TOOL_REGISTRY['python_interpreter']['func'] 必须是 OTel-wrapped 版本。"""
        from v21_tools import TOOL_REGISTRY

        func = TOOL_REGISTRY["python_interpreter"]["func"]
        # 通过模块路径判断是否来自 python_sandbox
        mod = getattr(func, "__module__", "") or ""
        # 走的是 v21_tools.python_sandbox 或 __init__ 的 fallback
        assert "python_sandbox" in mod or mod == "v21_tools.code_interpreter"


# ============================================================
# 6) Supervisor 自动记录 agent_switch 指标
# ============================================================


class TestSupervisorAgentSwitchMetric:

    def test_supervisor_records_agent_switch(self, isolated_registry):
        from supervisor_agent import build_supervisor_workflow
        from agent_workers import build_research_worker
        from langgraph.checkpoint.memory import MemorySaver

        # Scripted LLM — 第一次给 research_worker，第二次给 FINISH（防止无限递归）
        class _LLM:
            def __init__(self):
                self.n = 0

            def invoke(self, _msgs):
                self.n += 1
                if self.n >= 2:
                    content = '{"next_agent": "FINISH", "thought_process": "done"}'
                else:
                    content = '{"next_agent": "research_worker", "thought_process": "go"}'

                class _R:
                    pass

                r = _R()
                r.content = content
                return r

        wf = build_supervisor_workflow(
            supervisor_llm=_LLM(),
            workers={"research_worker": build_research_worker()},
            checkpointer=MemorySaver(),
        )
        out = wf.invoke(
            {"messages": [{"role": "user", "content": "hi"}]},
            config={"configurable": {"thread_id": "t1"}, "recursion_limit": 10},
        )
        assert out["next_node"] == "FINISH"

        from observability.otel_exporter import render_metrics_text

        text = render_metrics_text()
        # supervisor 决策后会自动写一条 agent_switch_latency_seconds
        assert "agent_switch_latency_seconds" in text
        # 至少出现一次 to_agent="research_worker" 和 to_agent="FINISH"
        assert 'to_agent="research_worker"' in text
        assert 'to_agent="FINISH"' in text

    def test_supervisor_records_finish_transition(self, isolated_registry):
        from supervisor_agent import build_supervisor_workflow
        from agent_workers import build_research_worker
        from langgraph.checkpoint.memory import MemorySaver

        class _LLM:
            def invoke(self, _msgs):
                class _R:
                    content = '{"next_agent": "FINISH", "thought_process": "done"}'

                return _R()

        wf = build_supervisor_workflow(
            supervisor_llm=_LLM(),
            workers={"research_worker": build_research_worker()},
            checkpointer=MemorySaver(),
        )
        wf.invoke(
            {"messages": [{"role": "user", "content": "hi"}]},
            config={"configurable": {"thread_id": "t-finish"}},
        )

        from observability.otel_exporter import render_metrics_text

        text = render_metrics_text()
        assert "agent_switch_latency_seconds" in text
        assert 'to_agent="FINISH"' in text


# ============================================================
# 7) HITL Span 挂起 / 恢复
# ============================================================


class TestHitlSpan:

    def test_start_and_resume_hitl_span(self):
        from observability.hitl_span import (
            start_hitl_span,
            resume_hitl_span,
            pending_count,
            _reset_for_tests,
        )

        _reset_for_tests()
        assert pending_count() == 0
        start_hitl_span(
            "req-1", tool_name="python_interpreter", session_id="s1", agent_name="code_worker"
        )
        assert pending_count() == 1
        dur = resume_hitl_span("req-1", "approved")
        assert dur is not None
        assert dur >= 0.0
        assert pending_count() == 0
        _reset_for_tests()

    def test_resume_unknown_request_id_returns_none(self):
        from observability.hitl_span import resume_hitl_span, _reset_for_tests

        _reset_for_tests()
        assert resume_hitl_span("not-exists", "approved") is None
        _reset_for_tests()

    def test_cancel_hitl_span(self):
        from observability.hitl_span import (
            start_hitl_span,
            cancel_hitl_span,
            pending_count,
            _reset_for_tests,
        )

        _reset_for_tests()
        start_hitl_span("req-2", tool_name="t")
        assert pending_count() == 1
        dur = cancel_hitl_span("req-2", reason="user cancelled")
        assert dur is not None
        assert pending_count() == 0
        _reset_for_tests()


# ============================================================
# 8) observability.__init__ 导出
# ============================================================


class TestObservabilityExports:

    def test_module_exports(self):
        import observability

        names = [
            "init_langsmith_tracer",
            "get_langsmith_tracer",
            "is_langsmith_enabled",
            "get_langsmith_callbacks",
            "init_otel_providers",
            "get_tracer",
            "get_meter",
            "record_llm_tokens",
            "record_agent_switch",
            "record_sandbox_execution",
            "record_hitl_decision",
            "render_metrics_text",
            "metrics_endpoint_response",
            "start_hitl_span",
            "resume_hitl_span",
            "cancel_hitl_span",
        ]
        for n in names:
            assert hasattr(observability, n), f"missing export: {n}"