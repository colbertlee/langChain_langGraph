"""tools/archive_trend.py 单测（Day 18）。"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.archive_trend import (
    list_runs,
    diff_summary,
    render_trend,
    cmd_diff,
    cmd_render,
    ACCEPTANCE_DIR,
    TREND_DOC,
)


def _make_run(base: Path, ts: str, *, passed: int, failed: int, errored: int):
    d = base / ts
    d.mkdir(parents=True, exist_ok=True)
    data = {
        "started_at": ts,
        "finished_at": ts,
        "totals": {
            "files": 21,
            "passed": passed,
            "failed": failed,
            "errored": errored,
            "skipped": 0,
            "ran_ratio": f"{passed}/{passed+failed+errored}",
        },
    }
    (d / "summary.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return d


# ---- list_runs ----

def test_list_runs_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_trend.ACCEPTANCE_DIR", tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    assert list_runs() == []


def test_list_runs_orders_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_trend.ACCEPTANCE_DIR", tmp_path)
    _make_run(tmp_path, "20250101_000000", passed=5, failed=10, errored=0)
    _make_run(tmp_path, "20250102_000000", passed=8, failed=8, errored=0)
    _make_run(tmp_path, "20250103_000000", passed=10, failed=6, errored=0)

    runs = list_runs()
    assert len(runs) == 3
    # newest first
    assert runs[0][0].name == "20250103_000000"
    assert runs[2][0].name == "20250101_000000"


def test_list_runs_respects_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_trend.ACCEPTANCE_DIR", tmp_path)
    for i in range(15):
        _make_run(tmp_path, f"20250101_{i:06d}", passed=i, failed=1, errored=0)

    assert len(list_runs(limit=5)) == 5
    assert len(list_runs(limit=20)) == 15


def test_list_runs_skips_invalid(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_trend.ACCEPTANCE_DIR", tmp_path)
    d = tmp_path / "bad"
    d.mkdir()
    (d / "summary.json").write_text("{not json", encoding="utf-8")
    _make_run(tmp_path, "20250101_000000", passed=1, failed=0, errored=0)
    runs = list_runs()
    assert len(runs) == 1


# ---- diff_summary ----

def test_diff_summary_basic():
    old = {"totals": {"passed": 5, "failed": 10, "errored": 0, "skipped": 0, "ran_ratio": "5/15"}}
    new = {"totals": {"passed": 8, "failed": 8, "errored": 0, "skipped": 0, "ran_ratio": "8/16"}}
    d = diff_summary(old, new)
    assert d["passed"] == {"old": 5, "new": 8, "delta": 3}
    assert d["failed"] == {"old": 10, "new": 8, "delta": -2}
    assert d["errored"] == {"old": 0, "new": 0, "delta": 0}


def test_diff_summary_handles_missing_fields():
    """老数据没有 ran_ratio 也不应崩。"""
    old = {"totals": {}}
    new = {"totals": {"passed": 1}}
    d = diff_summary(old, new)
    assert d["passed"]["delta"] == 1
    assert d["ran_ratio"]["old_str"] == "?"


# ---- render_trend ----

def test_render_trend_single_run():
    runs = [(Path("20250101_000000"), {"totals": {"files": 1, "passed": 1, "failed": 0, "errored": 0, "skipped": 0, "ran_ratio": "1/1"}})]
    md = render_trend(runs)
    assert "历史趋势" in md
    assert "1/1" in md
    assert "需要至少 2 次跑" in md


def test_render_trend_two_runs_show_diff():
    runs = [
        (Path("20250102_000000"), {"totals": {"files": 2, "passed": 1, "failed": 1, "errored": 0, "skipped": 0, "ran_ratio": "1/2"}}),
        (Path("20250101_000000"), {"totals": {"files": 2, "passed": 0, "failed": 2, "errored": 0, "skipped": 0, "ran_ratio": "0/2"}}),
    ]
    md = render_trend(runs)
    assert "🟢" in md  # 改进
    assert "(+1)" in md
    assert "(-1)" in md


# ---- cmd_render ----

def test_cmd_render_writes_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_trend.ACCEPTANCE_DIR", tmp_path)
    _make_run(tmp_path, "20250101_000000", passed=5, failed=0, errored=0)
    import argparse
    ns = argparse.Namespace(limit=10, output=str(tmp_path / "out.md"), diff=False, strict=False)
    rc = cmd_render(ns)
    assert rc == 0
    assert (tmp_path / "out.md").exists()


def test_cmd_render_no_data(capsys, monkeypatch):
    monkeypatch.setattr("tools.archive_trend.ACCEPTANCE_DIR", Path("/nonexistent_path_xyz"))
    import argparse
    ns = argparse.Namespace(limit=10, output=None, diff=False, strict=False)
    rc = cmd_render(ns)
    assert rc == 0
    err = capsys.readouterr().err
    assert "no acceptance runs" in err


# ---- cmd_diff ----

def test_cmd_diff_returns_1_on_regression(monkeypatch, tmp_path, capsys):
    """passed 下降 → exit 1"""
    monkeypatch.setattr("tools.archive_trend.ACCEPTANCE_DIR", tmp_path)
    _make_run(tmp_path, "20250102_000000", passed=2, failed=5, errored=0)  # newer
    _make_run(tmp_path, "20250101_000000", passed=5, failed=2, errored=0)  # older

    import argparse
    ns = argparse.Namespace(limit=2, diff=True, strict=True)
    rc = cmd_diff(ns)
    err = capsys.readouterr().err
    assert rc == 1
    assert "regression" in err


def test_cmd_diff_no_regression_when_progressing(monkeypatch, tmp_path):
    """passed 上升 → exit 0"""
    monkeypatch.setattr("tools.archive_trend.ACCEPTANCE_DIR", tmp_path)
    _make_run(tmp_path, "20250102_000000", passed=10, failed=2, errored=0)
    _make_run(tmp_path, "20250101_000000", passed=5, failed=10, errored=0)

    import argparse
    ns = argparse.Namespace(limit=2, diff=True, strict=True)
    rc = cmd_diff(ns)
    assert rc == 0


def test_cmd_diff_no_regression_when_stable(monkeypatch, tmp_path):
    """两次一样 → exit 0"""
    monkeypatch.setattr("tools.archive_trend.ACCEPTANCE_DIR", tmp_path)
    _make_run(tmp_path, "20250102_000000", passed=5, failed=2, errored=0)
    _make_run(tmp_path, "20250101_000000", passed=5, failed=2, errored=0)

    import argparse
    ns = argparse.Namespace(limit=2, diff=True, strict=True)
    rc = cmd_diff(ns)
    assert rc == 0


def test_cmd_diff_insufficient_runs(monkeypatch, tmp_path, capsys):
    """只有 1 次跑 → 友好提示"""
    monkeypatch.setattr("tools.archive_trend.ACCEPTANCE_DIR", tmp_path)
    _make_run(tmp_path, "20250101_000000", passed=1, failed=0, errored=0)

    import argparse
    ns = argparse.Namespace(limit=2, diff=True, strict=True)
    rc = cmd_diff(ns)
    err = capsys.readouterr().err
    assert rc == 0
    assert ">= 2 runs" in err


def test_cmd_diff_returns_1_on_errored_increase(monkeypatch, tmp_path, capsys):
    """errored 上升也视为回归"""
    monkeypatch.setattr("tools.archive_trend.ACCEPTANCE_DIR", tmp_path)
    _make_run(tmp_path, "20250102_000000", passed=5, failed=0, errored=5)
    _make_run(tmp_path, "20250101_000000", passed=5, failed=0, errored=0)

    import argparse
    ns = argparse.Namespace(limit=2, diff=True, strict=True)
    rc = cmd_diff(ns)
    err = capsys.readouterr().err
    assert rc == 1
    assert "regression" in err


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))