"""
Headless 持久化（Checkpoint / Resume）

目标
----
把 ``HeadlessAgent.stream()`` 的事件流持久化到本地 JSONL 文件，
以便：

1. **断点续跑**：跑挂后能从上次最后一个 DONE 事件（或可恢复断点）继续；
2. **审计回放**：把所有 headless 任务的输入输出存档，便于 harness / CI 比对；
3. **离线分析**：把 events 转成 DataFrame / 日志查询。

设计
----
- ``EventCheckpoint`` 单文件追加 JSONL，每行一条 HeadlessEvent（JSON 序列化）；
- ``CheckpointWriter`` 把 async 事件流转成 JSONL 写入（异步文件 I/O 走线程池）；
- ``EventLog`` 用于读取 + 回放；
- ``ResumePoint`` 表示"从哪里继续跑"：
  - ``DONE`` 事件之后的 query 视为已完成，无需重跑；
  - 其它情况允许从最早的非 DONE 断点重新执行（保守策略）。

注意
----
- 不假设事件已被保存到分布式存储；MVP 只做本地文件（atomic append + flush）；
- 不支持跨机器共享；分布式场景留给后续 PR。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from headless_events import HeadlessEvent, HeadlessEventType

logger = logging.getLogger(__name__)


# ============================================================
# 序列化辅助
# ============================================================

def _event_to_dict(ev: HeadlessEvent) -> Dict[str, Any]:
    return {
        "type": ev.type.value,
        "data": ev.data,
        "timestamp": ev.timestamp,
    }


def _dict_to_event(d: Dict[str, Any]) -> HeadlessEvent:
    return HeadlessEvent(
        type=HeadlessEventType(d["type"]),
        data=d.get("data", {}) or {},
        timestamp=float(d.get("timestamp", time.time())),
    )


# ============================================================
# Writer
# ============================================================

class EventCheckpoint:
    """把事件流追加写到 JSONL 文件。

    用法::

        ckpt = EventCheckpoint(path)
        async for ev in agent.stream(query):
            await ckpt.append(ev)
        await ckpt.close()
    """

    def __init__(self, path: str | os.PathLike, *, flush_every: int = 1) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._flush_every = max(1, int(flush_every))
        self._fh = open(self._path, "a", encoding="utf-8")
        self._buf = 0
        self._closed = False

    async def append(self, ev: HeadlessEvent) -> None:
        if self._closed:
            raise RuntimeError("EventCheckpoint 已关闭")
        line = json.dumps(_event_to_dict(ev), ensure_ascii=False, default=str)
        # 文件 I/O 走线程池，避免阻塞事件循环
        await asyncio.to_thread(self._write_line, line + "\n")

    def _write_line(self, line: str) -> None:
        self._fh.write(line)
        self._buf += 1
        if self._buf >= self._flush_every:
            self._fh.flush()
            self._buf = 0

    async def close(self) -> None:
        if self._closed:
            return
        await asyncio.to_thread(self._sync_close)
        self._closed = True

    def _sync_close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception as e:  # pragma: no cover
            logger.warning(f"[EventCheckpoint] close error: {e}")

    async def __aenter__(self) -> "EventCheckpoint":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()


# ============================================================
# Reader / Replay
# ============================================================

class EventLog:
    """只读模式读取 JSONL 文件并支持按条件查询。"""

    def __init__(self, path: str | os.PathLike) -> None:
        self._path = Path(path)
        if not self._path.exists():
            self._path.touch()  # 空文件也算合法 log

    def events(self) -> List[HeadlessEvent]:
        """一次性把所有事件读出来（适合小文件 / 离线分析）。"""
        out: list[HeadlessEvent] = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(_dict_to_event(json.loads(line)))
                except json.JSONDecodeError:
                    logger.warning(f"[EventLog] 跳过非法 JSON 行: {line[:80]}")
        return out

    def last_done(self) -> Optional[HeadlessEvent]:
        """返回最后一个 DONE 事件（用于 resume 时确认已完成）。"""
        last: Optional[HeadlessEvent] = None
        for ev in self.events():
            if ev.type == HeadlessEventType.DONE:
                last = ev
        return last

    def summary(self) -> Dict[str, Any]:
        """统计：事件总数、各类型计数、首末时间戳。"""
        events = self.events()
        counts: Dict[str, int] = {}
        first_ts: Optional[float] = None
        last_ts: Optional[float] = None
        for ev in events:
            counts[ev.type.value] = counts.get(ev.type.value, 0) + 1
            if first_ts is None or ev.timestamp < first_ts:
                first_ts = ev.timestamp
            if last_ts is None or ev.timestamp > last_ts:
                last_ts = ev.timestamp
        return {
            "path": str(self._path),
            "total": len(events),
            "by_type": counts,
            "first_ts": first_ts,
            "last_ts": last_ts,
            "has_done": any(ev.type == HeadlessEventType.DONE for ev in events),
        }


# ============================================================
# Resume（断点续跑）
# ============================================================

@dataclass
class ResumePoint:
    """断点续跑描述：哪个 log / 从哪条事件之后开始。

    Attributes:
        log_path: 历史事件 JSONL 路径。
        from_offset: 从第几条事件之后开始（0 = 从头重跑；None = 自动选最早可恢复点）。
        query: 本次任务的输入 query（用于日志归类 / 校验）。
    """

    log_path: str | os.PathLike
    from_offset: Optional[int] = None
    query: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


def compute_resume_offset(log: EventLog) -> int:
    """计算"从哪条事件之后开始重跑"。

    策略（保守）：
    - 若最后一个事件是 DONE：从最后一个 DONE 之后开始（视为已完成）；
    - 否则：从最早的非 DONE 断点开始（让所有事件重新生成，避免漏事件）。

    Returns:
        起始 offset；== len(events) 表示"全部已完成，不需要重跑"。
    """
    events = log.events()
    if not events:
        return 0
    # 找最后一个 DONE 的位置
    last_done_idx = -1
    for i, ev in enumerate(events):
        if ev.type == HeadlessEventType.DONE:
            last_done_idx = i
    if last_done_idx == len(events) - 1:
        # 最后一条就是 DONE，整体完成
        return len(events)
    if last_done_idx >= 0:
        # DONE 之后还有事件 → 之前有 DONE 但又重跑了：从 DONE 之后开始
        return last_done_idx + 1
    # 没有 DONE：从头开始
    return 0


async def replay_events(
    log: EventLog,
    offset: int = 0,
) -> AsyncIterator[HeadlessEvent]:
    """把 log 里的事件从 offset 起重新 yield（异步生成器形式）。"""
    events = log.events()
    for ev in events[offset:]:
        yield ev
        # 让出一次循环，避免长回放阻塞
        await asyncio.sleep(0)


__all__ = [
    "EventCheckpoint",
    "EventLog",
    "ResumePoint",
    "compute_resume_offset",
    "replay_events",
]