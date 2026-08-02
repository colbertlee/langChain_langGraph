"""Token Dashboard 模块测试（v0.5 新增）。

覆盖：
- snapshot()  schema 形状 + by_model / totals / scope
- _record_dashboard() 累加 + timeline 环形缓冲
- update_budget() 立刻生效（动态替换字段）
- update_prometheus() / push_now() 单测
- 告警去重 / cooldown / aggregation
- /api/token/usage 与 /api/token/budget 通过 FastAPI TestClient
"""

from __future__ import annotations

import json
import time
import types
from pathlib import Path

import pytest


# ============================================================
# 单元 1：snapshot 形状与累加
# ============================================================

def _build_state_with_usage(state: dict, usage: dict) -> dict:
    """构造一个 after_model 用的 state，附带 AIMessage 携带 usage。"""
    from langchain_core.messages import AIMessage

    msg = AIMessage(content="ok")
    # usage_metadata 是 langchain 1.x 标准
    msg.usage_metadata = {
        "input_tokens": usage["input"],
        "output_tokens": usage["output"],
        "total_tokens": usage["total"],
        "model_name": usage.get("model", "gpt-4o-mini"),
    }
    state = dict(state or {})
    state["messages"] = list(state.get("messages") or []) + [msg]
    return state


def test_snapshot_shape_and_totals(isolated_middleware_budget):
    from agent_middleware import TokenUsageConfig, TokenUsageMiddleware

    cfg = TokenUsageConfig(
        sinks=(),
        history_max=10,
        history_bucket_seconds=60,
        daily_budget_usd=0.001,
        enable_cost=True,
    )
    mw = TokenUsageMiddleware(config=cfg)
    state = _build_state_with_usage({}, {"input": 100, "output": 50, "total": 150, "model": "gpt-4o-mini"})
    mw.after_model(state, None)

    snap = mw.snapshot()
    assert snap["ok"] is True
    assert snap["totals"]["input"] == 100
    assert snap["totals"]["output"] == 50
    assert snap["totals"]["total"] == 150
    assert snap["totals"]["cost_usd"] > 0
    assert len(snap["by_model"]) == 1
    assert snap["by_model"][0]["model"] == "gpt-4o-mini"
    assert snap["by_model"][0]["calls"] == 1
    assert "daily" in snap["scope"]
    assert snap["scope"]["daily"]["budget"] == 0.001
    assert snap["scope"]["daily"]["used"] > 0
    assert snap["scope"]["daily"]["ratio"] > 0
    assert snap["scope"]["daily"]["ratio"] < 1.0
    # history 切桶
    assert isinstance(snap["history"], list)
    assert len(snap["history"]) >= 1
    assert snap["history"][0]["input"] == 100
    assert snap["history"][0]["output"] == 50


def test_record_dashboard_by_model(isolated_middleware_budget):
    from agent_middleware import TokenUsageConfig, TokenUsageMiddleware

    cfg = TokenUsageConfig(sinks=(), history_max=5, history_bucket_seconds=60)
    mw = TokenUsageMiddleware(config=cfg)
    for i in range(3):
        state = _build_state_with_usage(
            {}, {"input": 10 + i, "output": 5, "total": 15 + i, "model": "gpt-4o"}
        )
        mw.after_model(state, None)
    # 切换模型
    for i in range(2):
        state = _build_state_with_usage(
            {}, {"input": 7, "output": 3, "total": 10, "model": "gpt-4o-mini"}
        )
        mw.after_model(state, None)

    snap = mw.snapshot()
    by = {bm["model"]: bm for bm in snap["by_model"]}
    assert by["gpt-4o"]["calls"] == 3
    assert by["gpt-4o"]["input"] == 10 + 11 + 12  # 33
    assert by["gpt-4o-mini"]["calls"] == 2
    assert by["gpt-4o-mini"]["input"] == 14
    # 总数
    assert snap["totals"]["input"] == 33 + 14
    assert snap["totals"]["output"] == 3 * 5 + 2 * 3
    # 排序：cost_usd 降序
    costs = [bm["cost_usd"] for bm in snap["by_model"]]
    assert costs == sorted(costs, reverse=True)


def test_timeline_ring_buffer(isolated_middleware_budget):
    from agent_middleware import TokenUsageConfig, TokenUsageMiddleware

    cfg = TokenUsageConfig(sinks=(), history_max=3, history_bucket_seconds=60)
    mw = TokenUsageMiddleware(config=cfg)
    # 模拟 5 个不同桶（mock 进程时间）
    real_time = time.time
    try:
        base = int(real_time())
        offsets = [0, 70, 140, 210, 280]  # 每个隔 70s → 不同 1min 桶
        for i, off in enumerate(offsets):
            time.time = lambda v=base + off: v
            state = _build_state_with_usage(
                {}, {"input": 1, "output": 1, "total": 2, "model": "m"}
            )
            mw.after_model(state, None)
        snap = mw.snapshot()
        # 缓冲只保留 3 条
        assert len(snap["history"]) == 3
        # 留下的应是后 3 条；按 bucket_ts 验
        buckets = [h["bucket_ts"] for h in snap["history"]]
        assert buckets == sorted(buckets)
    finally:
        time.time = real_time


# ============================================================
# 单元 2：update_budget / update_prometheus
# ============================================================

def test_update_budget_runtime(isolated_middleware_budget):
    from agent_middleware import TokenUsageConfig, TokenUsageMiddleware

    cfg = TokenUsageConfig(sinks=(), daily_budget_usd=1.0)
    mw = TokenUsageMiddleware(config=cfg)
    # 改 daily + thresholds
    new_cfg = mw.update_budget({
        "daily_budget_usd": 5.0,
        "alert_thresholds": [[0.3, "info"], [0.6, "warn"], [1.0, "critical"]],
        "alert_cooldown": {"warn": 30.0, "critical": 120.0},
        "alert_aggregation_window": 15.0,
        "alert_aggregation_jitter": [0.1, 0.2],
    })
    assert new_cfg["alert_thresholds"] == [
        (0.3, "info"), (0.6, "warn"), (1.0, "critical"),
    ]
    assert new_cfg["alert_cooldown"] == {"warn": 30.0, "critical": 120.0}
    assert new_cfg["alert_aggregation_window"] == 15.0
    assert new_cfg["alert_aggregation_jitter"] == [0.1, 0.2]
    # snapshot 看到新 daily
    snap = mw.snapshot()
    assert snap["scope"]["daily"]["budget"] == 5.0


def test_update_budget_path_persist(tmp_path: Path, isolated_middleware_budget):
    from agent_middleware import TokenUsageConfig, TokenUsageMiddleware

    p1 = tmp_path / "b1.json"
    p2 = tmp_path / "b2.json"
    cfg = TokenUsageConfig(sinks=(), daily_budget_usd=1.0, budget_persist_path=str(p1))
    mw = TokenUsageMiddleware(config=cfg)
    state = _build_state_with_usage({}, {"input": 100, "output": 50, "total": 150})
    mw.after_model(state, None)
    # 切换路径
    mw.update_budget({"budget_persist_path": str(p2)})
    # 第二次写入应到 p2
    state2 = _build_state_with_usage({"messages": state["messages"]}, {"input": 1, "output": 1, "total": 2})
    mw.after_model(state2, None)
    assert p2.exists(), "budget_persist_path 切换未生效"


def test_update_prometheus_and_push_now(isolated_middleware_budget):
    from agent_middleware import TokenUsageConfig, TokenUsageMiddleware

    cfg = TokenUsageConfig(sinks=("prometheus",))
    mw = TokenUsageMiddleware(config=cfg)
    # prometheus 默认无 pushgateway → push_now 应返 0
    r = mw.push_now()
    assert r["pushed"] == 0
    # 设置一个不存在的 pushgateway_url；push_now 走一次（必然 connection_error）
    mw.update_prometheus({"pushgateway_url": "http://127.0.0.1:1", "pushgateway_job": "test"})
    info = mw._prometheus_runtime_info()
    assert info["pushgateway_url"] == "http://127.0.0.1:1"
    assert info["pushgateway_job"] == "test"
    r2 = mw.push_now()
    # push_to_gateway 失败（端口不通）→ 必然 errors 至少 1 条
    assert len(r2["errors"]) >= 1
    # 关闭 → 0
    mw.update_prometheus({"pushgateway_url": None})
    r3 = mw.push_now()
    assert r3["pushed"] == 0
    assert r3["errors"] == []
    # 验证 info 准确
    info = mw._prometheus_runtime_info()
    assert info["pushgateway_url"] is None
    assert info["pushgateway_job"] == "test"  # job 名仍保留


# ============================================================
# 单元 3：模块级注册表
# ============================================================

def test_module_registry_roundtrip(isolated_middleware_budget):
    from agent_middleware import (
        TokenUsageConfig,
        TokenUsageMiddleware,
        get_token_usage_registry,
        get_token_usage_snapshot,
        update_token_budget,
        update_token_prometheus,
        push_token_prometheus_now,
        _TOKEN_USAGE_REGISTRY,
    )
    _TOKEN_USAGE_REGISTRY.clear()
    mw1 = TokenUsageMiddleware(config=TokenUsageConfig(sinks=(), daily_budget_usd=3.0))
    mw2 = TokenUsageMiddleware(config=TokenUsageConfig(sinks=(), daily_budget_usd=7.0))
    assert len(get_token_usage_registry()) == 2
    snap = get_token_usage_snapshot()
    assert snap["ok"] is True
    # update_token_budget 应对所有实例生效
    res = update_token_budget({"daily_budget_usd": 12.0})
    assert res["ok"] is True
    # push_now 全 0（没 prometheus sink）
    pr = push_token_prometheus_now()
    assert pr["ok"] is True
    assert pr["pushed"] == 0
    # update_token_prometheus 容错（无 sink）
    res = update_token_prometheus({"pushgateway_url": "http://x:1"})
    assert res["ok"] is True


# ============================================================
# 单元 4：告警去重 / cooldown / aggregation
# ============================================================

def test_alert_dedup_and_cooldown(isolated_middleware_budget):
    from agent_middleware import TokenUsageConfig, TokenUsageMiddleware

    fired: list = []

    cfg = TokenUsageConfig(
        sinks=(),
        daily_budget_usd=1.0,
        alert_thresholds=((0.5, "warn"),),
        alert_cooldown={"warn": 10.0},  # 10 秒内不重复
        on_alerts=(lambda info: fired.append((info.scope, info.severity, info.current_usd)),),
    )
    mw = TokenUsageMiddleware(config=cfg)

    # 一次 call：cost 大到 0.6 → 触发
    state = _build_state_with_usage({}, {"input": 1000000, "output": 1000000, "total": 2000000})
    mw.after_model(state, None)
    assert len(fired) == 1
    # 二次 call：仍超阈值，但 cooldown 内 → 不重复
    state2 = _build_state_with_usage({"messages": state["messages"]}, {"input": 1000, "output": 1000, "total": 2000})
    mw.after_model(state2, None)
    assert len(fired) == 1, "cooldown 未生效"
    # 但 _last_alert 已记录
    snap = mw.snapshot()
    assert snap["last_alert"] is not None
    assert snap["last_alert"]["severity"] == "warn"


def test_alert_aggregation(isolated_middleware_budget):
    from agent_middleware import TokenUsageConfig, TokenUsageMiddleware

    fired: list = []

    cfg = TokenUsageConfig(
        sinks=(),
        daily_budget_usd=2.0,  # 留余量给第二次
        alert_thresholds=((0.5, "warn"),),
        alert_aggregation_window=300.0,
        on_alerts=(lambda info: fired.append(info),),
    )
    mw = TokenUsageMiddleware(config=cfg)

    # 第一次：触发（gpt-4o 拉大 cost）
    s1 = _build_state_with_usage({}, {"input": 200000, "output": 50000, "total": 250000, "model": "gpt-4o"})
    mw.after_model(s1, None)
    assert len(fired) == 1, f"first alert not fired, snapshot={mw.snapshot()['scope']}"
    # 第一次触发：aggregation_count=1（直接触发 / 聚合结果）
    assert fired[0].aggregation_count == 1
    # 第二次：被 _fired_alerts 去重（这是预期行为）—— 验证合并行为通过 snapshot.last_alert
    s2 = _build_state_with_usage({"messages": s1["messages"]}, {"input": 100, "output": 100, "total": 200, "model": "gpt-4o"})
    mw.after_model(s2, None)
    # 验证 _aggregation_pending 内部保存了窗口状态（同 scope/severity 在 aggregation window 内）
    assert ("daily", "warn") in mw._aggregation_pending
    pending = mw._aggregation_pending[("daily", "warn")]
    assert pending["count"] >= 1
    assert pending["total_metric"] > 0
    # 验证 snapshot 的 last_alert 字段记录了首次触发
    snap = mw.snapshot()
    assert snap["last_alert"] is not None
    assert snap["last_alert"]["aggregation_count"] == 1


# ============================================================
# 单元 5：last_alert 记录
# ============================================================

def test_last_alert_recorded(isolated_middleware_budget):
    from agent_middleware import TokenUsageConfig, TokenUsageMiddleware

    cfg = TokenUsageConfig(
        sinks=(),
        daily_budget_usd=2.0,  # 大于单次 cost
        alert_thresholds=((0.5, "warn"),),
    )
    mw = TokenUsageMiddleware(config=cfg)
    # gpt-4o: 2000000 input @ 0.01/1k + 500000 output @ 0.03/1k = 20 + 15 = 35 USD
    # ratio = 35/2 = 17.5（远超 0.5 → 触发；但 daily 已超额 2.0 → 抛 TokenBudgetExceeded）
    # 改用 gpt-4o-mini：1000000 * 0.00015 + 500000 * 0.0006 = 0.15 + 0.3 = 0.45 < 2.0
    # 需更大 input：4_000_000 * 0.00015 + 500_000 * 0.0006 = 0.6 + 0.3 = 0.9 → ratio 0.45（不够 0.5）
    # 选 5_000_000 + 1_000_000 → 0.75 + 0.6 = 1.35 → ratio 0.675
    state = _build_state_with_usage(
        {}, {"input": 5_000_000, "output": 1_000_000, "total": 6_000_000, "model": "gpt-4o-mini"}
    )
    mw.after_model(state, None)
    snap = mw.snapshot()
    assert snap["last_alert"] is not None, f"alert not recorded, scope={snap['scope']}"
    assert snap["last_alert"]["scope"] == "daily"
    assert snap["last_alert"]["severity"] == "warn"
    assert snap["last_alert"]["ratio"] >= 0.5
    # ack 后清空
    mw.reset_last_alert()
    snap2 = mw.snapshot()
    assert snap2["last_alert"] is None


# ============================================================
# 单元 6：FastAPI 端点（用真实 app）
# ============================================================

@pytest.fixture
def app_client():
    """构造一个最小可用的 FastAPI TestClient。"""
    try:
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
    except ImportError:
        pytest.skip("fastapi not installed")

    # 复用 app.py 的 app（直接 import）
    from app import app
    return TestClient(app)


def test_api_token_usage_schema(app_client):
    r = app_client.get("/api/token/usage")
    assert r.status_code == 200
    d = r.json()
    # 即便没有 instance，schema 必须齐全
    assert "totals" in d
    assert "by_model" in d
    assert "scope" in d
    assert "history" in d
    assert "prometheus" in d
    assert "config" in d
    assert "alert_thresholds" in d["config"]
    assert "alert_cooldown" in d["config"]


def test_api_token_budget_get_post(app_client):
    r = app_client.get("/api/token/budget")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert "config" in d and "scope" in d and "prometheus" in d

    # 跑一个 post → 应当正常 round-trip
    payload = {
        "daily_budget_usd": 99.0,
        "alert_thresholds": [[0.5, "info"], [0.8, "warn"], [1.0, "critical"]],
        "alert_cooldown": {"warn": 30.0, "critical": 60.0},
        "alert_aggregation_window": 10.0,
        "alert_aggregation_jitter": [0.1, 0.2],
        "history_max": 100,
        "history_bucket_seconds": 30,
    }
    r2 = app_client.post("/api/token/budget", json=payload)
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["ok"] is True
    # JSON 序列化后 tuple → list（按 ratio 数字比较）
    ths = d2["config"]["alert_thresholds"]
    assert sorted([(float(a), str(b)) for a, b in ths]) == [
        (0.5, "info"), (0.8, "warn"), (1.0, "critical"),
    ]
    assert d2["config"]["alert_cooldown"] == {"warn": 30.0, "critical": 60.0}
    assert d2["config"]["alert_aggregation_window"] == 10.0


def test_api_token_history_with_range_and_bucket(app_client):
    r = app_client.get("/api/token/usage/history?range=24h&bucket=300")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["range"] == "24h"
    assert d["bucket"] == "300"
    assert isinstance(d["history"], list)


def test_api_token_prometheus(app_client):
    r = app_client.post(
        "/api/token/prometheus",
        json={
            "pushgateway_url": "http://127.0.0.1:1",
            "pushgateway_job": "test_job",
            "push_to_gateway_every_n": 10,
            "grouping_key": {"env": "test"},
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True


def test_api_token_alert_ack(app_client):
    r = app_client.post("/api/token/alert/ack")
    assert r.status_code == 200
    assert r.json()["ok"] is True
