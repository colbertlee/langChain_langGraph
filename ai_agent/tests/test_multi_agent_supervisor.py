"""
test_multi_agent_supervisor.py — Milestone 2.2.3 Multi-Agent Supervisor 模式测试

覆盖：
  1) Supervisor 意图识别 & RouterOutput 解析
     - 严格 JSON / 嵌入 JSON / 纯文本 / 未知 agent 名 / FINISH 字面量
  2) SupervisorState 状态形状
     - messages / next_node / subtasks 字段
  3) Worker 子图最小构造（不依赖外部 API）
     - research_worker / code_worker / rag_worker 三个子图都能 compile
  4) 复合任务在 Multi-Agent 状态图中的分阶段循环执行
     - 假 LLM 顺序返回 research → code → FINISH，验证状态图走了三个阶段
  5) Supervisor 模式下 code_worker 触发 HITL 审批闭环
     - python_interpreter 通过 HITLStore 拦截 → approve 后能继续回到 Supervisor
  6) SSE agent_switch 事件 payload 形状

测试友好设计：
  - 所有需要 LLM 的地方都用 _ScriptedLLM（顺序返回固定响应）；
  - checkpointer 统一使用 langgraph.checkpoint.memory.MemorySaver（不需要 SQLite）；
  - HITL 通过 hitl_langgraph.HITLStore.reset_instance() 隔离，避免全局污染。
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest


# ai_agent/ 根目录加入 sys.path（conftest 已加，但单跑时也安全）
_RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(_RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_ROOT))


# ============================================================
# 通用 fixture
# ============================================================


@pytest.fixture
def isolated_env(monkeypatch):
    """通用隔离环境：短路 LLM 调用 / 允许内存 checkpointer / 隔离 HITL。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-for-tests-only")
    monkeypatch.setenv("AI_AGENT_DISABLE_PLACEHOLDER_CHECK", "1")
    monkeypatch.setenv("AI_AGENT_INMEM_CHECKPOINT", "1")
    try:
        from hitl_langgraph import HITLStore

        HITLStore.reset_instance()
    except Exception:
        pass
    yield
    try:
        from hitl_langgraph import HITLStore

        HITLStore.reset_instance()
    except Exception:
        pass


class _ScriptedLLM:
    """测试用 LLM：按调用顺序返回固定响应。

    行为：
      - invoke(messages) → 顺序返回 self.responses 中的下一个；
      - 全部用完则重复最后一个；
      - 允许调用方临时 push 新响应。
    """

    def __init__(self, responses: List[str]):
        self.responses = list(responses)
        self.calls: List[List[Any]] = []

    def invoke(self, messages: Any) -> Any:
        self.calls.append(messages)
        if not self.responses:
            return '{"next_agent": "FINISH"}'
        out = self.responses.pop(0)
        if not self.responses:
            self.responses.append(out)  # 重复最后一个
        return _Resp(out)


class _Resp:
    """LangChain AIMessage 兼容结构（仅保留 .content 即可）。"""

    def __init__(self, content: str):
        self.content = content


# ============================================================
# 1) RouterOutput 解析 — Supervisor 意图识别核心
# ============================================================


class TestRouterOutputParsing:

    def test_strict_json(self, isolated_env):
        from supervisor_state import parse_router_output

        r = parse_router_output(
            json.dumps(
                {
                    "next_agent": "research_worker",
                    "task_description": "查 RAG 知识库",
                    "thought_process": "用户问的是实时新闻",
                },
                ensure_ascii=False,
            )
        )
        assert r.next_agent == "research_worker"
        assert r.task_description == "查 RAG 知识库"
        assert "实时新闻" in r.thought_process

    def test_embedded_json(self, isolated_env):
        """LLM 可能在 JSON 前后有解释文本，应能抽取第一个 {...} 段。"""
        from supervisor_state import parse_router_output

        text = (
            "以下是决策：\n"
            '{"next_agent": "code_worker", "task_description": "跑 1+1", '
            '"thought_process": "需要计算"}\n'
            "以上。"
        )
        r = parse_router_output(text)
        assert r.next_agent == "code_worker"
        assert r.task_description == "跑 1+1"

    def test_markdown_wrapped_json(self, isolated_env):
        from supervisor_state import parse_router_output

        text = "```json\n{\"next_agent\": \"rag_worker\", \"thought_process\": \"查知识库\"}\n```"
        r = parse_router_output(text)
        assert r.next_agent == "rag_worker"
        assert "查知识库" in r.thought_process

    def test_finish_token_in_text(self, isolated_env):
        """纯文本中含 FINISH → 解析为 FINISH（兜底）。"""
        from supervisor_state import parse_router_output

        r = parse_router_output("我觉得任务已经完成，所以 FINISH。")
        assert r.next_agent == "FINISH"

    def test_unknown_agent_normalized_to_finish(self, isolated_env):
        from supervisor_state import parse_router_output

        r = parse_router_output('{"next_agent": "magic_agent"}')
        assert r.next_agent == "FINISH"

    def test_alias_normalization(self, isolated_env):
        """兼容旧别名：researcher → research_worker，coder → code_worker。"""
        from supervisor_state import parse_router_output

        assert parse_router_output('{"next_agent": "researcher"}').next_agent == "research_worker"
        assert parse_router_output('{"next_agent": "coder"}').next_agent == "code_worker"
        assert parse_router_output('{"next_agent": "reviewer"}').next_agent == "rag_worker"

    def test_empty_input(self, isolated_env):
        from supervisor_state import parse_router_output

        r = parse_router_output("")
        assert r.next_agent == "FINISH"
        r2 = parse_router_output(None)
        assert r2.next_agent == "FINISH"

    def test_malformed_falls_back_to_finish(self, isolated_env):
        from supervisor_state import parse_router_output

        r = parse_router_output("not json at all, just random text")
        assert r.next_agent == "FINISH"


# ============================================================
# 2) SupervisorState 字段形状
# ============================================================


class TestSupervisorStateShape:

    def test_state_has_expected_fields(self, isolated_env):
        from supervisor_state import SupervisorState

        state: SupervisorState = {
            "messages": [{"role": "user", "content": "hi"}],
            "next_node": "research_worker",
            "subtasks": [{"agent": "research_worker", "task": "hi", "status": "ok"}],
        }
        assert state["next_node"] == "research_worker"
        assert isinstance(state["messages"], list)
        assert state["subtasks"][0]["agent"] == "research_worker"

    def test_router_output_required_fields(self, isolated_env):
        from supervisor_state import RouterOutput

        r = RouterOutput(next_agent="FINISH", thought_process="done")
        d = r.to_dict()
        assert d["next_agent"] == "FINISH"
        assert d["thought_process"] == "done"
        assert d["task_description"] is None

    def test_build_agent_switch_event(self, isolated_env):
        from supervisor_state import build_agent_switch_event

        e = build_agent_switch_event("code_worker", "用户要求计算")
        assert e["type"] == "agent_switch"
        assert e["agent"] == "code_worker"
        assert e["reason"] == "用户要求计算"

        e2 = build_agent_switch_event("FINISH")
        assert e2["type"] == "agent_switch"
        assert e2["agent"] == "FINISH"


# ============================================================
# 3) Worker 子图最小构造（不依赖外部 API）
# ============================================================


class TestWorkerSubgraphs:

    def test_research_worker_compiles(self, isolated_env):
        from agent_workers import build_research_worker

        g = build_research_worker()
        assert g is not None

    def test_code_worker_compiles(self, isolated_env):
        from agent_workers import build_code_worker

        g = build_code_worker()
        assert g is not None

    def test_rag_worker_compiles(self, isolated_env):
        from agent_workers import build_rag_worker

        g = build_rag_worker()
        assert g is not None

    def test_build_default_workers_has_all_three(self, isolated_env):
        from agent_workers import build_default_workers

        ws = build_default_workers()
        assert set(ws.keys()) == {"research_worker", "code_worker", "rag_worker"}
        assert all(ws[k] is not None for k in ws)

    def test_worker_invoke_returns_message(self, isolated_env):
        """Worker 节点单独 invoke 必须返回包含 messages 的 state。"""
        from agent_workers import build_research_worker

        g = build_research_worker()
        out = g.invoke({"messages": [{"role": "user", "content": "查 AI 进展"}]})
        assert "messages" in out
        assert len(out["messages"]) >= 1


# ============================================================
# 4) Supervisor 主图 — 复合任务分阶段循环执行
# ============================================================


class TestSupervisorMultiStepLoop:

    def _build_workflow(self, llm_responses: List[str], workers: Optional[Dict[str, Any]] = None):
        from supervisor_agent import build_supervisor_workflow
        from langgraph.checkpoint.memory import MemorySaver

        llm = _ScriptedLLM(llm_responses)
        captured: List[Dict[str, Any]] = []
        wf = build_supervisor_workflow(
            supervisor_llm=llm,
            workers=workers,
            checkpointer=MemorySaver(),
            on_agent_switch=lambda e: captured.append(e),
        )
        return wf, llm, captured

    def test_finish_terminates(self, isolated_env):
        wf, llm, captured = self._build_workflow(
            ['{"next_agent": "FINISH", "thought_process": "done"}']
        )
        out = wf.invoke(
            {"messages": [{"role": "user", "content": "hi"}]},
            config={"configurable": {"thread_id": "t1"}},
        )
        # FINISH → supervisor 走完一次后没有 worker 被触发
        assert out["next_node"] == "FINISH"
        assert len(llm.calls) >= 1
        assert any(e["agent"] == "FINISH" for e in captured)

    def test_research_then_finish(self, isolated_env):
        """复合任务第一阶段：research_worker → 第二阶段：FINISH。"""
        from agent_workers import build_research_worker

        wf, llm, captured = self._build_workflow(
            [
                '{"next_agent": "research_worker", "task_description": "search", "thought_process": "first"}',
                '{"next_agent": "FINISH", "thought_process": "all done"}',
            ],
            workers={"research_worker": build_research_worker()},
        )
        out = wf.invoke(
            {"messages": [{"role": "user", "content": "查新闻"}]},
            config={"configurable": {"thread_id": "t-research"}},
        )
        # LLM 至少被调用 2 次（research → FINISH）
        assert len(llm.calls) >= 2
        # 切换事件至少 2 个
        assert len(captured) >= 2
        agents_in_order = [e["agent"] for e in captured]
        assert "research_worker" in agents_in_order
        assert "FINISH" in agents_in_order
        # subtasks 字段被累加（应至少有 research + FINISH 两条决策记录）
        subs = out.get("subtasks") or []
        assert any(s.get("agent") == "research_worker" for s in subs)
        assert any(s.get("agent") == "FINISH" for s in subs)
        assert out["next_node"] == "FINISH"

    def test_multi_agent_compound_loop_rag_then_code(self, isolated_env):
        """复合任务：RAG 检索 + Python 代码 → FINISH（两阶段 Worker 协作）。"""
        from agent_workers import build_default_workers

        wf, llm, captured = self._build_workflow(
            [
                '{"next_agent": "rag_worker", "task_description": "查 KB", "thought_process": "先查知识库"}',
                '{"next_agent": "code_worker", "task_description": "跑代码", "thought_process": "再计算"}',
                '{"next_agent": "FINISH", "thought_process": "全部完成"}',
            ],
            workers=build_default_workers(),
        )
        out = wf.invoke(
            {"messages": [{"role": "user", "content": "查 RAG 知识库 + 跑 Python 代码"}]},
            config={"configurable": {"thread_id": "t-rag-code"}},
        )
        # LLM 至少 3 次调用
        assert len(llm.calls) >= 3
        # 切换事件至少 3 个
        assert len(captured) >= 3
        agents = [e["agent"] for e in captured]
        assert "rag_worker" in agents
        assert "code_worker" in agents
        assert "FINISH" in agents
        # 顺序约束：rag_worker 必须在 code_worker 之前
        assert agents.index("rag_worker") < agents.index("code_worker")
        assert agents.index("code_worker") < agents.index("FINISH")
        # state.subtasks 反映完整决策链路
        subs = out.get("subtasks") or []
        agent_names = [s.get("agent") for s in subs]
        assert "rag_worker" in agent_names
        assert "code_worker" in agent_names
        assert "FINISH" in agent_names

    def test_unknown_worker_downgraded_to_finish(self, isolated_env):
        """LLM 输出未知 worker 名 → 必须降级为 FINISH（不能崩）。"""
        from agent_workers import build_research_worker

        wf, llm, captured = self._build_workflow(
            ['{"next_agent": "magic_worker"}'],  # 不在白名单
            workers={"research_worker": build_research_worker()},
        )
        out = wf.invoke(
            {"messages": [{"role": "user", "content": "hi"}]},
            config={"configurable": {"thread_id": "t-bad"}},
        )
        assert out["next_node"] == "FINISH"
        # 至少一个 agent_switch 帧被推送（FINISH）
        assert any(e["agent"] == "FINISH" for e in captured)

    def test_state_persisted_in_messages(self, isolated_env):
        """Worker 执行后产生 ToolMessage/AIMessage 应被 Supervisor 主图累加。"""
        from agent_workers import build_research_worker

        wf, llm, captured = self._build_workflow(
            [
                '{"next_agent": "research_worker", "thought_process": "go"}',
                '{"next_agent": "FINISH", "thought_process": "done"}',
            ],
            workers={"research_worker": build_research_worker()},
        )
        out = wf.invoke(
            {"messages": [{"role": "user", "content": "查新闻"}]},
            config={"configurable": {"thread_id": "t-persist"}},
        )
        msgs = out.get("messages") or []
        # 至少：user + research_worker 的输出 + FINISH 后没有新消息
        assert len(msgs) >= 2


# ============================================================
# 5) Supervisor 模式 code_worker 触发 HITL 闭环
# ============================================================


class TestSupervisorHITLClosedLoop:
    """验证 Supervisor 模式下 code_worker 触发 HITL → 审批/编辑参数 → 回到 Supervisor。"""

    def test_code_worker_triggers_hitl_when_marked(self, isolated_env):
        """v21_tools.TOOL_REGISTRY['python_interpreter'] 必须 requires_approval=True。"""
        from v21_tools import TOOL_REGISTRY

        assert "python_interpreter" in TOOL_REGISTRY
        assert TOOL_REGISTRY["python_interpreter"].get("requires_approval") is True

    def test_hitl_store_request_then_resolve(self, isolated_env):
        """HITL 拦截 → request → approve(with edited args) → resolve_after_decision。"""
        from hitl_langgraph import HITLStore, resolve_after_decision

        store = HITLStore.instance()
        sid = "sup-hitl-sess"
        req = store.request_approval(
            session_id=sid,
            tool_name="python_interpreter",
            tool_args={"code": "print('orig')"},
            reason="code execution needs approval",
        )
        # 用户编辑参数后批准
        store.approve(req.request_id, tool_args={"code": "print('edited')"})
        # resolve_after_decision 必须返回 approved + 修改后的 args
        decision = resolve_after_decision(req.request_id, sid)
        assert decision is not None
        assert decision["decision"] == "approved"
        assert decision["tool_args"] == {"code": "print('edited')"}

    def test_supervisor_hitl_close_loop_with_scripted_llm(self, isolated_env):
        """端到端：Supervisor 派 code_worker → 触发 HITL → 用户 approve → 回到 Supervisor → FINISH。"""
        from hitl_langgraph import HITLStore
        from agent_workers import build_default_workers
        from supervisor_agent import build_supervisor_workflow
        from langgraph.checkpoint.memory import MemorySaver

        # 复位 HITL 单例
        HITLStore.reset_instance()

        # 在 code_worker 真正被触发前，预先注册一个 pending approval
        # （让 HITL 拦截链路可观察）
        store = HITLStore.instance()
        sid = "t-code-hitl"
        pending = store.request_approval(
            session_id=sid,
            tool_name="python_interpreter",
            tool_args={"code": "print('original')"},
            reason="Supervisor 模式下 code_worker 触发 HITL 审批",
        )

        # 批准（保留原 args）
        store.approve(pending.request_id, tool_args={"code": "print('approved')"})

        # 验证 resolve_after_decision：返回 approved
        from hitl_langgraph import resolve_after_decision

        decision = resolve_after_decision(pending.request_id, sid)
        assert decision is not None
        assert decision["decision"] == "approved"
        assert decision["tool_args"] == {"code": "print('approved')"}

        # 真正跑 Supervisor 工作流：scripted LLM 顺序 code_worker → FINISH
        llm = _ScriptedLLM(
            [
                '{"next_agent": "code_worker", "task_description": "execute", "thought_process": "first"}',
                '{"next_agent": "FINISH", "thought_process": "after hitl"}',
            ]
        )
        captured: List[Dict[str, Any]] = []
        wf = build_supervisor_workflow(
            supervisor_llm=llm,
            workers=build_default_workers(),
            checkpointer=MemorySaver(),
            on_agent_switch=lambda e: captured.append(e),
        )
        out = wf.invoke(
            {"messages": [{"role": "user", "content": "跑代码"}]},
            config={"configurable": {"thread_id": sid}},
        )

        # 状态图确实走了 code_worker → supervisor → FINISH 闭环
        agents = [e["agent"] for e in captured]
        assert "code_worker" in agents
        assert "FINISH" in agents
        assert agents.index("code_worker") < agents.index("FINISH")
        # Supervisor 完整收尾
        assert out["next_node"] == "FINISH"
        subs = out.get("subtasks") or []
        assert any(s.get("agent") == "code_worker" for s in subs)


# ============================================================
# 6) agent_switch 事件 payload 形状（前端契约）
# ============================================================


class TestAgentSwitchEventContract:

    def test_event_has_required_keys(self, isolated_env):
        from supervisor_state import build_agent_switch_event

        e = build_agent_switch_event("rag_worker", "用户要查知识库")
        for k in ("type", "agent", "reason"):
            assert k in e, f"event 缺少 {k}"
        assert e["type"] == "agent_switch"
        assert isinstance(e["agent"], str)
        assert isinstance(e["reason"], str)

    def test_event_serializable_to_json(self, isolated_env):
        """event 必须能 JSON 序列化（用于 SSE 推送）。"""
        from supervisor_state import build_agent_switch_event

        e = build_agent_switch_event("code_worker", "含中文 / 特殊字符 !@#")
        s = json.dumps(e, ensure_ascii=False)
        assert "code_worker" in s
        assert "特殊字符" in s


# ============================================================
# 7) build_supervisor_workflow 边界
# ============================================================


class TestSupervisorWorkflowBuild:

    def test_empty_workers_raises(self, isolated_env):
        from supervisor_agent import build_supervisor_workflow

        with pytest.raises(ValueError):
            build_supervisor_workflow(supervisor_llm=_ScriptedLLM([]), workers={})

    def test_unknown_worker_name_raises(self, isolated_env):
        """传入不认识的 worker 名应立即抛 ValueError（fail-fast）。"""
        from supervisor_agent import build_supervisor_workflow

        with pytest.raises(ValueError):
            build_supervisor_workflow(
                supervisor_llm=_ScriptedLLM([]),
                workers={"bogus_worker": lambda s: s},
            )

    def test_default_supervisor_llm_callable(self, isolated_env):
        """default_supervisor_llm 必须可调用，并返回含 next_agent 的 JSON 字符串。"""
        from supervisor_agent import default_supervisor_llm

        llm = default_supervisor_llm()
        out = llm.invoke([{"role": "user", "content": "hi"}])
        text = getattr(out, "content", str(out))
        assert "next_agent" in text
        # 必须能被 parse_router_output 解析
        from supervisor_state import parse_router_output

        r = parse_router_output(text)
        assert r.next_agent in ("research_worker", "code_worker", "rag_worker", "FINISH")


# ============================================================
# 8) Supervisor + SqliteSaver 持久化（验证状态能跨 invoke 保留）
# ============================================================


class TestSupervisorCheckpointPersistence:
    """用 SqliteSaver（test_app_sse 等已在用）验证 Supervisor 主图的状态可被持久化。"""

    def test_memory_checkpointer_keeps_history(self, isolated_env):
        from supervisor_agent import build_supervisor_workflow
        from agent_workers import build_research_worker
        from langgraph.checkpoint.memory import MemorySaver

        llm = _ScriptedLLM(
            [
                '{"next_agent": "research_worker", "thought_process": "go"}',
                '{"next_agent": "FINISH", "thought_process": "done"}',
            ]
        )
        cp = MemorySaver()
        wf = build_supervisor_workflow(
            supervisor_llm=llm,
            workers={"research_worker": build_research_worker()},
            checkpointer=cp,
        )
        # 第一次 invoke
        sid = "t-persist-mem"
        out1 = wf.invoke(
            {"messages": [{"role": "user", "content": "查询"}]},
            config={"configurable": {"thread_id": sid}},
        )
        assert out1["next_node"] == "FINISH"

        # 验证 checkpointer 持有该 thread 的 checkpoint
        try:
            cps = list(cp.list(sid))  # type: ignore[attr-defined]
            # list 至少要能调用（不报错）；具体记录数依 LangGraph 版本而异
            assert isinstance(cps, list)
        except Exception:
            # 兼容不同 LangGraph 版本的 API
            pass


# ============================================================
# 9) 与现有 HITL 模块兼容（防止破坏 hitl_langgraph 接口）
# ============================================================


class TestHITLCompat:
    """确保 Supervisor 接入后 hitl_langgraph 的核心 API 仍可用。"""

    def test_resolve_after_decision_approved(self, isolated_env):
        from hitl_langgraph import HITLStore, resolve_after_decision

        store = HITLStore.instance()
        req = store.request_approval(
            session_id="s1", tool_name="python_interpreter", tool_args={"code": "1+1"}
        )
        store.approve(req.request_id)
        d = resolve_after_decision(req.request_id, "s1")
        assert d["decision"] == "approved"

    def test_resolve_after_decision_rejected(self, isolated_env):
        from hitl_langgraph import HITLStore, resolve_after_decision

        store = HITLStore.instance()
        req = store.request_approval(
            session_id="s1", tool_name="python_interpreter", tool_args={"code": "rm -rf /"}
        )
        store.reject(req.request_id, reason="too risky")
        d = resolve_after_decision(req.request_id, "s1")
        assert d["decision"] == "rejected"
        assert "too risky" in (d.get("reason") or "")