"""
supervisor_state.py — Milestone 2.2.3 LangGraph Multi-Agent Supervisor 模式（State 定义）

设计目标
  - 在 SqliteSaver Checkpointer + HITL + Local Chroma RAG 基础上，引入 Supervisor Multi-Agent 架构。
  - Supervisor 节点用结构化输出 ``RouterOutput`` 显式声明"下一个 Worker + 任务描述 + 思考过程"。
  - Worker 节点只负责执行；执行完毕后把控制权交还给 Supervisor，由 Supervisor 决定下一步。

状态字段
  - messages: LangGraph 标准消息列表（``add_messages`` reducer 自动追加）
  - next_node:  Supervisor 决策的下一个 Worker（research_worker / code_worker / rag_worker / FINISH）
  - subtasks:   Supervisor 已派发的子任务追踪列表（用于审计 / 调试）

设计要点
  - SupervisorState 用 TypedDict + Annotated["add_messages"]：与 LangGraph 1.x StateGraph 兼容，
    可直接传给 ``create_agent`` / ``StateGraph``，并被 SqliteSaver 完整持久化。
  - RouterOutput 是 Pydantic BaseModel：兼容 LangChain 的 ``with_structured_output`` 调用，
    可被 LLM 直接生成结构化 JSON；同时也可被 ``parse_router_output`` 容错地从字符串解析（测试友好）。
  - FINISH 是字面常量（不用 Enum），便于在 ``add_conditional_edges`` 中直接用作路由终点。

与 v2_slim.multi_agent_v2.SupervisorState 的关系
  - 老 SupervisorState 只有 ``messages`` + ``next``；本次扩展新增 ``subtasks`` 字段，
    并显式给出 RouterOutput（之前只有字符串解析）。两者不互相覆盖：v2_slim 的版本保留供
    旧 API 使用；新 Supervisor Multi-Agent 用本模块。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Annotated, Any, Dict, List, Literal, Optional

from langgraph.graph import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)


# ============================================================
# 1) SupervisorState — LangGraph State
# ============================================================


# Supervisor 节点可选的下一步（也作为 Worker 子图的节点名）。
# 用 Literal 而非 Enum：方便 add_conditional_edges 直接比较；FINISH 作为终点字面量。
WorkerName = Literal["research_worker", "code_worker", "rag_worker", "FINISH"]


class SupervisorState(TypedDict, total=False):
    """Multi-Agent Supervisor 主图的状态。

    字段：
      - messages:  LangChain 标准消息列表（HumanMessage / AIMessage / ToolMessage）。
                   用 ``add_messages`` reducer，节点返回新消息会被自动追加，
                   而不是整段替换。这是 LangGraph 1.x StateGraph 的"标准模式"。
      - next_node: Supervisor 决策的下一个 Worker（含 FINISH）。
                   供 ``add_conditional_edges`` 读取，决定路由目标。
      - subtasks:  Supervisor 已派发的子任务追踪列表（只追加，不重写）。
                   每条形如 ``{"agent": "code_worker", "task": "...", "status": "ok"}``。
    """

    messages: Annotated[List[Any], add_messages]
    next_node: WorkerName
    subtasks: List[Dict[str, Any]]


# ============================================================
# 2) RouterOutput — Supervisor 的结构化输出
# ============================================================


class RouterOutput(BaseModel):
    """Supervisor LLM 的结构化输出。

    字段：
      - next_agent:      下一个 Worker 节点名（含 FINISH）。
      - task_description: 派给该 Worker 的具体任务描述（FINISH 时可为 None）。
      - thought_process:  Supervisor 的思考过程（用于 SSE agent_switch.reason 推送）。
    """

    next_agent: WorkerName = Field(
        ...,
        description="下一个 Worker 节点名；research_worker/code_worker/rag_worker/FINISH",
    )
    task_description: Optional[str] = Field(
        default=None,
        description="派给 Worker 的具体子任务描述（FINISH 时为 None）",
    )
    thought_process: str = Field(
        default="",
        description="Supervisor 选择该 Worker 的思考过程，会作为 SSE agent_switch 的 reason",
    )

    def to_dict(self) -> Dict[str, Any]:
        """dict 序列化（与 Pydantic v2 的 model_dump 等价，但保持向后兼容）。"""
        return self.model_dump()


# ============================================================
# 3) 容错解析：LLM 输出不一定是严格 JSON
# ============================================================


_FINISH_TOKEN = "FINISH"
_KNOWN_AGENTS = ("research_worker", "code_worker", "rag_worker")


def parse_router_output(text: str) -> RouterOutput:
    """从 LLM 输出文本中容错解析 RouterOutput。

    策略（按优先级）：
      1. 严格 JSON.loads（理想情况）
      2. 截取第一个 {...} 段后再 JSON.loads（兼容模型多吐一句 "下面是 JSON：..."）
      3. 正则匹配 ``"next_agent"\\s*:\\s*"<name>"``：至少把 next_agent 抽出来
      4. 兜底：纯文本包含 FINISH → next_agent="FINISH"；否则默认 FINISH（避免死循环）

    Args:
        text: LLM 原始输出（可能是 Markdown 块、JSON、纯文本）

    Returns:
        RouterOutput 实例；任何字段缺失都会被默认值填充。
    """
    raw = (text or "").strip()
    if not raw:
        return RouterOutput(next_agent="FINISH", thought_process="empty LLM output")

    # 1) 直接 JSON
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return _coerce_router_dict(obj)
    except Exception:
        pass

    # 2) 抽取第一个 {...} 段
    try:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return _coerce_router_dict(obj)
    except Exception:
        pass

    # 3) 正则抽 next_agent
    m = re.search(r'"next_agent"\s*:\s*"([^"]+)"', raw)
    if m:
        candidate = m.group(1).strip()
        return RouterOutput(
            next_agent=_normalize_agent(candidate),
            thought_process=f"regex fallback: {raw[:120]}",
        )

    # 4) 兜底
    upper = raw.upper()
    if _FINISH_TOKEN in upper:
        return RouterOutput(next_agent="FINISH", thought_process="FINISH token fallback")
    # 任何已知 agent 关键字出现
    for agent in _KNOWN_AGENTS:
        if agent in raw:
            return RouterOutput(
                next_agent=agent,  # type: ignore[arg-type]
                thought_process=f"keyword fallback: {agent}",
            )
    return RouterOutput(next_agent="FINISH", thought_process="unknown output fallback")


def _coerce_router_dict(obj: Dict[str, Any]) -> RouterOutput:
    """把 dict 强转成 RouterOutput，缺失字段用默认值补齐。"""
    raw_agent = obj.get("next_agent") or obj.get("next") or "FINISH"
    return RouterOutput(
        next_agent=_normalize_agent(str(raw_agent)),
        task_description=obj.get("task_description"),
        thought_process=str(obj.get("thought_process") or ""),
    )


def _normalize_agent(name: str) -> WorkerName:
    """规范化 agent 名：去除空白 + 白名单校验；非法值降级为 FINISH。"""
    n = (name or "").strip()
    if n in _KNOWN_AGENTS or n == "FINISH":
        return n  # type: ignore[return-value]
    # 兼容老版本别名（researcher/coder/reviewer → research/code/rag）
    aliases = {
        "researcher": "research_worker",
        "search": "research_worker",
        "coder": "code_worker",
        "code": "code_worker",
        "reviewer": "rag_worker",
        "rag": "rag_worker",
    }
    aliased = aliases.get(n.lower())
    if aliased:
        logger.debug(f"RouterOutput normalized alias: {n!r} -> {aliased}")
        return aliased  # type: ignore[return-value]
    return "FINISH"


# ============================================================
# 4) Agent Switch SSE 事件（前端 UI 提示 Worker 切换）
# ============================================================


def build_agent_switch_event(
    next_agent: WorkerName, thought_process: str = ""
) -> Dict[str, Any]:
    """构造 agent_switch SSE 事件 dict。

    字段：
      - type: 固定 "agent_switch"
      - agent: 目标 Worker 名（含 FINISH）
      - reason: Supervisor 的思考过程
    """
    return {
        "type": "agent_switch",
        "agent": next_agent,
        "reason": thought_process or "",
    }


__all__ = [
    "SupervisorState",
    "RouterOutput",
    "WorkerName",
    "parse_router_output",
    "build_agent_switch_event",
]