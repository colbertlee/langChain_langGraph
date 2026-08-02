"""Headless SSE Adapter 单测。"""
from __future__ import annotations

import json

import pytest

from headless_events import HeadlessEvent, HeadlessEventType
from headless_sse import SSEConfig, to_sse_lines


async def _events():
    yield HeadlessEvent.token("你")
    yield HeadlessEvent.token("好")
    yield HeadlessEvent.tool_call("t", {"a": 1})
    yield HeadlessEvent.done("你好")


@pytest.mark.asyncio
async def test_sse_basic_format() -> None:
    lines: list[str] = []
    async for chunk in to_sse_lines(_events()):
        lines.append(chunk)
    # 4 个事件 → 4 个 SSE 块；每个块含 event/data + 空行
    assert len(lines) == 4
    for chunk in lines:
        assert chunk.endswith("\n\n"), f"SSE 块必须以空行结尾: {chunk!r}"
        assert chunk.startswith("event: "), f"SSE 块必须以 event: 开头: {chunk!r}"
        assert "\ndata: " in chunk


@pytest.mark.asyncio
async def test_sse_event_name_matches_type() -> None:
    chunks: list[str] = []
    async for chunk in to_sse_lines(_events()):
        chunks.append(chunk)
    # 第一块：event: token
    assert "event: token\n" in chunks[0]
    assert "event: tool_call\n" in chunks[2]
    assert "event: done\n" in chunks[3]


@pytest.mark.asyncio
async def test_sse_data_is_valid_json() -> None:
    chunks: list[str] = []
    async for chunk in to_sse_lines(_events()):
        chunks.append(chunk)
    # 取第二块 (token "好") 的 data 行
    data_line = chunks[1].splitlines()[1]
    assert data_line.startswith("data: ")
    body = json.loads(data_line[len("data: ") :])
    assert body["type"] == "token"
    assert body["data"]["delta"] == "好"
    assert isinstance(body["timestamp"], float)


@pytest.mark.asyncio
async def test_sse_heartbeat_emitted_on_idle() -> None:
    """心跳：事件静默期插入 keepalive 注释帧。"""

    async def _slow_events():
        yield HeadlessEvent.token("a")
        # 长时间静默（模拟模型思考）
        await __import__("asyncio").sleep(0.2)
        yield HeadlessEvent.done("a")

    cfg = SSEConfig(heartbeat_interval_s=0.05)
    chunks: list[str] = []
    async for chunk in to_sse_lines(_slow_events(), cfg):
        chunks.append(chunk)
    # 至少有 1 个心跳（": keepalive"）和 2 个事件帧
    assert any(chunk.startswith(": keepalive") for chunk in chunks), chunks
    assert any("event: token" in chunk for chunk in chunks)
    assert any("event: done" in chunk for chunk in chunks)