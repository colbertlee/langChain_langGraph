"""
Headless Runner — 把 HeadlessAgent 接入 EvalRegistry。

设计
----
- 注册 category ``"headless"``：case 走 ``HeadlessAgent.stream()``；
- 注册 category ``"headless_sync"``：case 走 ``HeadlessAgent.run()``（一次性文本）；
- runner 接收 ``CaseResult`` 风格的 case dict，包含：

  ::

      {
        "name": "qa_001",
        "category": "headless",         # 或 "headless_sync"
        "input": "介绍一下 LangChain",
        "expected": "...",              # 可选
        "expect_substring": "LangChain",  # 可选
        "expect_min_tokens": 5,         # 可选（基于 TOKEN.delta 总长）
        "expect_event_types": ["token", "done"],  # 可选（必须包含）
        "headless": {                   # 可选，HeadlessAgent 配置
            "hitl": "auto",             # "auto" | "no" | 自定义 adapter 路径
            "agent": None,              # 注入 AIAgent；None 时懒加载
        }
      }

- runner 返回 ``CaseResult``：passed 由断言规则计算，detail 包含 HeadlessEvent 摘要。

为什么独立 category 而不是改 agent_end_to_end
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- agent_end_to_end 走 ``AIAgent.run_task()``（harness 协议），
  适合"轨迹/预算/budget/dry_run"等评测；
- headless_runner 走 ``HeadlessAgent.stream()``（headless 协议），
  适合"事件流断言 / SSE 兼容性 / 多 Agent 编排"等 headless-only 评测；
- 两者并存，调用方按 case 类型选择。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from evals.registry import CaseResult, EvalRegistry

logger = logging.getLogger(__name__)


# ============================================================
# 共享：构造 HeadlessAgent
# ============================================================

def _build_headless_agent(spec: Optional[Dict[str, Any]]) -> Any:
    """从 case.headless spec 构造 HeadlessAgent。"""
    from headless_agent import AutoHITL, HeadlessAgent, NoHITL

    spec = spec or {}
    base_agent = spec.get("agent")  # 允许注入（测试用）

    hitl_spec = spec.get("hitl", "auto")
    if hitl_spec == "auto":
        hitl = AutoHITL()
    elif hitl_spec == "no":
        hitl = NoHITL()
    else:
        # 留口子：未来支持传入可调用对象路径
        hitl = AutoHITL()

    return HeadlessAgent(agent=base_agent, hitl=hitl)


# ============================================================
# 断言
# ============================================================

def _evaluate_assertions(
    events: List[Any],
    expected_text: str,
    *,
    expect_substring: Optional[str] = None,
    expect_min_tokens: Optional[int] = None,
    expect_event_types: Optional[List[str]] = None,
) -> tuple[bool, str]:
    """跑全部断言；返回 (passed, detail)。"""
    token_total = sum(
        len(ev.data.get("delta", ""))
        for ev in events
        if ev.type.value == "token"
    )

    # 拼接最终文本（用 DONE.final_text 优先，TOKEN 兜底）
    final_text = ""
    seen_done = False
    for ev in events:
        if ev.type.value == "token":
            final_text += ev.data.get("delta", "")
        elif ev.type.value == "done" and not seen_done:
            seen_done = True
            ft = ev.data.get("final_text")
            if ft and len(final_text) < len(ft):
                final_text = ft

    # expected 字符串匹配（精确相等）
    if expected_text and final_text.strip() != expected_text.strip():
        return False, (
            f"text mismatch: expected={expected_text!r} "
            f"actual={final_text[:80]!r}"
        )

    # expect_substring
    if expect_substring and expect_substring not in final_text:
        return False, (
            f"missing substring {expect_substring!r} in "
            f"actual={final_text[:80]!r}"
        )

    # expect_min_tokens
    if expect_min_tokens is not None and token_total < expect_min_tokens:
        return False, (
            f"token total {token_total} < expected min {expect_min_tokens}"
        )

    # expect_event_types
    if expect_event_types:
        present = {ev.type.value for ev in events}
        missing = [t for t in expect_event_types if t not in present]
        if missing:
            return False, f"missing event types: {missing}"

    return True, f"final_len={len(final_text)}, tokens={token_total}"


# ============================================================
# async runner：headless category
# ============================================================

@EvalRegistry.register("headless")
async def run_headless(case: Dict[str, Any]) -> CaseResult:
    """异步跑一次 HeadlessAgent.stream()，做断言。"""
    name = case.get("name", "headless_case")
    user_input = case.get("input") or case.get("description") or ""
    headless_spec = case.get("headless")

    t0 = time.monotonic()
    detail = ""
    passed = False
    observed: Any = None
    try:
        agent = _build_headless_agent(headless_spec)
        events: list[Any] = []
        async for ev in agent.stream(user_input):
            events.append(ev)
        # 必须有 DONE
        if not any(ev.type.value == "done" for ev in events):
            detail = "stream ended without DONE"
        else:
            passed, detail = _evaluate_assertions(
                events,
                expected_text=case.get("expected", ""),
                expect_substring=case.get("expect_substring"),
                expect_min_tokens=case.get("expect_min_tokens"),
                expect_event_types=case.get("expect_event_types"),
            )
        # 摘要放进 observed
        observed = {
            "event_count": len(events),
            "by_type": {
                t: sum(1 for ev in events if ev.type.value == t)
                for t in {ev.type.value for ev in events}
            },
        }
    except Exception as e:
        detail = f"runner exception: {type(e).__name__}: {e}"
        passed = False

    return CaseResult(
        name=name,
        category="headless",
        passed=passed,
        duration_ms=(time.monotonic() - t0) * 1000.0,
        detail=detail,
        observed=observed,
    )


# ============================================================
# 同步 runner：headless_sync category
# ============================================================

def _run_headless_sync(case: Dict[str, Any]) -> CaseResult:
    """同步包装：内部走 asyncio.run。"""
    return asyncio.run(run_headless(case))


@EvalRegistry.register("headless_sync")
def run_headless_sync(case: Dict[str, Any]) -> CaseResult:
    """同步跑 HeadlessAgent.run()。"""
    name = case.get("name", "headless_sync_case")
    user_input = case.get("input") or case.get("description") or ""

    t0 = time.monotonic()
    detail = ""
    passed = False
    final_text = ""
    try:
        agent = _build_headless_agent(case.get("headless"))
        # run() 是 async，但 CaseResult 不要求 async runner；
        # 用 asyncio.run 桥接
        final_text = asyncio.run(agent.run(user_input))
        # 同步 runner 只能断言字符串
        expect_substring = case.get("expect_substring")
        expected = case.get("expected", "")
        if expected and final_text.strip() != expected.strip():
            passed = False
            detail = f"text mismatch: expected={expected!r} actual={final_text[:80]!r}"
        elif expect_substring and expect_substring not in final_text:
            passed = False
            detail = f"missing substring {expect_substring!r}"
        else:
            passed = True
            detail = f"final_len={len(final_text)}"
    except Exception as e:
        detail = f"runner exception: {type(e).__name__}: {e}"
        passed = False

    return CaseResult(
        name=name,
        category="headless_sync",
        passed=passed,
        duration_ms=(time.monotonic() - t0) * 1000.0,
        detail=detail,
        observed={"final_text": final_text[:200] if final_text else ""},
    )


__all__ = ["run_headless", "run_headless_sync"]