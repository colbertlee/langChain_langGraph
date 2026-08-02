"""
SSE Adapter (Server-Sent Events)

把 ``HeadlessAgent.stream()`` 的事件流转成 SSE 格式字符串，供 Web / 任何
HTTP SSE 端点消费。

特点
----
- 零框架依赖：纯 Python + 标准库，不绑 fastapi/starlette/uvicorn；
- 输出符合 SSE 规范：``data: <json>\\n\\n``，每事件以空行分隔；
- 支持可选 ``event: <name>`` 字段（前端 ``EventSource`` 可按事件名监听）；
- 支持可注入的 ``Heartbeat``（长连接保活）；
- ``to_sse_lines()`` 是同步函数，便于与任何异步 server 配合（async server
  一般 ``async for chunk in async_iter``，包一层即可）。

SSE 协议要点
~~~~~~~~~~~~
::

    event: token
    data: {"type":"token","data":{"delta":"你"},"timestamp":1700000000.0}

    event: done
    data: {"type":"done","data":{"final_text":"你好","usage":{}},"timestamp":...}

设计
----
每个事件产出：

- 一行 ``event: <event_name>``（事件名 = HeadlessEventType.value）
- 一行 ``data: <json>``（json 序列化整个 HeadlessEvent）
- 一个空行（事件分隔）

心跳
----
调用方可通过 ``heartbeat_interval_s`` 注入一个 ``AsyncIterator[bytes]``，
adapter 在主事件静默超过该秒数时插入 ``: keepalive\\n\\n``（注释行，
前端 EventSource 不会触发 onmessage）。
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from headless_events import HeadlessEvent


# ============================================================
# 事件名映射：HeadlessEventType → SSE event 字段
# ============================================================

def _event_name(ev: HeadlessEvent) -> str:
    """HeadlessEventType.value 已经稳定，直接用作 SSE event 名。"""
    return ev.type.value


def _serialize_event(ev: HeadlessEvent) -> str:
    """单条 HeadlessEvent → SSE 文本块（含尾部空行）。"""
    payload = {
        "type": ev.type.value,
        "data": ev.data,
        "timestamp": ev.timestamp,
    }
    body = json.dumps(payload, ensure_ascii=False, default=str)
    # SSE 规范：多行 data 必须每行前缀 "data: "；json 单行所以一次即可
    return f"event: {_event_name(ev)}\ndata: {body}\n\n"


# ============================================================
# 公共 API
# ============================================================

@dataclass
class SSEConfig:
    """SSE Adapter 配置。

    Attributes:
        heartbeat_interval_s: > 0 时启用心跳；<= 0 禁用。
        heartbeat_payload: 心跳帧内容（注释行，以 ``:`` 开头）。
        include_done: 是否在末尾追加 ``event: done`` 显式结束（默认 True）。
    """

    heartbeat_interval_s: float = 0.0
    heartbeat_payload: str = ": keepalive\n\n"
    include_done: bool = True


async def to_sse_lines(
    events: AsyncIterator[HeadlessEvent],
    config: Optional[SSEConfig] = None,
) -> AsyncIterator[str]:
    """把 headless 事件流转成 SSE 字符串流。

    Args:
        events: ``HeadlessAgent.stream()`` 产出的事件流。
        config: SSE 配置；None 时使用默认（无心跳、包含 done）。

    Yields:
        SSE 文本块（含每个事件的完整帧）。

    说明：
    - 如果 events 自身已经包含 DONE 事件，adapter 不会再注入重复 done。
    - 心跳仅在事件静默期生效；DONE 后立刻停止 yield。
    """
    cfg = config or SSEConfig()
    saw_done = False
    last_event_at = asyncio.get_event_loop().time()

    if cfg.heartbeat_interval_s <= 0:
        # 无心跳：直接逐个 yield
        async for ev in events:
            yield _serialize_event(ev)
            if ev.type.value == "done":
                return
        return

    # 启用心跳：使用"事件 vs 心跳 timeout"竞争
    # 关键技巧：用 ``asyncio.wait_for`` 给事件加超时 = 心跳间隔；
    # 超时则发心跳；否则发事件帧。
    ev_iter = events.__aiter__()
    pending_ev: Optional[asyncio.Task] = None
    try:
        while True:
            if pending_ev is None:
                pending_ev = asyncio.ensure_future(ev_iter.__anext__())

            try:
                ev = await asyncio.wait_for(
                    asyncio.shield(pending_ev),
                    timeout=cfg.heartbeat_interval_s,
                )
            except asyncio.TimeoutError:
                # 静默期：发心跳
                yield cfg.heartbeat_payload
                # ticker 继续等下一次超时（pending_ev 仍在跑，不取消）
                continue
            except StopAsyncIteration:
                return

            last_event_at = asyncio.get_event_loop().time()
            yield _serialize_event(ev)
            if ev.type.value == "done":
                saw_done = True
                return
            pending_ev = None  # 让下一轮重新拉
    finally:
        if pending_ev is not None and not pending_ev.done():
            pending_ev.cancel()


async def to_sse_bytes(
    events: AsyncIterator[HeadlessEvent],
    config: Optional[SSEConfig] = None,
) -> AsyncIterator[bytes]:
    """``to_sse_lines`` 的 bytes 版本，方便直接写 socket/Response。"""
    async for line in to_sse_lines(events, config):
        yield line.encode("utf-8")


__all__ = ["SSEConfig", "to_sse_lines", "to_sse_bytes"]