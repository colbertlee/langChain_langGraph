"""ai_agent.observability — Milestone 2.3.1 LangSmith + OTel 双引擎可观测性

对外暴露：
  - langsmith_config:  init_langsmith_tracer / get_langsmith_tracer / is_langsmith_enabled
  - otel_exporter:     init_otel_providers / get_tracer / get_meter / record_* 指标辅助函数
  - python_sandbox:    受 OTel Span 包裹的 python_interpreter

设计原则：
  1) "可观测性" 默认开启但不强制：在 OTel SDK / langsmith 不可用时优雅降级，
     所有公共 API 在降级模式下不抛异常（仅 logger.warning）。
  2) LangSmith 与 OTel 双引擎互不耦合：
     - LangSmith 只在 LANGCHAIN_TRACING_V2=true 时启用（影响 LangChain 调用链路）；
     - OTel 总是可用（业务侧手工 span / metric）。
  3) 测试友好：所有模块级别 Provider 都是惰性单例（_reset_for_tests() 重置），
     避免单测间 state 污染。
"""
from __future__ import annotations

from .langsmith_config import (
    init_langsmith_tracer,
    get_langsmith_tracer,
    is_langsmith_enabled,
    get_langsmith_callbacks,
    _reset_for_tests,
)
from .otel_exporter import (
    init_otel_providers,
    get_tracer,
    get_meter,
    set_metrics_exporter,
    render_metrics_text,
    metrics_endpoint_response,
    record_llm_tokens,
    record_agent_switch,
    record_sandbox_execution,
    record_hitl_decision,
    _reset_for_tests as _reset_otel_for_tests,
)
from .hitl_span import (
    start_hitl_span,
    resume_hitl_span,
    cancel_hitl_span,
    pending_count as pending_hitl_spans,
    _reset_for_tests as _reset_hitl_span_for_tests,
)
from .event_bus import EventBus
from .metrics_registry import MetricsRegistry

__all__ = [
    "init_langsmith_tracer",
    "get_langsmith_tracer",
    "is_langsmith_enabled",
    "get_langsmith_callbacks",
    "init_otel_providers",
    "get_tracer",
    "get_meter",
    "set_metrics_exporter",
    "render_metrics_text",
    "metrics_endpoint_response",
    "record_llm_tokens",
    "record_agent_switch",
    "record_sandbox_execution",
    "record_hitl_decision",
    "_reset_for_tests",
    "_reset_otel_for_tests",
]