"""长期守护：harness_api（PR2 / PR6 / PR11 / PR13 / PR15）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.harness_api import run_case, run_suite, score  # noqa: E402
from evals.harness._fixtures import FakeAgent, make_trajectory  # noqa: E402
from agent import Event, Trajectory  # noqa: E402


def test_run_case_intent_routing():
    """PR2：旧 runner 仍正常。"""
    cr = run_case({
        "name": "intent_greet", "category": "intent_routing",
        "input": "你好", "expected_intent": "greeting",
    })
    assert cr.passed


def test_run_case_calculator_with_tolerance():
    """PR2：calculator runner + tolerance 评分。"""
    cr = run_case({
        "name": "calc", "category": "calculator",
        "input": "1+2", "expected_output": 3, "tolerance": 0.0,
    })
    assert cr.passed


def test_run_case_with_fake_agent():
    """PR6：run_case 注入 fake agent。"""
    cr = run_case(
        {"name": "e2e", "category": "agent_end_to_end",
         "input": "hi", "expected_output": "echo"},
        agent=FakeAgent(),
    )
    assert cr.passed


def test_run_case_dry_run_env_var(monkeypatch):
    """PR11：HARNESS_DRY_RUN=1 → final="" → expected_output 不命中。"""
    monkeypatch.setenv("HARNESS_DRY_RUN", "1")
    cr = run_case(
        {"name": "e2e_dry", "category": "agent_end_to_end",
         "input": "hi", "expected_output": "echo"},
        agent=FakeAgent(),
    )
    assert not cr.passed
    assert "expected_output substring not found" in cr.detail


def test_run_case_dry_run_explicit_wins(monkeypatch):
    """PR11：显式 dry_run=False 优先于环境变量。"""
    monkeypatch.setenv("HARNESS_DRY_RUN", "1")
    cr = run_case(
        {"name": "e2e_explicit", "category": "agent_end_to_end",
         "input": "hi", "expected_output": "echo"},
        agent=FakeAgent(),
        dry_run=False,
    )
    assert cr.passed


def test_run_suite_writes_artifacts(tmp_path):
    """PR2：run_suite 落盘 summary.json + cases.jsonl。"""
    cases = [
        {"name": "intent_greet", "category": "intent_routing",
         "input": "你好", "expected_intent": "greeting"},
        {"name": "calc", "category": "calculator",
         "input": "1+2", "expected_output": 3},
    ]
    sm = run_suite(cases, out_dir=str(tmp_path / "demo"))
    assert sm["cases_passed"] == 2
    # 落盘结构
    assert (tmp_path / "demo" / "summary.json").exists()
    assert (tmp_path / "demo" / "cases.jsonl").exists()
    summary = json.loads((tmp_path / "demo" / "summary.json").read_text(encoding="utf-8"))
    assert summary["cases_total"] == 2


def test_score_expected_intent_from_events():
    """PR13：score 从 trajectory.events 找 intent。"""
    t = Trajectory(
        events=[Event(kind="intent", name="x", payload={"intent": "greeting"})],
        final="hello",
    )
    cr = score(t, {"name": "t", "expected_intent": "greeting"})
    assert cr.passed

    cr2 = score(t, {"name": "t", "expected_intent": "calculate"})
    assert not cr2.passed


def test_score_expected_output_substring():
    """PR2：expected_output substring 匹配。"""
    t = make_trajectory(final="结果是 3.14")
    cr = score(t, {"name": "t", "expected_output": "3.14"})
    assert cr.passed


def test_score_expected_output_numeric():
    """PR2：expected_output 数值 + tolerance。"""
    t = make_trajectory(final="结果是 3.14")
    cr = score(t, {"name": "t", "expected_output": 3.14, "tolerance": 0.01})
    assert cr.passed


def test_score_expect_error():
    """PR2：expect_error 路径。"""
    t = make_trajectory(final="", error="TimeoutError")
    cr = score(t, {"name": "t", "expect_error": True})
    assert cr.passed


def test_score_max_duration_ms():
    """PR2：max_duration_ms 路径。"""
    t = make_trajectory(final="hi", elapsed_s=0.005)
    cr = score(t, {"name": "t", "max_duration_ms": 1000})
    assert cr.passed

    cr2 = score(t, {"name": "t", "max_duration_ms": 1})
    assert not cr2.passed
