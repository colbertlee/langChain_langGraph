"""Day 23：bucket_evals / bucket_chats 单测（period 应用于所有 panel）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.archive_dashboard import (
    _bucket_ts_from_iso,
    bucket_evals,
    bucket_chats,
)


# ---- _bucket_ts_from_iso ----

def test_bucket_iso_format():
    """ISO ``YYYY-MM-DDTHH:MM:SS``"""
    assert _bucket_ts_from_iso("2026-07-26T10:30:00", "daily") == "2026-07-26"


def test_bucket_space_format():
    assert _bucket_ts_from_iso("2026-07-26 10:30:00", "daily") == "2026-07-26"


def test_bucket_short_format():
    assert _bucket_ts_from_iso("2026-07-26", "daily") == "2026-07-26"


def test_bucket_compact_format():
    assert _bucket_ts_from_iso("20260726_103000", "daily") == "2026-07-26"


def test_bucket_iso_weekly():
    assert _bucket_ts_from_iso("2026-07-26", "weekly").startswith("2026-W")


def test_bucket_iso_monthly():
    assert _bucket_ts_from_iso("2026-07-26", "monthly") == "2026-07"


def test_bucket_iso_invalid():
    """非法输入 → 原样返回"""
    assert _bucket_ts_from_iso("invalid", "daily") == "invalid"
    assert _bucket_ts_from_iso("", "weekly") == ""


def test_bucket_iso_none_period():
    assert _bucket_ts_from_iso("2026-07-26", "none") == "2026-07-26"


# ---- bucket_evals ----

def test_bucket_evals_none_unchanged():
    evals = [
        {"ts": "2026-07-01T10:00", "pass_rate": 0.9, "total": 10, "latency_ms": 100},
        {"ts": "2026-07-02T10:00", "pass_rate": 0.85, "total": 10, "latency_ms": 150},
    ]
    out = bucket_evals(evals, "none")
    assert out == evals


def test_bucket_evals_daily_picks_latest():
    """同一天多条 → 取 latest（按 evals 升序遍历，后覆盖前）"""
    evals = [
        {"ts": "2026-07-01T09:00", "pass_rate": 0.8, "total": 10, "latency_ms": 200},
        {"ts": "2026-07-01T18:00", "pass_rate": 0.95, "total": 10, "latency_ms": 100},  # latest
        {"ts": "2026-07-02T10:00", "pass_rate": 0.9, "total": 10, "latency_ms": 120},
    ]
    out = bucket_evals(evals, "daily")
    assert len(out) == 2
    assert out[0]["ts"] == "2026-07-01"
    assert out[0]["pass_rate"] == 0.95  # 18:00 那条
    assert out[0]["latency_ms"] == 100
    assert out[1]["ts"] == "2026-07-02"


def test_bucket_evals_weekly():
    evals = [
        {"ts": "2026-07-01T09:00", "pass_rate": 0.8, "total": 10, "latency_ms": 100},
        {"ts": "2026-07-05T09:00", "pass_rate": 0.9, "total": 10, "latency_ms": 100},  # 同一 ISO 周
    ]
    out = bucket_evals(evals, "weekly")
    assert len(out) == 1
    assert out[0]["pass_rate"] == 0.9


def test_bucket_evals_monthly():
    evals = [
        {"ts": "2026-07-01", "pass_rate": 0.8, "total": 10, "latency_ms": 100},
        {"ts": "2026-07-15", "pass_rate": 0.9, "total": 10, "latency_ms": 100},
        {"ts": "2026-08-01", "pass_rate": 0.95, "total": 10, "latency_ms": 100},
    ]
    out = bucket_evals(evals, "monthly")
    assert len(out) == 2
    assert out[0]["ts"] == "2026-07"
    assert out[1]["ts"] == "2026-08"


def test_bucket_evals_empty():
    assert bucket_evals([], "daily") == []


def test_bucket_evals_handles_mixed_formats():
    evals = [
        {"ts": "2026-07-26T10:00", "pass_rate": 0.8, "total": 10, "latency_ms": 100},
        {"ts": "20260726_110000", "pass_rate": 0.85, "total": 10, "latency_ms": 100},
        {"ts": "2026-07-26 12:00:00", "pass_rate": 0.9, "total": 10, "latency_ms": 100},
    ]
    out = bucket_evals(evals, "daily")
    # 三种格式都解析到同一天
    assert len(out) == 1
    assert out[0]["ts"] == "2026-07-26"
    assert out[0]["pass_rate"] == 0.9  # latest


# ---- bucket_chats ----

def test_bucket_chats_none_unchanged():
    chats = [{"ts": "t1", "latency_ms": 100}, {"ts": "t2", "latency_ms": 200}]
    out = bucket_chats(chats, "none")
    assert out == chats


def test_bucket_chats_daily_averages():
    """chats 是样本，应 average 而不是 latest"""
    chats = [
        {"ts": "2026-07-26T10:00", "latency_ms": 100},
        {"ts": "2026-07-26T11:00", "latency_ms": 200},
        {"ts": "2026-07-26T12:00", "latency_ms": 300},
        # next day
        {"ts": "2026-07-27T10:00", "latency_ms": 400},
    ]
    out = bucket_chats(chats, "daily")
    assert len(out) == 2
    assert out[0]["ts"] == "2026-07-26"
    assert out[0]["latency_ms"] == 200.0  # avg(100, 200, 300)
    assert out[1]["ts"] == "2026-07-27"
    assert out[1]["latency_ms"] == 400.0


def test_bucket_chats_monthly():
    chats = [
        {"ts": "2026-07-01T10:00", "latency_ms": 100},
        {"ts": "2026-07-15T10:00", "latency_ms": 300},
        {"ts": "2026-08-01T10:00", "latency_ms": 200},
    ]
    out = bucket_chats(chats, "monthly")
    assert len(out) == 2
    assert out[0]["ts"] == "2026-07"
    assert out[0]["latency_ms"] == 200.0  # avg(100, 300)
    assert out[1]["ts"] == "2026-08"
    assert out[1]["latency_ms"] == 200.0


def test_bucket_chats_empty():
    assert bucket_chats([], "daily") == []


def test_bucket_chats_single_sample_unchanged():
    """一个桶只有一个样本 → avg = 该样本"""
    chats = [{"ts": "2026-07-26T10:00", "latency_ms": 250}]
    out = bucket_chats(chats, "daily")
    assert len(out) == 1
    assert out[0]["latency_ms"] == 250.0


# ---- main CLI ----

def test_main_period_daily_applies_to_all_panels(tmp_path, monkeypatch):
    """CLI --period daily 应影响所有 panel"""
    import json
    monkeypatch.setattr("tools.archive_dashboard.ACCEPTANCE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_dashboard.DEFAULT_OUTPUT", tmp_path / "d.svg")
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)

    (tmp_path / "evals_history.json").write_text(
        json.dumps([
            {"ts": "2026-07-26T09:00", "pass_rate": 0.8, "total": 10, "latency_ms": 100},
            {"ts": "2026-07-26T18:00", "pass_rate": 0.9, "total": 10, "latency_ms": 200},
        ]), encoding="utf-8")
    (tmp_path / "chat_latency.json").write_text(
        json.dumps([
            {"ts": "2026-07-26T10:00", "latency_ms": 100},
            {"ts": "2026-07-26T11:00", "latency_ms": 200},
        ]), encoding="utf-8")

    from tools.archive_dashboard import main
    rc = main(["--period", "daily", "--panels", "evals"])
    assert rc == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))