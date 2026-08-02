"""Day 21：archive_dashboard 多 panel 单测。"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools import archive_dashboard as ad
from tools.archive_dashboard import (
    load_runs,
    load_evals,
    load_chats,
    render_multipanel_svg,
    _render_archive_trend_panel,
    _render_evals_panel,
    _render_latency_panel,
)


def _make_summary(base: Path, ts: str, totals: dict):
    d = base / ts
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(
        json.dumps({"started_at": ts, "finished_at": ts, "totals": totals, "files": []},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---- load_evals ----

def test_load_evals_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    assert load_evals() == []


def test_load_evals_reads_list(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    p = tmp_path / "evals_history.json"
    p.write_text(json.dumps([{"ts": "20260101", "pass_rate": 0.9, "total": 10, "latency_ms": 100}]), encoding="utf-8")
    out = load_evals(path=p)
    assert len(out) == 1
    assert out[0]["pass_rate"] == 0.9


def test_load_evals_respects_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    p = tmp_path / "evals_history.json"
    p.write_text(json.dumps([{"ts": f"t{i}", "pass_rate": i/10, "total": i, "latency_ms": i*10} for i in range(20)]), encoding="utf-8")
    out = load_evals(limit=5, path=p)
    assert len(out) == 5


def test_load_evals_handles_non_list(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    p = tmp_path / "evals_history.json"
    p.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    assert load_evals(path=p) == []


# ---- load_chats ----

def test_load_chats_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    assert load_chats() == []


def test_load_chats_reads_list(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    p = tmp_path / "chat_latency.json"
    p.write_text(json.dumps([{"ts": "t1", "latency_ms": 100}, {"ts": "t2", "latency_ms": 200}]), encoding="utf-8")
    out = load_chats(path=p)
    assert len(out) == 2


# ---- render_multipanel_svg ----

def test_multipanel_svg_returns_valid_xml():
    svg = render_multipanel_svg(
        {"archive_trend": [], "evals": [], "chats": []},
    )
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    # 3 个"no xxx data" 占位
    assert "no archive data" in svg
    assert "no evals data" in svg
    assert "no chat data" in svg


def test_multipanel_svg_with_all_data(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ACCEPTANCE_DIR", tmp_path)
    _make_summary(tmp_path, "20250101_000000",
                  totals={"passed": 5, "failed": 2, "errored": 0})
    _make_summary(tmp_path, "20250102_000000",
                  totals={"passed": 8, "failed": 1, "errored": 0})

    svg = render_multipanel_svg(
        {
            "archive_trend": load_runs(),
            "evals": [
                {"ts": "20250101T10:00", "pass_rate": 0.9, "total": 30, "latency_ms": 100},
                {"ts": "20250102T10:00", "pass_rate": 0.85, "total": 28, "latency_ms": 150},
            ],
            "chats": [
                {"ts": "t1", "latency_ms": 300},
                {"ts": "t2", "latency_ms": 450},
                {"ts": "t3", "latency_ms": 200},
            ],
        },
    )
    assert "<svg" in svg
    # 没有"no xxx data"
    assert "no archive data" not in svg
    assert "no evals data" not in svg
    assert "no chat data" not in svg
    # 标题应包含 "multi-panel"
    assert "multi-panel" in svg


def test_multipanel_svg_3_panels_layout():
    """3 panel 横向分布"""
    svg = render_multipanel_svg(
        {"archive_trend": [], "evals": [], "chats": []},
        width=900, height=300,
    )
    # 三个 panel title 都存在
    assert "archive trend" in svg
    assert "evals" in svg
    assert "chat latency" in svg


# ---- _render_evals_panel ----

def test_evals_panel_with_data():
    parts: list[str] = []
    _render_evals_panel(
        [
            {"ts": "t1", "pass_rate": 0.9, "total": 10, "latency_ms": 100},
            {"ts": "t2", "pass_rate": 0.8, "total": 10, "latency_ms": 200},
        ],
        x=0, y=0, w=360, h=300, parts=parts,
    )
    out = "\n".join(parts)
    assert "polyline" in out  # pass_rate 线
    assert "rect" in out  # latency bars
    assert "pass_rate" in out


def test_evals_panel_empty():
    parts: list[str] = []
    _render_evals_panel([], 0, 0, 360, 300, parts)
    assert "no evals data" in "\n".join(parts)


# ---- _render_latency_panel ----

def test_latency_panel_with_data():
    parts: list[str] = []
    _render_latency_panel(
        [
            {"ts": "t1", "latency_ms": 100},
            {"ts": "t2", "latency_ms": 500},
            {"ts": "t3", "latency_ms": 200},
        ],
        x=0, y=0, w=360, h=300, parts=parts,
    )
    out = "\n".join(parts)
    assert "rect" in out
    assert "avg" in out


def test_latency_panel_empty():
    parts: list[str] = []
    _render_latency_panel([], 0, 0, 360, 300, parts)
    assert "no chat data" in "\n".join(parts)


def test_latency_panel_color_thresholds():
    """< 50% → 绿；50-75% → 橙；> 75% → 红"""
    parts: list[str] = []
    _render_latency_panel(
        [
            {"ts": "t1", "latency_ms": 10},    # 最小 → 绿
            {"ts": "t2", "latency_ms": 60},    # 60% → 橙
            {"ts": "t3", "latency_ms": 90},    # 90% → 红
        ],
        x=0, y=0, w=360, h=300, parts=parts,
    )
    out = "\n".join(parts)
    # 三种颜色都应出现
    assert "#34c759" in out  # passed
    assert "#ff9500" in out  # failed
    assert "#ff3b30" in out  # errored


# ---- _render_archive_trend_panel ----

def test_archive_trend_panel_with_data():
    parts: list[str] = []
    _render_archive_trend_panel(
        [
            {"started_at": "20250101_000000", "totals": {"passed": 5, "failed": 0, "errored": 0}},
            {"started_at": "20250102_000000", "totals": {"passed": 8, "failed": 0, "errored": 0}},
        ],
        x=0, y=0, w=360, h=300, parts=parts,
    )
    out = "\n".join(parts)
    assert "polyline" in out
    assert "circle" in out


def test_archive_trend_panel_empty():
    parts: list[str] = []
    _render_archive_trend_panel([], 0, 0, 360, 300, parts)
    assert "no archive data" in "\n".join(parts)


# ---- CLI main ----

def test_main_panels_all(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ACCEPTANCE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_dashboard.DEFAULT_OUTPUT", tmp_path / "dashboard.svg")
    _make_summary(tmp_path, "20250101_000000", totals={"passed": 5, "failed": 0, "errored": 0})

    # mock evals/chats
    (tmp_path / "evals_history.json").write_text(json.dumps([{"ts": "t", "pass_rate": 0.9, "total": 1, "latency_ms": 1}]), encoding="utf-8")
    (tmp_path / "chat_latency.json").write_text(json.dumps([{"ts": "t", "latency_ms": 100}]), encoding="utf-8")
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)

    from tools.archive_dashboard import main
    rc = main(["--panels", "all"])
    assert rc == 0
    assert (tmp_path / "dashboard.svg").exists()


def test_main_panels_archive_only(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ACCEPTANCE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_dashboard.DEFAULT_OUTPUT", tmp_path / "dashboard.svg")
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    _make_summary(tmp_path, "20250101_000000", totals={"passed": 5, "failed": 0, "errored": 0})

    from tools.archive_dashboard import main
    rc = main(["--panels", "archive"])
    assert rc == 0


def test_main_panels_evals_only(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.DEFAULT_OUTPUT", tmp_path / "dashboard.svg")
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    (tmp_path / "evals_history.json").write_text(json.dumps([{"ts": "t", "pass_rate": 0.9, "total": 1, "latency_ms": 1}]), encoding="utf-8")
    from tools.archive_dashboard import main
    rc = main(["--panels", "evals"])
    assert rc == 0


def test_main_panels_chats_only(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.DEFAULT_OUTPUT", tmp_path / "dashboard.svg")
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    (tmp_path / "chat_latency.json").write_text(json.dumps([{"ts": "t", "latency_ms": 100}]), encoding="utf-8")
    from tools.archive_dashboard import main
    rc = main(["--panels", "chats"])
    assert rc == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))