"""
可靠性机制单元测试

覆盖：
1. RetryPolicy 各种退避算法
2. CircuitBreaker 状态转换
3. DeadLetterQueue 添加/列表/清除
4. ReliabilityLayer 整体协作
5. MessageBus.send 重试 + DLQ
6. WorkerAgent.execute_task 重试 + 降级
"""

import asyncio
import os
import logging

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
# 1. RetryPolicy 测试
# ============================================================

def test_retry_policy_backoff():
    print("\n[1] RetryPolicy 退避算法")
    from reliability import RetryPolicy, RetryBackoff

    # FIXED
    p = RetryPolicy(backoff=RetryBackoff.FIXED, initial_delay=0.5, jitter_factor=0)
    assert p.compute_delay(0) == 0.5
    assert p.compute_delay(5) == 0.5

    # LINEAR
    p = RetryPolicy(backoff=RetryBackoff.LINEAR, initial_delay=0.5, jitter_factor=0)
    assert p.compute_delay(0) == 0.5
    assert p.compute_delay(2) == 1.5

    # EXPONENTIAL
    p = RetryPolicy(backoff=RetryBackoff.EXPONENTIAL, initial_delay=0.1, jitter_factor=0)
    assert p.compute_delay(0) == 0.1
    assert p.compute_delay(2) == 0.4  # 0.1 * 4
    assert p.compute_delay(5) == 3.2

    # Max delay cap
    p = RetryPolicy(backoff=RetryBackoff.EXPONENTIAL, initial_delay=1.0, max_delay=2.0, jitter_factor=0)
    assert p.compute_delay(10) == 2.0

    print(f"  PASS - all backoff strategies work")


async def test_retry_policy_execute():
    print("\n[2] RetryPolicy.execute() 自动重试")
    from reliability import RetryPolicy, RetryBackoff

    # 失败的函数
    attempts = [0]

    async def failing():
        attempts[0] += 1
        if attempts[0] < 3:
            raise RuntimeError(f"fail #{attempts[0]}")
        return "ok"

    policy = RetryPolicy(max_attempts=5, backoff=RetryBackoff.EXP_JITTER, initial_delay=0.01)
    result = await policy.attempts().execute(failing)
    assert result == "ok"
    assert attempts[0] == 3

    # 一直失败
    async def always_fail():
        attempts[0] += 1
        raise RuntimeError("always")

    attempts[0] = 0
    policy = RetryPolicy(max_attempts=2, backoff=RetryBackoff.EXP_JITTER, initial_delay=0.01)
    try:
        await policy.attempts().execute(always_fail)
        assert False, "Should have raised"
    except RuntimeError:
        assert attempts[0] == 2

    print(f"  PASS - retries {attempts[0]} times correctly")


# ============================================================
# 2. CircuitBreaker 测试
# ============================================================

async def test_circuit_breaker():
    print("\n[3] CircuitBreaker 状态机")
    from reliability import CircuitBreaker, CircuitState

    cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=0.1)

    # CLOSED -> 允许
    assert cb.state == CircuitState.CLOSED
    assert await cb.allow()

    # 失败 3 次 -> OPEN
    for i in range(3):
        await cb.record_failure(f"err{i}")
    assert cb.state == CircuitState.OPEN

    # OPEN -> 拒绝
    assert not await cb.allow()

    # 等 recovery_timeout -> HALF_OPEN
    await asyncio.sleep(0.15)
    assert await cb.allow()  # 进入 HALF_OPEN
    assert cb.state == CircuitState.HALF_OPEN

    # 探测成功 -> CLOSED
    await cb.record_success()
    assert cb.state == CircuitState.CLOSED

    print(f"  PASS - state transitions work")


async def test_circuit_breaker_probe_failure():
    print("\n[4] CircuitBreaker 探测失败")
    from reliability import CircuitBreaker, CircuitState

    cb = CircuitBreaker(name="test2", failure_threshold=2, recovery_timeout=0.1)
    await cb.record_failure("err1")
    await cb.record_failure("err2")
    assert cb.state == CircuitState.OPEN

    await asyncio.sleep(0.15)
    await cb.allow()  # half-open
    await cb.record_failure("probe_fail")
    assert cb.state == CircuitState.OPEN  # 又回 OPEN

    print(f"  PASS - probe failure correctly resets to OPEN")


# ============================================================
# 3. DeadLetterQueue 测试
# ============================================================

def test_dlq_basic():
    print("\n[5] DeadLetterQueue 基本操作")
    from reliability import DeadLetterQueue

    dlq = DeadLetterQueue(max_size=3)
    dlq.add("m1", {"data": 1}, "reason1")
    dlq.add("m2", {"data": 2}, "reason2")
    dlq.add("m3", {"data": 3}, "reason3")
    dlq.add("m4", {"data": 4}, "reason4")  # 触发 max_size 截断

    assert dlq.size() == 3
    letters = dlq.list()
    assert letters[0].msg_id == "m2"  # m1 被丢弃
    assert letters[-1].msg_id == "m4"

    # clear
    n = dlq.clear()
    assert n == 3
    assert dlq.size() == 0

    print(f"  PASS - DLQ add/clear/size work")


# ============================================================
# 4. ReliabilityLayer 整体测试
# ============================================================

async def test_reliability_layer():
    print("\n[6] ReliabilityLayer 整体协作")
    from reliability import ReliabilityLayer, RetryPolicy, RetryBackoff, get_reliability

    rl = ReliabilityLayer(
        retry_policy=RetryPolicy(max_attempts=3, initial_delay=0.01, backoff=RetryBackoff.EXP_JITTER),
    )

    # 测试成功路径
    async def succeed():
        return "ok"

    result = await rl.call_with_reliability("test_op", succeed)
    assert result == "ok"

    # 测试失败重试后进 DLQ
    async def fail():
        raise RuntimeError("test failure")

    try:
        await rl.call_with_reliability("fail_op", fail)
        assert False, "Should have raised"
    except RuntimeError:
        pass

    # 验证 DLQ
    assert rl.dlq.size() == 1
    letter = rl.dlq.list()[0]
    assert letter.reason == "max_retries_exceeded"
    assert letter.attempts == 3

    print(f"  PASS - reliability layer retries + DLQs correctly")


async def test_reliability_layer_circuit_open():
    print("\n[7] ReliabilityLayer 断路器打开时拒绝请求")
    from reliability import (
        ReliabilityLayer, RetryPolicy, RetryBackoff, CircuitBreaker
    )

    def make_aggressive_breaker(name):
        return CircuitBreaker(name=name, failure_threshold=2, recovery_timeout=1.0)

    rl = ReliabilityLayer(
        retry_policy=RetryPolicy(max_attempts=3, initial_delay=0.01, backoff=RetryBackoff.EXP_JITTER),
        circuit_breaker_factory=make_aggressive_breaker,
    )

    async def fail():
        raise RuntimeError("oops")

    # 触发 2 次失败（断路器阈值）-> OPEN
    for i in range(2):
        try:
            await rl.call_with_reliability("trip_op", fail)
        except RuntimeError:
            pass

    # 第三次直接被断路器拒绝
    breaker = rl.get_breaker("trip_op")
    assert breaker.state.value == "open", f"expected open, got {breaker.state.value}"

    try:
        await rl.call_with_reliability("trip_op", succeed := (lambda: None))
        assert False, "Should have raised due to OPEN circuit"
    except RuntimeError as e:
        assert "OPEN" in str(e)

    print(f"  PASS - circuit breaker correctly rejects when OPEN")


# ============================================================
# 5. MessageBus.send 集成重试
# ============================================================

async def test_message_bus_with_reliability():
    print("\n[8] MessageBus.send 启用可靠性机制")
    from reliability import get_reliability, reset_reliability
    reset_reliability()

    from message_bus import get_message_bus, BaseAgent
    from message_protocol import MessageType, Message

    bus = get_message_bus()
    bus.reset()
    bus.enable_reliability()

    # 创建一个总是抛错的 Agent
    class FailingAgent(BaseAgent):
        def __init__(self):
            super().__init__(agent_id="failing", name="Failing")

        async def receive(self, message):
            raise RuntimeError("boom")

    FailingAgent()

    msg = Message(
        msg_type=MessageType.TEXT,
        sender_id="test",
        receiver_id="failing",
        content="hello",
    )

    sent = await bus.send(msg, timeout=2.0)
    # send 失败但 DLQ 应该已经有该消息
    rl = get_reliability()
    dlq_size = rl.dlq.size()
    assert dlq_size > 0, f"DLQ should have entries, got {dlq_size}"

    print(f"  PASS - MessageBus.send + reliability, dlq size={dlq_size}")


# ============================================================
# 6. WorkerAgent.execute_task 重试 + 降级
# ============================================================

async def test_worker_retry_and_fallback():
    print("\n[9] WorkerAgent.execute_task 重试 + 降级")
    from reliability import reset_reliability, RetryPolicy, RetryBackoff
    reset_reliability()

    from message_bus import get_message_bus, BaseAgent
    from message_protocol import MessageType, Message
    from multi_agent import WorkerAgent

    bus = get_message_bus()
    bus.reset()

    # 任务执行器：前2次失败，第3次成功
    call_count = [0]

    async def flaky_executor(description, data):
        call_count[0] += 1
        if call_count[0] < 3:
            raise RuntimeError(f"flake #{call_count[0]}")
        return f"recovered on attempt {call_count[0]}"

    worker = WorkerAgent(
        agent_id="w1",
        name="FlakyWorker",
        capabilities=["general"],
        executor=flaky_executor,
        retry_policy=RetryPolicy(max_attempts=5, initial_delay=0.01),
    )
    # 启动 worker 的消息循环（让 TASK 消息能被 handler 处理）
    await worker.start()

    msg = Message(
        msg_type=MessageType.TASK,
        sender_id="supervisor",
        receiver_id="w1",
        content="do something",
        payload={"task_data": {"task_id": "t1", "description": "test"}},
    )

    await worker.receive(msg)
    await asyncio.sleep(0.5)

    # 验证：执行器被调用了 3 次，结果被存
    assert call_count[0] == 3, f"expected 3 attempts, got {call_count[0]}"
    result = worker.get_result("t1")
    assert "recovered" in str(result), f"unexpected result: {result}"

    await worker.stop()
    print(f"  PASS - Worker retried 3 times and recovered")


async def test_worker_fallback():
    print("\n[10] WorkerAgent 全部失败 -> 降级 -> DLQ")
    from reliability import reset_reliability, RetryPolicy, RetryBackoff, get_reliability
    reset_reliability()

    from message_bus import get_message_bus
    from message_protocol import MessageType, Message
    from multi_agent import WorkerAgent

    bus = get_message_bus()
    bus.reset()

    async def always_fail(description, data):
        raise RuntimeError("always fails")

    fallback_calls = [0]

    async def my_fallback(task_id, error, attempts):
        fallback_calls[0] += 1
        return {"fallback": True, "task_id": task_id, "msg": "graceful"}

    worker = WorkerAgent(
        agent_id="w2",
        name="BadWorker",
        capabilities=["general"],
        executor=always_fail,
        retry_policy=RetryPolicy(max_attempts=2, initial_delay=0.01),
        on_failure=my_fallback,
    )
    await worker.start()

    msg = Message(
        msg_type=MessageType.TASK,
        sender_id="supervisor",
        receiver_id="w2",
        content="do something",
        payload={"task_data": {"task_id": "t_fail", "description": "test"}},
    )

    await worker.receive(msg)
    await asyncio.sleep(0.5)

    # 验证降级被调用，结果含 fallback 标记
    assert fallback_calls[0] == 1, f"expected 1 fallback call, got {fallback_calls[0]}"
    result = worker.get_result("t_fail")
    assert result is not None
    assert result.get("fallback") is True
    assert result.get("_fallback") is True

    await worker.stop()
    print(f"  PASS - fallback engaged with _fallback=True")


async def test_worker_dlq_no_fallback():
    print("\n[11] WorkerAgent 全部失败 + 无降级 -> DLQ")
    from reliability import reset_reliability, RetryPolicy, get_reliability
    reset_reliability()

    from message_bus import get_message_bus
    from message_protocol import MessageType, Message
    from multi_agent import WorkerAgent

    bus = get_message_bus()
    bus.reset()

    async def always_fail(description, data):
        raise RuntimeError("permafail")

    worker = WorkerAgent(
        agent_id="w3",
        name="DeadWorker",
        capabilities=["general"],
        executor=always_fail,
        retry_policy=RetryPolicy(max_attempts=2, initial_delay=0.01),
        # 不设置 on_failure
    )
    await worker.start()

    msg = Message(
        msg_type=MessageType.TASK,
        sender_id="supervisor",
        receiver_id="w3",
        content="task",
        payload={"task_data": {"task_id": "t_dlq", "description": "test"}},
    )

    await worker.receive(msg)
    await asyncio.sleep(0.5)

    result = worker.get_result("t_dlq")
    assert result is not None, "result should not be None"
    assert result.get("dead_lettered") is True
    assert result.get("attempts") == 2

    # DLQ 应该有这条
    rl = get_reliability()
    assert rl.dlq.size() > 0, f"DLQ should have entries, got {rl.dlq.size()}"
    found = any(
        l.msg_id == "t_dlq" for l in rl.dlq.list()
    )
    assert found, "task_id t_dlq should be in DLQ"

    await worker.stop()
    print(f"  PASS - failed task dead-lettered correctly")


# ============================================================
# 主函数
# ============================================================

async def main():
    print("\n" + "#"*60)
    print(" Reliability Mechanism Tests")
    print("#"*60)

    failures = []

    tests = [
        ("retry_backoff", test_retry_policy_backoff, False),
        ("retry_execute", test_retry_policy_execute, True),
        ("breaker_states", test_circuit_breaker, True),
        ("breaker_probe_fail", test_circuit_breaker_probe_failure, True),
        ("dlq_basic", test_dlq_basic, False),
        ("layer_overall", test_reliability_layer, True),
        ("layer_circuit_open", test_reliability_layer_circuit_open, True),
        ("bus_with_reliability", test_message_bus_with_reliability, True),
        ("worker_retry", test_worker_retry_and_fallback, True),
        ("worker_fallback", test_worker_fallback, True),
        ("worker_dlq", test_worker_dlq_no_fallback, True),
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
