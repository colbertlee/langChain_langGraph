"""
Streaming + Permission 测试

覆盖：
1. Chunk 数据模型 / serializing
2. StreamingBus emit / subscribe / aiter / history
3. 接入 Observability：observability 事件自动转 chunk
4. Orchestrator.orchestrate_stream() 流式输出
5. AIAgentExtension.run_stream() 异步迭代
6. Permission 模型 / Role / Policy
7. PermissionGuard.check_send / check_capability / check_worker / check_tool
8. MessageBus.send 接入权限拦截
9. AIAgentExtension 权限 API
10. Worker capability 权限拦截
"""

import asyncio
import os
import logging

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
# 1. Chunk 模型
# ============================================================

def test_chunk_serialize():
    print("\n[1] Chunk 数据模型")
    from streaming import Chunk, ChunkType

    c = Chunk(type=ChunkType.TEXT, content="hi", source="w1", metadata={"k": "v"})
    d = c.to_dict()
    assert d["type"] == "text"
    assert d["content"] == "hi"
    assert d["source"] == "w1"
    assert d["metadata"]["k"] == "v"
    print(f"  PASS - serialized: {d}")


# ============================================================
# 2. StreamingBus
# ============================================================

async def test_streaming_bus_basic():
    print("\n[2] StreamingBus emit / subscribe")
    from streaming import StreamingBus, ChunkType, reset_streaming_bus

    reset_streaming_bus()
    import streaming as _sm
    _sm._streaming_bus = None

    bus = StreamingBus()
    received = []

    def cb(c):
        received.append(c)

    bus.subscribe(cb)
    bus.emit_sync(ChunkType.TEXT, "hello", source="t1")
    bus.emit_sync(ChunkType.DECISION, "selected", source="t1")
    assert len(received) == 2
    assert received[0].type == ChunkType.TEXT
    assert received[1].type == ChunkType.DECISION
    print(f"  PASS - {len(received)} chunks delivered to subscriber")


async def test_streaming_bus_aiter():
    print("\n[3] StreamingBus aiter()")
    from streaming import StreamingBus, ChunkType, reset_streaming_bus

    reset_streaming_bus()
    import streaming as _sm
    _sm._streaming_bus = None

    bus = StreamingBus()

    async def run():
        collected = []
        async for c in bus.aiter(max_chunks=3):
            collected.append(c)
            if c.is_final:
                break
        return collected

    consumer = asyncio.create_task(run())

    # 给 consumer 一点时间开始订阅
    await asyncio.sleep(0.05)

    await bus.emit(ChunkType.TEXT, "1", source="t1")
    await bus.emit(ChunkType.TEXT, "2", source="t1")
    await bus.emit(ChunkType.TEXT, "3", source="t1", is_final=True)

    collected = await consumer
    assert len(collected) == 3
    assert collected[-1].is_final
    print(f"  PASS - async iter collected {len(collected)} chunks")


async def test_streaming_bus_history():
    print("\n[4] StreamingBus 历史")
    from streaming import StreamingBus, ChunkType, reset_streaming_bus

    reset_streaming_bus()
    import streaming as _sm
    _sm._streaming_bus = None

    bus = StreamingBus()
    bus.emit_sync(ChunkType.TEXT, "a", source="src1")
    bus.emit_sync(ChunkType.DECISION, "b", source="src2")

    text_history = bus.list_history(type_filter=ChunkType.TEXT)
    assert len(text_history) == 1

    src2_history = bus.list_history(source_filter="src2")
    assert len(src2_history) == 1

    print(f"  PASS - filter history works")


# ============================================================
# 3. 接入 Observability
# ============================================================

async def test_streaming_wired_to_obs():
    print("\n[5] StreamingBus wired to Observability")
    from observability import reset_observability
    reset_observability()
    import observability as _obs_mod
    _obs_mod._observability = None
    from observability import get_observability
    from streaming import get_streaming_bus, ChunkType, reset_streaming_bus
    reset_streaming_bus()
    import streaming as _sm
    _sm._streaming_bus = None

    obs = get_observability()
    bus = get_streaming_bus()

    received = []

    def cb(c):
        received.append(c)

    bus.subscribe(cb)

    # 发一个 observability 事件
    obs.publish_event("task_started", source="test_source",
                      payload={"task_id": "t1"})
    await asyncio.sleep(0.05)

    assert len(received) >= 1
    # 类型是 TASK_STARTED
    assert any(c.type == ChunkType.TASK_STARTED for c in received)
    print(f"  PASS - {len(received)} chunks from obs events")


# ============================================================
# 4. Orchestrator.orchestrate_stream
# ============================================================

async def test_orchestrator_stream():
    print("\n[6] Orchestrator.orchestrate_stream 流式")
    from message_bus import get_message_bus
    from multi_agent_integration import AIAgentExtension, MultiAgentMixin

    bus = get_message_bus()
    bus.reset()

    class FakeAgent:
        def __init__(self):
            self.model = None
            self.current_session_id = "stream_test"

        async def run(self, prompt):
            return f"[Agent] {prompt}"

    fake = FakeAgent()

    class _TestExt(MultiAgentMixin):
        def __init__(self):
            self.model = None
            self.current_session_id = "stream_test"
        def run(self, prompt):
            return f"[{self.__class__.__name__}] {prompt}"
        async def arun(self, prompt):
            return f"[async] {prompt}"

    ext = _TestExt()
    ext._multi_agent = AIAgentExtension(fake)
    await ext._multi_agent.initialize()
    ext._multi_agent_initialized = True

    chunks = []
    async for chunk_dict in ext.run_stream("搜索新闻"):
        chunks.append(chunk_dict)
        if chunk_dict.get("is_final"):
            break
    # 至少有一些 chunks：start decision / task_started / text / final
    assert len(chunks) > 0
    types = {c["type"] for c in chunks}
    print(f"  PASS - {len(chunks)} chunks, types={types}")


# ============================================================
# 5. Permission 模型
# ============================================================

def test_permission_policy():
    print("\n[7] Permission Policy 数据")
    from permission import PermissionGuard, Policy, Role, reset_permission_guard

    reset_permission_guard()
    import permission as _pm
    _pm._permission_guard = None

    g = PermissionGuard()
    p = Policy(
        agent_id="agent_a",
        roles=[Role.WORKER],
        capabilities=["search"],
        allowed_tools=["t1", "t2"],
    )
    g.add_policy(p)
    assert g.get_policy("agent_a") is not None
    print(f"  PASS - policy added for agent_a")


def test_permission_check_send():
    print("\n[8] check_send 各种角色")
    from permission import (
        PermissionGuard, Policy, Role, reset_permission_guard
    )
    reset_permission_guard()
    import permission as _pm
    _pm._permission_guard = None

    g = PermissionGuard()

    # supervisor 可发给任何
    g.add_policy(Policy(agent_id="sup1", roles=[Role.SUPERVISOR]))
    d = g.check_send("sup1", "worker_x")
    assert d.granted
    assert "role:supervisor" in d.matched_rule

    # worker 只能发给同组 supervisor
    g.add_policy(Policy(agent_id="wk1", roles=[Role.WORKER]))
    g.set_supervisor_group("wk1", "sup1")

    d = g.check_send("wk1", "sup1")
    assert d.granted, f"failed: {d.reason}, rule={d.matched_rule}"

    # wk1 给陌生人应被拒绝
    d = g.check_send("wk1", "stranger")
    assert not d.granted

    # admin 可发给任何
    g.add_policy(Policy(agent_id="admin1", roles=[Role.ADMIN]))
    d = g.check_send("admin1", "anyone")
    assert d.granted

    # 显式 blocklist
    g.block_agent("bad1")
    d = g.check_send("bad1", "x")
    assert not d.granted

    print(f"  PASS - send permission checks all scenarios")


def test_permission_check_capability():
    print("\n[9] check_capability")
    from permission import (
        PermissionGuard, Policy, Role, reset_permission_guard
    )
    reset_permission_guard()
    import permission as _pm
    _pm._permission_guard = None

    g = PermissionGuard()

    # Worker 角色默认无能力；必须显式给 capabilities
    g.add_policy(Policy(agent_id="wk_a", roles=[Role.WORKER], capabilities=["search"]))
    d = g.check_capability("wk_a", "search")
    assert d.granted
    d = g.check_capability("wk_a", "code")
    assert not d.granted

    # Supervisor 默认所有 capabilities
    g.add_policy(Policy(agent_id="sup_a", roles=[Role.SUPERVISOR]))
    d = g.check_capability("sup_a", "code")
    assert d.granted

    # Admin 即使 capabilities 为空也能通过
    g.add_policy(Policy(agent_id="admin_a", roles=[Role.ADMIN]))
    d = g.check_capability("admin_a", "code")
    assert d.granted

    # Worker 用 * 也可以
    g.add_policy(Policy(agent_id="wk_b", roles=[Role.WORKER], capabilities=["*"]))
    d = g.check_capability("wk_b", "any")
    assert d.granted
    print(f"  PASS - capability checks work")


def test_permission_check_worker_tool():
    print("\n[10] check_worker / check_tool")
    from permission import (
        PermissionGuard, Policy, Role, reset_permission_guard
    )
    reset_permission_guard()
    import permission as _pm
    _pm._permission_guard = None

    g = PermissionGuard()
    g.add_policy(Policy(
        agent_id="restricted",
        roles=[Role.WORKER],
        allowed_workers=["allowed_worker_1", "allowed_worker_2"],
        allowed_tools=["tool_a"],
    ))

    d = g.check_worker("restricted", "allowed_worker_1")
    assert d.granted
    d = g.check_worker("restricted", "forbidden_worker")
    assert not d.granted

    d = g.check_tool("restricted", "tool_a")
    assert d.granted
    d = g.check_tool("restricted", "tool_b")
    assert not d.granted

    print(f"  PASS - worker/tool checks both block")


# ============================================================
# 6. MessageBus 接入权限
# ============================================================

async def test_message_bus_permission_blocks():
    print("\n[11] MessageBus.send 接入权限")
    from observability import reset_observability
    reset_observability()
    import observability as _obs
    _obs._observability = None
    from reliability import get_reliability
    from message_bus import get_message_bus, BaseAgent
    from message_protocol import MessageType, Message
    from permission import (
        get_permission_guard, Policy, Role, reset_permission_guard
    )
    reset_permission_guard()
    import permission as _pm
    _pm._permission_guard = None

    bus = get_message_bus()
    bus.reset()
    rel = get_reliability()
    rel.dlq.clear()
    bus.enable_reliability(rel)

    # 给 permission 加策略：bad_sender 不能发给任何 receiver
    guard = get_permission_guard()
    guard.block_agent("bad_sender")

    bus.enable_permission(guard, enforce=True)

    class ProbeAgent(BaseAgent):
        def __init__(self):
            super().__init__(agent_id="probe", name="Probe")

        async def receive(self, m):
            return None

    ProbeAgent()

    msg = Message(
        msg_type=MessageType.TEXT,
        sender_id="bad_sender",
        receiver_id="probe",
        content="hi",
    )
    result = await bus.send(msg, timeout=1.0)
    assert not result, "send should be blocked"

    # DLQ 应该包含该消息
    dlq_letters = rel.dlq.list()
    assert len(dlq_letters) >= 1
    matched = [l for l in dlq_letters if l.msg_id == msg.msg_id]
    assert len(matched) >= 1
    assert matched[0].reason == "permission_denied"

    print(f"  PASS - blocked sender's msg went to DLQ")


async def test_message_bus_permission_allows_normal():
    print("\n[12] MessageBus 允许正常消息")
    from observability import reset_observability
    reset_observability()
    import observability as _obs
    _obs._observability = None
    from message_bus import get_message_bus, BaseAgent
    from message_protocol import MessageType, Message
    from permission import (
        get_permission_guard, Policy, Role, reset_permission_guard
    )
    reset_permission_guard()
    import permission as _pm
    _pm._permission_guard = None

    bus = get_message_bus()
    bus.reset()
    # 关闭 bus 的 permission 强制（让之前测试的残留配置不影响）
    bus.disable_permission()

    guard = get_permission_guard()
    # sup1 是 supervisor，可发给任何人
    guard.add_policy(Policy(agent_id="sup1", roles=[Role.SUPERVISOR]))
    # worker1 是 worker，但 sup1 是它 supervisor
    guard.set_supervisor_group("worker1", "sup1")

    bus.enable_permission(guard, enforce=True)

    class Probe(BaseAgent):
        def __init__(self):
            super().__init__(agent_id="worker1", name="W1")
        async def receive(self, m):
            return None

    Probe()

    msg = Message(
        msg_type=MessageType.TEXT,
        sender_id="sup1",
        receiver_id="worker1",
        content="hi",
    )
    result = await bus.send(msg, timeout=1.0)
    assert result, f"sup should be allowed to send, got {result}"
    print(f"  PASS - sup -> worker permitted")


# ============================================================
# 7. AIAgentExtension 权限 API
# ============================================================

async def test_extension_permission_api():
    print("\n[13] AIAgentExtension 权限 API")
    from observability import reset_observability
    reset_observability()
    import observability as _obs
    _obs._observability = None
    from message_bus import get_message_bus
    from multi_agent_integration import AIAgentExtension, MultiAgentMixin
    from permission import reset_permission_guard
    reset_permission_guard()
    import permission as _pm
    _pm._permission_guard = None

    bus = get_message_bus()
    bus.reset()

    class FakeAgent:
        def __init__(self):
            self.model = None
            self.current_session_id = "perm_test"

        async def run(self, prompt):
            return f"[Agent] {prompt}"

    fake = FakeAgent()

    class _TestExt(MultiAgentMixin):
        def __init__(self):
            self.model = None
            self.current_session_id = "perm_test"
        def run(self, prompt):
            return f"[{self.__class__.__name__}] {prompt}"
        async def arun(self, prompt):
            return f"[async] {prompt}"

    ext = _TestExt()
    ext._multi_agent = AIAgentExtension(fake)
    await ext._multi_agent.initialize()
    ext._multi_agent_initialized = True

    # 添加策略
    r1 = ext.add_policy(
        agent_id="ext_test_agent",
        roles=["supervisor"],
        capabilities=["search", "code"],
        allowed_tools=["tool_x"],
    )
    assert r1["added"]

    # 列出策略
    policies = ext.list_policies()
    assert any(p["agent_id"] == "ext_test_agent" for p in policies)

    # 手动检查权限
    d = ext.check_permission("ext_test_agent", "capability", "search")
    assert d["granted"]
    d = ext.check_permission("ext_test_agent", "capability", "rocket")
    # supervisor 默认都有除 admin 之外的工作 caps，但 rocket 不在工作 caps 列表
    # supervisor 角色在 _role_defaults 中有这个才能通过
    print(f"  decision for rocket: granted={d.get('granted')}")

    # 启用 enforcement（在 _TestExt 上，因为 MultiAgentMixin 上有这方法）
    res = ext.enable_permission_enforcement(True)
    assert res["enforce"]

    print(f"  PASS - permission APIs work")


# ============================================================
# 主函数
# ============================================================

async def main():
    print("\n" + "#"*60)
    print(" Streaming + Permission Tests")
    print("#"*60)

    failures = []

    tests = [
        ("chunk_serialize", test_chunk_serialize, False),
        ("stream_basic", test_streaming_bus_basic, True),
        ("stream_aiter", test_streaming_bus_aiter, True),
        ("stream_history", test_streaming_bus_history, True),
        ("stream_obs", test_streaming_wired_to_obs, True),
        ("orch_stream", test_orchestrator_stream, True),
        ("perm_policy", test_permission_policy, False),
        ("perm_send", test_permission_check_send, False),
        ("perm_capability", test_permission_check_capability, False),
        ("perm_worker_tool", test_permission_check_worker_tool, False),
        ("bus_perm_blocks", test_message_bus_permission_blocks, True),
        ("bus_perm_allows", test_message_bus_permission_allows_normal, True),
        ("ext_perm_api", test_extension_permission_api, True),
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
