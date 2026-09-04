"""
harness_observability 适配层 + Harness 真实上报测试。

覆盖:
1. record_metric 三条探测路径(legacy record_metric / metrics.counter / 简写)
2. record_event 两条探测路径(publish_event / events.publish)
3. 对真实 ObservabilityLayer(metrics.counter / publish_event)端到端验证
4. Harness 与 HarnessRunner 真实上报(替代之前的 fake Observability)
5. 防御性降级:obs=None / 全 API 缺失 都不崩
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_AI_AGENT = Path(__file__).resolve().parent.parent
if str(_AI_AGENT) not in sys.path:
    sys.path.insert(0, str(_AI_AGENT))

from harness_observability import (  # noqa: E402
    record_event, record_metric, get_event_count, get_metric_value,
)


# ============================================================
# Fixtures
# ============================================================

class LegacyFakeObs:
    """老式 fake:暴露 record_metric 接口。"""
    def __init__(self):
        self.metrics: list = []
        self.events: list = []

    def record_metric(self, name, value, tags=None):
        self.metrics.append((name, value, tags or {}))

    def publish_event(self, event_type, source, trace_id=None, payload=None):
        self.events.append({
            "event_type": event_type, "source": source,
            "trace_id": trace_id, "payload": payload or {},
        })


class RealObs:
    """模拟 ai_agent/observability.ObservabilityLayer 的真实 API。"""
    def __init__(self):
        from observability import EventBus, MetricsRegistry
        self.metrics = MetricsRegistry()
        self.events = EventBus()

    def publish_event(self, event_type, source, trace_id=None, payload=None):
        return self.events.publish(event_type, source, trace_id, payload)


class BareObs:
    """什么都没有的 obs,record_metric 应返回 False 而不是抛异常。"""
    pass


class PartialObs:
    """只有 metrics,没有 publish_event。"""
    def __init__(self):
        from observability import MetricsRegistry
        self.metrics = MetricsRegistry()


# ============================================================
# record_metric 三条路径
# ============================================================

def test_record_metric_legacy_path():
    obs = LegacyFakeObs()
    ok = record_metric(obs, "h.run.cnt", 1.0, tags={"k": "v"})
    assert ok is True
    assert obs.metrics == [("h.run.cnt", 1.0, {"k": "v"})]


def test_record_metric_real_observability_layer_path():
    obs = RealObs()
    ok = record_metric(obs, "h.run.cnt", 1.0, tags={"k": "v"}, help_text="count")
    assert ok is True
    # 真实 metric 已经写进去了
    val = get_metric_value(obs, "h.run.cnt", k="v")
    assert val == 1.0


def test_record_metric_real_layer_increments_counter():
    """连续两次上报同一个 metric,值应累加(因为 counter.inc)。"""
    obs = RealObs()
    record_metric(obs, "h.run.cnt", 1.0, tags={"x": "1"})
    record_metric(obs, "h.run.cnt", 1.0, tags={"x": "1"})
    record_metric(obs, "h.run.cnt", 2.0, tags={"x": "1"})
    assert get_metric_value(obs, "h.run.cnt", x="1") == 4.0


def test_record_metric_none_obs_returns_false():
    assert record_metric(None, "any", 1.0) is False


def test_record_metric_bare_obs_returns_false_not_crash():
    obs = BareObs()
    ok = record_metric(obs, "any", 1.0)
    assert ok is False


def test_record_metric_partial_obs_uses_metrics_path():
    """没有 publish_event,但 metrics 可用 → record_metric 仍应成功。"""
    obs = PartialObs()
    ok = record_metric(obs, "h.run.cnt", 3.0, tags={"z": "y"})
    assert ok is True
    assert get_metric_value(obs, "h.run.cnt", z="y") == 3.0


def test_record_metric_legacy_raises_still_safe():
    """legacy record_metric 抛异常 → 不应传播,应静默。"""
    class Boom:
        def record_metric(self, name, value, tags=None):
            raise RuntimeError("boom")
        metrics = None
    ok = record_metric(Boom(), "any", 1.0)
    assert ok is False


# ============================================================
# record_event 两条路径
# ============================================================

def test_record_event_legacy_path():
    obs = LegacyFakeObs()
    ok = record_event(obs, "h.run.done", "harness", trace_id="t1",
                      payload={"x": 1})
    assert ok is True
    assert len(obs.events) == 1
    assert obs.events[0]["event_type"] == "h.run.done"
    assert obs.events[0]["trace_id"] == "t1"


def test_record_event_real_observability_layer():
    obs = RealObs()
    ok = record_event(obs, "h.run.done", "harness", trace_id="t1",
                      payload={"x": 1})
    assert ok is True
    assert get_event_count(obs, "h.run.done") == 1
    assert get_event_count(obs, "h.run.other") == 0


def test_record_event_none_obs_returns_false():
    assert record_event(None, "any", "src") is False


def test_record_event_bare_obs_returns_false():
    assert record_event(BareObs(), "any", "src") is False


# ============================================================
# Harness + HarnessRunner 真实上报
# ============================================================

def test_harness_facade_reports_to_real_obs():
    """这是核心回归用例:Harness 跑完后,真实 ObservabilityLayer 上有数据。"""
    from harness import Harness, HarnessConfig

    obs = RealObs()

    class FakeAgent:
        def run(self, prompt, session_id=None, **kw): return "reply-for-" + prompt

    h = Harness(agent=FakeAgent(),
                config=HarnessConfig(enable_memory=False),
                observability=obs)
    h.run("hi")

    # 验证 counter 写进去了
    complete = get_metric_value(obs, "harness.run.complete", session_id=h.last_trace.session_id)
    assert complete == 1.0
    out_len = get_metric_value(obs, "harness.run.output_len",
                              session_id=h.last_trace.session_id)
    # output = "reply-for-hi",长度 12
    assert out_len == 12.0
    # 验证事件发布
    assert get_event_count(obs, "harness.run.completed") == 1


def test_harness_runner_reports_to_real_obs():
    """Eval Harness 跑完后,真实 ObservabilityLayer 上有数据(替代之前的警告)。"""
    from harness_runner import HarnessCase, HarnessConfig, HarnessRunner

    obs = RealObs()

    class FakeAgent:
        def __init__(self, replies): self.replies = replies; self.idx = 0
        def run(self, prompt, session_id=None):
            r = self.replies[self.idx % len(self.replies)]; self.idx += 1; return r

    cases = [
        HarnessCase(id="t1", prompt="echo: hi", expected="echo: hi"),
        HarnessCase(id="t2", prompt="echo: bye", expected="echo: bye"),
    ]
    result = HarnessRunner(agent=FakeAgent(["echo: hi", "echo: bye"]),
                           config=HarnessConfig(extra_tags={}),
                           observability=obs).run(cases)

    # 主指标
    assert get_metric_value(obs, "harness.run.pass_rate", run_id=result.run_id) == 1.0
    assert get_metric_value(obs, "harness.run.mean_score", run_id=result.run_id) == 1.0
    assert get_metric_value(obs, "harness.run.cases_total", run_id=result.run_id) == 2.0
    # 每条用例得分(2 个 case,值都是 1.0,counter 上累加为 2.0)
    case_score_t1 = get_metric_value(
        obs, "harness.case.score",
        case_id="t1", category="general", run_id=result.run_id,
    )
    case_score_t2 = get_metric_value(
        obs, "harness.case.score",
        case_id="t2", category="general", run_id=result.run_id,
    )
    assert case_score_t1 == 1.0
    assert case_score_t2 == 1.0
    # 事件
    assert get_event_count(obs, "harness.run.finished") == 1


def test_harness_runner_no_warning_on_real_obs(caplog):
    """真实 obs 存在时,不应出现 'observability record failed' 警告(本轮的 fix 目的)。"""
    import logging
    from harness_runner import HarnessCase, HarnessRunner

    obs = RealObs()

    class FakeAgent:
        def run(self, prompt, session_id=None): return "echo: hi"

    with caplog.at_level(logging.WARNING, logger="harness_runner"):
        HarnessRunner(agent=FakeAgent()).run(
            [HarnessCase(id="t1", prompt="echo: hi", expected="echo: hi")]
        )
    # 不应再有 warning 级"observability record failed"
    bad = [r for r in caplog.records
           if r.levelno >= logging.WARNING and "observability record failed" in r.message]
    assert bad == [], f"unexpected warnings: {[r.message for r in bad]}"