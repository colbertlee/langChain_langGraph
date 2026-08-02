"""Day 24：bucket_chats 多种聚合策略单测。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.archive_dashboard import (
    _aggregate,
    bucket_chats,
)


# ---- _aggregate ----

def test_aggregate_empty():
    assert _aggregate([], "avg") == 0.0
    assert _aggregate([], "max") == 0.0


def test_aggregate_avg():
    assert _aggregate([1, 2, 3, 4], "avg") == 2.5
    assert _aggregate([100, 200], "mean") == 150.0


def test_aggregate_max():
    assert _aggregate([1, 5, 3, 2], "max") == 5
    assert _aggregate([100], "max") == 100


def test_aggregate_min():
    assert _aggregate([1, 5, 3, 2], "min") == 1
    assert _aggregate([100], "min") == 100


def test_aggregate_median_odd():
    """奇数个元素 → 中位数是中间一个"""
    assert _aggregate([1, 2, 3, 4, 5], "median") == 3


def test_aggregate_median_even():
    """偶数个元素 → 中位数是中间两个的平均"""
    assert _aggregate([1, 2, 3, 4], "median") == 2.5


def test_aggregate_median_single():
    assert _aggregate([42], "median") == 42


def test_aggregate_p95():
    """p95 应接近最大但略小"""
    vals = [100, 200, 300, 400, 500]
    assert _aggregate(vals, "p95") > 400  # 大于第 4 个
    assert _aggregate(vals, "p95") <= 500  # ≤ 最大


def test_aggregate_p99():
    vals = list(range(100))
    val = _aggregate(vals, "p99")
    # 第 99 百分位接近最大
    assert val > 95


def test_aggregate_unknown_strategy_falls_back_to_avg():
    """未知策略 → 回退到 avg"""
    assert _aggregate([1, 2, 3, 4], "weird") == 2.5


def test_aggregate_invalid_percentile():
    """p 后面非数字 → 回退到 avg"""
    assert _aggregate([1, 2, 3, 4], "pxx") == 2.5
    assert _aggregate([1, 2, 3, 4], "p-50") == 2.5
    assert _aggregate([1, 2, 3, 4], "p200") == 2.5  # > 100


# ---- bucket_chats 多种 agg ----

def test_bucket_chats_default_avg():
    chats = [
        {"ts": "2026-07-26T10:00", "latency_ms": 100},
        {"ts": "2026-07-26T11:00", "latency_ms": 200},
        {"ts": "2026-07-26T12:00", "latency_ms": 300},
    ]
    out = bucket_chats(chats, "daily")
    assert out[0]["latency_ms"] == 200.0  # avg(100, 200, 300)


def test_bucket_chats_max():
    chats = [
        {"ts": "2026-07-26T10:00", "latency_ms": 100},
        {"ts": "2026-07-26T11:00", "latency_ms": 200},
        {"ts": "2026-07-26T12:00", "latency_ms": 300},
    ]
    out = bucket_chats(chats, "daily", agg="max")
    assert out[0]["latency_ms"] == 300


def test_bucket_chats_min():
    chats = [
        {"ts": "2026-07-26T10:00", "latency_ms": 100},
        {"ts": "2026-07-26T11:00", "latency_ms": 200},
        {"ts": "2026-07-26T12:00", "latency_ms": 300},
    ]
    out = bucket_chats(chats, "daily", agg="min")
    assert out[0]["latency_ms"] == 100


def test_bucket_chats_median():
    chats = [
        {"ts": "2026-07-26T10:00", "latency_ms": 100},
        {"ts": "2026-07-26T11:00", "latency_ms": 200},
        {"ts": "2026-07-26T12:00", "latency_ms": 300},
        {"ts": "2026-07-26T13:00", "latency_ms": 400},
    ]
    out = bucket_chats(chats, "daily", agg="median")
    # median(100, 200, 300, 400) = (200+300)/2 = 250
    assert out[0]["latency_ms"] == 250.0


def test_bucket_chats_p95():
    """p95 对性能 SLA 很重要"""
    chats = [
        {"ts": f"2026-07-26T{i:02d}:00", "latency_ms": 100 + i}
        for i in range(20)
    ]
    # 20 个 latency 100..119；p95 → ~118.55
    out = bucket_chats(chats, "daily", agg="p95")
    assert out[0]["latency_ms"] > 110


def test_bucket_chats_multi_buckets_each_aggregated():
    """多桶各自聚合"""
    chats = [
        {"ts": "2026-07-26T10:00", "latency_ms": 100},
        {"ts": "2026-07-26T11:00", "latency_ms": 300},
        {"ts": "2026-07-27T10:00", "latency_ms": 50},
        {"ts": "2026-07-27T11:00", "latency_ms": 150},
    ]
    out_max = bucket_chats(chats, "daily", agg="max")
    assert out_max[0]["latency_ms"] == 300  # day 1 max
    assert out_max[1]["latency_ms"] == 150  # day 2 max


# ---- main CLI ----

def test_main_chats_agg_max(tmp_path, monkeypatch):
    """CLI --chats-agg max 走通"""
    import json
    monkeypatch.setattr("tools.archive_dashboard.DEFAULT_OUTPUT", tmp_path / "d.svg")
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    (tmp_path / "chat_latency.json").write_text(
        json.dumps([
            {"ts": "2026-07-26T10:00", "latency_ms": 100},
            {"ts": "2026-07-26T11:00", "latency_ms": 200},
            {"ts": "2026-07-26T12:00", "latency_ms": 50},
        ]), encoding="utf-8")
    from tools.archive_dashboard import main
    rc = main(["--period", "daily", "--panels", "chats", "--chats-agg", "max"])
    assert rc == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))