"""长期守护：run_task 行为契约（PR1 / PR7 / PR10 / PR11 / PR12 / PR15）。

注：run_task 调 self.run()；本文件用 SlowAIAgent / RaisingAIAgent 替换 AIAgent.run，
而不依赖真实 LLM。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import AIAgent, Hooks, Event, Budget  # noqa: E402


def _make_event_capture():
    return Hooks(on_event=lambda e: _CAPTURED.append(e.kind))


_CAPTURED: list = []


class SlowAIAgent(AIAgent):
    """run() 同步 sleep 200ms，用于触发 timeout。"""

    def run(self, user_input, session_id=None):
        time.sleep(0.2)
        return "slow result"


class RaisingAIAgent(AIAgent):
    """run() 抛异常，用于触发 error 路径。"""

    def run(self, user_input, session_id=None):
        raise RuntimeError("boom")


def test_run_task_event_sequence():
    """PR7：events 包含 turn_start → final。"""
    global _CAPTURED
    _CAPTURED = []
    a = AIAgent()
    t = a.run_task("hi", hooks=_make_event_capture())
    assert [e.kind for e in t.events] == ["turn_start", "final"]
    assert t.error is None
    assert t.final  # graceful 错误也算非空


def test_run_task_hooks_on_event_called():
    """PR7：hooks.on_event 在每次 emit 时被调。"""
    captured = []
    a = AIAgent()
    a.run_task("hi", hooks=Hooks(on_event=lambda e: captured.append(e.kind)))
    assert "turn_start" in captured and "final" in captured


def test_run_task_dry_run_short_circuit():
    """PR11：dry_run=True → 不调 run()，直接返回空 final + dry_run 事件。"""
    captured = []
    a = SlowAIAgent()
    t = a.run_task("hi", dry_run=True, hooks=Hooks(on_event=lambda e: captured.append(e.kind)))
    # 不会被 sleep 200ms 阻塞
    assert t.final == ""
    assert t.error is None
    assert "dry_run" in captured
    assert "final" not in captured  # 业务路径没跑


def test_run_task_timeout_marker():
    """PR10：timeout_s < 实际跑时 → 标 TimeoutError + timeout 事件。"""
    a = SlowAIAgent()
    t = a.run_task("hi", budget=Budget(timeout_s=0.05))
    assert t.error is not None and "TimeoutError" in t.error
    assert t.final == ""
    assert "timeout" in [e.kind for e in t.events]


def test_run_task_budget_exceeded_tokens():
    """PR12：max_tokens 极小 + 较长 final → BudgetExhaustedError。"""
    a = AIAgent()
    # 输入文本较长，会让 final 长度 > 4 chars
    long_input = "这是一个测试文本，应该让 final 长度超过 1 个 token"
    t = a.run_task(long_input, budget=Budget(max_tokens=1))
    assert t.error is not None and "BudgetExhaustedError" in t.error
    assert "budget_exceeded" in [e.kind for e in t.events]


def test_run_task_exception_path():
    """PR7：run() 抛异常 → error 事件 + 兜底。"""
    global _CAPTURED
    _CAPTURED = []
    a = RaisingAIAgent()
    t = a.run_task("hi", hooks=_make_event_capture())
    assert t.error is not None and "RuntimeError" in t.error
    assert t.final == ""
    assert "error" in [e.kind for e in t.events]


def test_run_task_extra_events_bridge():
    """PR15：hooks.extra_events 注入 llm_result → Used.tokens/cost_usd 真实化。"""
    extra = []

    def hook(ev):
        if ev.kind == "turn_start":
            extra.append(Event(
                kind="llm_result", name="injected",
                payload={"tokens": 42, "cost_usd": 0.0007},
            ))

    a = AIAgent()
    t = a.run_task("hi", hooks=Hooks(on_event=hook, extra_events=extra))
    assert t.used.tokens == 42
    assert abs(t.used.cost_usd - 0.0007) < 1e-9


def test_run_task_no_hooks_still_records_events():
    """PR1：未传 hooks 时 events 仍写入。"""
    a = AIAgent()
    t = a.run_task("hi")
    assert len(t.events) >= 2  # turn_start + final
    assert [e.kind for e in t.events[:1]] == ["turn_start"]
