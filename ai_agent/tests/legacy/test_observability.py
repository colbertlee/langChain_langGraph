"""
可观测性（Observability）测试

覆盖：
1. Counter / Gauge / Histogram / MetricsRegistry
2. Tracer（span 嵌套、上下文、状态）
3. EventBus（publish/subscribe/list/replay）
4. ObservabilityLayer 集成
5. MessageBus.send 自动埋点
6. AgentOrchestrator.assign_task_via_auction 链路追踪
7. AuctionManager 事件发布
8. ReliabilityLayer + 断路器事件
9. Prometheus 文本输出
"""

import asyncio
import os
import logging

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
# 1. Counter / Gauge / Histogram
# ============================================================

def test_counter():
    print("\n[1] Counter 计数器")
    from observability import Counter

    c = Counter("test_counter", "test")
    c.inc()
    c.inc(5.0, method="GET")
    c.inc(3.0, method="POST")

    assert c.value() == 1.0
    assert c.value(method="GET") == 5.0
    assert c.value(method="POST") == 3.0

    snaps = c.snapshot()
    assert len(snaps) == 3
    print(f"  PASS - Counter values: total={sum(s.value for s in snaps)}")


def test_gauge():
    print("\n[2] Gauge 仪表")
    from observability import Gauge

    g = Gauge("test_gauge", "test")
    g.set(10.0)
    g.inc(5.0)
    g.dec(3.0)
    assert g.value() == 12.0

    g.set(0.0, host="server1")
    g.set(100.0, host="server2")
    assert g.value(host="server1") == 0.0
    assert g.value(host="server2") == 100.0
    print(f"  PASS - Gauge working with labels")


def test_histogram():
    print("\n[3] Histogram 直方图")
    from observability import Histogram

    h = Histogram("test_h", "test", buckets=(0.5, 1.0, 2.0))
    for v in [0.1, 0.3, 0.6, 0.8, 1.5, 2.5]:
        h.observe(v)

    snaps = h.snapshot()
    assert len(snaps) == 1
    assert 0.5 <= snaps[0].value <= 1.5  # avg of [0.1, 0.3, 0.6, 0.8, 1.5, 2.5] = 0.967

    text = h.to_prometheus()
    assert "test_h_bucket" in text
    assert "test_h_count" in text
    assert "test_h_sum" in text
    print(f"  PASS - Histogram with buckets and prometheus output")


def test_registry():
    print("\n[4] MetricsRegistry 注册中心")
    from observability import MetricsRegistry

    reg = MetricsRegistry()
    c = reg.counter("c1", "test")
    g = reg.gauge("g1", "test")
    h = reg.histogram("h1", "test")
    c.inc()
    g.set(42.0)
    h.observe(0.5)

    snap = reg.snapshot()
    assert len(snap["counters"]) == 1
    assert len(snap["gauges"]) == 1
    assert len(snap["histograms"]) == 1

    prom = reg.to_prometheus()
    assert "# HELP" in prom
    assert "# TYPE" in prom
    print(f"  PASS - Registry aggregates metrics")


# ============================================================
# 2. Tracer
# ============================================================

async def test_tracer_basic():
    print("\n[5] Tracer 基础 span")
    from observability import Tracer, Span

    t = Tracer(service_name="test")
    span = t.start_span("root_op", tags={"user_id": "u1"})
    assert span.span_id
    assert span.trace_id

    sub = t.start_span("sub_op", tags={"step": 1})
    assert sub.parent_span_id == span.span_id
    assert sub.trace_id == span.trace_id

    t.finish_span(sub)
    t.finish_span(span)

    spans = t.get_trace(span.trace_id)
    assert len(spans) == 2
    print(f"  PASS - Tracer creates parent/child spans, trace_id consistent")


async def test_tracer_contextmanager():
    print("\n[6] Tracer 同步/异步 上下文管理器")
    from observability import Tracer

    t = Tracer(service_name="test")
    with t.span("ctx_op") as s:
        s.set_tag("k", "v")
        assert s.tags["k"] == "v"

    async with t.async_span("async_op") as s2:
        s2.log("started", value=42)
        assert len(s2.logs) == 1
    print(f"  PASS - Context managers work")


# ============================================================
# 3. EventBus
# ============================================================

def test_event_bus():
    print("\n[7] EventBus 事件流")
    from observability import EventBus, EventType

    bus = EventBus()
    received = []

    def cb(event):
        received.append(event.event_type)

    bus.subscribe(EventType.TASK_CREATED, cb)
    bus.publish("task_created", source="test", payload={"task_id": "t1"})
    bus.publish("auction_started", source="test", payload={"auction_id": "a1"})
    bus.publish("task_created", source="test", payload={"task_id": "t2"})

    assert len(received) == 2
    assert received == ["task_created", "task_created"]

    # 查询
    task_events = bus.list_events(event_type="task_created")
    assert len(task_events) == 2
    print(f"  PASS - EventBus publish/subscribe/list working")


async def test_event_bus_replay():
    print("\n[8] EventBus 事件重放")
    from observability import EventBus

    bus = EventBus()
    bus.publish("e1", source="t1", payload={})
    bus.publish("e2", source="t2", payload={})
    bus.publish("e1", source="t3", payload={})

    received = []

    async def collect(event):
        received.append(event.event_type)

    n = await bus.replay(event_type="e1", callback=collect)
    assert n == 2
    assert received == ["e1", "e1"]
    print(f"  PASS - Replay correctly filtered to {n} events")


# ============================================================
# 4. ObservabilityLayer 集成
# ============================================================

def test_observability_layer():
    print("\n[9] ObservabilityLayer 集成")
    from observability import ObservabilityLayer, get_observability, reset_observability
    reset_observability()

    obs = get_observability()
    assert obs.metrics is not None
    assert obs.tracer is not None
    assert obs.events is not None

    # 测试预定义指标
    obs.msg_sent_total.inc(msg_type="test")
    assert obs.msg_sent_total.value(msg_type="test") == 1.0

    # 测试事件发布
    obs.publish_event("test_event", source="test", payload={"x": 1})
    events = obs.events.list_events(limit=10)
    assert any(e.event_type == "test_event" for e in events)

    # 测试 prom 输出
    prom = obs.to_prometheus()
    assert "agent_msg_sent_total" in prom
    print(f"  PASS - ObservabilityLayer has all 3 components")


# ============================================================
# 5. MessageBus 自动埋点
# ============================================================

async def test_message_bus_observability():
    print("\n[10] MessageBus.send 自动埋点")
    from observability import reset_observability, get_observability
    reset_observability()

    from message_bus import get_message_bus, BaseAgent
    from message_protocol import MessageType, Message

    bus = get_message_bus()
    bus.reset()
    bus.enable_observability()

    # 注册一个 agent
    class ProbeAgent(BaseAgent):
        def __init__(self):
            super().__init__(agent_id="probe", name="Probe")

        async def receive(self, m):
            return None

    ProbeAgent()

    obs = get_observability()
    initial_msg_count = obs.msg_sent_total.value(msg_type="text")

    msg = Message(
        msg_type=MessageType.TEXT,
        sender_id="test",
        receiver_id="probe",
        content="hello observability",
    )
    await bus.send(msg, timeout=1.0)

    after_msg_count = obs.msg_sent_total.value(msg_type="text")
    assert after_msg_count == initial_msg_count + 1, f"expected +1, got {after_msg_count}"

    # 验证 span 已被创建
    spans = obs.tracer.list_spans(limit=10)
    assert any(s.name == "msg.send" for s in spans)

    # 验证事件已被发布
    events = obs.events.list_events(limit=10)
    event_types = {e.event_type for e in events}
    assert "msg_sent" in event_types
    assert "msg_delivered" in event_types
    print(f"  PASS - MessageBus publishes msg_sent/msg_delivered events")


# ============================================================
# 6. Orchestrator 链路追踪
# ============================================================

async def test_orchestrator_trace():
    print("\n[11] AgentOrchestrator.assign_task_via_auction 追踪")
    from observability import reset_observability, get_observability
    reset_observability()

    from message_bus import get_message_bus
    from message_protocol import MessageType, Message
    from multi_agent_integration import AIAgentExtension

    bus = get_message_bus()
    bus.reset()

    class FakeAgent:
        def __init__(self):
            self.model = None
            self.current_session_id = "test_obs"

        async def run(self, prompt):
            return f"[Agent] {prompt}"

    agent = FakeAgent()
    extension = AIAgentExtension(agent)
    await extension.initialize()

    obs = get_observability()

    # 跑一个拍卖
    result = await extension.delegate_with_auction(
        task="search test",
        task_type="search",
        deadline_seconds=2.0,
    )

    assert result.get("winner_id") is not None
    await asyncio.sleep(0.3)

    # 验证 span
    spans = obs.tracer.list_spans(limit=50)
    span_names = [s.name for s in spans]
    assert "msg.send" in span_names, f"missing msg.send in {span_names}"
    assert "orchestrator.assign_via_auction" in span_names, f"missing in {span_names}"

    # 验证事件
    events = obs.events.list_events(limit=100)
    event_types = {e.event_type for e in events}
    assert "auction_started" in event_types, f"missing auction_started in {event_types}"
    assert "auction_awarded" in event_types, f"missing auction_awarded in {event_types}"
    assert "task_started" in event_types, f"missing task_started in {event_types}"

    print(f"  PASS - Orchestrator spans: {span_names}")
    print(f"          events: {sorted(event_types)}")


# ============================================================
# 7. AuctionManager 事件
# ============================================================

async def test_auction_events():
    print("\n[12] AuctionManager 事件发布")
    from observability import reset_observability, get_observability
    reset_observability()

    from negotiation import AuctionManager, AuctionStrategy

    obs = get_observability()
    mgr = AuctionManager()

    # 直接 add bid
    from negotiation import Bid
    auction = mgr.create_auction(
        auctioneer_id="sup",
        task_id="t1",
        task_type="search",
        strategy=AuctionStrategy.SCORED,
    )

    mgr.add_bid(auction.auction_id, Bid(
        auction_id=auction.auction_id,
        bidder_id="alice",
        price=10.0,
    ))
    mgr.add_bid(auction.auction_id, Bid(
        auction_id=auction.auction_id,
        bidder_id="bob",
        price=15.0,
    ))

    mgr.close_auction(auction.auction_id)

    # 验证事件
    event_types = {e.event_type for e in obs.events.list_events(limit=30)}
    assert "auction_bid_received" in event_types
    assert "auction_closed" in event_types
    print(f"  PASS - AuctionManager published {len(event_types)} event types")


# ============================================================
# 8. Reliability 集成
# ============================================================

async def test_reliability_observability():
    print("\n[13] ReliabilityLayer + 可观测性联动")
    from observability import reset_observability, get_observability
    reset_observability()

    from reliability import ReliabilityLayer, RetryPolicy, RetryBackoff, CircuitBreaker

    rl = ReliabilityLayer(
        retry_policy=RetryPolicy(max_attempts=3, initial_delay=0.01, backoff=RetryBackoff.EXP_JITTER),
    )

    obs = get_observability()

    async def fail():
        raise RuntimeError("test failure")

    # 触发重试
    try:
        await rl.call_with_reliability("test_op", fail)
    except RuntimeError:
        pass

    # 验证事件发布
    event_types = {e.event_type for e in obs.events.list_events(limit=30)}
    assert "retry_attempt" in event_types or "retry_exhausted" in event_types

    # 验证断路器状态变化事件
    breaker = rl.get_breaker("test_op")
    # 让 breaker 触发多次失败（threshold 默认=5）
    for _ in range(6):
        try:
            await rl.call_with_reliability("test_op", fail)
        except RuntimeError:
            pass

    # 等待异步事件被 publish（异步事件通过 create_task）
    await asyncio.sleep(0.2)

    event_types2 = {e.event_type for e in obs.events.list_events(limit=100)}
    assert "circuit_opened" in event_types2 or "circuit_half_open" in event_types2 \
        or any("circuit" in t for t in event_types2), \
        f"Expected circuit event in {event_types2}"
    print(f"  PASS - Reliability publishes events: {sorted(event_types2)}")


# ============================================================
# 9. Prometheus 文本输出
# ============================================================

def test_prometheus_output():
    print("\n[14] Prometheus 文本格式输出")
    from observability import MetricsRegistry, reset_observability
    reset_observability()

    from observability import get_observability
    obs = get_observability()

    obs.msg_sent_total.inc(msg_type="text", priority="normal")
    obs.msg_sent_total.inc(msg_type="text", priority="normal")
    obs.msg_sent_total.inc(msg_type="task", priority="high")
    obs.task_duration.observe(0.5, worker="w1")

    text = obs.to_prometheus()
    assert "# HELP" in text
    assert "# TYPE agent_msg_sent_total counter" in text
    assert 'agent_msg_sent_total{msg_type="text",priority="normal"} 2.0' in text
    assert "# TYPE agent_task_duration_seconds histogram" in text
    assert "agent_task_duration_seconds_bucket" in text
    assert "agent_task_duration_seconds_count" in text
    print(f"  PASS - Prometheus text format with {text.count('# TYPE')} metric types")


# ============================================================
# 主函数
# ============================================================

async def main():
    print("\n" + "#"*60)
    print(" Observability Tests")
    print("#"*60)

    failures = []

    tests = [
        ("counter", test_counter, False),
        ("gauge", test_gauge, False),
        ("histogram", test_histogram, False),
        ("registry", test_registry, False),
        ("tracer_basic", test_tracer_basic, True),
        ("tracer_cm", test_tracer_contextmanager, True),
        ("event_bus", test_event_bus, False),
        ("event_replay", test_event_bus_replay, True),
        ("obs_layer", test_observability_layer, False),
        ("bus_observability", test_message_bus_observability, True),
        ("orchestrator_trace", test_orchestrator_trace, True),
        ("auction_events", test_auction_events, True),
        ("reliability_obs", test_reliability_observability, True),
        ("prometheus", test_prometheus_output, False),
    ]

    for name, fn, is_async in tests:
        try:
            if is_async:
                await fn()
            else:
                fn()
        except Exception as e:
            failures.append((name, e))
            print(f"  FAIL: {e}")
            import traceback; traceback.print_exc()

    print("\n" + "#"*60)
    if not failures:
        print(f" All {len(tests)} tests passed")
    else:
        print(f" {len(failures)}/{len(tests)} failed: {[n for n,_ in failures]}")
    print("#"*60)


if __name__ == "__main__":
    asyncio.run(main())
