"""
v2.0 slim — 五层容错注入探针（核心闭环：ResilientLLMInvoker）

五层：
1. 超时        - invoke_timeout / total_timeout
2. 重试        - RetryConfig.max_attempts + retry_on_kinds
3. 熔断        - ProviderBreaker.record_failure / state transitions
4. 主备        - ModelFallbackChain.iter_attempts
5. 失败日志    - FailLogRepository.record / fingerprint_stats

本测试不依赖 LLM/网络，通过 mock agent_factory 模拟各种失败场景，
验证 ResilientLLMInvoker 走完五层容错链路。
"""
from __future__ import annotations

import sys
import time
import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# Helpers：mock agent_factory
# ============================================================

class _MockLLMError(Exception):
    def __init__(self, kind: str, msg: str = ""):
        super().__init__(f"{kind}: {msg}")
        self.kind = kind


class _ScriptedAgent:
    """按脚本返回结果或抛错的 mock agent。"""

    def __init__(self, behaviors: List[Dict]):
        self.behaviors = behaviors
        self.call_count = 0

    def invoke(self, payload, config=None):
        idx = min(self.call_count, len(self.behaviors) - 1)
        self.call_count += 1
        b = self.behaviors[idx]
        if b.get("raise") is not None:
            raise b["raise"]
        return b.get("call", lambda: "default")()


def _factory_for(providers: Dict[str, "_ScriptedAgent"]):
    def _factory(provider: str, model: str):
        return providers[provider]
    return _factory


def _make_invoker(candidates, retry_max=2, invoke_timeout=5.0, total_timeout=30.0, fail_log_db: Optional[str] = None):
    """构造 ResilientLLMInvoker。"""
    from llm_reliability import (
        ResilientLLMInvoker, ModelFallbackChain, FallbackCandidate,
        RetryConfig, FailLogRepository,
    )
    chain = ModelFallbackChain([
        FallbackCandidate(provider=p, model=m) for p, m in candidates
    ])
    fail_log = FailLogRepository(fail_log_db) if fail_log_db else None
    return ResilientLLMInvoker(
        fallback_chain=chain,
        retry_config=RetryConfig(max_attempts=retry_max, retry_on_kinds=("timeout", "rate_limit")),
        fail_log=fail_log,
        invoke_timeout=invoke_timeout,
        total_timeout=total_timeout,
    )


# ============================================================
# 1. 第 1 层：单次超时（invoke_timeout）触发
# ============================================================

def test_invoke_timeout_triggers():
    """第 1 层：单次 invoke 超时必须抛 LLMError(TIMEOUT)。"""
    from llm_reliability import LLMErrorKind, LLMError, ResilientLLMInvoker, ModelFallbackChain, FallbackCandidate, RetryConfig

    invoker = ResilientLLMInvoker(
        fallback_chain=ModelFallbackChain([FallbackCandidate(provider="x", model="y")]),
        retry_config=RetryConfig(max_attempts=1),
        invoke_timeout=1.0,
        total_timeout=5.0,
    )

    class _Block:
        def invoke(self, payload, config=None):
            time.sleep(10)
            return "never"

    start = time.time()
    with pytest.raises(LLMError) as ei:
        invoker._invoke_with_timeout(_Block(), {}, {})
    elapsed = time.time() - start
    assert ei.value.kind == LLMErrorKind.TIMEOUT, f"kind={ei.value.kind}"
    assert elapsed < 3.0, f"超时未在 1s 内触发（实际 {elapsed:.2f}s）"


# ============================================================
# 2. 第 2 层：重试（同 provider 内 max_attempts 次）
# ============================================================

def test_retry_within_single_provider():
    """第 2 层：retryable 错误必须按 RetryConfig.max_attempts 重试。"""
    p1 = _ScriptedAgent([
        {"raise": _MockLLMError("timeout", "1st")},
        {"raise": _MockLLMError("timeout", "2nd")},
        {"call": lambda: "success-on-3rd"},
    ])
    invoker = _make_invoker(
        candidates=[("openai", "gpt-4o-mini")],
        retry_max=3,
    )
    factory = _factory_for({"openai": p1})
    result = invoker.invoke(agent_factory=factory, payload={}, trace_id="t1")
    assert result.text == "success-on-3rd"
    assert p1.call_count == 3, f"应当重试 3 次（实际 {p1.call_count}）"
    assert result.degraded is False


def test_non_retryable_error_skips_retry():
    """非 retryable 错误（auth_error）必须立即停止重试，切到 fallback。"""
    from llm_reliability import LLMErrorKind, LLMError

    p1 = _ScriptedAgent([
        {"raise": LLMError(LLMErrorKind.AUTH, "bad api key")},
    ])
    p2 = _ScriptedAgent([
        {"call": lambda: "fallback-success"},
    ])
    invoker = _make_invoker(
        candidates=[("openai", "gpt-4o-mini"), ("deepseek", "deepseek-chat")],
        retry_max=3,
    )
    factory = _factory_for({"openai": p1, "deepseek": p2})
    result = invoker.invoke(agent_factory=factory, payload={}, trace_id="t2")
    assert result.text == "fallback-success"
    assert p1.call_count == 1, "auth_error 不应重试"
    assert p2.call_count == 1


# ============================================================
# 3. 第 3 层：熔断器
# ============================================================

def test_breaker_opens_after_consecutive_failures():
    """第 3 层：同一 provider 连续失败 N 次后熔断器 open，跳过该 provider。"""
    p1 = _ScriptedAgent([
        {"raise": _MockLLMError("timeout", "fail")},
        {"raise": _MockLLMError("timeout", "fail")},
        {"raise": _MockLLMError("timeout", "fail")},
        {"raise": _MockLLMError("timeout", "fail")},
    ])
    p2 = _ScriptedAgent([
        {"call": lambda: "fallback-after-breaker"},
    ])
    invoker = _make_invoker(
        candidates=[("openai", "gpt-4o-mini"), ("deepseek", "deepseek-chat")],
        retry_max=1,
    )
    factory = _factory_for({"openai": p1, "deepseek": p2})
    for i in range(5):
        result = invoker.invoke(agent_factory=factory, payload={}, trace_id=f"t-{i}")
        assert result.text == "fallback-after-breaker", f"iter {i}"

    # openai 的 breaker 应为 open（注意：state 是 str 不是 enum）
    assert invoker.breakers["openai"].state == "open", (
        f"连续失败后熔断器应为 open，实际 {invoker.breakers['openai'].state}"
    )


def test_breaker_skip_logs_during_iter():
    """open 状态的熔断器在 iter_attempts 中应被跳过（不调用 agent）。"""
    p1 = _ScriptedAgent([
        {"call": lambda: "never-called"},
    ])
    invoker = _make_invoker(candidates=[("openai", "gpt-4o-mini")], retry_max=1)
    invoker.breakers["openai"].state = "open"
    invoker.breakers["openai"].open_until = time.time() + 60  # 字段名是 open_until
    # 调试
    print(f"\n>>> breaker state={invoker.breakers['openai'].state}, allow={invoker.breakers['openai'].allow()}")
    factory = _factory_for({"openai": p1})
    result = invoker.invoke(agent_factory=factory, payload={}, trace_id="t-skip")
    print(f">>> result.degraded={result.degraded}, call_count={p1.call_count}")
    assert result.degraded is True
    assert p1.call_count == 0, "open 熔断器下不应调用 agent"


# ============================================================
# 4. 第 4 层：主备切换（PrimaryStandbyConfig）
# ============================================================

def test_primary_to_standby_fallback():
    """第 4 层：primary 失败时切换到 standby。"""
    from llm_reliability import (
        PrimaryStandbyConfig, FallbackCandidate,
        ResilientLLMInvoker, RetryConfig,
    )

    p1 = _ScriptedAgent([{"raise": _MockLLMError("timeout", "primary down")}])
    p2 = _ScriptedAgent([{"call": lambda: "standby-ok"}])
    cfg = PrimaryStandbyConfig(
        primary=FallbackCandidate(provider="openai", model="gpt-4o-mini"),
        standbys=[FallbackCandidate(provider="deepseek", model="deepseek-chat")],
    )
    invoker = ResilientLLMInvoker(
        fallback_chain=cfg.to_chain(),
        retry_config=RetryConfig(max_attempts=1, retry_on_kinds=("timeout",)),
    )
    factory = _factory_for({"openai": p1, "deepseek": p2})
    result = invoker.invoke(agent_factory=factory, payload={}, trace_id="t-primary")
    assert result.text == "standby-ok"
    assert result.degraded is False


def test_chain_iter_attempts_order():
    """FallbackChain.iter_attempts 必须按声明顺序遍历。"""
    from llm_reliability import ModelFallbackChain, FallbackCandidate
    chain = ModelFallbackChain([
        FallbackCandidate(provider="a", model="m1"),
        FallbackCandidate(provider="b", model="m2"),
        FallbackCandidate(provider="c", model="m3"),
    ])
    # FallbackAttempt 有 provider 属性（property 转发 candidate.provider）
    seq = [a.provider for a in chain.iter_attempts({})]
    assert seq == ["a", "b", "c"], f"iter_attempts 顺序错误：{seq}"


# ============================================================
# 5. 第 5 层：FailLog
# ============================================================

def test_fail_log_records_each_failure(tmp_path):
    """第 5 层：每次失败必须写入 FailLog。"""
    db = str(tmp_path / "fail.db")
    invoker = _make_invoker(
        candidates=[("openai", "gpt-4o-mini"), ("deepseek", "deepseek-chat")],
        retry_max=1,
        fail_log_db=db,
    )
    p1 = _ScriptedAgent([{"raise": _MockLLMError("timeout", "boom")}])
    p2 = _ScriptedAgent([{"call": lambda: "ok"}])
    factory = _factory_for({"openai": p1, "deepseek": p2})
    result = invoker.invoke(agent_factory=factory, payload={}, trace_id="trace-fail-1")
    assert result.text == "ok"

    conn = sqlite3.connect(db)
    cur = conn.execute(
        "SELECT provider, error_kind, attempts, fallbacks_tried, recovered FROM fail_log WHERE trace_id=?",
        ("trace-fail-1",),
    )
    rows = cur.fetchall()
    assert len(rows) >= 1, "FailLog 必须至少记录一次失败"
    providers = {r[0] for r in rows}
    assert "openai" in providers, f"FailLog 缺 openai 失败记录：{rows}"
    conn.close()


def test_fail_log_fingerprint_stats(tmp_path):
    """FailLogRepository.fingerprint_stats 必须按 error_fingerprint 聚合。"""
    from llm_reliability import FailLogRepository
    db = str(tmp_path / "fail2.db")
    repo = FailLogRepository(db)
    # 真实接口：record(trace_id, session_id, provider, model, error_kind, error_fingerprint, message, attempts, fallbacks_tried, recovered)
    repo.record(
        trace_id="t1", session_id=None, provider="openai", model="gpt-4o-mini",
        error_kind="timeout", error_fingerprint="openai|timeout|boom",
        message="boom", attempts=3, fallbacks_tried=["deepseek"], recovered=True,
    )
    repo.record(
        trace_id="t2", session_id=None, provider="openai", model="gpt-4o-mini",
        error_kind="timeout", error_fingerprint="openai|timeout|boom",
        message="boom again", attempts=2, fallbacks_tried=["deepseek"], recovered=False,
    )
    stats = repo.fingerprint_stats()
    assert len(stats) >= 1
    openai_timeout = [s for s in stats if s["provider"] == "openai" and s["error_kind"] == "timeout"]
    assert openai_timeout, f"未找到 openai/timeout 聚合：{stats}"
    assert openai_timeout[0]["cnt"] >= 2
    assert openai_timeout[0]["recovered_cnt"] >= 1


# ============================================================
# 6. GracefulDegradation
# ============================================================

def test_graceful_degradation_when_all_fallbacks_fail():
    """全部 fallback 失败时，invoke 必须返回 degraded=True 回答。"""
    p1 = _ScriptedAgent([{"raise": _MockLLMError("timeout", "p1")}])
    p2 = _ScriptedAgent([{"raise": _MockLLMError("rate_limit", "p2")}])
    invoker = _make_invoker(
        candidates=[("openai", "gpt-4o-mini"), ("deepseek", "deepseek-chat")],
        retry_max=1,
    )
    factory = _factory_for({"openai": p1, "deepseek": p2})
    result = invoker.invoke(
        agent_factory=factory, payload={},
        user_input="测试输入", trace_id="t-degrade",
    )
    assert result.degraded is True
    assert result.text, "降级回答不能为空"


# ============================================================
# 7. 五层链路联动
# ============================================================

def test_five_layers_in_one_invoke(tmp_path):
    """单次 invoke 内触发：超时 + 重试 + 熔断 + 主备 + FailLog + 降级。"""
    db = str(tmp_path / "fail3.db")
    p1 = _ScriptedAgent([
        {"raise": _MockLLMError("timeout", "p1-1")},
        {"raise": _MockLLMError("timeout", "p1-2")},
    ])
    p2 = _ScriptedAgent([{"raise": _MockLLMError("rate_limit", "p2")}])
    p3 = _ScriptedAgent([{"raise": _MockLLMError("server", "p3")}])
    invoker = _make_invoker(
        candidates=[
            ("openai", "gpt-4o-mini"),
            ("deepseek", "deepseek-chat"),
            ("qwen", "qwen-turbo"),
        ],
        retry_max=2,
        fail_log_db=db,
    )
    factory = _factory_for({"openai": p1, "deepseek": p2, "qwen": p3})
    result = invoker.invoke(
        agent_factory=factory, payload={},
        user_input="测试联动", trace_id="t-five",
    )
    assert result.degraded is True
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM fail_log WHERE trace_id=?", ("t-five",)).fetchone()[0]
    conn.close()
    assert count >= 3, f"FailLog 应至少 3 条失败（实际 {count}）"


# ============================================================
# 8. ResilientLLMInvoker 的 LLMError 指纹契约
# ============================================================

def test_llm_error_fingerprint_stable():
    """LLMError.fingerprint 行为契约：
    - 完全相同的 message + kind → 相同 fingerprint
    - 不同 kind → 不同 fingerprint
    - UUID-like 尾部变量（如 abc-12345-def）→ 被归一化
    """
    from llm_reliability import LLMError, LLMErrorKind

    e1 = LLMError(LLMErrorKind.TIMEOUT, "Connection timeout")
    e2 = LLMError(LLMErrorKind.TIMEOUT, "Connection timeout")
    assert e1.fingerprint == e2.fingerprint, "完全相同 message 的 fingerprint 必须稳定"

    e3 = LLMError(LLMErrorKind.RATE_LIMIT, "rate limit exceeded")
    assert e1.fingerprint != e3.fingerprint, "不同 kind 的指纹必须不同"

    # UUID-like 数字 ID 应被归一化（独立数字或 UUID-like 字符串）
    e4 = LLMError(LLMErrorKind.UNAVAILABLE, "Internal error: req 12345 failed")
    e5 = LLMError(LLMErrorKind.UNAVAILABLE, "Internal error: req 67890 failed")
    assert e4.fingerprint == e5.fingerprint, "独立数字应被归一化为同一指纹"

    # UUID-like 字符串（长度 >=8 的 hex 串）应被归一化
    e6 = LLMError(LLMErrorKind.UNAVAILABLE, "Request abcdef12-3456-7890 failed")
    e7 = LLMError(LLMErrorKind.UNAVAILABLE, "Request fedcba09-8765-4321 failed")
    assert e6.fingerprint == e7.fingerprint, "UUID-like 串应被归一化为同一指纹"


# ============================================================
# 9. invoke timeout 不会拉爆 total timeout（双层独立）
# ============================================================

def test_invoke_timeout_independent_of_total_timeout():
    """单次 invoke 超时不应立即触发 total timeout。"""
    p1 = _ScriptedAgent([
        {"raise": _MockLLMError("timeout", "x")},
    ])
    invoker = _make_invoker(
        candidates=[("openai", "gpt-4o-mini")],
        retry_max=3, invoke_timeout=0.5, total_timeout=30.0,
    )
    factory = _factory_for({"openai": p1})
    # 重试 3 次：invoke 超时 3 次 → 切 fallback → 全部失败 → 降级
    result = invoker.invoke(agent_factory=factory, payload={}, trace_id="t-double")
    # 没备用 → 全部失败 → 降级
    assert result.degraded is True
