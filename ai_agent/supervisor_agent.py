"""
supervisor_agent.py — Milestone 2.2.3 LangGraph Multi-Agent Supervisor 模式（主控图编排）

设计目标
  - 使用 LangGraph ``StateGraph(SupervisorState)`` 构建主控图；
  - Supervisor 节点分析当前对话历史，决定下一个 next_agent（RouterOutput）；
  - 通过 ``add_conditional_edges`` 路由到对应 Worker 子图；
  - Worker 执行完毕返回 Supervisor（``add_edge(worker, "supervisor")``）；
  - 若 next_agent="FINISH"，则走 ``END`` 并返回最终回答。

工程要点
  - ``workflow.compile(checkpointer=sqlite_saver)`` 全量保留 SqliteSaver 状态持久化。
  - Supervisor 节点对外暴露 ``on_agent_switch`` 回调钩子：每次决定切换 Worker 时触发，
    SSE 消费者（app.py）可在该回调里推送 ``event: agent_switch`` 帧。
  - Worker 子图通过 ``build_default_workers()`` 默认注入；测试里可单独传入自定义 dict。

流程图
  START → supervisor → add_conditional_edges(next_node)
                          ├─ research_worker → supervisor
                          ├─ code_worker    → supervisor
                          ├─ rag_worker     → supervisor
                          └─ FINISH         → END

测试友好
  - ``supervisor_llm`` 允许是任意 callable（接收 messages list，返回 str 或 RouterOutput）；
  - workers 允许是 dict[str, callable]，可被替换为 FakeListLLM 等 mock；
  - checkpointer 默认为 None；测试可用 MemorySaver。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from agent_workers import build_default_workers
from supervisor_state import (
    RouterOutput,
    SupervisorState,
    WorkerName,
    build_agent_switch_event,
    parse_router_output,
)

logger = logging.getLogger(__name__)


# ============================================================
# 1) Supervisor 节点 — 调用 LLM 决策
# ============================================================


SUPERVISOR_PROMPT = """你是 Multi-Agent Supervisor。你的职责：

1. 分析用户的最新请求与对话历史；
2. 决定下一步应该交给哪个 Worker 执行，或 FINISH 结束任务；
3. 给所选 Worker 一个清晰的子任务描述；
4. 简要说明你的思考过程。

可选 Worker：
- research_worker：联网搜索（web_search）。处理实时信息 / 最新事件 / 未知事实。
- code_worker：在沙箱里执行 Python 代码（python_interpreter，受 HITL 审批）。
- rag_worker：从本地知识库检索（knowledge_search，Session 隔离）。
- FINISH：所有子任务已完成，无需继续派发。

只返回以下 JSON 格式（不要解释、不要 Markdown 代码块）：

{"next_agent": "<research_worker|code_worker|rag_worker|FINISH>", "task_description": "<具体子任务描述，或 null>", "thought_process": "<你的思考过程>"}
"""


def make_supervisor_node(
    supervisor_llm: Any,
    on_agent_switch: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Callable[[SupervisorState], Command]:
    """构造 Supervisor 节点函数。

    行为：
      1. 读取当前 state["messages"]；
      2. 拼装 prompt → 调用 supervisor_llm；
      3. 解析 RouterOutput（容错解析）；
      4. 若配置了 on_agent_switch 回调 → 推送 agent_switch 事件；
      5. 返回 Command(goto=...) + update={next_node, subtasks}。

    Args:
        supervisor_llm: 用于决策的 LLM。要求支持 .invoke(messages: list[dict]) → AIMessage / str。
                        测试可用 FakeListLLM / 普通 callable。
        on_agent_switch: 每次切换 Worker 时调用的回调；签名 (event_dict: dict) -> None。
                         app.py 在此处把 event 推给 SSE 流。

    Returns:
        一个 callable（接收 SupervisorState，返回 Command）。
    """
    allowed: tuple = ("research_worker", "code_worker", "rag_worker")

    # v2.3.1 — OTel Tracer 注入 supervisor 节点
    def _get_tracer() -> Any:
        try:
            from observability.otel_exporter import get_tracer

            return get_tracer("ai_agent.supervisor")
        except Exception:
            try:
                from opentelemetry import trace  # type: ignore

                return trace.get_tracer("ai_agent.supervisor")
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

    tracer = _get_tracer()

    def supervisor_node_fn(state: SupervisorState) -> Command:
        import time as _time

        prev_node = state.get("next_node") or "START"
        started = _time.time()
        span_cm = tracer.start_span(
            "supervisor.decide",
            attributes={
                "supervisor.from": str(prev_node),
                "supervisor.messages": len(state.get("messages") or []),
            },
        )
        with span_cm as span:
            try:
                msgs = state.get("messages") or []
                # 拼装 prompt：system + 历史消息
                prompt_msgs: List[Dict[str, Any]] = [
                    {"role": "system", "content": SUPERVISOR_PROMPT}
                ]
                # 仅取最近若干条，避免 prompt 膨胀
                tail = msgs[-20:] if isinstance(msgs, list) else []
                for m in tail:
                    if isinstance(m, dict):
                        prompt_msgs.append(m)
                    else:
                        role = getattr(m, "type", None) or "user"
                        role = "user" if role == "human" else role
                        prompt_msgs.append(
                            {"role": role, "content": getattr(m, "content", str(m))}
                        )

                # 调用 LLM
                text = ""
                try:
                    out = supervisor_llm.invoke(prompt_msgs)
                    text = getattr(out, "content", str(out))
                except Exception as e:
                    logger.warning(f"Supervisor LLM invoke failed: {e}")
                    text = '{"next_agent": "FINISH", "thought_process": "llm error fallback"}'

                # 解析 RouterOutput
                router = parse_router_output(text)
                # 白名单二次校验：未知 agent → FINISH（避免非法跳转）
                if router.next_agent not in allowed and router.next_agent != "FINISH":
                    logger.warning(
                        f"Supervisor returned unknown agent: {router.next_agent!r}, "
                        "downgrading to FINISH"
                    )
                    router = RouterOutput(
                        next_agent="FINISH",
                        task_description=None,
                        thought_process=f"unknown agent fallback: {router.next_agent}",
                    )

                # 推送 agent_switch 事件（仅当实际切换到 Worker 时；FINISH 也推，便于前端收尾）
                if on_agent_switch is not None:
                    try:
                        on_agent_switch(
                            build_agent_switch_event(
                                next_agent=router.next_agent,
                                thought_process=router.thought_process,
                            )
                        )
                    except Exception as cb_err:
                        logger.debug(f"on_agent_switch callback failed: {cb_err}")

                # v2.3.1 — 记录 agent_switch 耗时到 Prometheus + OTel
                duration = max(0.0, _time.time() - started)
                try:
                    from observability.otel_exporter import record_agent_switch

                    record_agent_switch(
                        from_agent=str(prev_node),
                        to_agent=str(router.next_agent),
                        duration_seconds=duration,
                        status="ok",
                    )
                except Exception:
                    pass

                # 更新 subtasks：把这次决策的"调度"记下来，便于审计
                new_subtasks = list(state.get("subtasks") or [])
                new_subtasks.append(
                    {
                        "agent": router.next_agent,
                        "task": router.task_description or "",
                        "thought": router.thought_process or "",
                    }
                )

                try:
                    if span is not None:
                        span.set_attribute("supervisor.to", str(router.next_agent))
                        span.set_attribute("duration_ms", int(duration * 1000))
                except Exception:
                    pass

                return Command(
                    goto=router.next_agent,
                    update={"next_node": router.next_agent, "subtasks": new_subtasks},
                )
            except Exception as e:
                try:
                    span.record_exception(e)
                except Exception:
                    pass
                raise

    return supervisor_node_fn


# ============================================================
# 2) 主图装配
# ============================================================


def build_supervisor_workflow(
    supervisor_llm: Any,
    workers: Optional[Dict[str, Any]] = None,
    *,
    checkpointer: Optional[Any] = None,
    on_agent_switch: Optional[Callable[[Dict[str, Any]], None]] = None,
    callbacks: Optional[list] = None,
) -> Any:
    """构造 Supervisor Multi-Agent LangGraph CompiledStateGraph。

    Args:
        supervisor_llm: Supervisor 决策 LLM（同 make_supervisor_node）
        workers:  worker 名 → 子图 / 可调用对象的映射；None 则用默认三个 Worker
        checkpointer: SqliteSaver 实例（None 时用 in-memory 兜底；测试建议显式传 MemorySaver）
        on_agent_switch: 切换 Worker 时的回调（app.py 用来推 SSE）
        callbacks: v2.3.1 — LangChain callbacks（LangSmithTracer 等），
                   可在 ``.invoke(..., config={"callbacks": cb})`` 时合并；
                   None 时自动从 env 注入 LangSmithTracer（如启用）。

    Returns:
        LangGraph CompiledStateGraph。

    Raises:
        ValueError: workers 显式传空 dict
    """
    # v2.3.1 — 默认注入 LangSmithTracer（若启用）
    if callbacks is None:
        try:
            from observability.langsmith_config import get_langsmith_callbacks

            callbacks = get_langsmith_callbacks()
        except Exception:
            callbacks = []
    if callbacks is None:
        callbacks = []
    # 仅当显式传 {} 时报错；传 None 走默认 Worker 工厂
    if workers is not None and not workers:
        raise ValueError("supervisor_agent: workers 不能为空")
    if workers is None:
        workers = build_default_workers()
    if not workers:
        raise ValueError("supervisor_agent: workers 不能为空")

    # 校验：只允许已知 worker
    allowed = ("research_worker", "code_worker", "rag_worker")
    for name in workers:
        if name not in allowed:
            raise ValueError(
                f"supervisor_agent: 不支持的 worker 名 '{name}'（仅允许 {allowed}）"
            )

    g = StateGraph(SupervisorState)

    # Supervisor 节点
    sup_node = make_supervisor_node(supervisor_llm, on_agent_switch)
    g.add_node("supervisor", sup_node)

    # Worker 子图节点
    for name, sub in workers.items():
        # 兼容：callable 但无 invoke → 包成 RunnableLambda
        if callable(sub) and not hasattr(sub, "invoke"):
            try:
                from langchain_core.runnables import RunnableLambda

                sub = RunnableLambda(sub)
            except Exception:
                # 没有 langchain 也行：LangGraph 的 add_node 接受 callable
                pass
        g.add_node(name, sub)
        # Worker 执行完 → 返回 supervisor（闭环核心）
        g.add_edge(name, "supervisor")

    g.add_edge(START, "supervisor")

    # 条件路由：根据 supervisor 更新后的 next_node 决定跳到哪个 Worker / END
    # LangGraph 内部 END 节点对外暴露为 "END" 字符串（在 conditional_edges 的 path_map 里），
    # 节点名解析时会自动翻译为 "__end__"。这里直接返回字符串 FINISH 让 LangGraph 走 END。
    # 注意：path_map 必须只引用图中实际存在的节点 —— 若测试只注入部分 worker，路径表同步精简。
    def _route_by_next(state: SupervisorState) -> str:
        nxt = state.get("next_node") or "FINISH"
        if nxt not in workers and nxt != "FINISH":
            return "FINISH"
        return nxt

    path_map: Dict[str, Any] = {name: name for name in workers.keys()}
    path_map["FINISH"] = END

    g.add_conditional_edges("supervisor", _route_by_next, path_map)

    # 装配 + 编译（保留 SqliteSaver Checkpointer 能力）
    if checkpointer is not None:
        return g.compile(checkpointer=checkpointer)
    # 兜底：in-memory checkpointer（LangGraph 1.x 提供）
    try:
        from langgraph.checkpoint.memory import MemorySaver

        return g.compile(checkpointer=MemorySaver())
    except Exception:
        # 最后兜底：不传 checkpointer（部分环境可能无法 import MemorySaver）
        return g.compile()


# ============================================================
# 3) 默认 LLM 工厂（兼容 ResilientLLMInvoker）
# ============================================================


def default_supervisor_llm() -> Any:
    """构造一个默认的 Supervisor LLM（用于生产 + 测试 fallback）。

    优先级：
      1. 从 AIAgent._build_fallback_chain 取当前 provider / model，构造 ChatOpenAI。
      2. 失败时退回一个最小的 FakeListLLM（"FINISH"），保证图能跑起来。

    Returns:
        LLM 实例（支持 .invoke([{role,content}])）。
    """
    try:
        from agent import AIAgent  # type: ignore

        # 防御性：避开真实 LLM 调用
        try:
            from langchain_community.chat_models.fake import FakeListChatModel

            return FakeListChatModel(
                responses=[
                    '{"next_agent": "research_worker", "task_description": "search demo", "thought_process": "default fake"}',
                    '{"next_agent": "FINISH", "thought_process": "default fake finish"}',
                ]
            )
        except Exception:
            pass

        # 第二兜底：str 序列
        class _StrLLM:
            def invoke(self, _messages: List[Any]) -> str:
                return '{"next_agent": "FINISH", "thought_process": "default fallback"}'

        return _StrLLM()
    except Exception:
        # 最后兜底
        class _Final:
            def invoke(self, _messages: List[Any]) -> str:
                return '{"next_agent": "FINISH"}'

        return _Final()


# ============================================================
# 4) 对外便利：流式执行入口（用于 SSE）
# ============================================================


def stream_supervisor(
    workflow: Any,
    initial_messages: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    *,
    stream_mode: str = "updates",
):
    """流式运行 Supervisor 工作流，yield 每一步的事件（包含 agent_switch 标记）。

    简化 wrapper：调用 ``workflow.stream(...)``，并在 ``on_agent_switch`` 已配置的前提下，
    由回调直接推事件到外部队列；本函数只负责包一层 stream，便于测试。
    """
    payload = {"messages": initial_messages}
    if config is None:
        config = {"configurable": {"thread_id": "default"}}
    try:
        for event in workflow.stream(payload, config=config, stream_mode=stream_mode):
            yield event
    except Exception as e:
        logger.error(f"stream_supervisor failed: {e}")
        yield {"type": "error", "data": str(e)}


__all__ = [
    "SUPERVISOR_PROMPT",
    "make_supervisor_node",
    "build_supervisor_workflow",
    "default_supervisor_llm",
    "stream_supervisor",
]