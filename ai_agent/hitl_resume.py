"""P1-5 — HITL 拒绝/批准后自动恢复生成

背景
====
v2.2.1 引入的 HITL 拦截：HITLStore 在工具调用前挂起，写 pending，前端 SSE 流 yield
`event: approval_required`。但当时没有恢复机制：
  - 用户拒绝 → store 标记 rejected → LangGraph 状态图不知道 → 流卡死
  - 用户批准 → 同上

本模块提供 resume_after_decision()：从 SqliteSaver 加载 thread state，
注入 ToolMessage（rejected）或实际执行工具（approved），然后重新 invoke agent，
把后续 SSE 流式事件 yield 给前端。

设计要点
========
- 不重写 run_stream；只是包一层 post-decision 续生成逻辑。
- 与原 run_stream 共用同一套 yield 协议（start / thinking / chunk / tool_* / complete）。
- session_id 与 checkpointer 必须仍存活（进程重启不丢 session 状态）。
- approve 路径：调用工具（沙箱 / HITL 同链路），拿到 ToolMessage 后注入 state，继续。
- reject 路径：构造 ToolMessage(content=reason, tool_call_id=...) 注入 state，继续。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 工具：注入 ToolMessage 到 LangGraph state
# ============================================================


async def _resume_graph_after_reject(
    *,
    agent: Any,
    session_id: str,
    tool_call_id: str,
    tool_name: str,
    reject_reason: str,
) -> AsyncGenerator[Dict[str, Any], None]:
    """reject 路径：构造 ToolMessage 注入 state，然后 invoke 续生成。

    Yields:
        dict 事件（hitl_resumed / chunk / complete / error）。
        agent 未初始化时 yield error 后退出。
    """
    if agent is None or agent.checkpointer is None or agent.agent is None:
        logger.warning("hitl_resume: agent/checkpointer not initialized")
        yield {
            "type": "error",
            "data": "agent/checkpointer not initialized",
            "retryable": False,
            "phase": "hitl_resume",
        }
        return

    try:
        from langchain_core.messages import ToolMessage
    except Exception as e:
        logger.error(f"hitl_resume: langchain_core.messages import failed: {e}")
        yield {
            "type": "error",
            "data": f"langchain_core import failed: {e}",
            "retryable": False,
            "phase": "hitl_resume",
        }
        return

    cfg = {"configurable": {"thread_id": session_id}}

    # 1) 构造 ToolMessage（content=拒绝原因），注入到 state
    try:
        tool_msg = ToolMessage(
            content=reject_reason or "Action cancelled by user",
            tool_call_id=tool_call_id,
            name=tool_name,
        )
        # LangGraph 1.x: agent.graph.update_state / agent.agent.update_state
        # 优先调 agent.agent.update_state（标准 LangGraph API）
        update_target = getattr(agent, "agent", None) or agent
        if not hasattr(update_target, "update_state"):
            # 退而求其次：通过 invoke 直接喂消息（部分图不支持 update_state）
            logger.debug("hitl_resume: update_state not available, falling back to invoke")
            state = agent.checkpointer.get(cfg) or {}
        else:
            update_target.update_state(cfg, {"messages": [tool_msg]})

        yield {
            "type": "hitl_resumed",
            "data": "",
            "phase": "rejected",
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
        }
    except Exception as e:
        logger.error(f"hitl_resume: failed to inject ToolMessage: {e}")
        yield {
            "type": "error",
            "data": f"hitl_resume inject ToolMessage failed: {e}",
            "retryable": False,
            "phase": "hitl_resume",
        }
        return

    # 2) 续生成：用 agent.invoke 拿到最终输出（不是 stream，因为 resume 后通常只走 1-2 个 chunk）
    try:
        result = await asyncio.to_thread(agent.agent.invoke, None, cfg)
        messages = result.get("messages", []) if isinstance(result, dict) else []
        # 把新增的消息逐条 yield 成 chunk
        # 用 LangGraph 1.x 的 _read_state 拿到上一次状态以计算增量
        prev_state = agent.checkpointer.get(cfg)
        prev_len = (
            len(prev_state.get("channel_values", {}).get("messages", []))
            if prev_state and "channel_values" in prev_state
            else 0
        )
        # 兜底：直接 yield 全部 messages（前端 chatStore 会去重）
        for msg in messages[prev_len:] if prev_len <= len(messages) else messages:
            try:
                txt = getattr(msg, "content", "")
                if isinstance(txt, list):
                    # OpenAI ChatCompletion 风格（list[dict]）
                    txt = "".join(
                        b.get("text", "") for b in txt if isinstance(b, dict)
                    )
                if not txt:
                    continue
                yield {"type": "chunk", "data": str(txt)}
            except Exception:
                continue
        yield {"type": "complete", "data": ""}
    except Exception as e:
        logger.error(f"hitl_resume: invoke failed: {e}")
        yield {
            "type": "error",
            "data": f"hitl_resume invoke failed: {e}",
            "retryable": True,
            "phase": "hitl_resume",
        }


async def _resume_graph_after_approve(
    *,
    agent: Any,
    session_id: str,
    tool_call_id: str,
    tool_name: str,
    tool_args: Dict[str, Any],
) -> AsyncGenerator[Dict[str, Any], None]:
    """approve 路径：执行工具 + 注入 ToolMessage(result) + 续生成。

    Yields:
        dict 事件（tool_result / tool_end / hitl_resumed / chunk / complete / error）。
    """
    if agent is None or agent.checkpointer is None or agent.agent is None:
        yield {
            "type": "error",
            "data": "agent/checkpointer not initialized",
            "retryable": False,
            "phase": "hitl_resume",
        }
        return

    try:
        from langchain_core.messages import ToolMessage
    except Exception as e:
        logger.error(f"hitl_resume: langchain_core.messages import failed: {e}")
        yield {
            "type": "error",
            "data": f"langchain_core import failed: {e}",
            "retryable": False,
            "phase": "hitl_resume",
        }
        return

    cfg = {"configurable": {"thread_id": session_id}}

    # 1) 找到原始 tool 实例（v2_slim / v21_tools registry）
    tool_instance: Any = None
    try:
        from tools_registry import resolve_tool_by_name
        tool_instance = resolve_tool_by_name(tool_name)
    except Exception as e:
        logger.debug(f"hitl_resume: registry lookup failed: {e}")

    # 2) 执行工具
    start_at = time.time()
    if tool_instance is not None:
        try:
            # StructuredTool 调用形式：invoke(dict)
            if hasattr(tool_instance, "invoke"):
                exec_result = await asyncio.to_thread(
                    tool_instance.invoke, dict(tool_args or {})
                )
            else:
                exec_result = await asyncio.to_thread(tool_instance, **dict(tool_args or {}))
        except Exception as e:
            logger.warning(f"hitl_resume: tool execution failed: {e}")
            exec_result = f"❌ Tool execution failed: {e}"
    else:
        exec_result = (
            f"⚠️ Tool '{tool_name}' not found in registry; "
            f"approving without execution. tool_args={json.dumps(tool_args, ensure_ascii=False)[:200]}"
        )
    duration_ms = (time.time() - start_at) * 1000.0

    # 3) 构造 ToolMessage 并 yield tool_result / tool_end（保持 P0-1 协议一致）
    yield {
        "type": "tool_result",
        "tool_call_id": tool_call_id,
        "name": tool_name,
        "result": str(exec_result),
        "duration_ms": duration_ms,
    }
    yield {
        "type": "tool_end",
        "tool_call_id": tool_call_id,
        "name": tool_name,
        "status": "success",
        "duration_ms": duration_ms,
    }

    # 4) 注入 ToolMessage 到 state 并 invoke 续生成
    try:
        tool_msg = ToolMessage(
            content=str(exec_result),
            tool_call_id=tool_call_id,
            name=tool_name,
        )
        update_target = getattr(agent, "agent", None) or agent
        if hasattr(update_target, "update_state"):
            update_target.update_state(cfg, {"messages": [tool_msg]})
        yield {
            "type": "hitl_resumed",
            "data": "",
            "phase": "approved",
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
        }
    except Exception as e:
        logger.error(f"hitl_resume: failed to inject approved ToolMessage: {e}")
        yield {
            "type": "error",
            "data": f"hitl_resume inject approved ToolMessage failed: {e}",
            "retryable": False,
            "phase": "hitl_resume",
        }
        return

    try:
        result = await asyncio.to_thread(agent.agent.invoke, None, cfg)
        messages = result.get("messages", []) if isinstance(result, dict) else []
        for msg in messages:
            try:
                txt = getattr(msg, "content", "")
                if isinstance(txt, list):
                    txt = "".join(
                        b.get("text", "") for b in txt if isinstance(b, dict)
                    )
                if not txt:
                    continue
                yield {"type": "chunk", "data": str(txt)}
            except Exception:
                continue
        yield {"type": "complete", "data": ""}
    except Exception as e:
        logger.error(f"hitl_resume: invoke after approve failed: {e}")
        yield {
            "type": "error",
            "data": f"hitl_resume invoke failed: {e}",
            "retryable": True,
            "phase": "hitl_resume",
        }


# ============================================================
# 顶层门面：根据 decision 路由
# ============================================================


async def resume_after_decision(
    *,
    request_id: str,
    session_id: str,
    agent: Any,
) -> Optional[AsyncGenerator[Dict[str, Any], None]]:
    """P1-5 — 在用户批准/拒绝后恢复生成。

    Args:
        request_id: HITL pending request id
        session_id: 用于校验
        agent: AIAgent 实例（提供 agent.checkpointer / agent.agent）

    Returns:
        async generator：yield dict 事件（chunk / tool_* / complete / error）；
        若 request_id 不存在 / 不属于该 session / agent 未初始化 → 返回 None。
    """
    try:
        from hitl_langgraph import HITLStore, resolve_after_decision
    except Exception as e:
        logger.error(f"hitl_resume: hitl_langgraph import failed: {e}")
        return None

    decision = resolve_after_decision(request_id, session_id)
    if decision is None:
        logger.warning(f"hitl_resume: request_id {request_id} not found / session mismatch")
        return None
    if decision.get("decision") == "pending":
        logger.info(f"hitl_resume: request {request_id} still pending")
        return None

    dec = decision.get("decision")
    tool_call_id = decision.get("tool_call_id") or ""
    tool_name = decision.get("tool_name") or "tool"

    # 标记 store 已被消费（防止其它 resume 调用重复触发）
    store = HITLStore.instance()
    with store._lock:
        p = store._by_id.get(request_id)
        if p is not None:
            p.status = "consumed"
            try:
                store._db.upsert(p)
            except Exception:
                pass

    if dec == "rejected":
        return _resume_graph_after_reject(
            agent=agent,
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            reject_reason=decision.get("reason") or "Action cancelled by user",
        )
    if dec == "approved":
        return _resume_graph_after_approve(
            agent=agent,
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_args=decision.get("tool_args") or {},
        )
    return None


__all__ = ["resume_after_decision", "_resume_graph_after_reject", "_resume_graph_after_approve"]
