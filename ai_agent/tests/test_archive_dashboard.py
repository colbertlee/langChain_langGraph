"""tools/archive_dashboard.py 单测（Day 20）。"""
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
    render_svg,
    _short_ts,
    _empty_svg,
    DEFAULT_OUTPUT,
    ACCEPTANCE_DIR,
)


def _make_summary(base: Path, ts: str, totals: dict):
    d = base / ts
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(
        json.dumps({"started_at": ts, "finished_at": ts, "totals": totals, "files": []},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---- _short_ts ----

def test_short_ts_format():
    assert _short_ts("20260726_174125") == "07-26 17:41"


def test_short_ts_handles_short_input():
    assert _short_ts("?") == "?"


def test_short_ts_handles_garbage():
    assert _short_ts("xxx") == "xxx"


# ---- load_runs ----

def test_load_runs_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ACCEPTANCE_DIR", tmp_path)
    assert load_runs() == []


def test_load_runs_orders_ascending(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ACCEPTANCE_DIR", tmp_path)
    _make_summary(tmp_path, "20250103_000000", totals={"passed": 10, "failed": 0, "errored": 0})
    _make_summary(tmp_path, "20250101_000000", totals={"passed": 5, "failed": 1, "errored": 0})
    _make_summary(tmp_path, "20250102_000000", totals={"passed": 8, "failed": 0, "errored": 1})

    runs = load_runs()
    assert [r["started_at"] for r in runs] == ["20250101_000000", "20250102_000000", "20250103_000000"]


def test_load_runs_skips_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ACCEPTANCE_DIR", tmp_path)
    _make_summary(tmp_path, "20250101_000000", totals={"passed": 0, "failed": 0, "errored": 0})
    _make_summary(tmp_path, "20250102_000000", totals={"passed": 5, "failed": 1, "errored": 0})

    runs = load_runs()
    assert len(runs) == 1
    assert runs[0]["started_at"] == "20250102_000000"


def test_load_runs_respects_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ACCEPTANCE_DIR", tmp_path)
    for i in range(15):
        _make_summary(tmp_path, f"20250101_{i:06d}",
                     totals={"passed": i, "failed": 0, "errored": 0})

    runs = load_runs(limit=5)
    assert len(runs) == 5


# ---- render_svg ----

def test_render_svg_returns_valid_xml():
    runs = [
        {"started_at": "20250101_000000", "totals": {"passed": 5, "failed": 2, "errored": 1, "skipped": 0}},
        {"started_at": "20250102_000000", "totals": {"passed": 8, "failed": 1, "errored": 0, "skipped": 0}},
    ]
    svg = render_svg(runs)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert 'viewBox="0 0 760 360"' in svg


def test_render_svg_empty_data():
    """Day 21：render_svg 现在走多 panel 模板。空数据应显示 "no xxx data"。"""
    svg = render_svg([])
    assert "no archive data" in svg


def test_render_svg_includes_all_lines():
    runs = [
        {"started_at": "20250101_000000", "totals": {"passed": 5, "failed": 2, "errored": 1, "skipped": 0}},
    ]
    svg = render_svg(runs)
    # 4 条线 (passed/failed/errored/ratio)
    assert svg.count("<polyline") == 4
    # 3 类点（passed/failed/errored 圆点）
    assert svg.count("<circle") == 3


def test_render_svg_with_x_labels():
    runs = [
        {"started_at": "20250101_000000", "totals": {"passed": 5, "failed": 0, "errored": 0, "skipped": 0}},
        {"started_at": "20250102_000000", "totals": {"passed": 8, "failed": 0, "errored": 0, "skipped": 0}},
    ]
    svg = render_svg(runs)
    # 应该有 X 轴 label
    assert "01-01" in svg
    assert "01-02" in svg


def test_render_svg_legend_present():
    """Day 21：render_svg 现在走多 panel 模板。"""
    runs = [{"started_at": "20250101_000000", "totals": {"passed": 5, "failed": 0, "errored": 0, "skipped": 0}}]
    svg = render_svg(runs)
    # panel 标题 + 颜色 line 存在
    assert "archive trend" in svg
    # 3 条线颜色 + 1 条 ratio 线
    assert "#34c759" in svg  # passed
    assert "#ff9500" in svg  # failed
    assert "#ff3b30" in svg  # errored
    assert "#0a84ff" in svg  # ran_ratio


def test_render_svg_uses_correct_colors():
    runs = [{"started_at": "20250101_000000", "totals": {"passed": 5, "failed": 0, "errored": 0, "skipped": 0}}]
    svg = render_svg(runs)
    # 验证绿色 (passed)
    assert "#34c759" in svg
    assert "#ff9500" in svg
    assert "#ff3b30" in svg
    assert "#0a84ff" in svg


# ---- _empty_svg ----

def test_empty_svg_includes_message():
    svg = _empty_svg("test msg", 760, 360)
    assert "test msg" in svg


# ---- CLI main ----

def test_main_writes_svg(tmp_path, monkeypatch):
    """CLI 默认写到 tests-archive/dashboard.svg"""
    monkeypatch.setattr("tools.archive_dashboard.ACCEPTANCE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_dashboard.DEFAULT_OUTPUT", tmp_path / "dashboard.svg")
    _make_summary(tmp_path, "20250101_000000", totals={"passed": 5, "failed": 0, "errored": 0})

    rc = ad.main([])
    assert rc == 0
    out = (tmp_path / "dashboard.svg").read_text(encoding="utf-8")
    assert out.startswith("<svg")


def test_main_with_slack_upload_mock(tmp_path, monkeypatch):
    """--slack-token + --slack-channel 触发上传（mocked）"""
    monkeypatch.setattr("tools.archive_dashboard.ACCEPTANCE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_dashboard.DEFAULT_OUTPUT", tmp_path / "dashboard.svg")
    _make_summary(tmp_path, "20250101_000000", totals={"passed": 5, "failed": 0, "errored": 0})

    fake_resp = MagicMock() if False else None  # noqa
    from unittest.mock import MagicMock
    fake_resp = MagicMock()
    fake_resp.getcode = MagicMock(return_value=200)
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=fake_resp):
        rc = ad.main(["--slack-token", "xoxb-test", "--slack-channel", "#daily-health"])
    assert rc == 0


def test_main_slack_upload_4xx_returns_1(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_dashboard.ACCEPTANCE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_dashboard.DEFAULT_OUTPUT", tmp_path / "dashboard.svg")
    _make_summary(tmp_path, "20250101_000000", totals={"passed": 5, "failed": 0, "errored": 0})

    import urllib.error
    fake = urllib.error.HTTPError(
        url="https://slack.com/api/files.upload",
        code=404, msg="Not Found", hdrs={}, fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=fake):
        rc = ad.main(["--slack-token", "xoxb-test", "--slack-channel", "#daily-health"])
    assert rc == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))