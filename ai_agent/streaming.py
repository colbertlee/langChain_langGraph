"""
多 Agent 流式输出（Streaming Bus）

设计：
- 与 MessageBus 并行，专门把"业务事件"翻译为"前端可消费的 chunk"
- 接入 Observability 模块的 EventBus，自动继承事件流
- 提供 sync（list-style）/ async（async iterator）/ callback 三种消费方式
- 多 Agent 编排器在 orchestrator.* 路径都发出 chunk

Chunk 类型：
    text           普通文本块（来自 LLM 或 Agent）
    task_started   任务分发
    task_progress  任务进行中
    task_complete  任务完成（含结果）
    task_error     任务失败
    auction_*      竞价事件
    negotiation_*  协商事件
    tool_call      工具调用
    decision       编排决策
    done           流结束
"""

import asyncio
import time
import uuid
import logging
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ============================================================
# Chunk 模型
# ============================================================

class ChunkType(str, Enum):
    """块类型"""
    TEXT = "text"
    TASK_STARTED = "task_started"
    TASK_PROGRESS = "task_progress"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_FALLBACK = "task_fallback"
    TOOL_CALL = "tool_call"
    DECISION = "decision"
    AUCTION_STARTED = "auction_started"
    AUCTION_BID = "auction_bid"
    AUCTION_CLOSED = "auction_closed"
    AUCTION_AWARDED = "auction_awarded"
    NEGOTIATION_STARTED = "negotiation_started"
    NEGOTIATION_ROUND = "negotiation_round"
    NEGOTIATION_RESULT = "negotiation_result"
    ERROR = "error"
    DONE = "done"


@dataclass
class Chunk:
    """流式块（前端的一个 token/事件）"""
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: ChunkType = ChunkType.TEXT
    content: str = ""
    source: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    is_final: bool = False

    def to_dict(self) -> Dict:
        return {
            "chunk_id": self.chunk_id,
            "type": self.type.value if isinstance(self.type, ChunkType) else str(self.type),
            "content": self.content,
            "source": self.source,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "is_final": self.is_final,
        }


# ============================================================
# 事件 → Chunk 转换器
# ============================================================

# 把业务事件映射到 chunk 类型
EVENT_TO_CHUNK = {
    "task_started": ChunkType.TASK_STARTED,
    "task_completed": ChunkType.TASK_COMPLETED,
    "task_failed": ChunkType.TASK_FAILED,
    "task_fallback": ChunkType.TASK_FALLBACK,
    "tool_call": ChunkType.TOOL_CALL,
    "worker_selected": ChunkType.DECISION,
    "auction_started": ChunkType.AUCTION_STARTED,
    "auction_bid_received": ChunkType.AUCTION_BID,
    "auction_closed": ChunkType.AUCTION_CLOSED,
    "auction_awarded": ChunkType.AUCTION_AWARDED,
    "negotiation_started": ChunkType.NEGOTIATION_STARTED,
    "negotiation_proposed": ChunkType.NEGOTIATION_ROUND,
    "negotiation_countered": ChunkType.NEGOTIATION_ROUND,
    "negotiation_accepted": ChunkType.NEGOTIATION_RESULT,
    "negotiation_rejected": ChunkType.NEGOTIATION_RESULT,
    "negotiation_ended": ChunkType.NEGOTIATION_RESULT,
}


# ============================================================
# StreamingBus
# ============================================================

class StreamingBus:
    """
    多 Agent 流式总线

    角色：
    - 把 Emitter 发出的 Chunk 分发给所有订阅者
    - 异步流式消费（async iter）
    - 同步回调消费（callback）
    - 历史缓冲（用于 finalize / replay）
    """

    def __init__(self, max_history: int = 1000):
        self._max_history = max_history
        self._history: List[Chunk] = []
        self._subscribers: List[Callable[[Chunk], None]] = []
        self._lock = asyncio.Lock()

    # ----------------- 发射 -----------------

    async def emit(
        self,
        type: ChunkType,
        content: str = "",
        source: str = "",
        metadata: Optional[Dict] = None,
        is_final: bool = False,
    ) -> Chunk:
        """发射一个 chunk 给所有订阅者"""
        chunk = Chunk(
            type=type,
            content=content,
            source=source,
            metadata=metadata or {},
            is_final=is_final,
        )
        await self._dispatch(chunk)
        return chunk

    def emit_sync(
        self,
        type: ChunkType,
        content: str = "",
        source: str = "",
        metadata: Optional[Dict] = None,
        is_final: bool = False,
    ) -> Chunk:
        """同步版本（用于非 async 上下文）"""
        chunk = Chunk(
            type=type,
            content=content,
            source=source,
            metadata=metadata or {},
            is_final=is_final,
        )
        # 同步分发（订阅者也用同步）
        for sub in self._subscribers:
            try:
                if asyncio.iscoroutinefunction(sub):
                    # 把它放到 event loop 中跑
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            loop.create_task(sub(chunk))
                    except RuntimeError:
                        pass
                else:
                    sub(chunk)
            except Exception as e:
                logger.warning(f"Stream subscriber error: {e}")
        # 加入历史
        self._history.append(chunk)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        return chunk

    async def _dispatch(self, chunk: Chunk) -> None:
        async with self._lock:
            self._history.append(chunk)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            subs = list(self._subscribers)
        for sub in subs:
            try:
                if asyncio.iscoroutinefunction(sub):
                    await sub(chunk)
                else:
                    sub(chunk)
            except Exception as e:
                logger.warning(f"Stream subscriber error: {e}")

    # ----------------- 订阅 -----------------

    def subscribe(self, callback: Callable[[Chunk], None]) -> None:
        """注册回调消费 chunk"""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    # ----------------- 流式消费 -----------------

    async def aiter(
        self,
        max_chunks: Optional[int] = None,
        filter_type: Optional[ChunkType] = None,
        filter_source: Optional[str] = None,
    ) -> AsyncIterator[Chunk]:
        """
        异步流式消费。

        简化实现：因为 emit 已经分发，新 chunk 会被订阅者收到。
        这里用一个 asyncio.Queue 给到一个临时消费者。
        """
        q: asyncio.Queue = asyncio.Queue()

        def cb(chunk: Chunk):
            if filter_type and chunk.type != filter_type:
                return
            if filter_source and chunk.source != filter_source:
                return
            try:
                q.put_nowait(chunk)
            except asyncio.QueueFull:
                pass

        self.subscribe(cb)
        try:
            count = 0
            while True:
                if max_chunks and count >= max_chunks:
                    break
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=None)
                except asyncio.CancelledError:
                    break
                if chunk.is_final:
                    yield chunk
                    break
                yield chunk
                count += 1
                # 安全：避免在没有 final 时无限阻塞
                if max_chunks is None:
                    # 默认无限循环直到 is_final / 外部取消
                    pass
        finally:
            self.unsubscribe(cb)

    # ----------------- 历史 -----------------

    def list_history(
        self,
        type_filter: Optional[ChunkType] = None,
        source_filter: Optional[str] = None,
        limit: int = 200,
    ) -> List[Chunk]:
        out = list(self._history)
        if type_filter:
            out = [c for c in out if c.type == type_filter]
        if source_filter:
            out = [c for c in out if c.source == source_filter]
        return out[-limit:]

    def clear(self) -> None:
        self._history.clear()


# ============================================================
# 默认总线 + 接入 Observability
# ============================================================

_streaming_bus: Optional[StreamingBus] = None


def get_streaming_bus() -> StreamingBus:
    """获取全局 StreamingBus 单例"""
    global _streaming_bus
    if _streaming_bus is None:
        _streaming_bus = StreamingBus()
        _wire_to_observability(_streaming_bus)
    return _streaming_bus


def reset_streaming_bus() -> None:
    """重置全局（测试用）"""
    global _streaming_bus
    _streaming_bus = None


def _wire_to_observability(bus: StreamingBus) -> None:
    """把 StreamingBus 接入 Observability：observability 事件自动转 chunk"""
    try:
        from observability import get_observability
        obs = get_observability()

        def event_to_chunk(event):
            ctype = EVENT_TO_CHUNK.get(event.event_type, ChunkType.DECISION)
            content = f"[{event.source}] {event.event_type}"
            metadata = dict(event.payload)
            metadata["event_type"] = event.event_type
            metadata["trace_id"] = event.trace_id
            metadata["source"] = event.source
            bus.emit_sync(
                type=ctype,
                content=content,
                source=event.source,
                metadata=metadata,
            )

        obs.events.subscribe("*", event_to_chunk)
        logger.info("StreamingBus wired to Observability EventBus")
    except Exception as e:
        logger.warning(f"Failed to wire streaming bus: {e}")


# ============================================================
# 工具函数：从 emitter 生成器模式构造流
# ============================================================

async def stream_from_emitter(
    bus: StreamingBus,
    emitter_func: Callable,
    *args,
    max_chunks: int = 200,
    **kwargs,
) -> AsyncIterator[Chunk]:
    """
    让一个 async callable（返回 chunk 流）在自己的 bus 上运行，
    然后外部消费者能从这个生成器拿到所有 chunk。

    用法：
        async def my_emitter():
            await bus.emit(...)
            await bus.emit(...)
        async for chunk in stream_from_emitter(bus, my_emitter):
            process(chunk)
    """
    q: asyncio.Queue = asyncio.Queue()
    received = []

    def cb(c):
        try:
            q.put_nowait(c)
        except asyncio.QueueFull:
            pass

    bus.subscribe(cb)
    try:
        task = asyncio.create_task(emitter_func(*args, **kwargs))
        try:
            count = 0
            while True:
                if max_chunks and count >= max_chunks:
                    break
                try:
                    chunk = await q.get()
                except asyncio.CancelledError:
                    break
                if chunk.is_final:
                    yield chunk
                    break
                yield chunk
                count += 1
            await task
        except asyncio.CancelledError:
            task.cancel()
            raise
    finally:
        bus.unsubscribe(cb)
