"""evals/runners/agent_end_to_end.py — PR16 拆分。

原先位于 ``evals/builtin_runners.py`` 的 ``run_agent_end_to_end`` runner
放到这里，让 ``builtin_runners`` 收窄为"规则化 / 工具类"分类 runner。

协议与字段不变（PR1-15 已稳定的契约）：
- 接受 ``hooks`` / ``budget`` / ``agent`` / ``dry_run``；
- ``agent is None`` 时默认走 ``FakeAgent``（PR9）；
- ``dry_run=True`` 时直接返回空 final（PR11）；
- ``score`` 之前会注入 ``intent`` 事件（PR13）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from evals.registry import CaseResult, EvalRegistry


@EvalRegistry.register("agent_end_to_end")
def run_agent_end_to_end(
    case: Dict[str, Any],
    hooks: Optional[Any] = None,
    budget: Optional[Any] = None,
    agent: Optional[Any] = None,
    dry_run: bool = False,
) -> CaseResult:
    """通过 ``agent.run_task`` 跑一条 catriage → harness 评分。

    协议：新协议 runner（接受 hooks/budget/agent/dry_run）。
    - **PR9** 行为契约：
      - ``agent`` 注入优先级最高；测试 / CI 注入 fake agent 即可正式跑分。
      - ``agent is None`` 时，本函数改为 ``FakeAgent``（来自
        ``evals.harness._fixtures``），**不再自建 ``AIAgent()``**——
        保证 ``evals/`` 内部跑分不需要真实 LLM。
      - 单测场景若要测真实流程，仍可直接调用 ``AIAgent.run_task``，与本 runner 无关。
    - **PR11** 行为契约：
      - ``dry_run=True`` 时直接构造空 final，**不调 ``agent.run_task``**。
      - 默认 ``dry_run=False``：按业务路径跑（依旧使用 FakeAgent）。
    - **PR13** 行为契约：
      - 如果 ``agent`` 有 ``_detect_intent`` 方法（真实 ``AIAgent`` 有，
        ``FakeAgent`` 没有），runner 会把 intent 写入 ``Trajectory.events``，
        便于下游 ``score`` 走 ``expected_intent`` 维度。

    case 字段：
    - ``input`` (str, 必填)
    - ``expected_output`` / ``expect_blocked`` / ``expect_error`` / ``max_duration_ms``
      / ``expected_intent``（任选；评分由 ``evals.harness_api.score`` 完成）
    """
    from evals.harness_api import score  # 本地 import，避免 evals 包初始化时环

    text = str(case.get("input", ""))
    if not text:
        return CaseResult(
            name=str(case.get("name", "unknown")),
            category="agent_end_to_end",
            passed=False,
            duration_ms=0.0,
            detail="case missing 'input'",
        )

    # PR9：默认走 FakeAgent（不再自建 AIAgent）。
    if agent is None:
        from evals.harness._fixtures import FakeAgent
        agent = FakeAgent()

    # PR11：dry_run=True 时直接构造空 final。
    if dry_run:
        from evals.harness._fixtures import make_trajectory
        traj = make_trajectory("")
    else:
        traj = agent.run_task(text, hooks=hooks, budget=budget, dry_run=dry_run)

    # PR13：补 intent 事件（仅当 agent 有 _detect_intent 时）。
    if hasattr(agent, "_detect_intent"):
        try:
            intent, _ = agent._detect_intent(text)
            from agent import Event
            traj.events.append(Event(
                kind="intent", name="agent._detect_intent",
                payload={"intent": intent},
            ))
        except Exception:
            # intent 抽取失败不致命；score 兜底会标 got_intent=None
            pass

    return score(traj, case)


__all__ = ["run_agent_end_to_end"]
