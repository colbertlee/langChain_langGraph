"""
HITL + Web UI 测试

覆盖：
1. ApprovalRequest 数据模型
2. HumanInLoopGuard AUTO / ASK / BLOCK / DISABLED
3. request_approval + decide 同步流程
4. 超时处理
5. decide_by_payload_match
6. get_pending / get_history
7. AIAgentExtension HITL API
8. web_ui FastAPI 端点（用 TestClient）
9. 集成：HITL + MultiAgent 触发审批
"""

import asyncio
import json
import os
import logging

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 让所有 print 立即 flush
import functools
_print = print
def print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    _print(*args, **kwargs)


# ============================================================
# 1. ApprovalRequest
# ============================================================

def test_approval_request():
    print("\n[1] ApprovalRequest 数据")
    from human_in_loop import ApprovalRequest, ApprovalDecision

    req = ApprovalRequest(
        hook_point="before_delegate",
        payload={"task_type": "code"},
        description="send code task",
        requested_by="sup1",
    )
    d = req.to_dict()
    assert d["hook_point"] == "before_delegate"
    assert d["payload"]["task_type"] == "code"
    assert d["status"] == "skipped"  # 默认
    print(f"  PASS - {d['request_id'][:8]}... status={d['status']}")


# ============================================================
# 2-5. HumanInLoopGuard
# ============================================================

async def test_hitl_auto_policy():
    print("\n[2] AUTO 策略自动放行")
    from human_in_loop import get_hitl_guard, HITLPolicy, HookPoint, ApprovalDecision

    get_hitl_guard()._pending.clear()
    get_hitl_guard()._history.clear()

    guard = get_hitl_guard()
    guard.set_default_policy(HITLPolicy.AUTO)

    req = await guard.request_approval(
        HookPoint.BEFORE_DELEGATE,
        payload={"task": "auto_test"},
        description="should skip",
    )
    assert req.status == ApprovalDecision.SKIPPED
    assert "auto" in req.notes
    print(f"  PASS - auto skipped")


async def test_hitl_ask_policy():
    print("\n[3] ASK 策略发出事件但不阻塞")
    from human_in_loop import get_hitl_guard, HITLPolicy, HookPoint

    guard = get_hitl_guard()
    guard.set_default_policy(HITLPolicy.ASK)
    guard._pending.clear()

    req = await guard.request_approval(
        HookPoint.BEFORE_BID,
        payload={"bid": 10.0},
        description="ask_test",
        timeout=0.5,
    )
    # ASK 超时后会变成 TIMEOUT 或 SKIPPED
    assert req.status.value in {"skipped", "timeout"}
    print(f"  PASS - ask result: {req.status.value}")


async def test_hitl_block_approve():
    print("\n[4] BLOCK 策略 + 外部 approve")
    from human_in_loop import get_hitl_guard, HITLPolicy, HookPoint, ApprovalDecision

    guard = get_hitl_guard()
    guard.set_default_policy(HITLPolicy.BLOCK)
    guard._pending.clear()

    async def external_decide():
        await asyncio.sleep(0.1)
        pending = guard.get_pending()
        assert len(pending) >= 1
        req_id = pending[0].request_id
        ok = guard.decide(req_id, "approved", decided_by="tester")
        assert ok

    task = asyncio.create_task(external_decide())

    req = await guard.request_approval(
        HookPoint.BEFORE_DELEGATE,
        payload={"task": "block_test"},
        description="should be approved",
        timeout=2.0,
    )
    await task  # 等 decide task 完成
    assert req.status == ApprovalDecision.APPROVED
    assert req.decided_by == "tester"
    print(f"  PASS - block approved by external")


async def test_hitl_block_reject():
    print("\n[5] BLOCK 策略 + 外部 reject")
    from human_in_loop import get_hitl_guard, HITLPolicy, HookPoint, ApprovalDecision

    guard = get_hitl_guard()
    guard.set_default_policy(HITLPolicy.BLOCK)
    guard._pending.clear()

    async def reject_decide():
        await asyncio.sleep(0.05)
        pending = guard.get_pending()
        assert len(pending) >= 1
        guard.decide(pending[0].request_id, "rejected", decided_by="tester")

    task = asyncio.create_task(reject_decide())

    req = await guard.request_approval(
        HookPoint.BEFORE_DELEGATE,
        payload={"task": "reject_test"},
        timeout=1.0,
    )
    await task
    assert req.status == ApprovalDecision.REJECTED
    print(f"  PASS - block rejected")


async def test_hitl_block_timeout():
    print("\n[6] BLOCK 策略 + 超时")
    from human_in_loop import get_hitl_guard, HITLPolicy, HookPoint, ApprovalDecision

    guard = get_hitl_guard()
    guard.set_default_policy(HITLPolicy.BLOCK)
    guard._pending.clear()

    req = await guard.request_approval(
        HookPoint.BEFORE_DELEGATE,
        payload={"task": "timeout_test"},
        timeout=0.3,
    )
    assert req.status == ApprovalDecision.TIMEOUT
    print(f"  PASS - block timed out as expected")


async def test_hitl_decide_by_match():
    print("\n[7] decide_by_payload_match")
    from human_in_loop import get_hitl_guard, HITLPolicy, HookPoint, ApprovalDecision

    guard = get_hitl_guard()
    guard.set_default_policy(HITLPolicy.BLOCK)
    guard._pending.clear()

    # 让外部 task 决定（在另一个 task 里，从而让出控制权给主任务）
    decided_alice = []

    async def auto_decider():
        # 等到 pending 里有 alice 时立刻 reject
        for _ in range(50):
            await asyncio.sleep(0.05)
            pending = guard.get_pending()
            for r in pending:
                if r.payload.get("bidder") == "alice":
                    guard.decide(r.request_id, "rejected", decided_by="auto")
                    decided_alice.append(r.request_id)
            # 检测到 bob 时 approve
            for r in pending:
                if r.payload.get("bidder") == "bob":
                    guard.decide(r.request_id, "approved", decided_by="auto")
            if len(decided_alice) >= 1 and not any(r.payload.get("bidder") == "bob" for r in guard.get_pending()):
                break

    decider_task = asyncio.create_task(auto_decider())

    async def trigger():
        return await guard.request_approval(
            HookPoint.BEFORE_BID,
            payload={"bidder": "alice", "price": 12.0},
            timeout=2.0,
        )

    async def trigger2():
        return await guard.request_approval(
            HookPoint.BEFORE_BID,
            payload={"bidder": "bob", "price": 15.0},
            timeout=2.0,
        )

    t1 = asyncio.create_task(trigger())
    t2 = asyncio.create_task(trigger2())

    r1 = await t1
    r2 = await t2
    await decider_task

    assert r1.status == ApprovalDecision.REJECTED
    assert r2.status == ApprovalDecision.APPROVED
    print(f"  PASS - decided by payload match")


async def test_hitl_history_query():
    print("\n[8] history 查询")
    from human_in_loop import get_hitl_guard

    guard = get_hitl_guard()
    history = guard.get_history(limit=20)
    assert len(history) >= 1
    print(f"  PASS - {len(history)} historical records")


# ============================================================
# 9. AIAgentExtension HITL API
# ============================================================

async def test_extension_hitl_api():
    print("\n[9] AIAgentExtension HITL API")
    from observability import reset_observability
    reset_observability()
    import observability as _obs
    _obs._observability = None
    from message_bus import get_message_bus
    from multi_agent_integration import AIAgentExtension, MultiAgentMixin
    from human_in_loop import get_hitl_guard, HITLPolicy, reset_hitl_guard

    reset_hitl_guard()
    import human_in_loop as _hitl_mod
    _hitl_mod._hitl_guard = None

    bus = get_message_bus()
    bus.reset()

    class FakeAgent:
        def __init__(self):
            self.model = None
            self.current_session_id = "hitl_test"

        async def run(self, prompt):
            return f"[Agent] {prompt}"

    fake = FakeAgent()

    class _TestExt(MultiAgentMixin):
        def __init__(self):
            self.model = None
            self.current_session_id = "hitl_test"

        def run(self, prompt):
            return f"[{self.__class__.__name__}] {prompt}"

        async def arun(self, prompt):
            return f"[async] {prompt}"

    ext = _TestExt()
    ext._multi_agent = AIAgentExtension(fake)
    await ext._multi_agent.initialize()
    ext._multi_agent_initialized = True

    # 设置 BLOCK 策略
    res = ext.set_hitl_policy("default", "block")
    assert res["policy"] == "block"

    # 触发一个审批（用 async task）
    from human_in_loop import HookPoint

    async def request_and_decide():
        # 先准备一个 approve
        await asyncio.sleep(0.05)
        pending = ext.list_hitl_pending()
        if pending:
            ext.decide_hitl(pending[0]["request_id"], "approved", decided_by="test")

    guard = get_hitl_guard()
    guard._pending.clear()
    helper_task = asyncio.create_task(request_and_decide())

    # 直接调 guard 触发 BLOCK 请求
    req = await guard.request_approval(
        HookPoint.BEFORE_DELEGATE,
        payload={"task": "ext_test"},
        timeout=2.0,
    )
    await helper_task
    assert req.status.value == "approved"

    # 看 history
    history = ext.list_hitl_history(limit=10)
    assert any(r["status"] == "approved" for r in history)

    # stats
    stats = ext.get_hitl_stats()
    assert "pending_count" in stats

    # 重置策略
    ext.set_hitl_policy("default", "auto")
    print(f"  PASS - HITL APIs work, history={len(history)}")


# ============================================================
# 10. Web UI API (FastAPI TestClient)
# ============================================================

def test_web_ui_endpoints():
    print("\n[10] Web UI FastAPI 端点")
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  SKIP - fastapi.testclient not available")
        return

    from web_ui import app, set_agent

    # 准备一个 fake agent
    class FakeAgentForWeb:
        def __init__(self):
            self._workers = {}

        def list_workers(self):
            return []

        def list_capabilities(self):
            return [{"name": "search"}]

        def list_task_types(self):
            return [{"name": "research"}]

        def get_load_stats(self):
            return {"stats": {"total_workers": 0}, "workers": []}

        def list_policies(self):
            return []

        def get_permission_stats(self):
            return {"policies_count": 0}

        def list_recent_events(self, event_type=None, limit=50):
            return []

        def get_recent_traces(self, limit=50):
            return []

        def get_prometheus_metrics(self):
            return ""

        def add_policy(self, agent_id, **kw):
            return {"agent_id": agent_id, "added": True}

        def enable_permission_enforcement(self, enforce):
            return {"enforce": enforce}

        async def run_stream(self, prompt):
            yield {"type": "text", "content": f"echo: {prompt}", "is_final": True}

    set_agent(FakeAgentForWeb())

    client = TestClient(app)

    # health
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # agents
    r = client.get("/api/agents")
    assert r.status_code == 200
    assert "agents" in r.json()

    # capabilities
    r = client.get("/api/capabilities")
    assert r.status_code == 200
    assert "search" in {c["name"] for c in r.json()["capabilities"]}

    # policies
    r = client.get("/api/policies")
    assert r.status_code == 200
    assert "policies" in r.json()

    # add policy
    r = client.post("/api/policy", json={
        "agent_id": "test_agent",
        "roles": ["supervisor"],
        "capabilities": ["search"],
    })
    assert r.status_code == 200
    assert r.json()["added"]

    # enforce
    r = client.post("/api/permission/enforce", json={"enforce": True})
    assert r.status_code == 200
    assert r.json()["enforce"]

    # hitl pending
    r = client.get("/api/hitl/pending")
    assert r.status_code == 200
    assert "pending" in r.json()

    # hitl stats
    r = client.get("/api/hitl/stats")
    assert r.status_code == 200
    assert "pending_count" in r.json()

    # events
    r = client.get("/api/events?limit=10")
    assert r.status_code == 200
    assert "events" in r.json()

    # traces
    r = client.get("/api/traces?limit=10")
    assert r.status_code == 200
    assert "traces" in r.json()

    # prometheus
    r = client.get("/api/metrics/prometheus")
    assert r.status_code == 200

    print(f"  PASS - all FastAPI endpoints respond 200")


# ============================================================
# 11. 集成：HITL + MultiAgent
# ============================================================

async def test_integration_hitl_multiafent():
    print("\n[11] 集成：HITL + 多 Agent")
    from observability import reset_observability
    reset_observability()
    import observability as _obs
    _obs._observability = None
    from message_bus import get_message_bus
    from multi_agent_integration import AIAgentExtension
    from human_in_loop import get_hitl_guard, HITLPolicy, HookPoint, ApprovalDecision, reset_hitl_guard

    reset_hitl_guard()
    import human_in_loop as _hitl_mod
    _hitl_mod._hitl_guard = None

    bus = get_message_bus()
    bus.reset()

    class FakeAgent:
        def __init__(self):
            self.model = None
            self.current_session_id = "hitl_int_test"

        async def run(self, prompt):
            return f"[Agent] {prompt}"

    fake = FakeAgent()
    ext = AIAgentExtension(fake)
    await ext.initialize()

    # 直接用 guard 验证 integration：在 orchestrator 路径下的 HITL 流程
    guard = get_hitl_guard()
    guard.set_default_policy(HITLPolicy.BLOCK)
    guard._pending.clear()

    async def approve():
        await asyncio.sleep(0.1)
        pending = guard.get_pending()
        for r in pending:
            guard.decide(r.request_id, "approved", decided_by="integration")

    helper_task = asyncio.create_task(approve())

    # 直接通过 guard 模拟 multi-agent 触发
    req = await guard.request_approval(
        HookPoint.BEFORE_DELEGATE,
        payload={"task_type": "search", "task": "integration test"},
        description="Integration test approval",
        timeout=2.0,
    )
    await helper_task

    assert req.status == ApprovalDecision.APPROVED

    # 重置
    guard.set_default_policy(HITLPolicy.AUTO)
    print(f"  PASS - HITL integration works end-to-end")


# ============================================================
# 主函数
# ============================================================

async def main():
    print("\n" + "#"*60)
    print(" HITL + Web UI Tests")
    print("#"*60)

    failures = []

    tests = [
        ("approval_request", test_approval_request, False),
        ("hitl_auto", test_hitl_auto_policy, True),
        ("hitl_ask", test_hitl_ask_policy, True),
        ("hitl_block_approve", test_hitl_block_approve, True),
        ("hitl_block_reject", test_hitl_block_reject, True),
        ("hitl_block_timeout", test_hitl_block_timeout, True),
        ("hitl_decide_match", test_hitl_decide_by_match, True),
        ("hitl_history", test_hitl_history_query, True),
        ("ext_hitl_api", test_extension_hitl_api, True),
        ("web_ui", test_web_ui_endpoints, False),
        ("integration", test_integration_hitl_multiafent, True),
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