"""
Planner + Memory 测试

覆盖：
1. Step / Plan 数据模型
2. Plan.critical_path / ready_steps
3. Planner.create_plan_from_intent / from_goal
4. Planner.create_research_plan / code_plan
5. PlanExecutor：并行/串行执行
6. PlanExecutor：失败 + skip_downstream / retry
7. MemoryItem / MemoryStore put / get / query
8. MemoryStore 持久化
9. MemoryStore 过期淘汰
10. AIAgentExtension Planner / Memory API
11. 集成：Planner + Worker 执行
"""

import asyncio
import os
import logging
import json
import tempfile

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

import functools
_print = print
def print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    _print(*args, **kwargs)


# ============================================================
# 1-2. Step / Plan 数据
# ============================================================

def test_plan_model():
    print("\n[1] Plan 数据模型")
    from planner import Plan, Step

    plan = Plan(goal="test")
    s1 = plan.add_step("search", "find X")
    s2 = plan.add_step("analysis", "analyze X", depends_on=[s1.step_id])
    s3 = plan.add_step("write", "write report", depends_on=[s2.step_id])

    assert len(plan.steps) == 3
    assert plan.get_step(s1.step_id).step_id == s1.step_id

    # ready_steps
    ready = plan.ready_steps()
    assert len(ready) == 1
    assert ready[0].step_id == s1.step_id

    # critical_path
    path = plan.critical_path()
    assert len(path) == 3
    print(f"  PASS - plan has {len(plan.steps)} steps, path={len(path)}")


# ============================================================
# 3-4. Planner
# ============================================================

def test_planner_create_from_goal():
    print("\n[2] Planner.create_plan_from_goal")
    from planner import get_planner, reset_planner
    import planner as _pl
    _pl._planner = None
    planner = get_planner()

    plan = planner.create_plan_from_goal("搜索 AI 论文并写报告")
    # 应该有 search + analysis + write
    caps = [s.capability for s in plan.steps]
    assert "search" in caps
    print(f"  PASS - plan: {caps}")


def test_planner_research_plan():
    print("\n[3] Planner.create_research_plan")
    from planner import get_planner

    planner = get_planner()
    plan = planner.create_research_plan("大模型架构")
    assert len(plan.steps) == 3
    # deps 必须正确
    last_step = plan.steps[-1]
    assert last_step.depends_on == [plan.steps[-2].step_id]
    print(f"  PASS - research plan: {[s.capability for s in plan.steps]}")


def test_planner_replan_skip_downstream():
    print("\n[4] Planner.replan skip_downstream")
    from planner import get_planner, StepStatus

    planner = get_planner()
    plan = planner.create_research_plan("X")
    s1, s2, s3 = plan.steps
    plan.steps[1].status = StepStatus.FAILED  # analysis 失败

    planner.replan(plan, s2.step_id, strategy="skip_downstream")
    # failed step 保持 FAILED
    assert plan.get_step(s2.step_id).status == StepStatus.FAILED
    # 下游 s3（write）应该是 SKIPPED
    assert plan.get_step(s3.step_id).status == StepStatus.SKIPPED
    print(f"  PASS - downstream skipped after failure")


def test_planner_replan_retry():
    print("\n[5] Planner.replan retry")
    from planner import get_planner, StepStatus

    planner = get_planner()
    plan = planner.create_research_plan("Y")
    s2 = plan.steps[1]
    s2.status = StepStatus.FAILED

    planner.replan(plan, s2.step_id, strategy="retry")
    assert plan.get_step(s2.step_id).status == StepStatus.PENDING
    print(f"  PASS - retry resets to PENDING")


# ============================================================
# 5-6. PlanExecutor
# ============================================================

async def test_executor_serial_plan():
    print("\n[6] PlanExecutor 串行")
    from planner import PlanExecutor, get_planner

    planner = get_planner()
    plan = planner.create_research_plan("A")

    executed = []

    async def runner(step):
        executed.append(step.step_id)
        return f"result_{step.step_id}"

    executor = PlanExecutor(plan, step_runner=runner)
    await executor.run()

    assert plan.status == "completed"
    # 串行执行，顺序应该是依赖顺序
    assert executed[0] == plan.steps[0].step_id
    print(f"  PASS - {len(executed)} steps executed in order")


async def test_executor_failure_skip():
    print("\n[7] PlanExecutor 失败 + skip_downstream")
    from planner import PlanExecutor, get_planner

    planner = get_planner()
    plan = planner.create_research_plan("B")

    async def runner(step):
        if "analysis" in step.capability:
            raise RuntimeError("simulated failure")
        return f"result_{step.step_id}"

    executor = PlanExecutor(
        plan,
        step_runner=runner,
        on_step_failed=lambda s: "skip_downstream",
    )
    await executor.run()

    # analysis 应该是 FAILED / write 应该是 SKIPPED
    statuses = {s.capability: s.status.value for s in plan.steps}
    assert statuses["search"] == "completed"
    assert statuses["analysis"] == "failed"
    assert statuses["write"] == "skipped"
    print(f"  PASS - statuses: {statuses}")


async def test_executor_with_steps():
    print("\n[8] PlanExecutor 复杂依赖图")
    from planner import Planner, Plan, PlanExecutor, StepStatus

    planner = Planner()
    plan = Plan(goal="fan-out / fan-in")
    a = plan.add_step("search", "A")
    b = plan.add_step("search", "B", depends_on=[a.step_id])
    c = plan.add_step("search", "C", depends_on=[a.step_id])
    d = plan.add_step("analysis", "D", depends_on=[b.step_id, c.step_id])

    parallel_seen = []

    async def runner(step):
        parallel_seen.append(step.step_id)
        await asyncio.sleep(0.01)
        return f"ok_{step.step_id}"

    executor = PlanExecutor(plan, step_runner=runner)
    await executor.run()

    assert plan.status == "completed"
    # d 应该在 b, c 之后
    assert parallel_seen.index(d.step_id) > parallel_seen.index(b.step_id)
    assert parallel_seen.index(d.step_id) > parallel_seen.index(c.step_id)
    print(f"  PASS - fan-out / fan-in executed correctly")


# ============================================================
# 7-9. MemoryStore
# ============================================================

def test_memory_basic():
    print("\n[9] MemoryStore put / get / query")
    from memory import get_memory_store, MemoryType, reset_memory_store
    import memory as _m
    _m._memory_store = None
    store = get_memory_store()

    store.put("user_name", "Alice", memory_type=MemoryType.FACT)
    store.put("language", "zh", memory_type=MemoryType.PREFERENCE)
    store.put("last_search", "AI 论文", memory_type=MemoryType.TASK_HISTORY)

    # get
    item = store.get("user_name")
    assert item is not None
    assert item.value == "Alice"
    assert item.access_count >= 1

    # query
    prefs = store.query(memory_type=MemoryType.PREFERENCE)
    assert len(prefs) == 1
    assert prefs[0].key == "language"
    print(f"  PASS - stored 3 items, query returns by type")


def test_memory_scope_isolation():
    print("\n[10] MemoryStore scope 隔离")
    from memory import get_memory_store, MemoryType

    store = get_memory_store()
    store.put("theme", "dark", scope="user:alice")
    store.put("theme", "light", scope="user:bob")

    alice = store.get("theme", scope="user:alice")
    bob = store.get("theme", scope="user:bob")
    assert alice.value == "dark"
    assert bob.value == "light"
    print(f"  PASS - alice=dark, bob=light")


def test_memory_keyword_search():
    print("\n[11] MemoryStore 关键词搜索")
    from memory import get_memory_store, MemoryType

    store = get_memory_store()
    store.put("k1", "搜索 AI 论文的最新进展", scope="global", tags=["research"])
    store.put("k2", "今天天气真好", scope="global")
    store.put("k3", "Python tutorial", scope="global", tags=["programming"])

    results = store.query(keyword="AI")
    assert any("AI" in str(r.value) for r in results)

    results = store.query(tags=["research"])
    assert len(results) >= 1
    print(f"  PASS - keyword and tag search")


def test_memory_update_existing():
    print("\n[12] MemoryStore 更新已有条目")
    from memory import get_memory_store, MemoryType

    store = get_memory_store()
    item1 = store.put("name", "Alice", scope="user:x", importance=0.3)
    item2 = store.put("name", "Alicia", scope="user:x", importance=0.7)

    assert item1.item_id == item2.item_id, "should update same item"
    current = store.get("name", scope="user:x")
    assert current.value == "Alicia"
    assert current.importance == 0.7
    print(f"  PASS - update preserves item_id")


def test_memory_persistence():
    print("\n[13] MemoryStore 持久化")
    from memory import get_memory_store, MemoryType
    import memory as _m

    _m._memory_store = None
    store = get_memory_store()
    store.put("test_persist", "value_42", scope="global")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name

    try:
        store.save_to_file(path)
        assert os.path.exists(path)

        # 重置 + 加载
        _m._memory_store = None
        store2 = get_memory_store()
        assert store2.get("test_persist") is None
        n = store2.load_from_file(path)
        assert n >= 1
        loaded = store2.get("test_persist")
        assert loaded.value == "value_42"
    finally:
        os.unlink(path)
    print(f"  PASS - saved/loaded from file")


def test_memory_expiry():
    print("\n[14] MemoryStore 过期")
    from memory import get_memory_store, MemoryType

    store = get_memory_store()
    store.put("short_lived", "x", expires_in_seconds=0.05)
    assert store.get("short_lived") is not None
    import time as _t
    _t.sleep(0.1)
    assert store.get("short_lived") is None, "should be expired"
    print(f"  PASS - expiry works")


# ============================================================
# 10. AIAgentExtension API
# ============================================================

async def test_extension_planner_memory_api():
    print("\n[15] AIAgentExtension Planner/Memory API")
    from observability import reset_observability
    reset_observability()
    import observability as _obs
    _obs._observability = None
    from message_bus import get_message_bus
    from multi_agent_integration import AIAgentExtension, MultiAgentMixin
    from planner import reset_planner
    from memory import reset_memory_store
    import planner as _pl
    import memory as _m
    _pl._planner = None
    _m._memory_store = None

    bus = get_message_bus()
    bus.reset()

    class FakeAgent:
        def __init__(self):
            self.model = None
            self.current_session_id = "pm_test"

        async def run(self, prompt):
            return f"[Agent] {prompt}"

    fake = FakeAgent()

    class _TestExt(MultiAgentMixin):
        def __init__(self):
            self.model = None
            self.current_session_id = "pm_test"

        def run(self, prompt):
            return f"[{self.__class__.__name__}] {prompt}"

        async def arun(self, prompt):
            return f"[async] {prompt}"

    ext = _TestExt()
    ext._multi_agent = AIAgentExtension(fake)
    await ext._multi_agent.initialize()
    ext._multi_agent_initialized = True

    # Planner API
    plan = ext.create_plan("搜索 AI 新闻并写报告")
    assert "steps" in plan
    assert len(plan["steps"]) > 0

    # Research / Code plans
    rplan = ext.create_research_plan("X")
    cplan = ext.create_code_plan("Y")
    assert len(rplan["steps"]) == 3
    assert len(cplan["steps"]) == 3

    # Memory API
    r = ext.remember("user_lang", "中文", memory_type="preference", scope="user:test")
    assert r["value"] == "中文"

    found = ext.recall("user_lang", scope="user:test")
    assert found is not None
    assert found["value"] == "中文"

    results = ext.search_memory(keyword="中文")
    assert len(results) >= 1

    # forget
    ok = ext.forget("user_lang", scope="user:test")
    assert ok
    assert ext.recall("user_lang", scope="user:test") is None

    # stats
    stats = ext.get_memory_stats()
    assert "total_items" in stats

    print(f"  PASS - {len(plan['steps'])} plan steps + memory CRUD")


# ============================================================
# 11. 集成：Planner + Worker 执行
# ============================================================

async def test_planner_with_workers():
    print("\n[16] 集成 Planner + Worker 执行")
    from observability import reset_observability
    reset_observability()
    import observability as _obs
    _obs._observability = None
    from message_bus import get_message_bus
    from multi_agent_integration import AIAgentExtension
    from planner import reset_planner, StepStatus
    import planner as _pl
    _pl._planner = None

    bus = get_message_bus()
    bus.reset()

    class FakeAgent:
        def __init__(self):
            self.model = None
            self.current_session_id = "plan_int"

        async def run(self, prompt):
            return f"[Agent] {prompt}"

    fake = FakeAgent()
    ext = AIAgentExtension(fake)
    await ext.initialize()

    # 直接通过 orchestrator.run_plan
    result = await ext.run_plan("搜索 AI 论文")

    assert "plan_id" in result
    assert "steps" in result
    # 默认 worker 有 search capability，应该能执行
    print(f"  PASS - {result.get('status')}, {len(result['steps'])} steps")


# ============================================================
# 主函数
# ============================================================

async def main():
    print("\n" + "#"*60)
    print(" Planner + Memory Tests")
    print("#"*60)

    failures = []

    tests = [
        ("plan_model", test_plan_model, False),
        ("plan_from_goal", test_planner_create_from_goal, False),
        ("research_plan", test_planner_research_plan, False),
        ("replan_skip", test_planner_replan_skip_downstream, False),
        ("replan_retry", test_planner_replan_retry, False),
        ("exec_serial", test_executor_serial_plan, True),
        ("exec_fail_skip", test_executor_failure_skip, True),
        ("exec_fanout", test_executor_with_steps, True),
        ("mem_basic", test_memory_basic, False),
        ("mem_scope", test_memory_scope_isolation, False),
        ("mem_search", test_memory_keyword_search, False),
        ("mem_update", test_memory_update_existing, False),
        ("mem_persist", test_memory_persistence, False),
        ("mem_expiry", test_memory_expiry, False),
        ("ext_api", test_extension_planner_memory_api, True),
        ("integration", test_planner_with_workers, True),
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