"""HeadlessWorker 多 Agent 接入单测。"""
from __future__ import annotations

from typing import Any, Iterator, List

import pytest

from headless_events import HeadlessEvent, HeadlessEventType
from multi_agent_headless import HeadlessWorker


class _FakeHeadless:
    """HeadlessAgent 替身：stream() 返回固定事件序列。"""

    def __init__(self, chunks: List[dict]) -> None:
        self._chunks = chunks
        self.calls: list[str] = []

    async def stream(self, query: str, **_: Any) -> Iterator[HeadlessEvent]:
        self.calls.append(query)
        for c in self._chunks:
            yield HeadlessEvent(
                type=HeadlessEventType(c["type"]),
                data=c.get("data", {}) or {},
            )

    async def run(self, query: str) -> str:
        # Fake 不实现 run；HeadlessWorker 走 stream 路径，这里仅占位。
        raise NotImplementedError("HeadlessWorker uses stream(); run() is a passthrough")


def _make_worker(chunks: List[dict]) -> HeadlessWorker:
    """用 fake HeadlessAgent 构造 HeadlessWorker。"""
    fake = _FakeHeadless(chunks)
    w = HeadlessWorker(name="w", capabilities=["general"])
    # 注入 fake
    w._agent = fake  # type: ignore[attr-defined]
    return w


@pytest.mark.asyncio
async def test_headless_worker_run_returns_final_text() -> None:
    chunks = [
        {"type": "token", "data": {"delta": "A"}},
        {"type": "token", "data": {"delta": "B"}},
        {"type": "done", "data": {"final_text": "AB"}},
    ]
    w = _make_worker(chunks)
    text = await w.run("hi")
    assert text == "AB"


@pytest.mark.asyncio
async def test_headless_worker_buffers_last_events() -> None:
    chunks = [
        {"type": "token", "data": {"delta": "x"}},
        {"type": "tool_call", "data": {"name": "t", "args": {}}},
        {"type": "done", "data": {"final_text": "x"}},
    ]
    w = _make_worker(chunks)
    await w.run("q")
    events = w.last_events()
    assert len(events) == 3
    assert events[-1].type == HeadlessEventType.DONE


def test_as_executor_returns_async_callable() -> None:
    chunks = [{"type": "done", "data": {"final_text": "OK"}}]
    w = _make_worker(chunks)
    exec_ = w.as_executor()
    # 是 async callable
    import inspect
    assert inspect.iscoroutinefunction(exec_)
    # 跑一下
    import asyncio
    assert asyncio.run(exec_("anything")) == "OK"


def test_to_worker_agent_constructs_real_worker() -> None:
    """HeadlessWorker.to_worker_agent() 能产出 multi_agent.WorkerAgent 实例。"""
    chunks = [{"type": "done", "data": {"final_text": "OK"}}]
    w = _make_worker(chunks)
    worker = w.to_worker_agent()
    # 来自 multi_agent.WorkerAgent
    from multi_agent import WorkerAgent
    assert isinstance(worker, WorkerAgent)
    # executor 已注入
    assert worker._executor is not None  # type: ignore[attr-defined]


def test_to_worker_agent_rejects_executor_override() -> None:
    """不应让调用方覆盖 executor（防注入 bug）。"""
    w = _make_worker([])
    with pytest.raises(ValueError):
        w.to_worker_agent(executor=lambda x: x)