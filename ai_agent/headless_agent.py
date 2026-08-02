"""
Headless Agent（MVP）。

目标
----
在 ``AIAgent`` 之上提供一个**零 Web 依赖**的入口，供脚本/CI/嵌入式调用。
行为契约：

1. ``HeadlessAgent`` 组合而非继承 ``AIAgent``，复用其 LLM/tool/middleware/容错栈。
2. 异步生成器 ``stream()`` 按 ``headless_events.HeadlessEventType`` 协议 yield
   7 类事件，且**至少会发出一个 DONE**（成功路径或失败路径）。
3. ``run()`` 是 ``stream()`` 的消费版，拼接 TOKEN.delta 返回最终文本。
4. HITL 默认走 ``AutoHITL``（按 permission.py 规则自动批），可在构造时替换。

不依赖
------
- 不引入 fastapi / uvicorn / websockets / starlette。
- 不修改 ``AIAgent`` / ``permission.py`` / ``streaming.py`` 现有源码。
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional, Protocol

from headless_events import HeadlessEvent, HeadlessEventType

logger = logging.getLogger(__name__)


# ============================================================
# HITL 适配器接口
# ============================================================

@dataclass
class PermissionRequest:
    """权限请求（headless 内部数据类，与 permission.py 解耦）。"""

    tool: str
    args: Dict[str, Any]
    context: Dict[str, Any] | None = None  # 透传 context（intent/session_id 等）


@dataclass
class PermissionResponse:
    """权限决策结果。"""

    approved: bool
    reason: str = ""
    rule: str = ""  # 命中规则（用于可观测性）


class HITLAdapter(Protocol):
    """HITL 适配器接口。MVP 仅暴露 ``decide``。"""

    async def decide(self, request: PermissionRequest) -> PermissionResponse: ...


class AutoHITL:
    """按 permission.py 现有规则自动决策（默认）。

    决策逻辑：
    - 调用 ``permission.get_permission_guard().check_tool()``；
    - 若 tool 命中全局审批清单（``require_approval_tools()``）→ deny；
    - 默认 policy 未指定时，follow "default_allow"（与现有 guard 行为一致）。

    说明：
    - 这里不强制"必须人工"，headless 默认就是要"自动批"，否则会卡住；
    - 调用方若要更严策略，可在构造 ``HeadlessAgent`` 时传入自定义 adapter。
    """

    def __init__(self, deny_tools: Optional[set[str]] = None) -> None:
        # 允许注入额外 deny 集合（不需要走 permission guard）
        self._extra_deny: set[str] = set(deny_tools or ())

    async def decide(self, request: PermissionRequest) -> PermissionResponse:
        # 1. 强 deny：用户在构造时明确指定的工具
        if request.tool in self._extra_deny:
            return PermissionResponse(
                approved=False,
                reason=f"tool '{request.tool}' is in deny-list",
                rule="extra_deny",
            )

        # 2. 查 permission guard（懒导入，避免模块加载时强依赖）
        try:
            from permission import (
                get_permission_guard,
                is_require_approval,
            )
        except Exception as e:  # pragma: no cover - 防御性
            logger.warning(f"[AutoHITL] permission import failed, fallback to allow: {e}")
            return PermissionResponse(approved=True, reason="permission_unavailable", rule="fallback")

        try:
            guard = get_permission_guard()
            decision = guard.check_tool(caller_id="headless", tool_name=request.tool)
        except Exception as e:  # pragma: no cover - 防御性
            logger.warning(f"[AutoHITL] guard.check_tool failed, fallback to allow: {e}")
            return PermissionResponse(approved=True, reason="guard_error", rule="fallback")

        # 3. 高危工具：全局审批清单命中 → 视为 deny
        if is_require_approval(request.tool):
            return PermissionResponse(
                approved=False,
                reason=f"tool '{request.tool}' requires approval",
                rule="require_approval",
            )

        if not decision.granted:
            return PermissionResponse(
                approved=False,
                reason=decision.reason or "denied by policy",
                rule=decision.matched_rule or "denied",
            )

        return PermissionResponse(
            approved=True,
            reason=decision.reason or "allowed",
            rule=decision.matched_rule or "allowed",
        )


class NoHITL:
    """永 deny 的占位实现。Headless 默认不用它，留作显式开关使用。"""

    async def decide(self, request: PermissionRequest) -> PermissionResponse:  # noqa: D401
        return PermissionResponse(approved=False, reason="NoHITL denies all", rule="no_hitl")


# ============================================================
# HeadlessAgent
# ============================================================

class HeadlessAgent:
    """Headless Agent 入口（零 Web 依赖）。

    使用方式::

        agent = HeadlessAgent()                    # 复用默认 AIAgent 单例
        text = await agent.run("你好")
        async for ev in agent.stream("你好"):
            print(ev.type, ev.data)

    参数
    ----
    agent : ``AIAgent`` 实例，None 时懒加载单例。
    hitl  : HITL 适配器；None 时用 ``AutoHITL()``。
    """

    def __init__(
        self,
        agent: Any = None,            # 避免类型注解硬依赖 agent.py（循环）
        hitl: Optional[HITLAdapter] = None,
    ) -> None:
        self._agent = agent
        self._hitl: HITLAdapter = hitl or AutoHITL()

    # -------- 内部：懒加载 AIAgent 单例 --------

    def _resolve_agent(self) -> Any:
        if self._agent is None:
            from agent import AIAgent  # 懒导入
            self._agent = AIAgent()
        return self._agent

    # -------- 公共 API --------

    async def run(self, query: str, **kwargs: Any) -> str:
        """一次性返回最终文本（非流式）。"""
        final_text = ""
        async for ev in self.stream(query, **kwargs):
            if ev.type == HeadlessEventType.TOKEN and "delta" in ev.data:
                final_text += ev.data["delta"]
            elif ev.type == HeadlessEventType.DONE:
                # DONE.data.final_text 是更权威的"最终文本"
                final_text = ev.data.get("final_text", final_text)
        return final_text

    async def stream(self, query: str, **kwargs: Any) -> AsyncIterator[HeadlessEvent]:
        """异步生成器：按 7 类事件协议 yield。

        保证：**至少一个 DONE** 事件会被发出。
        """
        agent = self._resolve_agent()

        # run_stream 是同步生成器（yield str），用 to_thread 避免阻塞事件循环
        try:
            gen = agent.run_stream(query, **kwargs)
            chunks = await asyncio.to_thread(_drain_sync_iter, gen)
        except Exception as e:
            yield HeadlessEvent.error(
                message=str(e),
                traceback=traceback.format_exc(),
            )
            yield HeadlessEvent.done(final_text="")
            return

        final_text_parts: list[str] = []
        had_error = False

        try:
            async for ev in _convert_chunks(chunks, hitl=self._hitl):
                if ev.type == HeadlessEventType.TOKEN:
                    final_text_parts.append(ev.data.get("delta", ""))
                elif ev.type == HeadlessEventType.ERROR:
                    had_error = True
                yield ev
        except Exception as e:  # pragma: no cover - 防御性
            had_error = True
            yield HeadlessEvent.error(
                message=str(e),
                traceback=traceback.format_exc(),
            )

        # 收尾：保证 DONE 一定发出
        yield HeadlessEvent.done(
            final_text="".join(final_text_parts),
            usage={} if not had_error else {"errors": True},
        )


# ============================================================
# 内部：同步生成器 → 异步生成器
# ============================================================

def _drain_sync_iter(gen: Any) -> list[Dict[str, Any]]:
    """把 ``AIAgent.run_stream`` 的同步生成器一次性耗尽成 list[dict]。

    为什么不直接 ``async for``：
    - ``run_stream`` 是同步 ``yield dict``，无法直接 ``__aiter__``；
    - headless 调用方期望异步 API，所以一次性 drain 后再 async yield；
    - 内存压力可控：典型 run 输出 < 几十 KB；超大输出场景留给后续 PR。

    返回 list[dict] 而非 AsyncIterator，是为了在 asyncio 上下文里更容易 mock 测试。
    """
    items: list[Dict[str, Any]] = []
    for item in gen:
        items.append(item)
    return items


async def _convert_chunks(
    chunks: list[Dict[str, Any]],
    hitl: HITLAdapter,
) -> AsyncIterator[HeadlessEvent]:
    """把 ``run_stream`` 产出的 dict 事件流转换成 HeadlessEvent 流。

    ``run_stream`` 事件类型（agent.py 已实现）：
    - ``start``   : 用户输入起点
    - ``chunk``   : 文本增量（data 是 delta 字符串）
    - ``thinking``: CoT 思考段增量
    - ``tool_call``: 工具调用（name + args）
    - ``reset``   : 上游整段重置
    - ``safety``  : 输出被安全策略拦截
    - ``error``   : 流式错误
    - ``complete``: 流式结束（data 是完整 final_text）
    """
    final_text = ""

    for ch in chunks:
        etype = ch.get("type")
        data = ch.get("data", "")
        if data is None:
            data = ""

        if etype == "start":
            # headless 不需要"起点"事件，保持静默
            continue

        if etype == "chunk":
            # 文本增量
            if data:
                final_text += data
                yield HeadlessEvent.token(delta=data)
            continue

        if etype == "thinking":
            # CoT 思考段：MVP 不单独暴露，归并到 token（避免协议扩散）
            if data:
                yield HeadlessEvent.token(delta=data)
            continue

        if etype == "tool_call":
            name = ch.get("name", "") or ""
            args = ch.get("args", {}) or {}
            # MVP：在 tool_call 时走一次 HITL 决策（AutoHITL 默认放行）
            yield HeadlessEvent.tool_call(name=name, args=args)

            req = PermissionRequest(tool=name, args=args)
            yield HeadlessEvent.permission_request(tool=name, args=args)
            try:
                resp = await hitl.decide(req)
            except Exception as e:
                resp = PermissionResponse(
                    approved=False,
                    reason=f"HITL adapter raised: {e}",
                    rule="adapter_error",
                )
            yield HeadlessEvent.permission_response(
                tool=name,
                approved=resp.approved,
                reason=resp.reason,
            )
            # 不真正阻断 tool 执行（Agent 自身容错链会处理），
            # 仅把决策结果作为事件曝光，便于 headless 调用方观测/审计。
            continue

        if etype == "reset":
            # 上游整体重置：清空累积
            final_text = ""
            yield HeadlessEvent(type=HeadlessEventType.ERROR, data={"message": "stream_reset"})
            continue

        if etype == "safety":
            yield HeadlessEvent.error(message=str(data))
            continue

        if etype == "error":
            yield HeadlessEvent.error(message=str(data))
            continue

        if etype == "complete":
            # run_stream 在结束时再 yield 一次 complete(data=full_output)
            # 我们已经通过 chunk 累积了 final_text，这里以 complete.data 为准
            full = data if isinstance(data, str) else ""
            if full:
                final_text = full
            continue

        # 未知事件类型：忽略但记录（便于后续扩展时排查）
        logger.debug(f"[HeadlessAgent] unknown event type from run_stream: {etype!r}")


__all__ = [
    "HeadlessAgent",
    "HITLAdapter",
    "AutoHITL",
    "NoHITL",
    "PermissionRequest",
    "PermissionResponse",
]