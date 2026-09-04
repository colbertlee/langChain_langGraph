"""
v2.0 slim — multi_agent_v2.py（仅保留 Sequential + Supervisor）

裁剪：
- 删除 PARALLEL / HIERARCHICAL / FANOUT
- 删除 negotiation.py（Auction / Bid / NegotiationParticipantMixin）
- 保留 5 种 OrchestrationMode 枚举的 SEQUENTIAL / SUPERVISOR 用于前端展示

设计：
- create_sequential_agent：线性节点链，前一节点输出作为后一节点入参
- create_supervisor_agent：supervisor LLM 决策 worker 路由（add_conditional_edges）
- 5 层容错（ResilientLLMInvoker）从 agent.py 注入到 supervisor_llm
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, TypedDict, Annotated

logger = logging.getLogger(__name__)


# ============================================================
# 模式枚举（仅保留 SEQUENTIAL / SUPERVISOR）
# ============================================================

class OrchestrationMode(str, Enum):
    SEQUENTIAL = "sequential"
    SUPERVISOR = "supervisor"


# ============================================================
# Sequential Agent
# ============================================================

class SequentialState(TypedDict, total=False):
    """Sequential 状态：messages + 步骤计数 + 中间产物。"""
    messages: Annotated[List[Any], "add_messages"]
    step: int
    scratchpad: Dict[str, Any]


def create_sequential_agent(
    nodes: Sequence[Callable[[Dict[str, Any]], Dict[str, Any]]],
    *,
    checkpointer: Optional[Any] = None,
) -> Any:
    """构造线性顺序执行的 LangGraph CompiledStateGraph。

    Args:
        nodes: 节点函数列表。每个函数接收 state dict，返回增量 state dict。
        checkpointer: SqliteSaver 实例；不传则用 in-memory。

    Returns:
        CompiledStateGraph。
    """
    from langgraph.graph import StateGraph, START, END

    if not nodes:
        raise ValueError("create_sequential_agent: nodes 不能为空")

    g = StateGraph(SequentialState)
    prev_node: Optional[str] = None
    for i, fn in enumerate(nodes):
        node_name = f"step_{i}"
        # 包装：注入 step 计数 + 合并 scratchpad
        def _make_wrapper(f: Callable, idx: int):
            def _wrapper(state: SequentialState) -> Dict[str, Any]:
                out = f(state) or {}
                out.setdefault("step", idx + 1)
                if "scratchpad" in out and "scratchpad" in state:
                    merged = {**state["scratchpad"], **out["scratchpad"]}
                    out["scratchpad"] = merged
                return out
            return _wrapper

        g.add_node(node_name, _make_wrapper(fn, i))
        if prev_node is None:
            g.add_edge(START, node_name)
        else:
            g.add_edge(prev_node, node_name)
        prev_node = node_name

    g.add_edge(prev_node, END)
    return g.compile(checkpointer=checkpointer)


# ============================================================
# Supervisor Agent
# ============================================================

SupervisorDecision = Literal["researcher", "coder", "reviewer", "FINISH"]


class SupervisorState(TypedDict, total=False):
    """Supervisor 状态：messages + 当前轮 next。"""
    messages: Annotated[List[Any], "add_messages"]
    next: str


SUPERVISOR_PROMPT = """你是 supervisor。在以下 worker 中选择一个下一步执行：
- researcher：信息检索
- coder：写代码/执行
- reviewer：质量检查
或 FINISH 结束任务。
仅返回 JSON：{{"next": "<worker|FINISH>"}}
"""


def _parse_route(text: str) -> Dict[str, str]:
    """极简 route 解析：从 LLM 输出抽取 {"next": "..."}。"""
    import json, re
    text = (text or "").strip()
    # 尝试直接 JSON
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "next" in obj:
            return {"next": str(obj["next"]).strip()}
    except Exception:
        pass
    # 退化：正则匹配
    m = re.search(r'"next"\s*:\s*"([^"]+)"', text)
    if m:
        return {"next": m.group(1).strip()}
    # 最后兜底
    if "FINISH" in text.upper():
        return {"next": "FINISH"}
    return {"next": "FINISH"}


def create_supervisor_agent(
    supervisor_llm: Any,
    workers: Dict[str, Any],
    *,
    checkpointer: Optional[Any] = None,
    allowed_workers: Optional[Sequence[str]] = None,
) -> Any:
    """构造 Supervisor 模式的 LangGraph CompiledStateGraph。

    Args:
        supervisor_llm: 通过 ResilientLLMInvoker 包装后的 LLM（享受五层容错）。
        workers: 名称 -> 已编译子图 / 节点函数的映射。
        checkpointer: SqliteSaver 实例；不传则 in-memory。
        allowed_workers: 限制 supervisor 只能选这些 worker（None = 全部）。

    Returns:
        CompiledStateGraph。
    """
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import Command

    if not workers:
        raise ValueError("create_supervisor_agent: workers 不能为空")

    whitelist = set(allowed_workers) if allowed_workers else set(workers.keys())

    g = StateGraph(SupervisorState)

    # supervisor 节点：调用 LLM 决策
    def supervisor_node(state: SupervisorState) -> Command:
        msgs = state.get("messages") or []
        prompt_msgs = [{"role": "system", "content": SUPERVISOR_PROMPT}] + list(msgs)
        try:
            out = supervisor_llm.invoke(prompt_msgs)
            text = getattr(out, "content", str(out))
        except Exception as e:
            logger.warning("supervisor LLM 调用失败，默认 FINISH: %s", e)
            text = '{"next": "FINISH"}'
        route = _parse_route(text)
        # 白名单校验
        if route["next"] not in whitelist and route["next"] != "FINISH":
            route["next"] = "FINISH"
        return Command(goto=route["next"], update={"next": route["next"]})

    g.add_node("supervisor", supervisor_node)
    for name, sub in workers.items():
        # 子图作为节点；如果是 callable 则用 RunnableLambda 包装
        if callable(sub) and not hasattr(sub, "invoke"):
            from langchain_core.runnables import RunnableLambda
            sub = RunnableLambda(sub)
        g.add_node(name, sub)
        # 子图跑完后回到 supervisor
        g.add_edge(name, "supervisor")

    g.add_edge(START, "supervisor")
    return g.compile(checkpointer=checkpointer)


# ============================================================
# 已裁剪模式（冻结占位）
# ============================================================

from .frozen import frozen


@frozen("create_parallel_agent")
def create_parallel_agent(*args, **kwargs):
    """PARALLEL 模式（已冻结于 v2.0 slim）。"""
    pass


@frozen("create_hierarchical_agent")
def create_hierarchical_agent(*args, **kwargs):
    """HIERARCHICAL 模式（已冻结于 v2.0 slim）。"""
    pass


@frozen("create_fanout_agent")
def create_fanout_agent(*args, **kwargs):
    """FANOUT 模式（已冻结于 v2.0 slim）。"""
    pass