"""evals/runners/headless_runner.py 单测。"""
from __future__ import annotations

from typing import Any, Iterator, List

import pytest

# 触发 runner 注册（装饰器 @EvalRegistry.register 只在 import 时执行）
import evals.runners.headless_runner  # noqa: F401


# ---------- fake HeadlessAgent ----------

class _FakeHeadlessAgent:
    def __init__(self, chunks: List[dict], *, run_return: str = "FAKE") -> None:
        self._chunks = chunks
        self._run_return = run_return
        self.stream_calls: list[str] = []
        self.run_calls: list[str] = []

    async def stream(self, query: str, **_: Any) -> Iterator[Any]:
        from headless_events import HeadlessEvent, HeadlessEventType
        self.stream_calls.append(query)
        for c in self._chunks:
            yield HeadlessEvent(
                type=HeadlessEventType(c["type"]),
                data=c.get("data", {}) or {},
            )

    async def run(self, query: str) -> str:
        from headless_agent import AutoHITL, HeadlessAgent
        self.run_calls.append(query)
        return self._run_return


def _patch_headless_agent(monkeypatch, fake: _FakeHeadlessAgent) -> None:
    """monkeypatch headless_runner._build_headless_agent 整体替换。"""
    import evals.runners.headless_runner as headless_runner
    monkeypatch.setattr(
        headless_runner,
        "_build_headless_agent",
        lambda spec=None: fake,
    )


# ---------- tests ----------

def test_registry_includes_headless_categories() -> None:
    """import headless_runner 后 EvalRegistry 应包含 headless / headless_sync。"""
    from evals.registry import EvalRegistry

    cats = EvalRegistry.all_categories()
    assert "headless" in cats
    assert "headless_sync" in cats


@pytest.mark.asyncio
async def test_run_headless_basic_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [
        {"type": "token", "data": {"delta": "Hi"}},
        {"type": "token", "data": {"delta": " there"}},
        {"type": "done", "data": {"final_text": "Hi there"}},
    ]
    fake = _FakeHeadlessAgent(chunks)
    _patch_headless_agent(monkeypatch, fake)

    from evals.runners.headless_runner import run_headless

    case = {
        "name": "case_001",
        "input": "hello",
        "expect_substring": "Hi",
        "expect_event_types": ["token", "done"],
    }
    result = await run_headless(case)
    assert result.passed is True
    assert result.category == "headless"
    assert "final_len=8" in result.detail


@pytest.mark.asyncio
async def test_run_headless_missing_event_type(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [
        {"type": "token", "data": {"delta": "Hi"}},
        {"type": "done", "data": {"final_text": "Hi"}},
    ]
    fake = _FakeHeadlessAgent(chunks)
    _patch_headless_agent(monkeypatch, fake)

    from evals.runners.headless_runner import run_headless

    case = {
        "name": "case_002",
        "input": "x",
        "expect_event_types": ["token", "done", "tool_call"],
    }
    result = await run_headless(case)
    assert result.passed is False
    assert "tool_call" in result.detail


@pytest.mark.asyncio
async def test_run_headless_no_done_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [{"type": "token", "data": {"delta": "Hi"}}]
    fake = _FakeHeadlessAgent(chunks)
    _patch_headless_agent(monkeypatch, fake)

    from evals.runners.headless_runner import run_headless

    case = {"name": "case_003", "input": "x"}
    result = await run_headless(case)
    assert result.passed is False
    assert "DONE" in result.detail


@pytest.mark.asyncio
async def test_run_headless_min_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [
        {"type": "token", "data": {"delta": "Hi"}},  # 2 chars
        {"type": "done", "data": {"final_text": "Hi"}},
    ]
    fake = _FakeHeadlessAgent(chunks)
    _patch_headless_agent(monkeypatch, fake)

    from evals.runners.headless_runner import run_headless

    case = {"name": "case_004", "input": "x", "expect_min_tokens": 10}
    result = await run_headless(case)
    assert result.passed is False
    assert "token total 2 < expected min 10" in result.detail


def test_run_headless_sync_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeHeadlessAgent([], run_return="Hello world")
    _patch_headless_agent(monkeypatch, fake)

    from evals.runners.headless_runner import run_headless_sync

    case = {
        "name": "sync_001",
        "input": "x",
        "expect_substring": "Hello",
    }
    result = run_headless_sync(case)
    assert result.passed is True
    assert result.category == "headless_sync"


def test_run_headless_sync_missing_substring(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeHeadlessAgent([], run_return="Hello world")
    _patch_headless_agent(monkeypatch, fake)

    from evals.runners.headless_runner import run_headless_sync

    case = {
        "name": "sync_002",
        "input": "x",
        "expect_substring": "Goodbye",
    }
    result = run_headless_sync(case)
    assert result.passed is False
