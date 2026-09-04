"""
Eval Harness 单元测试。

覆盖:
- CaseLoader(JSONL 加载/注释/缺字段/重复 id)
- KeywordScorer / CompositeScorer
- HarnessRunner(空用例、单条失败、混合)
- Storage 写盘(目录结构兼容 evals/runs 既有)
- CLI --dry-run 路径(不调真实 Agent)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# 保证 ai_agent/ 可被 import
_AI_AGENT = Path(__file__).resolve().parent.parent
if str(_AI_AGENT) not in sys.path:
    sys.path.insert(0, str(_AI_AGENT))

from harness_runner import (  # noqa: E402
    CaseResult, CompositeScorer, EmbedScorer, HarnessCase, HarnessConfig,
    HarnessRunner, KeywordScorer, RunResult, Scorer, ScorerRegistry, SubScore,
)
from harness_storage import CaseLoader, Storage  # noqa: E402


# ============================================================
# CaseLoader
# ============================================================

def test_case_loader_basic(tmp_path):
    p = tmp_path / "cases.jsonl"
    p.write_text(
        '{"id":"a","prompt":"x","expected":"x"}\n'
        '# comment\n'
        '\n'
        '{"id":"b","prompt":"y","expected":"y","scorers":["embed"]}\n',
        encoding="utf-8",
    )
    cases = CaseLoader.load(p)
    assert [c.id for c in cases] == ["a", "b"]
    assert cases[0].scorers == ["keyword"]
    assert cases[1].scorers == ["embed"]


def test_case_loader_missing_prompt(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"id":"a"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="missing 'prompt'"):
        CaseLoader.load(p)


def test_case_loader_duplicate_id(tmp_path):
    p = tmp_path / "dup.jsonl"
    p.write_text(
        '{"id":"a","prompt":"1"}\n{"id":"a","prompt":"2"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate case id"):
        CaseLoader.load(p)


def test_case_loader_empty(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("# only comment\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no valid cases"):
        CaseLoader.load(p)


def test_case_loader_load_dir(tmp_path):
    (tmp_path / "a.jsonl").write_text('{"id":"a1","prompt":"1"}\n', encoding="utf-8")
    (tmp_path / "b.jsonl").write_text('{"id":"b1","prompt":"2"}\n', encoding="utf-8")
    cases = CaseLoader.load_dir(tmp_path)
    assert {c.id for c in cases} == {"a1", "b1"}


# ============================================================
# Scorers
# ============================================================

def test_keyword_scorer_full_hit():
    s = KeywordScorer()
    sub = s.score("echo: hi there", HarnessCase(id="x", prompt="p", expected="echo: hi"))
    assert sub.value == 1.0
    assert sub.detail["hits"] == 2


def test_keyword_scorer_partial():
    s = KeywordScorer()
    # expected="echo hi" → tokens=["echo", "hi"]; output="echo only" → 仅 "echo" 命中
    sub = s.score("echo only", HarnessCase(id="x", prompt="p", expected="echo hi"))
    assert sub.value == pytest.approx(0.5)


def test_keyword_scorer_empty_expected():
    s = KeywordScorer()
    sub = s.score("anything", HarnessCase(id="x", prompt="p", expected=""))
    assert sub.value == 0.0


def test_composite_scorer_weighted():
    s = CompositeScorer()
    case = HarnessCase(
        id="x", prompt="p", expected="echo: hi",
        scorers=["composite"],
        scorer_config={"weights": {"keyword": 1, "embed": 0}},
    )
    sub = s.score("echo: hi", case)
    # 关键词 1.0, embed 没权重,仍按定义算
    assert sub.detail["sub_scores"]["keyword"] == 1.0


def test_scorer_registry_register_and_get():
    class _Tmp(Scorer):
        name = "tmp"
        def score(self, output, case):
            return SubScore("tmp", 0.5, {})
    ScorerRegistry.register("tmp", _Tmp())
    s = ScorerRegistry.get("tmp")
    assert s.score("", HarnessCase(id="x", prompt="p")).value == 0.5
    assert "tmp" in ScorerRegistry.names()
    with pytest.raises(KeyError):
        ScorerRegistry.get("not_exist")


def test_embed_scorer_without_ref():
    s = EmbedScorer()
    sub = s.score("output", HarnessCase(id="x", prompt="p"))
    assert sub.value == 0.0


# ============================================================
# HarnessRunner(用 fake agent,避免调真实 LLM)
# ============================================================

class _FakeAgent:
    """模拟 AIAgent:按 prompt 返回 expected 文本(用于跑通评分链路)。"""
    def __init__(self, fail_ids=()):
        self.fail_ids = set(fail_ids)
        self.calls = []

    def run(self, prompt, session_id=None):
        self.calls.append((prompt, session_id))
        return prompt  # 直接 echo


class _BrokenAgent:
    def run(self, prompt, session_id=None):
        raise RuntimeError("boom")


def test_runner_empty():
    runner = HarnessRunner(agent=_FakeAgent(), config=HarnessConfig())
    r = runner.run([])
    assert r.cases_total == 0
    assert r.pass_rate == 0.0


def test_runner_all_pass():
    cases = [
        HarnessCase(id="a", prompt="echo: hi", expected="echo: hi"),
        HarnessCase(id="b", prompt="echo: 1+2", expected="echo: 1+2"),
    ]
    runner = HarnessRunner(agent=_FakeAgent(), config=HarnessConfig(pass_threshold=0.6))
    r = runner.run(cases)
    assert r.cases_total == 2
    assert r.cases_passed == 2
    assert r.cases_failed == 0
    assert r.pass_rate == 1.0


def test_runner_partial_fail():
    cases = [
        HarnessCase(id="a", prompt="echo: hi", expected="echo: hi"),  # 通过
        HarnessCase(id="b", prompt="echo: 1+2", expected="totally different"),  # 失败
    ]
    runner = HarnessRunner(agent=_FakeAgent(), config=HarnessConfig(pass_threshold=0.6))
    r = runner.run(cases)
    assert r.cases_passed == 1
    assert r.cases_failed == 1
    assert r.pass_rate == 0.5


def test_runner_agent_exception_recorded():
    cases = [HarnessCase(id="x", prompt="hi", expected="hi")]
    runner = HarnessRunner(agent=_BrokenAgent(), config=HarnessConfig())
    r = runner.run(cases)
    assert r.cases_errored == 1
    assert r.cases_passed == 0
    assert r.cases[0].error and "boom" in r.cases[0].error
    assert r.cases[0].passed is False


def test_runner_session_isolation():
    """每个 case 应该用独立 session_id,避免污染上下文。"""
    agent = _FakeAgent()
    runner = HarnessRunner(agent=agent)
    cases = [
        HarnessCase(id="a", prompt="1", expected="1"),
        HarnessCase(id="b", prompt="2", expected="2"),
    ]
    runner.run(cases)
    sids = {c[1] for c in agent.calls}
    assert len(sids) == 2
    assert all(s.startswith("harness-") for s in sids)


# ============================================================
# Storage
# ============================================================

def _make_run_result() -> RunResult:
    return RunResult(
        run_id="harness_test_xxx",
        started_at="2026-09-04T00:00:00",
        finished_at="2026-09-04T00:00:01",
        cases_total=2,
        cases_passed=1,
        cases_failed=1,
        cases_errored=0,
        pass_rate=0.5,
        mean_score=0.6,
        p50_latency_ms=10.0,
        p95_latency_ms=20.0,
        set_path="x.jsonl",
        config={"threshold": 0.6},
        cases=[
            CaseResult(
                case_id="a", category="smoke", passed=True, score=1.0,
                sub_scores={"keyword": SubScore("keyword", 1.0, {})},
                observed={"final": "echo: hi", "elapsed_ms": 5.0},
            ),
            CaseResult(
                case_id="b", category="qa", passed=False, score=0.2,
                sub_scores={"keyword": SubScore("keyword", 0.2, {})},
                observed={"final": "wrong", "elapsed_ms": 15.0},
            ),
        ],
    )


def test_storage_writes_all_files(tmp_path):
    out = tmp_path / "evals"
    res = _make_run_result()
    d = Storage.write(res, root=out, tag="pytest")
    assert d.is_dir()
    assert (d / "summary.json").exists()
    assert (d / "cases.jsonl").exists()
    assert (d / "metrics.json").exists()
    assert (d / "report.md").exists()
    summary = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    # 兼容既有 evals/runs 字段
    assert summary["cases_total"] == 2
    assert summary["cases"][0]["name"] == "a"
    assert summary["cases"][0]["category"] == "smoke"
    assert summary["cases"][0]["passed"] is True
    metrics = json.loads((d / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["pass_rate"] == 0.5
    assert "by_category" in metrics
    # cases.jsonl 每行一条 JSON
    lines = (d / "cases.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    json.loads(lines[0])  # 每行可解析
    # report.md 有 Overall 段
    md = (d / "report.md").read_text(encoding="utf-8")
    assert "## Overall" in md
    assert "## By Category" in md
    assert "## Cases" in md


# ============================================================
# CLI --dry-run
# ============================================================

def test_cli_dry_run(tmp_path, monkeypatch, capsys):
    """dry-run 不调 Agent,只校验用例集 + 默认通过,返回 0。"""
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        '{"id":"a","prompt":"echo: hi","expected":"echo: hi"}\n',
        encoding="utf-8",
    )
    out_dir = tmp_path / "runs"
    from harness_cli import main
    rc = main([
        "--set", str(cases_path),
        "--out", str(out_dir),
        "--dry-run",
        "--tag", "pytest",
        "--threshold", "0.5",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "loaded 1 cases" in captured.out
    assert "pass_rate: 100.00%" in captured.out
    # 目录被创建
    assert any(out_dir.iterdir())


def test_cli_list_scorers(capsys):
    from harness_cli import main
    rc = main(["--list-scorers"])
    assert rc == 0
    out = capsys.readouterr().out
    for name in ("keyword", "embed", "composite"):
        assert name in out


def test_cli_missing_set(tmp_path):
    from harness_cli import main
    rc = main(["--set", str(tmp_path / "no.jsonl")])
    assert rc != 0  # FileNotFoundError → exit code != 0


def test_cli_invalid_json_weights(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text('{"id":"a","prompt":"x"}\n', encoding="utf-8")
    from harness_cli import main
    rc = main([
        "--set", str(p),
        "--out", str(tmp_path / "runs"),
        "--scorer-weights", "not-json",
        "--dry-run",
    ])
    assert rc == 2