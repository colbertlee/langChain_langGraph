"""长期守护：_accept 适配器 + fixtures + agent_end_to_end runner（PR3-9 / PR16）。"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.builtin_runners import _accept  # noqa: E402
from evals.registry import EvalRegistry, CaseResult  # noqa: E402
from evals.harness._fixtures import FakeAgent, FakeLLM, make_trajectory, isolated_env_func, DEFAULT_FAKE_KEYS  # noqa: E402
from evals.harness_api import run_case  # noqa: E402
from agent import AIAgent, Hooks, Event  # noqa: E402


def test_accept_legacy_runner_wraps():
    """PR3：旧 runner(case) 被 _accept 包成新协议。"""
    def legacy(case):
        return CaseResult(
            name=case["name"], category=case["category"], passed=True,
            duration_ms=0.0, detail="ok",
        )
    wrapped = _accept(legacy)
    sig = inspect.signature(wrapped)
    # 至少含 hooks / budget / agent / dry_run 形参
    for k in ("hooks", "budget", "agent", "dry_run"):
        assert k in sig.parameters, f"missing {k} in {sig}"
    # 旧 runner 行为不变
    cr = wrapped({"name": "x", "category": "y"}, None, None, None, False)
    assert cr.passed


def test_accept_new_runner_unchanged():
    """PR3：新协议 runner（接受 hooks）原样返回。"""
    def newone(case, hooks=None, budget=None, agent=None, dry_run=False):
        return CaseResult(
            name=case["name"], category=case["category"], passed=True,
            duration_ms=0.0, detail="new",
        )
    wrapped = _accept(newone)
    assert wrapped is newone


def test_accept_legacy_drops_extra_args():
    """PR3+PR11：旧 runner 接收 dry_run=True 不应崩。"""
    def legacy(case):
        return CaseResult(
            name=case["name"], category=case["category"], passed=True,
            duration_ms=0.0, detail="ok",
        )
    wrapped = _accept(legacy)
    cr = wrapped({"name": "x", "category": "y"}, None, None, None, True)
    assert cr.passed


def test_fake_agent_default_echo():
    """PR8：FakeAgent.run_task 默认 echo。"""
    out = FakeAgent().run_task("hi")
    assert out.final == "echo: hi"


def test_fake_agent_response_map():
    """PR8：FakeAgent 优先用 response_map。"""
    fa = FakeAgent(response_map={"ping": "pong"})
    assert fa.run_task("ping").final == "pong"
    assert fa.run_task("anything").final == "echo: anything"


def test_fake_agent_raise():
    """PR8：FakeAgent raise_exc 触发异常。"""
    fa = FakeAgent(raise_exc=ValueError("bad"))
    try:
        fa.run_task("x")
        assert False
    except ValueError:
        pass


def test_fake_agent_emits_hooks():
    """PR8：FakeAgent.run_task 触发 hooks.on_event。"""
    captured = []
    FakeAgent().run_task("hi", hooks=Hooks(on_event=lambda e: captured.append(e.kind)))
    assert "turn_start" in captured and "final" in captured


def test_fake_llm_counts_calls():
    """PR8：FakeLLM 计数。"""
    llm = FakeLLM(response="hi")
    llm.invoke("x")
    llm.invoke("y")
    assert len(llm.calls) == 2


def test_isolated_env_func_returns_keys():
    """PR4：isolated_env_func 单一真相源。"""
    keys = isolated_env_func()
    assert keys == DEFAULT_FAKE_KEYS


def test_run_case_with_fake_agent_and_dry_run():
    """PR9 / PR11：run_case + fake_agent + dry_run=True → final=""。"""
    cr = run_case(
        {"name": "e2e", "category": "agent_end_to_end",
         "input": "hi", "expected_output": "echo"},
        agent=FakeAgent(),
        dry_run=True,
    )
    assert not cr.passed  # final="" 不命中 "echo"


def test_run_agent_end_to_end_runner_registered():
    """PR16：agent_end_to_end runner 在独立模块，但仍被注册。"""
    assert "agent_end_to_end" in EvalRegistry.all_categories()
    from evals.runners.agent_end_to_end import run_agent_end_to_end
    assert callable(run_agent_end_to_end)


def test_run_agent_end_to_end_with_real_detect_intent():
    """PR13 + PR16：AIAgent 注入时，runner 注入 intent 事件。"""
    cr = run_case(
        {"name": "e2e_intent", "category": "agent_end_to_end",
         "input": "你好", "expected_intent": "greeting"},
        agent=AIAgent(),
    )
    assert cr.passed
