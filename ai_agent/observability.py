"""
可观测性（Observability）模块

提供：
1. Metrics         指标收集（计数/计时/直方图，可输出 Prometheus 文本格式）
2. Tracer          链路追踪（trace_id + 嵌套 span，跨 Agent 传递）
3. EventBus        业务事件流（协商/竞价/任务生命周期，可重放/可订阅）
4. ObservabilityLayer 总控：把三者组合起来

设计：
- 自带内存实现（无第三方依赖），便于单元测试
- 接口对齐 Prometheus + OpenTelemetry 的常见 API，可替换为真实后端
- 三者协作：同一 trace_id 既在 Metrics 标签中，也在 Spans 中，也在 Events 中
"""

import asyncio
import time
import uuid
import logging
import threading
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Iterable
from dataclasses import dataclass, field
from collections import defaultdict
from contextlib import contextmanager, asynccontextmanager

logger = logging.getLogger(__name__)


# ============================================================
# Metrics（指标）
# ============================================================

class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class MetricSnapshot:
    """指标的一个时间点快照"""
    name: str
    type: MetricType
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    help: str = ""
    timestamp: float = field(default_factory=time.time)


class Counter:
    """单调递增计数器"""
    def __init__(self, name: str, help: str = ""):
        self.name = name
        self.help = help
        self._values: Dict[Tuple[Tuple[str, str], ...], float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **labels) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[key] += amount

    def value(self, **labels) -> float:
        key = tuple(sorted(labels.items()))
        return self._values.get(key, 0.0)

    def snapshot(self) -> List[MetricSnapshot]:
        out = []
        for key, val in self._values.items():
            labels = dict(key)
            out.append(MetricSnapshot(self.name, MetricType.COUNTER, val, labels, self.help))
        return out


class Gauge:
    """可增可减的仪表"""
    def __init__(self, name: str, help: str = ""):
        self.name = name
        self.help = help
        self._values: Dict[Tuple[Tuple[str, str], ...], float] = defaultdict(float)
        self._lock = threading.Lock()

    def set(self, value: float, **labels) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[key] = value

    def inc(self, amount: float = 1.0, **labels) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[key] += amount

    def dec(self, amount: float = 1.0, **labels) -> None:
        self.inc(-amount, **labels)

    def value(self, **labels) -> float:
        key = tuple(sorted(labels.items()))
        return self._values.get(key, 0.0)

    def snapshot(self) -> List[MetricSnapshot]:
        out = []
        for key, val in self._values.items():
            labels = dict(key)
            out.append(MetricSnapshot(self.name, MetricType.GAUGE, val, labels, self.help))
        return out


class Histogram:
    """直方图（按桶统计分布）"""
    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(self, name: str, help: str = "", buckets: Optional[Tuple[float, ...]] = None):
        self.name = name
        self.help = help
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._buckets: Dict[Tuple[Tuple[str, str], ...], Dict[float, int]] = defaultdict(
            lambda: {b: 0 for b in self.buckets}
        )
        self._counts: Dict[Tuple[Tuple[str, str], ...], int] = defaultdict(int)
        self._sums: Dict[Tuple[Tuple[str, str], ...], float] = defaultdict(float)
        self._lock = threading.Lock()

    def observe(self, value: float, **labels) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._counts[key] += 1
            self._sums[key] += value
            for b in self.buckets:
                if value <= b:
                    self._buckets[key][b] += 1

    def snapshot(self) -> List[MetricSnapshot]:
        out = []
        for key, count in self._counts.items():
            labels = dict(key)
            avg = self._sums[key] / count if count > 0 else 0.0
            out.append(MetricSnapshot(self.name, MetricType.HISTOGRAM, avg, labels, self.help))
        return out

    def to_prometheus(self) -> str:
        """输出 Prometheus 文本格式"""
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        for key, count in self._counts.items():
            labels_str = ",".join(f'{k}="{v}"' for k, v in sorted(key))
            for b in self.buckets:
                lc = ("," + labels_str) if labels_str else ""
                lb = "," + labels_str.replace('"', '_str"').replace('"', '"') + f',le="{b}"' if labels_str else f'le="{b}"'
                lines.append(f'{self.name}_bucket{{le="{b}"{"," + labels_str if labels_str else ""}}} {self._buckets[key][b]}')
            lines.append(f'{self.name}_count{{{("," + labels_str) if labels_str else ""}}} {count}')
            lines.append(f'{self.name}_sum{{{("," + labels_str) if labels_str else ""}}} {self._sums[key]:.6f}')
        return "\n".join(lines)


class MetricsRegistry:
    """指标注册中心 + 全局访问点"""
    def __init__(self):
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._lock = threading.Lock()

    def counter(self, name: str, help: str = "") -> Counter:
        if name not in self._counters:
            with self._lock:
                if name not in self._counters:
                    self._counters[name] = Counter(name, help)
        return self._counters[name]

    def gauge(self, name: str, help: str = "") -> Gauge:
        if name not in self._gauges:
            with self._lock:
                if name not in self._gauges:
                    self._gauges[name] = Gauge(name, help)
        return self._gauges[name]

    def histogram(self, name: str, help: str = "", buckets: Optional[Tuple[float, ...]] = None) -> Histogram:
        if name not in self._histograms:
            with self._lock:
                if name not in self._histograms:
                    self._histograms[name] = Histogram(name, help, buckets)
        return self._histograms[name]

    def snapshot(self) -> Dict[str, List[MetricSnapshot]]:
        return {
            "counters": [s for c in self._counters.values() for s in c.snapshot()],
            "gauges": [s for g in self._gauges.values() for s in g.snapshot()],
            "histograms": [s for h in self._histograms.values() for s in h.snapshot()],
        }

    def to_prometheus(self) -> str:
        """输出所有指标的 Prometheus 文本格式"""
        lines = []
        for c in self._counters.values():
            for snap in c.snapshot():
                label_str = ",".join(f'{k}="{v}"' for k, v in snap.labels.items())
                lines.append(f"# HELP {c.name} {c.help}")
                lines.append(f"# TYPE {c.name} counter")
                lines.append(f'{c.name}{{{label_str}}} {snap.value}')
        for g in self._gauges.values():
            for snap in g.snapshot():
                label_str = ",".join(f'{k}="{v}"' for k, v in snap.labels.items())
                lines.append(f"# HELP {g.name} {g.help}")
                lines.append(f"# TYPE {g.name} gauge")
                lines.append(f'{g.name}{{{label_str}}} {snap.value}')
        for h in self._histograms.values():
            lines.append(h.to_prometheus())
        return "\n".join(lines)

    def reset(self) -> None:
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()


# ============================================================
# Tracer（链路追踪）
# ============================================================

@dataclass
class Span:
    """一个时间区间 span"""
    span_id: str = field(default_factory=lambda: str(uuid.uuid4())[:16])
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_span_id: Optional[str] = None
    name: str = ""
    service_name: str = "default"
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    tags: Dict[str, Any] = field(default_factory=dict)
    logs: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "ok"  # ok/error/unset
    error: Optional[str] = None

    def finish(self, status: str = "ok", error: Optional[str] = None) -> None:
        if self.end_time is None:
            self.end_time = time.time()
            self.duration_ms = (self.end_time - self.start_time) * 1000.0
        self.status = status
        if error:
            self.error = error

    def set_tag(self, key: str, value: Any) -> None:
        self.tags[key] = value

    def log(self, message: str, **fields: Any) -> None:
        self.logs.append({
            "timestamp": time.time(),
            "message": message,
            **fields,
        })

    def to_dict(self) -> Dict:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "service": self.service_name,
            "start_time": self.start_time,
            "duration_ms": self.duration_ms,
            "tags": self.tags,
            "status": self.status,
            "error": self.error,
        }


class Tracer:
    """追踪器（trace + span）"""

    def __init__(self, service_name: str = "ai_agent"):
        self.service_name = service_name
        self._spans: List[Span] = []
        self._lock = threading.Lock()
        # 用 contextvar 风格：通过线程本地或显式 context 传递
        self._active_spans: List[Span] = []

    def current_span(self) -> Optional[Span]:
        return self._active_spans[-1] if self._active_spans else None

    def current_trace_id(self) -> Optional[str]:
        s = self.current_span()
        return s.trace_id if s else None

    def start_span(self, name: str, parent_span: Optional[Span] = None, tags: Optional[Dict] = None) -> Span:
        """开启一个新 span"""
        parent = parent_span or self.current_span()
        span = Span(
            trace_id=parent.trace_id if parent else str(uuid.uuid4()),
            parent_span_id=parent.span_id if parent else None,
            name=name,
            service_name=self.service_name,
            tags=dict(tags or {}),
        )
        with self._lock:
            self._spans.append(span)
        self._active_spans.append(span)
        return span

    def finish_span(self, span: Span, status: str = "ok", error: Optional[str] = None) -> None:
        """结束一个 span"""
        span.finish(status=status, error=error)
        if self._active_spans and self._active_spans[-1].span_id == span.span_id:
            self._active_spans.pop()
        else:
            # 容错：从中间删除（不应该发生）
            try:
                self._active_spans.remove(span)
            except ValueError:
                pass

    @contextmanager
    def span(self, name: str, tags: Optional[Dict] = None):
        """同步上下文管理器使用 span"""
        s = self.start_span(name, tags=tags)
        try:
            yield s
            self.finish_span(s)
        except Exception as e:
            self.finish_span(s, status="error", error=str(e))
            raise

    @asynccontextmanager
    async def async_span(self, name: str, tags: Optional[Dict] = None):
        """异步上下文管理器使用 span"""
        s = self.start_span(name, tags=tags)
        try:
            yield s
            await asyncio.sleep(0)  # 让出控制权
            self.finish_span(s)
        except Exception as e:
            self.finish_span(s, status="error", error=str(e))
            raise

    def list_spans(self, trace_id: Optional[str] = None, limit: int = 100) -> List[Span]:
        spans = list(reversed(self._spans))  # 最新的在前
        if trace_id:
            spans = [s for s in spans if s.trace_id == trace_id]
        return spans[:limit]

    def get_trace(self, trace_id: str) -> List[Span]:
        """获取一条 trace 链路中的所有 span"""
        spans = [s for s in self._spans if s.trace_id == trace_id]
        return sorted(spans, key=lambda s: s.start_time)

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()
            self._active_spans.clear()


# ============================================================
# EventBus（业务事件流）
# ============================================================

class EventType(str, Enum):
    """预定义事件类型"""
    # 消息层
    MSG_SENT = "msg_sent"
    MSG_DELIVERED = "msg_delivered"
    MSG_DELIVERY_FAILED = "msg_delivery_failed"

    # 任务层
    TASK_CREATED = "task_created"
    TASK_ASSIGNED = "task_assigned"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_FALLBACK = "task_fallback"
    TASK_DLQ = "task_dlq"

    # 协商层
    NEGOTIATION_STARTED = "negotiation_started"
    NEGOTIATION_PROPOSED = "negotiation_proposed"
    NEGOTIATION_COUNTERED = "negotiation_countered"
    NEGOTIATION_ACCEPTED = "negotiation_accepted"
    NEGOTIATION_REJECTED = "negotiation_rejected"
    NEGOTIATION_ENDED = "negotiation_ended"

    # 竞价层
    AUCTION_STARTED = "auction_started"
    AUCTION_BID_RECEIVED = "auction_bid_received"
    AUCTION_CLOSED = "auction_closed"
    AUCTION_AWARDED = "auction_awarded"

    # 可靠性层
    RETRY_ATTEMPT = "retry_attempt"
    RETRY_EXHAUSTED = "retry_exhausted"
    CIRCUIT_OPENED = "circuit_opened"
    CIRCUIT_CLOSED = "circuit_closed"
    CIRCUIT_HALF_OPEN = "circuit_half_open"

    # 系统
    AGENT_STARTED = "agent_started"
    AGENT_STOPPED = "agent_stopped"


@dataclass
class Event:
    """业务事件"""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    timestamp: float = field(default_factory=time.time)
    source: str = "unknown"  # 哪个组件发出的
    trace_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "source": self.source,
            "trace_id": self.trace_id,
            "payload": self.payload,
        }


class EventBus:
    """
    业务事件总线

    角色：
    - 各组件通过 publish() 发事件
    - 订阅者通过 subscribe() 收回调
    - 事件按时间顺序存入环形缓冲，支持 replay
    """

    def __init__(self, max_history: int = 1000):
        self._history: List[Event] = []
        self._max_history = max_history
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def publish(
        self,
        event_type: str,
        source: str,
        trace_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Event:
        """发布一个事件"""
        event = Event(
            event_type=event_type,
            source=source,
            trace_id=trace_id,
            payload=payload or {},
        )
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
        # 触发订阅者（异步）
        for cb in self._subscribers.get(event_type, []) + self._subscribers.get("*", []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.create_task(cb(event))
                else:
                    cb(event)
            except Exception as e:
                logger.warning(f"Event subscriber error: {e}")
        return event

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """订阅某个事件类型（用 '*' 订阅所有事件）"""
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        if callback in self._subscribers.get(event_type, []):
            self._subscribers[event_type].remove(callback)

    def list_events(
        self,
        event_type: Optional[str] = None,
        trace_id: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
    ) -> List[Event]:
        events = list(self._history)
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if trace_id:
            events = [e for e in events if e.trace_id == trace_id]
        if source:
            events = [e for e in events if e.source == source]
        return list(reversed(events))[:limit]

    async def replay(self, event_type: Optional[str] = None, callback: Optional[Callable] = None) -> int:
        """重放历史事件（按时间顺序，可按类型过滤）"""
        events = self.list_events(event_type=event_type, limit=len(self._history))
        events.reverse()  # 时序正向
        for event in events:
            if callback:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        callback(event)
                except Exception as e:
                    logger.warning(f"Replay callback error: {e}")
        return len(events)

    def clear(self) -> None:
        with self._lock:
            self._history.clear()


# ============================================================
# ObservabilityLayer（总控）
# ============================================================

class ObservabilityLayer:
    """
    可观测性层（总控）

    把 Metrics / Tracer / EventBus 三者组合起来，
    并暴露：
    - 装饰器 / 上下文管理器用于埋点
    - 创建新 trace / span
    - 把事件+指标+trace 关联（同一 trace_id 同时出现在三个地方）
    """

    def __init__(
        self,
        service_name: str = "ai_agent",
        metrics: Optional[MetricsRegistry] = None,
        tracer: Optional[Tracer] = None,
        event_bus: Optional[EventBus] = None,
    ):
        self.service_name = service_name
        self.metrics = metrics or MetricsRegistry()
        self.tracer = tracer or Tracer(service_name=service_name)
        self.events = event_bus or EventBus()

        # 预设的常用指标
        self.msg_sent_total = self.metrics.counter(
            "agent_msg_sent_total", "Total messages sent"
        )
        self.msg_delivered_total = self.metrics.counter(
            "agent_msg_delivered_total", "Total messages delivered"
        )
        self.msg_failed_total = self.metrics.counter(
            "agent_msg_failed_total", "Total failed deliveries"
        )
        self.task_total = self.metrics.counter(
            "agent_tasks_total", "Total tasks by type and status"
        )
        self.task_duration = self.metrics.histogram(
            "agent_task_duration_seconds", "Task execution duration"
        )
        self.auction_bids = self.metrics.counter(
            "agent_auction_bids_total", "Total bids received in auctions"
        )
        self.auctions_total = self.metrics.counter(
            "agent_auctions_total", "Total auctions"
        )
        self.negotiations_total = self.metrics.counter(
            "agent_negotiations_total", "Total negotiations"
        )
        self.retries_total = self.metrics.counter(
            "agent_retries_total", "Total retries by operation"
        )
        self.circuit_state = self.metrics.gauge(
            "agent_circuit_state", "Circuit breaker state (0=closed, 1=half_open, 2=open)"
        )

    def new_trace(self, name: str, tags: Optional[Dict] = None) -> Span:
        """开启一个新的根 span（新 trace）"""
        return self.tracer.start_span(name, tags=tags)

    def finish_trace(self, span: Span, status: str = "ok", error: Optional[str] = None) -> None:
        self.tracer.finish_span(span, status=status, error=error)

    @contextmanager
    def trace_span(self, name: str, tags: Optional[Dict] = None):
        """同步 span 上下文"""
        with self.tracer.span(name, tags=tags) as s:
            yield s

    @asynccontextmanager
    async def async_trace_span(self, name: str, tags: Optional[Dict] = None):
        async with self.tracer.async_span(name, tags=tags) as s:
            yield s

    def publish_event(
        self,
        event_type: str,
        source: str,
        trace_id: Optional[str] = None,
        payload: Optional[Dict] = None,
    ) -> Event:
        return self.events.publish(event_type, source, trace_id, payload)

    def get_stats(self) -> Dict[str, Any]:
        """获取所有可观测性的当前快照"""
        return {
            "metrics_snapshot": self.metrics.snapshot(),
            "trace_count": len(self.tracer._spans),
            "active_spans": len(self.tracer._active_spans),
            "event_count": len(self.events._history),
        }

    def to_prometheus(self) -> str:
        return self.metrics.to_prometheus()


# ============================================================
# 全局单例 + 工具
# ============================================================

_observability: Optional[ObservabilityLayer] = None


def get_observability() -> ObservabilityLayer:
    """获取全局可观测性单例"""
    global _observability
    if _observability is None:
        _observability = ObservabilityLayer()
    return _observability


def reset_observability() -> None:
    """重置全局单例（测试用）"""
    global _observability
    _observability = None


# ============================================================
# 便捷集成函数
# ============================================================

def trace_message(message, span_name: str = None) -> Span:
    """为一条消息开启一个 span（用 msg_id 做 span_name 或自定义）"""
    obs = get_observability()
    name = span_name or f"{message.msg_type}"
    tags = {
        "msg_id": message.msg_id,
        "msg_type": str(message.msg_type),
        "sender_id": message.sender_id,
        "receiver_id": message.receiver_id,
    }
    return obs.tracer.start_span(name, tags=tags)


def trace_async_call(coro, span_name: str, tags: Optional[Dict] = None):
    """
    异步跟踪装饰器

    用法：
        @trace_async_call_helper("send_msg")
        async def send_msg(...):
            ...
    """
    obs = get_observability()

    async def wrapped(*args, **kwargs):
        span = obs.tracer.start_span(span_name, tags=tags or {})
        try:
            result = await coro(*args, **kwargs)
            obs.tracer.finish_span(span)
            return result
        except Exception as e:
            obs.tracer.finish_span(span, status="error", error=str(e))
            raise

    return wrapped
