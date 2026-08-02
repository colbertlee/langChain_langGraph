"""
多 Agent 编排 ↔ HeadlessAgent 桥接

目标
----
让 HeadlessAgent 能作为 `WorkerAgent`（multi_agent.py 中的执行节点）被
Supervisor/Parallel/Sequential 等编排模式调度，无需任何 Web 依赖。

实现策略
--------
不修改 multi_agent.py，而是利用 ``WorkerAgent(executor=...)`` 的扩展点：

- 传入一个 **async** executor：每次执行 ``executor(description)`` 返回最终文本；
- ``HeadlessWorker`` 是一个工厂类，帮调用方完成 HeadlessAgent → executor 包装。

使用::

    from multi_agent_headless import HeadlessWorker
    from multi_agent import AgentOrchestrator

    orch = AgentOrchestrator()
    orch.add_worker(HeadlessWorker(name="searcher", capabilities=["search"]))
    result = await orch.execute_task("帮我搜索 LangChain 最新动态")

也可独立使用::

    worker = HeadlessWorker(name="general")
    text = await worker.run("你好")

为什么这样设计
~~~~~~~~~~~~~~
- ``WorkerAgent`` 的 executor 默认签名 ``(description: str) -> str``，
  HeadlessAgent 的 stream/run 都是 async；本模块做异步适配 + 文本拼接，
  让多 Agent 编排可以零侵入使用 HeadlessAgent。
- HeadlessWorker 内部持有一个 HeadlessAgent 实例，可共享工具栈 / 记忆 /
  容错链；如果想给每个 worker 配独立 HITL 策略，可注入不同 ``hitl``。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, List, Optional

from headless_agent import HeadlessAgent
from headless_events import HeadlessEvent, HeadlessEventType

logger = logging.getLogger(__name__)


@dataclass
class HeadlessWorker:
    """Headless Agent 作为多 Agent Worker 的轻量包装。

    Attributes:
        name: Worker 显示名。
        capabilities: 能力标签（与 multi_agent 的 capability registry 对齐）。
        headless_agent: 已构造的 HeadlessAgent；None 时懒加载默认。
        max_event_buffer: 每个任务最多缓存多少 HeadlessEvent，便于事后审计。
    """

    name: str = "HeadlessWorker"
    capabilities: Optional[List[str]] = None
    headless_agent: Optional[HeadlessAgent] = None
    max_event_buffer: int = 1000

    def __post_init__(self) -> None:
        self.capabilities = list(self.capabilities or ["general"])
        self._agent: Optional[HeadlessAgent] = self.headless_agent
        # 最近一次执行的 events 缓冲（worker 级别；多 worker 不共享）
        self._last_events: List[HeadlessEvent] = []
        self._agent_id: str = str(uuid.uuid4())

    # -------- 内部 --------

    def _resolve_agent(self) -> HeadlessAgent:
        if self._agent is None:
            self._agent = HeadlessAgent()
        return self._agent

    async def _run_and_collect(self, query: str) -> tuple[str, List[HeadlessEvent]]:
        """跑一次 headless stream，缓存 events 并返回最终文本。

        注意：DONE.final_text 已包含完整回答；不再追加，避免与 TOKEN 累积重复。
        """
        agent = self._resolve_agent()
        final_text_parts: list[str] = []
        buf: list[HeadlessEvent] = []
        done_seen = False
        async for ev in agent.stream(query):
            buf.append(ev)
            if len(buf) > self.max_event_buffer:
                # 超过上限：从头部截断，保留尾部；防止内存爆炸
                buf = buf[-self.max_event_buffer :]
            if ev.type == HeadlessEventType.TOKEN and "delta" in ev.data:
                final_text_parts.append(ev.data["delta"])
            elif ev.type == HeadlessEventType.DONE and not done_seen:
                # 第一个 DONE 才覆盖；后续 DONE（如 resume 残留）忽略
                done_seen = True
                # 若 TOKEN 没产出文本（如纯 tool_call 流），fallback 到 final_text
                if not final_text_parts:
                    final_text_parts.append(ev.data.get("final_text", ""))
        self._last_events = buf
        return "".join(final_text_parts), buf

    # -------- WorkerAgent 适配入口 --------

    async def run(self, query: str) -> str:
        """直接调用（不依赖 multi_agent.py）。"""
        text, _ = await self._run_and_collect(query)
        return text

    def as_executor(self):
        """返回符合 ``WorkerAgent(executor=...)`` 签名的异步 callable。"""
        worker = self

        async def _executor(description: str) -> str:
            return await worker.run(description)

        return _executor

    def to_worker_agent(self, **kwargs: Any):
        """构造一个 multi_agent.WorkerAgent 实例（带本 worker 的 executor）。

        Args:
            **kwargs: 透传给 ``WorkerAgent.__init__``（agent_id/name 等），
                      但 ``executor`` 由本类注入，不要覆盖。
        """
        from multi_agent import WorkerAgent  # 懒导入，避免循环依赖

        if "executor" in kwargs:
            raise ValueError("executor 由 HeadlessWorker 注入，请勿在 kwargs 里传")

        return WorkerAgent(
            name=kwargs.pop("name", self.name),
            capabilities=kwargs.pop("capabilities", self.capabilities),
            executor=self.as_executor(),
            **kwargs,
        )

    # -------- 观测 --------

    def last_events(self) -> List[HeadlessEvent]:
        """返回上一次执行的 events 快照（供调用方审计/调试）。"""
        return list(self._last_events)

    @property
    def agent_id(self) -> str:
        return self._agent_id


__all__ = ["HeadlessWorker"]