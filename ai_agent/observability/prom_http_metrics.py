"""P2-5 — Prometheus HTTP / SSE 中间件

设计目标
========
为 FastAPI 后端注入 HTTP 维度指标：

  - ``http_requests_total``        Counter   HTTP 请求计数（按 method/route/status 分桶）
  - ``http_request_duration_seconds`` Histogram HTTP 请求耗时分布（按 method/route 分桶）
  - ``http_requests_in_progress``  Gauge     当前在途请求数（按 method/route）
  - ``http_request_size_bytes``    Histogram 请求 body 大小分布
  - ``http_response_size_bytes``   Histogram 响应 body 大小分布
  - ``sse_active_connections``     Gauge     当前活跃 SSE 连接数（按 route 分桶）
  - ``sse_bytes_sent_total``       Counter   SSE 已发送字节数（按 route 分桶）
  - ``sse_events_sent_total``      Counter   SSE 已发送事件数（按 route/event_type 分桶）
  - ``sse_connection_duration_seconds`` Histogram SSE 连接总时长分布

与现有 otel_exporter.py 的区别
------------------------------
otel_exporter 关注业务层（LLM token / agent switch / sandbox / HITL decision）；
本模块关注**协议层 / 传输层**（HTTP 方法路径、状态码、SSE 流）。

两者互补，不重复。

降级策略
--------
如果 prometheus_client 不可用 / OTel SDK 缺失 → 全部指标变 NoOp，
不阻断业务，但 /metrics 端点会返回空文本。

路由归一化
----------
用 ``route.path``（FastAPI 路由模板，如 ``/api/chat/{session_id}``）而不是
``request.url.path``（实际路径，如 ``/api/chat/abc-123``），
避免高基数 / 内存爆炸。

SSE 流检测
----------
通过判断 response.media_type == "text/event-stream" 识别 SSE；
需要在 StreamingResponse body 包装层累计字节 / 事件。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Iterable, Optional

from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# ============================================================
# 指标注册（与 otel_exporter 同套 fallback 友好策略）
# ============================================================

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )
    _HAS_PROM = True
except Exception:  # pragma: no cover
    _HAS_PROM = False
    Counter = Histogram = Gauge = CollectorRegistry = generate_latest = CONTENT_TYPE_LATEST = None  # type: ignore


# HTTP buckets: 1ms → 30s（覆盖 LLM 慢响应）
_HTTP_LATENCY_BUCKETS = (
    0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5,
    1.0, 2.5, 5.0, 10.0, 30.0,
)

# SSE 连接时长 buckets: 1s → 30min
_SSE_LATENCY_BUCKETS = (
    1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0,
)

# Body size buckets: 1KB → 10MB
_SIZE_BUCKETS = (
    1024, 10 * 1024, 100 * 1024, 1 * 1024 * 1024,
    5 * 1024 * 1024, 10 * 1024 * 1024,
)


class HttpMetricsRegistry:
    """HTTP / SSE 指标的轻量级注册中心。

    注意：与 otel_exporter.py 不同的是，这里所有 metric 都用
    prometheus_client（不用 OTel SDK），这样可以被 prometheus.yml
    直接 scrape，无需 OTLP collector。
    """

    def __init__(self, registry: Optional[Any] = None) -> None:
        if not _HAS_PROM:
            self._noop = True
            return
        self._noop = False
        self.registry = registry or CollectorRegistry()

        # HTTP 层
        self.requests_total = Counter(
            "http_requests_total",
            "Total HTTP requests (method x route x status)",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self.request_duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request latency in seconds (method x route)",
            ("method", "route"),
            buckets=_HTTP_LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.requests_in_progress = Gauge(
            "http_requests_in_progress",
            "Number of HTTP requests currently in flight (method x route)",
            ("method", "route"),
            registry=self.registry,
        )
        self.request_size = Histogram(
            "http_request_size_bytes",
            "HTTP request body size in bytes (method x route)",
            ("method", "route"),
            buckets=_SIZE_BUCKETS,
            registry=self.registry,
        )
        self.response_size = Histogram(
            "http_response_size_bytes",
            "HTTP response body size in bytes (method x route)",
            ("method", "route"),
            buckets=_SIZE_BUCKETS,
            registry=self.registry,
        )

        # SSE 层
        self.sse_active = Gauge(
            "sse_active_connections",
            "Number of active SSE connections (route)",
            ("route",),
            registry=self.registry,
        )
        self.sse_bytes = Counter(
            "sse_bytes_sent_total",
            "Total SSE bytes sent (route)",
            ("route",),
            registry=self.registry,
        )
        self.sse_events = Counter(
            "sse_events_sent_total",
            "Total SSE events sent (route x event_type)",
            ("route", "event_type"),
            registry=self.registry,
        )
        self.sse_duration = Histogram(
            "sse_connection_duration_seconds",
            "SSE connection lifetime in seconds (route)",
            ("route",),
            buckets=_SSE_LATENCY_BUCKETS,
            registry=self.registry,
        )

    def render(self) -> bytes:
        """生成 Prometheus text 格式的指标导出。"""
        if self._noop:
            return b"# prometheus_client not available\n"
        return generate_latest(self.registry)


# ============================================================
# 全局默认 registry（方便挂载与 /metrics 端点复用）
# ============================================================

_DEFAULT_REGISTRY: Optional[HttpMetricsRegistry] = None


def get_default_registry() -> HttpMetricsRegistry:
    """懒加载全局 registry（避免 import 时副作用）。"""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = HttpMetricsRegistry()
    return _DEFAULT_REGISTRY


# ============================================================
# 路由归一化辅助
# ============================================================


def normalize_route(request: Request) -> str:
    """获取 FastAPI 路由模板（不是实际路径）。

    优先级：
      1) request.scope.get("route").path  （FastAPI 注入）
      2) request.url.path（fallback）

    实际路径会带参数 ID（高基数），所以必须归一化到模板。
    """
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    return request.url.path


def method_of(request: Request) -> str:
    return request.method or "UNKNOWN"


# ============================================================
# 中间件
# ============================================================


class HttpMetricsMiddleware(BaseHTTPMiddleware):
    """FastAPI / Starlette 中间件。

    记录每个 HTTP 请求的：
      - 计数（method × route × status）
      - 时长（method × route）
      - 在途数（method × route）
      - 请求 / 响应大小（method × route）

    SSE 响应额外记录：
      - 活跃连接数
      - 已发送字节 / 事件数
      - 连接持续时长

    用法：
        app.add_middleware(HttpMetricsMiddleware)
    """

    def __init__(self, app: ASGIApp, registry: Optional[HttpMetricsRegistry] = None) -> None:
        super().__init__(app)
        self.registry = registry or get_default_registry()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if self.registry._noop:
            return await call_next(request)

        method = method_of(request)
        route = normalize_route(request)

        # 1. 在途 +1
        self.registry.requests_in_progress.labels(method=method, route=route).inc()
        start = time.perf_counter()

        # 2. 请求 body 大小（若已有 content-length）
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                self.registry.request_size.labels(method=method, route=route).observe(
                    float(content_length)
                )
            except ValueError:
                pass

        # 3. 调下游；捕获异常
        try:
            response = await call_next(request)
        except Exception:
            # 异常路径：在途 -1，计数 +1（status=500）
            elapsed = time.perf_counter() - start
            self.registry.requests_in_progress.labels(method=method, route=route).dec()
            self.registry.request_duration.labels(method=method, route=route).observe(elapsed)
            self.registry.requests_total.labels(
                method=method, route=route, status="500"
            ).inc()
            raise

        # 4. 正常路径
        elapsed = time.perf_counter() - start
        self.registry.requests_in_progress.labels(method=method, route=route).dec()
        self.registry.request_duration.labels(method=method, route=route).observe(elapsed)
        status = str(response.status_code)
        self.registry.requests_total.labels(
            method=method, route=route, status=status
        ).inc()

        # 5. SSE 包装
        if self._is_sse(response):
            wrapped = self._wrap_sse(response, route)
            # 复制原 response headers 到 wrapped（除 content-length，由 streaming 自动算）
            return wrapped

        # 6. 非 SSE：记录响应大小
        response_size_header = response.headers.get("content-length")
        if response_size_header:
            try:
                self.registry.response_size.labels(method=method, route=route).observe(
                    float(response_size_header)
                )
            except ValueError:
                pass

        return response

    @staticmethod
    def _is_sse(response: Response) -> bool:
        """判断响应是否是 SSE 流。"""
        ctype = response.headers.get("content-type", "")
        return "text/event-stream" in ctype.lower()

    def _wrap_sse(self, response: Response, route: str):
        """包装 SSE 响应，统计活跃连接 + 字节 + 事件 + 时长。"""
        registry = self.registry
        inner = response.body_iterator if hasattr(response, "body_iterator") else None

        async def sse_wrapper():
            registry.sse_active.labels(route=route).inc()
            start = time.perf_counter()
            bytes_sent = 0
            events_sent = 0
            try:
                # response 是 StreamingResponse / 任何带 body_iterator 的响应
                iterator = response.body_iterator
                if iterator is None:
                    return
                async for chunk in iterator:
                    if isinstance(chunk, bytes):
                        bytes_sent += len(chunk)
                        events_sent += chunk.count(b"\n\n")
                    elif isinstance(chunk, str):
                        encoded = chunk.encode("utf-8")
                        bytes_sent += len(encoded)
                        events_sent += chunk.count("\n\n")
                    yield chunk
            finally:
                duration = time.perf_counter() - start
                registry.sse_active.labels(route=route).dec()
                registry.sse_bytes.labels(route=route).inc(bytes_sent)
                registry.sse_duration.labels(route=route).observe(duration)
                # events：粗粒度（按"event: xx\n"行算）
                # 注：上面的 count("\n\n") 已大致对（每个 SSE 帧以 \n\n 结尾）

        return StreamingResponse(
            sse_wrapper(),
            status_code=response.status_code,
            headers={k: v for k, v in response.headers.items() if k.lower() != "content-length"},
            media_type=response.media_type,
        )


# ============================================================
# 便捷函数：导出当前注册表为 prometheus text
# ============================================================


def render_metrics() -> bytes:
    """导出当前默认 registry 的指标。"""
    return get_default_registry().render()
