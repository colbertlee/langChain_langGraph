"""Day 25：业务 metrics panel + bucket_business 单测。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.archive_dashboard import (
    load_business,
    bucket_business,
    _render_business_panel,
    render_multipanel_svg,
)
from tools.business_metrics import (
    inject_mock,
    aggregate_daily,
    save,
    load as bm_load,
    DEFAULT_PATH,
)


# ---- load_business ----

def test_load_business_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    assert load_business() == []


def test_load_business_reads_list(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    p = tmp_path / "bm.json"
    p.write_text(json.dumps([
        {"ts": "2026-07-26T00:00", "chat_count": 100, "user_count": 50, "revenue_usd": 10.0},
    ]), encoding="utf-8")
    out = load_business(path=p)
    assert len(out) == 1
    assert out[0]["chat_count"] == 100


# ---- bucket_business ----

def test_bucket_business_none_unchanged():
    data = [{"ts": "t", "chat_count": 1}]
    assert bucket_business(data, "none") == data


def test_bucket_business_daily_sum_chat_revenue():
    """chat_count / revenue 按日求和；user_count 取 last"""
    data = [
        {"ts": "2026-07-26T09:00", "chat_count": 100, "user_count": 50, "revenue_usd": 10.0},
        {"ts": "2026-07-26T15:00", "chat_count": 200, "user_count": 55, "revenue_usd": 20.0},
        {"ts": "2026-07-27T10:00", "chat_count": 150, "user_count": 60, "revenue_usd": 15.0},
    ]
    out = bucket_business(data, "daily")
    assert len(out) == 2
    # Day 1
    assert out[0]["ts"] == "2026-07-26"
    assert out[0]["chat_count"] == 300   # sum
    assert out[0]["revenue_usd"] == 30.0
    assert out[0]["user_count"] == 55   # last (latest row)
    # Day 2
    assert out[1]["chat_count"] == 150
    assert out[1]["user_count"] == 60


def test_bucket_business_monthly():
    data = [
        {"ts": "2026-07-01", "chat_count": 100, "revenue_usd": 10.0},
        {"ts": "2026-07-15", "chat_count": 200, "revenue_usd": 20.0},
        {"ts": "2026-08-01", "chat_count": 150, "revenue_usd": 15.0},
    ]
    out = bucket_business(data, "monthly")
    assert len(out) == 2
    assert out[0]["chat_count"] == 300
    assert out[1]["chat_count"] == 150


def test_bucket_business_empty():
    assert bucket_business([], "daily") == []


# ---- _render_business_panel ----

def test_render_business_panel_empty():
    parts: list[str] = []
    _render_business_panel([], 0, 0, 360, 300, parts)
    out = "\n".join(parts)
    assert "no business data" in out


def test_render_business_panel_with_data():
    parts: list[str] = []
    business = [
        {"ts": "2026-07-26", "chat_count": 100, "user_count": 50, "revenue_usd": 10.0},
        {"ts": "2026-07-27", "chat_count": 200, "user_count": 60, "revenue_usd": 20.0},
        {"ts": "2026-07-28", "chat_count": 150, "user_count": 70, "revenue_usd": 15.0},
    ]
    _render_business_panel(business, 0, 0, 360, 300, parts)
    out = "\n".join(parts)
    assert "business" in out
    assert "polyline" in out   # chat_count line
    assert "rect" in out        # revenue bars
    assert "users 70" in out    # latest user_count


def test_render_business_panel_single_point():
    parts: list[str] = []
    business = [{"ts": "2026-07-26", "chat_count": 100, "user_count": 50, "revenue_usd": 10.0}]
    _render_business_panel(business, 0, 0, 360, 300, parts)
    out = "\n".join(parts)
    assert "polyline" in out  # 应能渲染（n=1）
    assert "users 50" in out


# ---- render_multipanel_svg 4 panel ----

def test_multipanel_svg_with_business_panel():
    svg = render_multipanel_svg(
        {
            "archive_trend": [],
            "evals": [],
            "chats": [],
            "business": [{"ts": "2026-07-26", "chat_count": 100, "user_count": 50, "revenue_usd": 10.0}],
        },
    )
    assert "no archive data" in svg
    assert "no evals data" in svg
    assert "no chat data" in svg
    assert "business" in svg
    # 默认 width = 1440 (4 panel 拉宽)
    assert 'width="1440"' in svg


def test_multipanel_svg_width_4_panels():
    svg = render_multipanel_svg(
        {"archive_trend": [], "evals": [], "chats": [], "business": []},
    )
    # 4 panel 横向布局；width 拉到 1440
    assert 'width="1440"' in svg
    # 4 个 no xxx data 占位（每个 panel 一个）
    assert "no archive data" in svg
    assert "no evals data" in svg
    assert "no chat data" in svg
    assert "no business data" in svg


# ---- business_metrics 工具 ----

def test_business_inject_mock(tmp_path):
    data = inject_mock(n=5)
    assert len(data) == 5
    assert all("chat_count" in d for d in data)
    assert all("user_count" in d for d in data)
    assert all("revenue_usd" in d for d in data)


def test_business_aggregate_daily():
    data = [
        {"ts": "2026-07-26T09:00", "chat_count": 100, "user_count": 50, "revenue_usd": 10.0},
        {"ts": "2026-07-26T15:00", "chat_count": 200, "user_count": 55, "revenue_usd": 20.0},
        {"ts": "2026-07-27T10:00", "chat_count": 150, "user_count": 60, "revenue_usd": 15.0},
    ]
    out = aggregate_daily(data)
    assert len(out) == 2
    assert out[0]["chat_count"] == 300
    assert out[0]["user_count"] == 55
    assert out[0]["revenue_usd"] == 30.0


def test_business_save_load(tmp_path):
    p = tmp_path / "bm.json"
    data = inject_mock(n=3)
    save(data, p)
    loaded = bm_load(p)
    assert len(loaded) == 3
    assert loaded[0]["chat_count"] == data[0]["chat_count"]


# ---- main CLI business panel ----

def test_main_panels_business(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr("tools.archive_dashboard.DEFAULT_OUTPUT", tmp_path / "d.svg")
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    (tmp_path / "business_metrics.json").write_text(
        json.dumps([
            {"ts": "2026-07-26", "chat_count": 100, "user_count": 50, "revenue_usd": 10.0},
            {"ts": "2026-07-27", "chat_count": 150, "user_count": 60, "revenue_usd": 15.0},
        ]), encoding="utf-8")
    from tools.archive_dashboard import main
    rc = main(["--panels", "business"])
    assert rc == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))