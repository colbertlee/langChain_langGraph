"""Headless 持久化 / Checkpoint 单测。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from headless_events import HeadlessEvent, HeadlessEventType
from headless_persistence import (
    EventCheckpoint,
    EventLog,
    compute_resume_offset,
    replay_events,
)


def _ev(type_: str, data: dict, ts: float = 0.0) -> HeadlessEvent:
    return HeadlessEvent(
        type=HeadlessEventType(type_),
        data=data,
        timestamp=ts or 1.0,
    )


@pytest.mark.asyncio
async def test_checkpoint_writes_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    async with EventCheckpoint(path) as ckpt:
        await ckpt.append(_ev("token", {"delta": "A"}))
        await ckpt.append(_ev("token", {"delta": "B"}))
        await ckpt.append(_ev("done", {"final_text": "AB"}))

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    for ln in lines:
        json.loads(ln)  # 必须是合法 JSON
    rec = [json.loads(ln) for ln in lines]
    assert rec[0]["type"] == "token"
    assert rec[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_eventlog_reads_back(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    async with EventCheckpoint(path) as ckpt:
        await ckpt.append(_ev("token", {"delta": "x"}))
        await ckpt.append(_ev("done", {"final_text": "x"}))
    log = EventLog(path)
    events = log.events()
    assert len(events) == 2
    assert events[0].type == HeadlessEventType.TOKEN
    assert events[1].type == HeadlessEventType.DONE


def test_eventlog_summary(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "token", "data": {"delta": "a"}, "timestamp": 1.0}) + "\n")
        f.write(json.dumps({"type": "tool_call", "data": {"name": "t", "args": {}}, "timestamp": 2.0}) + "\n")
        f.write(json.dumps({"type": "done", "data": {"final_text": "a"}, "timestamp": 3.0}) + "\n")
    log = EventLog(path)
    s = log.summary()
    assert s["total"] == 3
    assert s["by_type"]["token"] == 1
    assert s["by_type"]["tool_call"] == 1
    assert s["by_type"]["done"] == 1
    assert s["has_done"] is True


def test_resume_offset_when_done_at_end(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "token", "data": {"delta": "a"}, "timestamp": 1.0}) + "\n")
        f.write(json.dumps({"type": "done", "data": {"final_text": "a"}, "timestamp": 2.0}) + "\n")
    log = EventLog(path)
    # DONE 在末尾 → offset = 总数（无需重跑）
    assert compute_resume_offset(log) == 2


def test_resume_offset_when_done_in_middle(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "token", "data": {"delta": "a"}, "timestamp": 1.0}) + "\n")
        f.write(json.dumps({"type": "done", "data": {"final_text": "a"}, "timestamp": 2.0}) + "\n")
        # 之后还有事件（说明上次没跑完）
        f.write(json.dumps({"type": "token", "data": {"delta": "b"}, "timestamp": 3.0}) + "\n")
    log = EventLog(path)
    # DONE 不是最后一条 → 从 DONE 之后开始
    assert compute_resume_offset(log) == 2


def test_resume_offset_when_no_done(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "token", "data": {"delta": "a"}, "timestamp": 1.0}) + "\n")
    log = EventLog(path)
    # 没有 DONE → 从头开始
    assert compute_resume_offset(log) == 0


def test_resume_offset_when_empty(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    log = EventLog(path)  # 自动创建空文件
    assert compute_resume_offset(log) == 0


@pytest.mark.asyncio
async def test_replay_events_from_offset(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    async with EventCheckpoint(path) as ckpt:
        await ckpt.append(_ev("token", {"delta": "a"}))
        await ckpt.append(_ev("done", {"final_text": "a"}))
        await ckpt.append(_ev("token", {"delta": "b"}))  # 模拟之后的事件
    log = EventLog(path)
    out = []
    async for ev in replay_events(log, offset=2):
        out.append(ev)
    assert len(out) == 1
    assert out[0].data["delta"] == "b"