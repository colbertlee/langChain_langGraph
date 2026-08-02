"""tools/archive_changelog.py Day 20 退化 emoji 单测。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.archive_changelog import (
    _read_two_latest_summaries,
    _regression_emoji,
    build_line,
    append_changelog_line,
)


def _make_summary(base: Path, ts: str, totals: dict):
    d = base / ts
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(
        json.dumps(
            {
                "started_at": ts,
                "finished_at": ts,
                "totals": totals,
                "files": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ---- _regression_emoji ----

def test_regression_emoji_when_passed_decreases():
    latest = {"totals": {"passed": 5, "failed": 3, "errored": 0}}
    prev = {"totals": {"passed": 8, "failed": 3, "errored": 0}}
    out = _regression_emoji(latest, prev)
    assert "⚠️" in out


def test_regression_emoji_when_failed_increases():
    latest = {"totals": {"passed": 5, "failed": 10, "errored": 0}}
    prev = {"totals": {"passed": 5, "failed": 3, "errored": 0}}
    out = _regression_emoji(latest, prev)
    assert "🚨" in out


def test_regression_emoji_when_errored_increases():
    latest = {"totals": {"passed": 5, "failed": 0, "errored": 5}}
    prev = {"totals": {"passed": 5, "failed": 0, "errored": 0}}
    out = _regression_emoji(latest, prev)
    assert "🚨" in out


def test_regression_emoji_when_no_change():
    latest = {"totals": {"passed": 5, "failed": 3, "errored": 0}}
    prev = {"totals": {"passed": 5, "failed": 3, "errored": 0}}
    out = _regression_emoji(latest, prev)
    assert out.startswith("🟢")


def test_regression_emoji_when_all_progressing():
    """全变好 → 应是 🟢"""
    latest = {"totals": {"passed": 10, "failed": 0, "errored": 0}}
    prev = {"totals": {"passed": 5, "failed": 5, "errored": 0}}
    out = _regression_emoji(latest, prev)
    assert out.startswith("🟢")


def test_regression_emoji_when_no_prev():
    """没有 prev → 无 emoji"""
    out = _regression_emoji({"totals": {}}, None)
    assert out == ""


def test_regression_emoji_multi_flags():
    """passed↓ + failed↑ + errored↑ → 三 emoji 全出现"""
    latest = {"totals": {"passed": 5, "failed": 8, "errored": 2}}
    prev = {"totals": {"passed": 10, "failed": 3, "errored": 0}}
    out = _regression_emoji(latest, prev)
    assert "⚠️" in out
    assert "🚨" in out
    assert not out.startswith("🟢")


# ---- _read_two_latest_summaries ----

def test_read_two_latest_returns_both(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_changelog.ACCEPTANCE_DIR", tmp_path)
    _make_summary(tmp_path, "20250102_000000",
                  totals={"passed": 8, "failed": 2, "errored": 1, "skipped": 0, "ran_ratio": "8/11", "files": 11})
    _make_summary(tmp_path, "20250101_000000",
                  totals={"passed": 5, "failed": 5, "errored": 0, "skipped": 0, "ran_ratio": "5/10", "files": 10})

    latest, prev = _read_two_latest_summaries()
    assert latest is not None
    assert prev is not None
    assert latest["totals"]["ran_ratio"] == "8/11"
    assert prev["totals"]["ran_ratio"] == "5/10"


def test_read_two_latest_skips_empty_runs(tmp_path, monkeypatch):
    """最近一次跑空 → 跳过，取上两次真跑"""
    monkeypatch.setattr("tools.archive_changelog.ACCEPTANCE_DIR", tmp_path)
    _make_summary(tmp_path, "20250103_000000",
                  totals={"passed": 0, "failed": 0, "errored": 0, "skipped": 0, "ran_ratio": "0/0", "files": 0})  # 空跑
    _make_summary(tmp_path, "20250102_000000",
                  totals={"passed": 8, "failed": 2, "errored": 0, "skipped": 0, "ran_ratio": "8/10", "files": 10})
    _make_summary(tmp_path, "20250101_000000",
                  totals={"passed": 5, "failed": 5, "errored": 0, "skipped": 0, "ran_ratio": "5/10", "files": 10})

    latest, prev = _read_two_latest_summaries()
    # latest 应该是 20250102（跳过 20250103 空跑）
    assert latest["started_at"] == "20250102_000000"
    assert prev["started_at"] == "20250101_000000"


def test_read_two_latest_only_one(tmp_path, monkeypatch):
    """只有一份 summary → prev = None"""
    monkeypatch.setattr("tools.archive_changelog.ACCEPTANCE_DIR", tmp_path)
    _make_summary(tmp_path, "20250101_000000",
                  totals={"passed": 5, "failed": 0, "errored": 0, "skipped": 0, "ran_ratio": "5/5", "files": 5})
    latest, prev = _read_two_latest_summaries()
    assert latest is not None
    assert prev is None


# ---- build_line ----

def test_build_line_without_emoji_when_no_prev():
    s = {"started_at": "2026-12-01T10:00:00", "totals": {"ran_ratio": "5/10", "passed": 5, "failed": 2, "errored": 1, "skipped": 0}}
    line = build_line(s)
    assert "🟢" not in line
    assert "⚠️" not in line
    assert "🚨" not in line


def test_build_line_with_warning_emoji():
    latest = {"started_at": "2026-12-01T10:00:00", "totals": {"ran_ratio": "5/10", "passed": 5, "failed": 2, "errored": 0, "skipped": 0}}
    prev = {"totals": {"passed": 8, "failed": 2, "errored": 0}}  # passed 下降
    line = build_line(latest, prev=prev)
    assert "⚠️" in line


def test_build_line_with_no_regression_green_emoji():
    latest = {"started_at": "2026-12-01T10:00:00", "totals": {"ran_ratio": "10/10", "passed": 10, "failed": 0, "errored": 0, "skipped": 0}}
    prev = {"totals": {"passed": 5, "failed": 0, "errored": 0}}  # 改善
    line = build_line(latest, prev=prev)
    assert "🟢" in line


# ---- append_changelog_line 集成 ----

def test_append_changelog_with_regression_marker(tmp_path, monkeypatch):
    """end-to-end：prev 差 + latest 退步，应自动加 emoji"""
    monkeypatch.setattr("tools.archive_changelog.ACCEPTANCE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_changelog.CHANGELOG", tmp_path / "CHANGELOG.md")

    # prev 更好
    _make_summary(tmp_path, "20250102_000000",
                  totals={"passed": 10, "failed": 0, "errored": 0, "skipped": 0, "ran_ratio": "10/10", "files": 10})
    # latest 退步
    _make_summary(tmp_path, "20250103_000000",
                  totals={"passed": 5, "failed": 5, "errored": 2, "skipped": 0, "ran_ratio": "5/12", "files": 12})

    rc = append_changelog_line()
    assert rc == 0
    out = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    # 至少有一个退化 emoji
    assert "⚠️" in out or "🚨" in out


def test_append_changelog_no_regression_green(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_changelog.ACCEPTANCE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_changelog.CHANGELOG", tmp_path / "CHANGELOG.md")
    _make_summary(tmp_path, "20250102_000000",
                  totals={"passed": 5, "failed": 0, "errored": 0, "skipped": 0, "ran_ratio": "5/5", "files": 5})
    _make_summary(tmp_path, "20250103_000000",
                  totals={"passed": 10, "failed": 0, "errored": 0, "skipped": 0, "ran_ratio": "10/10", "files": 10})

    rc = append_changelog_line()
    assert rc == 0
    out = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "🟢" in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))