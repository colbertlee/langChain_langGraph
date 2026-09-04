"""
Harness 门面单元测试(纯 fake,不调真实 LLM/DB)。

覆盖:
- HarnessConfig / Trace / TraceStep 数据模型
- run() / run_stream() 同步与流式入口
- 注入子模块路径(security / permission / memory / observability 都会被调用并打点)
- 防御性降级:任意子模块抛异常,Harness 不崩
- 空 prompt 直接短路
- enabled_modules 反映当前启用状态
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

import pytest

_AI_AGENT = Path(__file__).resolve().parent.parent
if str(_AI_AGENT) not in sys.path:
    sys.path.insert(0, str(_AI_AGENT))

from harness import Harness, HarnessConfig, Trace, TraceStep  # noqa: E402


# ============================================================
# Fixtures
# ============================================================

class FakeAgent:
    """模拟 AIAgent:支持 run() / run_stream()。"""
    def __init__(self, text: str = "ok") -> None:
        self.text = text
        self.calls: list[tuple[str, str]] = []

    def run(self, prompt: str, session_id=None, **kwargs) -> str:
        self.calls.append((prompt, session_id or ""))
        return self.text

    def run_stream(self, prompt: str, session_id=None, **kwargs) -> Iterator[str]:
        self.calls.append((prompt, session_id or ""))
        for c in self.text:
            yield c


class FakeSecurity:
    def __init__(self, allow: bool = True, reason: str = "") -> None:
        self.allow = allow
        self.reason = reason
        self.calls: list[str] = []

    def check_input(self, prompt: str):
        self.calls.append(prompt)
        return (self.allow, self.reason)


class FakeMemory:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def record(self, session_id: str, role: str, content: str) -> None:
        self.records.append({"session_id": session_id, "role": role, "content": content})


class FakeObservability:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, float, dict]] = []

    def record_metric(self, name: str, value: float, tags: dict | None = None) -> None:
        self.metrics.append((name, value, tags or {}))


class FakePermission:
    def check(self, prompt: str):
        class _D:
            allowed = True
        return _D()


class FakePlanner:
    def __init__(self, steps=None) -> None:
        self.steps = steps or ["step1", "step2"]

    def plan(self, prompt: str):
        return list(self.steps)


# ============================================================
# 数据模型
# ============================================================

def test_config_defaults():
    cfg = HarnessConfig()
    assert cfg.sandbox == "off"
    assert cfg.enable_memory is True
    assert cfg.enable_observability is True
    assert cfg.enable_planner is False
    assert cfg.session_id is None


def test_trace_to_dict_minimal():
    t = Trace(session_id="s", prompt="hi", started_at="2026-09-04T00:00:00")
    t.steps.append(TraceStep(stage="security", name="intent_check",
                              started_at=0.0, duration_ms=1.0, status="ok"))
    d = t.to_dict()
    assert d["session_id"] == "s"
    assert d["steps"][0]["stage"] == "security"
    assert d["steps"][0]["duration_ms"] == 1.0


# ============================================================
# 基本入口
# ============================================================

def test_run_empty_prompt_returns_error():
    h = Harness(agent=FakeAgent())
    out = h.run("   ")
    assert "❌" in out
    assert h.last_trace is None  # 短路不打 trace


def test_run_basic_agent_only():
    h = Harness(agent=FakeAgent("hello"))
    out = h.run("hi")
    assert out == "hello"
    assert h.last_trace is not None
    assert h.last_trace.output == "hello"
    # 默认 enable_observability=True,无注入时会 lazy 加载
    # 子模块不可用时直接跳过,不影响主流程


def test_run_stream_basic():
    h = Harness(agent=FakeAgent("ABC"))
    chunks = list(h.run_stream("hi"))
    assert "".join(chunks) == "ABC"
    assert h.last_trace.output == "ABC"


def test_run_stream_empty_prompt():
    h = Harness(agent=FakeAgent())
    out = list(h.run_stream(""))
    assert len(out) == 1
    assert "❌" in out[0]


def test_run_agent_exception_returns_error():
    class Boom:
        def run(self, prompt, session_id=None, **kwargs):
            raise RuntimeError("agent boom")
    h = Harness(agent=Boom())
    out = h.run("hi")
    assert "Harness error" in out
    assert "agent boom" in out
    assert h.last_trace is not None
    assert h.last_trace.error and "agent boom" in h.last_trace.error


def test_run_stream_agent_exception_yields_then_stops():
    class Boom:
        def run_stream(self, prompt, session_id=None, **kwargs):
            yield "partial-"
            raise RuntimeError("stream boom")
    h = Harness(agent=Boom())
    chunks = list(h.run_stream("hi"))
    assert "".join(chunks).startswith("partial-")
    assert h.last_trace.error and "stream boom" in h.last_trace.error


# ============================================================
# session_id 管理
# ============================================================

def test_session_id_explicit():
    h = Harness(agent=FakeAgent(), config=HarnessConfig(session_id="user-42"))
    h.run("hi")
    assert h.last_trace.session_id == "user-42"


def test_session_id_auto_generated_unique():
    h = Harness(agent=FakeAgent())
    h.run("a")
    s1 = h.last_trace.session_id
    h.run("b")
    s2 = h.last_trace.session_id
    assert s1.startswith("harness-")
    assert s2.startswith("harness-")
    assert s1 != s2


# ============================================================
# 子模块注入 + 打点
# ============================================================

def test_security_injected_recorded_in_trace():
    sec = FakeSecurity(allow=True)
    h = Harness(agent=FakeAgent(), security=sec)
    h.run("hi")
    assert len(sec.calls) == 1
    security_steps = [s for s in h.last_trace.steps if s.stage == "security"]
    assert len(security_steps) == 1
    assert security_steps[0].status == "ok"


def test_security_blocking_recorded_as_fail():
    sec = FakeSecurity(allow=False, reason="blocked")
    h = Harness(agent=FakeAgent(), security=sec)
    h.run("bad")
    sec_steps = [s for s in h.last_trace.steps if s.stage == "security"]
    assert sec_steps[0].status == "fail"
    assert sec_steps[0].detail.get("reason") == "blocked"


def test_security_disabled_by_config():
    """config.enable_security=False → 完全跳过安全检查,不打点。"""
    h = Harness(agent=FakeAgent(),
                config=HarnessConfig(enable_security=False))
    h.run("hi")
    sec_steps = [s for s in h.last_trace.steps if s.stage == "security"]
    assert sec_steps == []


def test_memory_records_user_and_assistant():
    mem = FakeMemory()
    h = Harness(agent=FakeAgent("reply"), memory_store=mem)
    h.run("hi")
    assert len(mem.records) == 2
    assert mem.records[0]["role"] == "user"
    assert mem.records[1]["role"] == "assistant"
    assert mem.records[0]["content"] == "hi"
    assert mem.records[1]["content"] == "reply"


def test_memory_disabled_no_calls():
    mem = FakeMemory()
    h = Harness(agent=FakeAgent(), memory_store=mem,
                config=HarnessConfig(enable_memory=False))
    h.run("hi")
    assert mem.records == []


def test_observability_records_metrics():
    obs = FakeObservability()
    h = Harness(agent=FakeAgent("x"), observability=obs)
    h.run("hi")
    names = [m[0] for m in obs.metrics]
    assert "harness.run.complete" in names
    assert "harness.run.output_len" in names


def test_planner_records_steps_when_enabled():
    h = Harness(agent=FakeAgent(), planner=FakePlanner(["a", "b", "c"]),
                config=HarnessConfig(enable_planner=True))
    h.run("hi")
    plan_steps = [s for s in h.last_trace.steps if s.stage == "planner"]
    assert len(plan_steps) == 1
    assert plan_steps[0].detail["steps"] == 3


def test_permission_check_recorded():
    h = Harness(agent=FakeAgent(), permission=FakePermission())
    h.run("hi")
    perm_steps = [s for s in h.last_trace.steps if s.stage == "permission"]
    assert len(perm_steps) == 1
    assert perm_steps[0].status == "ok"


def test_sandbox_off_skipped():
    h = Harness(agent=FakeAgent(), config=HarnessConfig(sandbox="off"))
    h.run("hi")
    sb_steps = [s for s in h.last_trace.steps if s.stage == "sandbox"]
    assert sb_steps == []


# ============================================================
# 防御性降级:子模块抛异常不崩
# ============================================================

def test_security_exception_does_not_crash():
    class BadSec:
        def check_input(self, prompt):
            raise RuntimeError("sec boom")
    h = Harness(agent=FakeAgent(), security=BadSec())
    out = h.run("hi")  # 不应抛
    assert out == "ok"  # 主流程继续
    sec_step = [s for s in h.last_trace.steps if s.stage == "security"][0]
    assert sec_step.status == "fail"
    assert "sec boom" in sec_step.detail["error"]


def test_memory_exception_does_not_crash():
    class BadMem:
        def record(self, session_id, role, content):
            raise RuntimeError("mem boom")
    h = Harness(agent=FakeAgent(), memory_store=BadMem())
    out = h.run("hi")
    assert out == "ok"
    mem_step = [s for s in h.last_trace.steps if s.stage == "memory"][0]
    assert mem_step.status == "fail"


def test_observability_exception_does_not_crash():
    class BadObs:
        def record_metric(self, name, value, tags=None):
            raise RuntimeError("obs boom")
    h = Harness(agent=FakeAgent(), observability=BadObs())
    out = h.run("hi")
    assert out == "ok"
    obs_step = [s for s in h.last_trace.steps if s.stage == "observability"][0]
    assert obs_step.status == "fail"


def test_planner_exception_does_not_crash():
    class BadPlanner:
        def plan(self, prompt):
            raise RuntimeError("planner boom")
    h = Harness(agent=FakeAgent(), planner=BadPlanner(),
                config=HarnessConfig(enable_planner=True))
    out = h.run("hi")
    assert out == "ok"
    p_step = [s for s in h.last_trace.steps if s.stage == "planner"][0]
    assert p_step.status == "fail"


# ============================================================
# enabled_modules 反射
# ============================================================

def test_enabled_modules_reflects_config():
    cfg = HarnessConfig(
        session_id="s", sandbox="standard",
        enable_planner=True, enable_memory=False,
        enable_observability=True, enable_security=False,
    )
    h = Harness(agent=FakeAgent(), config=cfg)
    em = h.enabled_modules
    assert em["agent"] is True
    assert em["planner"] is True
    assert em["memory"] is False
    assert em["observability"] is True
    assert em["security"] is False
    assert em["sandbox"] is True  # sandbox="standard" → on


def test_from_config_shortcut():
    h = Harness.from_config(HarnessConfig(session_id="u1"))
    assert h.config.session_id == "u1"