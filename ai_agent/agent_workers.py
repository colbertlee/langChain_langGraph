"""
agent_workers.py — Milestone 2.2.3 LangGraph Multi-Agent Supervisor 模式（Worker 子图）

设计目标
  - 三个 Worker（research_worker / code_worker / rag_worker）各自是一个 LangGraph 子图；
    每个子图只挂载自己需要的工具集（最小授权原则）。
  - Worker 节点执行完毕后必须"返回控制权给 Supervisor"——通过子图输出 ``{"next": "supervisor"}``
    或由主图 add_edge("research_worker", "supervisor") 强制收敛。
  - code_worker 必须保留 HITL 包裹（python_interpreter 在 v21_tools.TOOL_REGISTRY 里
    已标记 ``requires_approval=True``，会被 agent.py 的 _HITLWrappedTool 自动包装）。

子图设计
  - 每个 Worker 内部都是简单结构：ToolNode → AIMessage 整理节点 → 返回。
  - 用 LangGraph 1.x 标准的 ``create_agent`` 工厂返回 CompiledStateGraph 作为子图节点。
  - 子图状态用统一的 ``WorkerState`` TypedDict（messages + agent_name），便于被 Supervisor
    主图的 add_edge 接收时统一处理。

测试友好
  - 允许在测试里把 ``llm`` 替换为 FakeListLLM（langchain_core 的测试用 LLM），
    并把 ``tools`` 替换为最小 stub，使得 Worker 子图可在不联网/无 API Key 情况下跑通。
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)


# ============================================================
# 1) Worker 子图状态（统一）
# ============================================================


class WorkerState(TypedDict, total=False):
    """Worker 子图的内部状态。

    字段：
      - messages:    Worker 子图内部消息列表（ToolNode 会自动追加 ToolMessage）。
      - agent_name:  当前 Worker 名（用于日志 / 审计）。

    说明：
      - Supervisor 主图与 Worker 子图状态不直接共用；Worker 通过 ``invoke`` 接收
        Supervisor 传来的消息列表，然后把自己的结果以 ToolMessage / AIMessage 形式
        返回，让 Supervisor 在主图 messages 里继续累加。
    """

    messages: List[Any]
    agent_name: str


# ============================================================
# 2) 工具解析（按需加载，避免硬依赖）
# ============================================================


def _load_tools_for(agent_name: str) -> List[Any]:
    """按 Worker 名加载所需工具。

    异常时返回空列表（防御性降级：Worker 仍能运行，只是没有工具可用）。

    Args:
        agent_name: research_worker / code_worker / rag_worker
    """
    try:
        if agent_name == "research_worker":
            from v21_tools import TOOL_REGISTRY

            if "web_search" not in TOOL_REGISTRY:
                logger.warning("research_worker: web_search not in TOOL_REGISTRY")
                return []
            return [TOOL_REGISTRY["web_search"]["func"]]

        if agent_name == "code_worker":
            from v21_tools import TOOL_REGISTRY

            if "python_interpreter" not in TOOL_REGISTRY:
                logger.warning("code_worker: python_interpreter not in TOOL_REGISTRY")
                return []
            return [TOOL_REGISTRY["python_interpreter"]["func"]]

        if agent_name == "rag_worker":
            # knowledge_search 是 session-aware tool，需要通过 v21_tools 构造器获取
            from v21_tools import build_session_tools

            tools = build_session_tools(["knowledge_search"])
            return tools

        logger.warning(f"_load_tools_for: unknown agent_name={agent_name!r}")
        return []
    except Exception as e:
        logger.warning(f"_load_tools_for({agent_name}) failed: {e}")
        return []


# ============================================================
# 3) Worker 节点工厂
# ============================================================


def _get_worker_tracer() -> Any:
    """获取 OTel Tracer（用于 Worker 子图 Span 包装）；不可用时返回 NoOp。"""
    try:
        from observability.otel_exporter import get_tracer

        return get_tracer("ai_agent.workers")
    except Exception:
        try:
            from opentelemetry import trace  # type: ignore

            return trace.get_tracer("ai_agent.workers")
        except Exception:
            class _NoOp:
                def start_span(self, *a, **kw):
                    class _S:
                        def __enter__(self_inner):
                            return self_inner

                        def __exit__(self_inner, *a):
                            return False

                        def set_attribute(self_inner, *a, **kw):
                            return None

                        def end(self_inner, *a, **kw):
                            return None

                    return _S()

            return _NoOp()


def _extract_session_id(state: Any) -> str:
    """从 WorkerState 里抽取 session_id（可观察 attribute）。"""
    if isinstance(state, dict):
        # Supervisor 主图传入 WorkerState 时可能含 session_id
        sid = state.get("session_id") or state.get("sessionId")
        if isinstance(sid, str):
            return sid
    return "default"


# v2.3.1 — 正则抽取 request_id 兜底（HITL 异常对象有时是裸 Exception）
_REQUEST_ID_PATTERNS = [
    re.compile(r"request[_ ]?id\s*[:=]\s*['\"]?([A-Za-z0-9_-]+)['\"]?", re.I),
    re.compile(r"\breq[_ ]?id\s*[:=]\s*['\"]?([A-Za-z0-9_-]+)['\"]?", re.I),
]


def _extract_request_id_from_str(text: str) -> Optional[str]:
    if not text:
        return None
    for pat in _REQUEST_ID_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None


def _build_worker_node(agent_name: str) -> Any:
    """构造一个 Worker 节点函数。

    Worker 节点行为：
      1. 从 state 里取最后一条 HumanMessage 文本作为"任务描述"（简化处理）；
      2. 若该 Worker 配置了工具，调用对应工具拿到结果；
      3. 把结果包装为 ToolMessage（如果调了工具）或 AIMessage（如果没调工具也能直接给回复）追加到 messages；
      4. 返回增量 state（LangGraph 1.x 风格）。

    Args:
        agent_name: Worker 名

    Returns:
        一个接收 state、返回增量 state 的 callable（可直接作为 StateGraph.add_node 的 node 参数）。
    """
    tools = _load_tools_for(agent_name)
    has_tools = bool(tools)
    tool_names = [getattr(t, "name", "") for t in tools]

    def worker_node(state: WorkerState) -> Dict[str, Any]:
        # v2.3.1 — OTel Span 包裹（每个 Worker 子图节点执行 = 一个 Span）
        tracer = _get_worker_tracer()
        session_id = _extract_session_id(state)
        span_cm = tracer.start_span(
            f"worker.{agent_name}",
            attributes={
                "agent.name": agent_name,
                "agent.kind": "supervisor_worker",
                "session_id": session_id,
                "tools.count": len(tool_names),
            },
        )
        with span_cm as span:
            try:
                return _worker_node_inner(state, span)
            except Exception as e:
                try:
                    span.record_exception(e)
                except Exception:
                    pass
                raise

    def _worker_node_inner(state: WorkerState, span: Any = None) -> Dict[str, Any]:
        msgs = state.get("messages") or []
        last_user_text = _extract_last_user_text(msgs)
        new_messages: List[Any] = []

        if has_tools and last_user_text:
            # 调用第一个工具（最小化：Worker 子图演示用，生产可换成 ReAct agent）
            tool = tools[0]
            try:
                # v2.3.1 — HITL 拦截检测：python_interpreter 等工具被
                # _HITLWrappedTool 包裹时会在 invoke 阶段 raise HITLApprovalRequired
                # 这里记录 agent-side 的"已派发"事件到 span，让 trace 上能看到。
                result = _invoke_tool(tool, last_user_text)
            except Exception as e:
                logger.warning(f"{agent_name} tool invoke failed: {e}")
                result = f"[{agent_name}] tool error: {e}"
                # HITL 拦截：写一个独立标记到 span（不抛；外层包装会结束 span）
                try:
                    err_text = str(e)
                    if span is not None and "approval" in err_text.lower():
                        span.set_attribute("hitl.required", True)
                        # 抽取 request_id（如果异常对象带）→ 创建挂起 Span
                        req_id = getattr(e, "request_id", None) or _extract_request_id_from_str(
                            err_text
                        )
                        if req_id:
                            try:
                                from observability.hitl_span import start_hitl_span

                                start_hitl_span(
                                    str(req_id),
                                    tool_name=getattr(tool, "name", ""),
                                    session_id=session_id,
                                    agent_name=agent_name,
                                )
                            except Exception:
                                pass
                except Exception:
                    pass
            try:
                from langchain_core.messages import ToolMessage

                tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
                new_messages.append(
                    ToolMessage(
                        content=_normalize_result(result),
                        tool_call_id=tool_call_id,
                        name=getattr(tool, "name", agent_name),
                    )
                )
            except Exception:
                # langchain_core 不可用：降级为简单 dict 形式的 message
                new_messages.append(
                    {"role": "tool", "content": _normalize_result(result)}
                )
        else:
            # 没有工具：直接给一段文本回复
            new_messages.append(
                {
                    "role": "assistant",
                    "content": f"[{agent_name}] received: {last_user_text[:80] if last_user_text else '<empty>'}",
                }
            )

        # 同时把"已派发任务"登记到 subtasks（若主图状态包含 subtasks）
        out: Dict[str, Any] = {"messages": new_messages, "agent_name": agent_name}
        try:
            existing = list(state.get("subtasks") or [])
            existing.append(
                {
                    "agent": agent_name,
                    "task": last_user_text or "",
                    "tools": tool_names,
                    "status": "ok",
                }
            )
            out["subtasks"] = existing
        except Exception:
            # WorkerState 没有 subtasks 字段时（独立跑）静默忽略
            pass
        return out

    return worker_node


def _extract_last_user_text(messages: List[Any]) -> str:
    """从 messages 列表中抽取最后一条用户消息文本。

    兼容：BaseMessage 实例（AIMessage/HumanMessage 等）与 dict 形态。
    """
    for msg in reversed(messages or []):
        # 1) BaseMessage-like
        content = getattr(msg, "content", None)
        if isinstance(content, str) and content.strip():
            # 优先返回最后一条 HumanMessage
            if msg.__class__.__name__ == "HumanMessage":
                return content
        # 2) dict 形态
        if isinstance(msg, dict):
            role = msg.get("role") or msg.get("type")
            text = msg.get("content")
            if role == "user" and isinstance(text, str) and text.strip():
                return text
            if role == "human" and isinstance(text, str) and text.strip():
                return text
        # 3) 退化：任何字符串 content
        if isinstance(content, str) and content.strip():
            return content
    return ""


def _invoke_tool(tool: Any, text: str) -> Any:
    """调用一个工具；兼容 BaseTool / StructuredTool / 简单 callable。

    优先用 tool.invoke(...)；失败时降级为 tool._run(...)；再降级为直接调用。
    """
    invoke = getattr(tool, "invoke", None)
    if callable(invoke):
        try:
            # 优先尝试 {"query": text} / {"code": text} / {"input": text} 三种 kwargs
            for kw in ({"query": text}, {"code": text}, {"input": text}, {}):
                try:
                    return invoke(kw)
                except TypeError:
                    continue
            # 最后：直接把 text 字符串喂进去
            return invoke(text)
        except Exception:
            pass
    run = getattr(tool, "_run", None)
    if callable(run):
        try:
            return run(**{"query": text})
        except TypeError:
            try:
                return run(text)
            except Exception:
                pass
    if callable(tool):
        try:
            return tool(text)
        except Exception:
            return f"[{getattr(tool, 'name', 'tool')}] no usable interface"
    return f"[{getattr(tool, 'name', 'tool')}] unsupported"


def _normalize_result(result: Any) -> str:
    """统一把工具结果转为字符串（Worker 子图只接受 str content）。"""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        try:
            import json

            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            return str(result)
    return str(result)


# ============================================================
# 4) 子图构造（暴露给 Supervisor 主图）
# ============================================================


def build_research_worker() -> Any:
    """构造研究子图：只加载 web_search。

    Returns:
        LangGraph CompiledStateGraph（research_worker 子图）。
    """
    g = StateGraph(WorkerState)
    g.add_node("research_worker", _build_worker_node("research_worker"))
    g.add_edge(START, "research_worker")
    g.add_edge("research_worker", END)
    return g.compile()


def build_code_worker() -> Any:
    """构造代码子图：加载 python_interpreter（保留 HITL 包裹）。

    注意：HITL 拦截发生在工具 invoke 层面（_HITLWrappedTool），不影响子图本身的结构。
    子图照常执行；ToolNode 在拿到 tool_call 时如果工具被 HITL 拦截，会返回 sentinel
    字符串，由 Supervisor 主图的 HITL 消费流程接管。
    """
    g = StateGraph(WorkerState)
    g.add_node("code_worker", _build_worker_node("code_worker"))
    g.add_edge(START, "code_worker")
    g.add_edge("code_worker", END)
    return g.compile()


def build_rag_worker() -> Any:
    """构造 RAG 子图：加载 knowledge_search（使用 Session 隔离的 ChromaDB）。

    注意：knowledge_search 在 v21_tools.rag_tool 里已经做了 session_id 隔离；
    子图只负责调用，不处理会话隔离逻辑。
    """
    g = StateGraph(WorkerState)
    g.add_node("rag_worker", _build_worker_node("rag_worker"))
    g.add_edge(START, "rag_worker")
    g.add_edge("rag_worker", END)
    return g.compile()


# ============================================================
# 5) 工厂批量入口（便捷）
# ============================================================


def build_default_workers() -> Dict[str, Any]:
    """一次性构造三个 Worker 子图。

    Returns:
        dict: {"research_worker": subgraph, "code_worker": subgraph, "rag_worker": subgraph}
    """
    return {
        "research_worker": build_research_worker(),
        "code_worker": build_code_worker(),
        "rag_worker": build_rag_worker(),
    }


__all__ = [
    "WorkerState",
    "build_research_worker",
    "build_code_worker",
    "build_rag_worker",
    "build_default_workers",
    "_load_tools_for",
]