"""长期守护：Event/Hooks/Budget/Used/Trajectory dataclass 形态（PR1 / PR15）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import Event, Hooks, Budget, Used, Trajectory  # noqa: E402


def test_event_fields():
    """PR1：Event(kind, name, payload, ts_ms) 字段。"""
    e = Event(kind="final", name="run", payload="hello", ts_ms=1.5)
    assert e.kind == "final" and e.name == "run"
    assert e.payload == "hello" and e.ts_ms == 1.5
    # 默认值
    e2 = Event(kind="x")
    assert e2.name == "" and e2.payload is None and e2.ts_ms == 0.0


def test_hooks_fields():
    """PR1 + PR15：Hooks 包含 on_event / on_tool_call / on_score / extra_events。"""
    h = Hooks()
    assert h.on_event is None and h.on_tool_call is None and h.on_score is None
    assert h.extra_events is None  # PR15

    extra = []
    h2 = Hooks(on_event=lambda e: None, extra_events=extra)
    assert h2.extra_events is extra


def test_budget_defaults():
    """PR1 / PR10 / PR12：Budget 全部默认 0 = 不限。"""
    b = Budget()
    assert b.timeout_s == 0.0
    assert b.max_tokens == 0
    assert b.max_cost_usd == 0.0


def test_used_defaults():
    """PR1 / PR15：Used 默认值。"""
    u = Used()
    assert u.elapsed_s == 0.0 and u.tokens == 0 and u.cost_usd == 0.0


def test_trajectory_defaults():
    """PR1：Trajectory 默认空 events / 空 final / 无 error。"""
    t = Trajectory()
    assert t.events == [] and t.final is None and t.error is None
    assert isinstance(t.used, Used)
