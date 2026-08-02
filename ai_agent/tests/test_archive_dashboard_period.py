"""Day 22：dashboard --period 单测。"""
import sys
from pathlib import Path
from datetime import datetime, date

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.archive_dashboard import (
    _bucket_ts,
    bucket_runs,
    load_runs,
    render_multipanel_svg,
)


# ---- _bucket_ts ----

def test_bucket_ts_daily():
    """YYYYMMDD_HHMMSS → YYYY-MM-DD"""
    assert _bucket_ts("20260726_174125", "daily") == "2026-07-26"


def test_bucket_ts_weekly():
    """2026-07-26 是 ISO 第 30 周"""
    # ISO week 计算：2026-07-26 是周日 → 属于 ISO 第 30 周
    # 但 weekly 字段值是 isocalendar()[0]-W{:02d}
    out = _bucket_ts("20260726_174125", "weekly")
    assert out.startswith("2026-W")
    # 验证格式
    assert len(out) == 8


def test_bucket_ts_monthly():
    """YYYY-MM"""
    assert _bucket_ts("20260726_174125", "monthly") == "2026-07"


def test_bucket_ts_none_unchanged():
    assert _bucket_ts("20260726_174125", "none") == "20260726_174125"


def test_bucket_ts_invalid_input():
    """非法输入不崩，原样返回"""
    assert _bucket_ts("invalid", "daily") == "invalid"
    assert _bucket_ts("", "weekly") == ""


def test_bucket_ts_unknown_period():
    """未知 period → 原样"""
    assert _bucket_ts("20260726_174125", "hourly") == "20260726_174125"


def test_bucket_ts_iso_week_consistency():
    """ISO 周号应与 Python isocalendar 一致"""
    ts = "20260101_000000"  # 2026-01-01
    d = datetime.strptime(ts[:8], "%Y%m%d").date()
    expected = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
    assert _bucket_ts(ts, "weekly") == expected


# ---- bucket_runs ----

def test_bucket_runs_unchanged_for_none():
    runs = [
        {"started_at": "20260701_100000", "totals": {"passed": 5}},
        {"started_at": "20260702_110000", "totals": {"passed": 6}},
    ]
    out = bucket_runs(runs, "none")
    assert out == runs


def test_bucket_runs_daily_picks_latest_per_day():
    """同一天多条 → 只保留最新（升序遍历，后覆盖前）"""
    runs = [
        {"started_at": "20260701_090000", "totals": {"passed": 5, "failed": 1, "errored": 0}},
        {"started_at": "20260701_180000", "totals": {"passed": 8, "failed": 0, "errored": 0}},  # latest
        {"started_at": "20260702_100000", "totals": {"passed": 10, "failed": 0, "errored": 0}},
    ]
    out = bucket_runs(runs, "daily")
    assert len(out) == 2
    # 第一天 latest → passed=8
    assert out[0]["started_at"] == "2026-07-01"
    assert out[0]["totals"]["passed"] == 8
    # 第二天
    assert out[1]["started_at"] == "2026-07-02"
    assert out[1]["totals"]["passed"] == 10


def test_bucket_runs_weekly_aggregates_across_week():
    """同周多条 → 只保留最新"""
    runs = [
        {"started_at": "20260701_090000", "totals": {"passed": 5}},  # 周三
        {"started_at": "20260705_090000", "totals": {"passed": 7}},  # 周日 → 同一 ISO 周
    ]
    out = bucket_runs(runs, "weekly")
    assert len(out) == 1
    assert out[0]["totals"]["passed"] == 7


def test_bucket_runs_monthly_aggregates_across_month():
    runs = [
        {"started_at": "20260701_090000", "totals": {"passed": 5}},
        {"started_at": "20260715_090000", "totals": {"passed": 7}},
        {"started_at": "20260801_090000", "totals": {"passed": 10}},  # 新月份
    ]
    out = bucket_runs(runs, "monthly")
    assert len(out) == 2
    assert out[0]["started_at"] == "2026-07"
    assert out[0]["totals"]["passed"] == 7
    assert out[1]["started_at"] == "2026-08"


def test_bucket_runs_empty():
    assert bucket_runs([], "daily") == []


def test_bucket_runs_invalid_ts_handled():
    runs = [
        {"started_at": "invalid", "totals": {"passed": 1}},
        {"started_at": "20260701_100000", "totals": {"passed": 5}},
    ]
    out = bucket_runs(runs, "daily")
    # invalid → bucket key = "invalid"（原样），但有效 ts 仍处理
    # 实际行为：invalid 也会被 key 化为 "invalid" 进入 dict
    assert len(out) >= 1


# ---- render_multipanel_svg 接受 bucketed data ----

def test_multipanel_svg_with_daily_bucketed_data():
    """daily bucket 后数据应正确渲染"""
    data = {
        "archive_trend": [
            {"started_at": "2026-07-01", "totals": {"passed": 5, "failed": 0, "errored": 0}},
            {"started_at": "2026-07-02", "totals": {"passed": 8, "failed": 0, "errored": 0}},
        ],
        "evals": [], "chats": [],
    }
    svg = render_multipanel_svg(data)
    assert "2026-07-01" in svg or "07-01" in svg


def test_multipanel_svg_with_monthly_bucketed_data():
    data = {
        "archive_trend": [
            {"started_at": "2026-07", "totals": {"passed": 8, "failed": 0, "errored": 0}},
            {"started_at": "2026-08", "totals": {"passed": 10, "failed": 0, "errored": 0}},
        ],
        "evals": [], "chats": [],
    }
    svg = render_multipanel_svg(data)
    assert "2026-07" in svg
    assert "2026-08" in svg


# ---- CLI main ----

def test_main_period_daily(tmp_path, monkeypatch):
    """--period daily 走通 CLI"""
    import json
    monkeypatch.setattr("tools.archive_dashboard.ACCEPTANCE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_dashboard.DEFAULT_OUTPUT", tmp_path / "d.svg")
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    # 两份 summary 同一天
    (tmp_path / "20260701_090000").mkdir()
    (tmp_path / "20260701_090000" / "summary.json").write_text(
        json.dumps({"started_at": "20260701_090000", "totals": {"passed": 5, "failed": 0, "errored": 0}, "files": []}), encoding="utf-8")
    (tmp_path / "20260701_180000").mkdir()
    (tmp_path / "20260701_180000" / "summary.json").write_text(
        json.dumps({"started_at": "20260701_180000", "totals": {"passed": 8, "failed": 0, "errored": 0}, "files": []}), encoding="utf-8")

    from tools.archive_dashboard import main
    rc = main(["--period", "daily", "--panels", "archive"])
    assert rc == 0
    svg = (tmp_path / "d.svg").read_text(encoding="utf-8")
    # 应该只显示 1 个点（daily bucket 合并了）
    assert "2026-07-01" in svg


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))