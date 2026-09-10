"""observability.otel_exporter — Milestone 2.3.1 OpenTelemetry + Prometheus

职责
----
  - 初始化 OTel ``TracerProvider`` / ``MeterProvider``；
  - 提供 OTel Tracer / Meter 懒加载单例；
  - 通过 ``prometheus_client`` 暴露业务 metric（与 OTel API 桥接），
    由 ``render_metrics_text()`` / ``metrics_endpoint_response()`` 输出 Prometheus 文本格式；
  - 提供 4 个高频指标的辅助记录函数（业务侧零门槛调用）：
      * ``record_llm_tokens(model, kind, n)`` —— 累加 token 用量
      * ``record_agent_switch(from_agent, to_agent, duration_seconds, status)`` —— 切换耗时
      * ``record_sandbox_execution(tool, duration_seconds, status)`` —— 沙箱执行耗时 + 超时
      * ``record_hitl_decision(decision, tool)`` —— HITL 决策计数

API
---
  - ``init_otel_providers(service_name="trae-agent-system")`` —— 幂等初始化
  - ``get_tracer(name="ai_agent")`` / ``get_meter(name="ai_agent")``
  - ``set_metrics_exporter(exporter)`` —— 注入自定义 exporter（测试用 in-memory）
  - ``render_metrics_text()`` —— Prometheus 文本格式字符串
  - ``metrics_endpoint_response()`` —— ``(body, content_type)`` 直接给 FastAPI /metrics

设计要点
----
  1) OTel SDK 不可用时整套 API 优雅降级（返回 NoOp tracer / meter），业务侧无需 try/except；
  2) prometheus_client 直接用，避免强依赖 ``opentelemetry-exporter-prometheus``；
     桥接策略：OTel Meter 仍创建真实 histogram / counter，并在每次
     ``record_*`` 后立即把指标同步到 prometheus_client 共享 registry。
  3) 单测可注入 ``InMemoryMetricReader`` 验证指标值。
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 懒加载单例（全局）
# ============================================================

_TRACER_PROVIDER: Optional[Any] = None
_METER_PROVIDER: Optional[Any] = None
_INITIALIZED: bool = False
_LOCK = threading.Lock()
_SERVICE_NAME: str = "trae-agent-system"

# 已创建的 OTel instrument（避免重复创建）
_INSTRUMENTS: Dict[str, Any] = {}

# prometheus_client 注册表（始终可用；测试可注入自定义 REGISTRY）
try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        REGISTRY as _DEFAULT_REGISTRY,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )
except Exception:  # pragma: no cover
    CollectorRegistry = None  # type: ignore
    Counter = None  # type: ignore
    Gauge = None  # type: ignore
    Histogram = None  # type: ignore
    _DEFAULT_REGISTRY = None  # type: ignore
    generate_latest = None  # type: ignore
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"

# 自定义 prometheus_client 指标（与 OTel 同源；命名一致以便 grafana / prometheus 识别）
_PROM_INSTRUMENTS: Dict[str, Any] = {}
_PROM_REGISTRY = _DEFAULT_REGISTRY  # 测试可替换


# ============================================================
# OTel SDK 检测 + 初始化
# ============================================================


def _has_otel_sdk() -> bool:
    try:
        from opentelemetry import trace, metrics  # noqa: F401
        from opentelemetry.sdk.trace import TracerProvider  # noqa: F401
        from opentelemetry.sdk.metrics import MeterProvider  # noqa: F401

        return True
    except Exception:
        return False


def init_otel_providers(
    service_name: Optional[str] = None,
    *,
    metrics_reader: Optional[Any] = None,
    span_exporter: Optional[Any] = None,
) -> Tuple[bool, Optional[Any], Optional[Any]]:
    """初始化 OTel TracerProvider / MeterProvider；幂等。

    Args:
        service_name: 资源属性 service.name，默认 ``trae-agent-system``。
        metrics_reader: 测试可注入自定义 reader（如 PeriodicExportingMetricReader + InMemoryExporter）；
                        None 时不导出（指标只入 OTel Meter，不外发）。
        span_exporter: 测试可注入自定义 exporter（InMemorySpanExporter）。

    Returns:
        (success, tracer_provider, meter_provider)；SDK 不可用时返回 (False, None, None)。
    """
    global _TRACER_PROVIDER, _METER_PROVIDER, _INITIALIZED, _SERVICE_NAME

    with _LOCK:
        if _INITIALIZED:
            return (
                _TRACER_PROVIDER is not None,
                _TRACER_PROVIDER,
                _METER_PROVIDER,
            )

        _SERVICE_NAME = service_name or os.environ.get(
            "OTEL_SERVICE_NAME", "trae-agent-system"
        )

        if not _has_otel_sdk():
            logger.warning(
                "OpenTelemetry SDK not available, observability in degraded mode"
            )
            _INITIALIZED = True
            return (False, None, None)

        try:
            from opentelemetry import trace, metrics
            from opentelemetry.sdk.trace import TracerProvider as _TracerProvider
            from opentelemetry.sdk.metrics import MeterProvider as _MeterProvider
            from opentelemetry.sdk.resources import Resource

            # TracerProvider
            resource = Resource.create({"service.name": _SERVICE_NAME})
            tracer_provider = _TracerProvider(resource=resource)
            if span_exporter is not None:
                try:
                    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

                    tracer_provider.add_span_processor(
                        SimpleSpanProcessor(span_exporter)
                    )
                except Exception as e:
                    logger.warning(f"add span processor failed: {e}")
            trace.set_tracer_provider(tracer_provider)
            _TRACER_PROVIDER = tracer_provider

            # MeterProvider
            meter_provider = _MeterProvider(resource=resource)
            if metrics_reader is not None:
                try:
                    meter_provider._reader = metrics_reader  # type: ignore[attr-defined]
                except Exception:
                    # 通过 sdk 公开的接口
                    try:
                        meter_provider = _MeterProvider(
                            resource=resource,
                            metric_readers=[metrics_reader],
                        )
                    except Exception as e:
                        logger.warning(f"meter_reader attach failed: {e}")
            metrics.set_meter_provider(meter_provider)
            _METER_PROVIDER = meter_provider

            _INITIALIZED = True
            logger.info(
                f"OpenTelemetry providers initialized (service={_SERVICE_NAME})"
            )
            return (True, tracer_provider, meter_provider)
        except Exception as e:
            logger.warning(f"OpenTelemetry init failed: {e}")
            _INITIALIZED = True
            return (False, None, None)


def _ensure_initialized() -> None:
    """确保 provider 已初始化（惰性）。"""
    if not _INITIALIZED:
        init_otel_providers()


def get_tracer(name: str = "ai_agent") -> Any:
    """获取 OTel tracer；SDK 不可用时返回 NoOp（业务侧零 try/except）。"""
    _ensure_initialized()
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:
        return _NoOpTracer()


def get_meter(name: str = "ai_agent") -> Any:
    """获取 OTel meter；SDK 不可用时返回 NoOp。"""
    _ensure_initialized()
    try:
        from opentelemetry import metrics

        return metrics.get_meter(name)
    except Exception:
        return _NoOpMeter()


# ============================================================
# 业务指标辅助
# ============================================================


def _get_or_create_prom_instrument(
    name: str,
    kind: str,
    help_text: str,
    label_names: Iterable[str] = (),
) -> Any:
    """获取或创建 prometheus_client 指标（始终 fallback 友好）。

    kind: 'counter' | 'histogram' | 'gauge'
    """
    global _PROM_REGISTRY
    if Counter is None:
        return None
    if name in _PROM_INSTRUMENTS:
        return _PROM_INSTRUMENTS[name]
    try:
        registry = _PROM_REGISTRY
        if kind == "counter":
            inst = Counter(name, help_text, list(label_names), registry=registry)
        elif kind == "histogram":
            inst = Histogram(name, help_text, list(label_names), registry=registry)
        elif kind == "gauge":
            inst = Gauge(name, help_text, list(label_names), registry=registry)
        else:
            return None
        _PROM_INSTRUMENTS[name] = inst
        return inst
    except ValueError as e:
        # 已注册过（跨 reload / 多 module import）
        if "Duplicated" in str(e):
            try:
                if _PROM_REGISTRY is not None:
                    return _PROM_REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
            except Exception:
                return None
        return None
    except Exception as e:
        logger.warning(f"create prom instrument {name} failed: {e}")
        return None


def _get_or_create_otel_histogram(
    name: str, unit: str = "s", description: str = ""
) -> Any:
    """获取或创建 OTel Histogram；用于 OTel-only 路径。"""
    if name in _INSTRUMENTS:
        return _INSTRUMENTS[name]
    meter = get_meter()
    try:
        inst = meter.create_histogram(
            name=name, unit=unit, description=description
        )
    except Exception:
        inst = _NoOpHistogram()
    _INSTRUMENTS[name] = inst
    return inst


def _get_or_create_otel_counter(name: str, description: str = "") -> Any:
    if name in _INSTRUMENTS:
        return _INSTRUMENTS[name]
    meter = get_meter()
    try:
        inst = meter.create_counter(name=name, description=description)
    except Exception:
        inst = _NoOpCounter()
    _INSTRUMENTS[name] = inst
    return inst


def record_llm_tokens(
    model: str, kind: str, n: int, *, service_name: Optional[str] = None
) -> None:
    """记录 LLM token 用量。

    Args:
        model: 模型名（gpt-4o / deepseek-chat 等）。
        kind: 'prompt' | 'completion' | 'total'。
        n: token 数。
        service_name: 自定义 service 标签（可选）。
    """
    if n < 0:
        return
    counter = _get_or_create_prom_instrument(
        "llm_token_usage_total",
        "counter",
        "LLM token usage (prompt / completion)",
        ("model", "kind", "service"),
    )
    if counter is not None:
        try:
            labels = {"model": model or "unknown", "kind": kind or "total"}
            labels["service"] = service_name or _SERVICE_NAME
            counter.labels(**labels).inc(n)
        except Exception as e:
            logger.debug(f"record_llm_tokens prom failed: {e}")

    otel_counter = _get_or_create_otel_counter(
        "llm_token_usage_total", "LLM token usage (prompt / completion)"
    )
    try:
        otel_counter.add(
            n,
            attributes={
                "model": model or "unknown",
                "kind": kind or "total",
                "service": service_name or _SERVICE_NAME,
            },
        )
    except Exception:
        pass


def record_agent_switch(
    from_agent: str,
    to_agent: str,
    duration_seconds: float,
    *,
    status: str = "ok",
) -> None:
    """记录 Supervisor 状态切换。"""
    if duration_seconds < 0:
        duration_seconds = 0.0
    hist = _get_or_create_prom_instrument(
        "agent_switch_latency_seconds",
        "histogram",
        "Supervisor agent switch latency (seconds)",
        ("from_agent", "to_agent", "status"),
    )
    if hist is not None:
        try:
            hist.labels(
                from_agent=from_agent or "unknown",
                to_agent=to_agent or "unknown",
                status=status or "ok",
            ).observe(duration_seconds)
        except Exception as e:
            logger.debug(f"record_agent_switch prom failed: {e}")

    otel_hist = _get_or_create_otel_histogram(
        "agent_switch_latency_seconds",
        unit="s",
        description="Supervisor agent switch latency (seconds)",
    )
    try:
        otel_hist.record(
            duration_seconds,
            attributes={
                "from_agent": from_agent or "unknown",
                "to_agent": to_agent or "unknown",
                "status": status or "ok",
            },
        )
    except Exception:
        pass


def record_sandbox_execution(
    tool: str,
    duration_seconds: float,
    *,
    status: str = "ok",
    timed_out: bool = False,
    timeout_label: Optional[str] = None,
) -> None:
    """记录沙箱代码执行耗时。

    Args:
        tool: 工具名（如 python_interpreter）。
        duration_seconds: 实际耗时。
        status: 'ok' | 'error' | 'timeout'。
        timed_out: 是否被 timeout 拦截（快捷位）。
        timeout_label: 显式 timeout 标签（可选）。
    """
    if duration_seconds < 0:
        duration_seconds = 0.0
    label = timeout_label or ("timeout" if timed_out else status)
    hist = _get_or_create_prom_instrument(
        "sandbox_execution_duration_seconds",
        "histogram",
        "Sandbox code execution duration (seconds)",
        ("tool", "status"),
    )
    if hist is not None:
        try:
            hist.labels(tool=tool or "unknown", status=label).observe(
                duration_seconds
            )
        except Exception as e:
            logger.debug(f"record_sandbox_execution prom failed: {e}")

    otel_hist = _get_or_create_otel_histogram(
        "sandbox_execution_duration_seconds",
        unit="s",
        description="Sandbox code execution duration (seconds)",
    )
    try:
        otel_hist.record(
            duration_seconds,
            attributes={"tool": tool or "unknown", "status": label},
        )
    except Exception:
        pass


def record_hitl_decision(decision: str, tool: str = "") -> None:
    """记录 HITL 决策（approved / rejected / timed_out）。"""
    counter = _get_or_create_prom_instrument(
        "hitl_decisions_total",
        "counter",
        "HITL approval decisions count",
        ("decision", "tool"),
    )
    if counter is not None:
        try:
            counter.labels(
                decision=decision or "unknown", tool=tool or "unknown"
            ).inc()
        except Exception as e:
            logger.debug(f"record_hitl_decision prom failed: {e}")


# ============================================================
# Prometheus 文本导出
# ============================================================


def set_metrics_exporter(registry: Any) -> None:
    """测试 / 多进程场景：注入自定义 prometheus_client CollectorRegistry。"""
    global _PROM_REGISTRY, _PROM_INSTRUMENTS
    _PROM_REGISTRY = registry
    _PROM_INSTRUMENTS = {}  # 重置（在新 registry 中重建）


def render_metrics_text() -> str:
    """返回 Prometheus 文本格式（``generate_latest``）。"""
    if generate_latest is None or _PROM_REGISTRY is None:
        return "# prometheus_client not available\n"
    try:
        return generate_latest(_PROM_REGISTRY).decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"render_metrics_text failed: {e}")
        return f"# render error: {e}\n"


def metrics_endpoint_response() -> Tuple[bytes, str]:
    """FastAPI ``/metrics`` 直接返回的 ``(body, content_type)``。"""
    body = render_metrics_text().encode("utf-8")
    return body, CONTENT_TYPE_LATEST


# ============================================================
# 测试重置
# ============================================================


def _reset_for_tests() -> None:
    """清空全局缓存；单测间隔离。"""
    global _TRACER_PROVIDER, _METER_PROVIDER, _INITIALIZED, _INSTRUMENTS
    global _PROM_INSTRUMENTS, _PROM_REGISTRY, _SERVICE_NAME
    _TRACER_PROVIDER = None
    _METER_PROVIDER = None
    _INITIALIZED = False
    _INSTRUMENTS = {}
    _PROM_INSTRUMENTS = {}
    _PROM_REGISTRY = _DEFAULT_REGISTRY
    _SERVICE_NAME = "trae-agent-system"


# ============================================================
# NoOp fallback（SDK 缺失 / OTel 不可用时使用）
# ============================================================


class _NoOpTracer:
    def start_span(self, *a, **kw):
        return _NoOpSpan()


class _NoOpSpan:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def set_attribute(self, *a, **kw):
        return None

    def set_status(self, *a, **kw):
        return None

    def end(self, *a, **kw):
        return None

    def record_exception(self, *a, **kw):
        return None


class _NoOpMeter:
    def create_histogram(self, *a, **kw):
        return _NoOpHistogram()

    def create_counter(self, *a, **kw):
        return _NoOpCounter()


class _NoOpHistogram:
    def record(self, *a, **kw):
        return None


class _NoOpCounter:
    def add(self, *a, **kw):
        return None


__all__ = [
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
]