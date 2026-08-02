"""tools/archive_changelog.py 单测（Day 19）。"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.archive_changelog import (
    _read_latest_summary,
    build_line,
    append_changelog_line,
    CHANGELOG,
    ACCEPTANCE_DIR,
)


def _make_acceptance(base: Path, ts: str, *, totals: dict, files_status: dict | None = None):
    d = base / ts
    d.mkdir(parents=True, exist_ok=True)
    files = []
    if files_status:
        for name, status in files_status.items():
            files.append({"file": name, "status": status, "passed": 0, "failed": 0, "errored": 0, "skipped": 0})
    (d / "summary.json").write_text(
        json.dumps(
            {"started_at": ts, "finished_at": ts, "totals": totals, "files": files},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )


# ---- _read_latest_summary ----

def test_read_latest_skips_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_changelog.ACCEPTANCE_DIR", tmp_path)
    _make_acceptance(tmp_path, "20250102_000000", totals={"files": 0, "passed": 0, "failed": 0, "errored": 0, "skipped": 0, "ran_ratio": "0/0"})
    _make_acceptance(tmp_path, "20250101_000000", totals={"files": 5, "passed": 5, "failed": 0, "errored": 0, "skipped": 0, "ran_ratio": "5/5"})
    s = _read_latest_summary()
    assert s["totals"]["ran_ratio"] == "5/5"


def test_read_latest_no_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_changelog.ACCEPTANCE_DIR", tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    assert _read_latest_summary() is None


# ---- build_line ----

def test_build_line_format():
    s = {
        "started_at": "2025-12-01T10:30:00",
        "totals": {"passed": 10, "failed": 5, "errored": 2, "skipped": 1, "ran_ratio": "10/18"},
    }
    line = build_line(s)
    assert "2025-12-01 10:30" in line
    assert "ran_ratio 10/18" in line
    assert "passed 10" in line
    assert "failed 5" in line
    assert "errored 2" in line
    assert "skipped 1" in line


def test_build_line_handles_bad_date():
    s = {
        "started_at": "bogus",
        "totals": {"passed": 1, "failed": 0, "errored": 0, "skipped": 0, "ran_ratio": "1/1"},
    }
    line = build_line(s)
    # 兜底用原始字符串
    assert "bogus" in line


# ---- append_changelog_line ----

def test_append_creates_file_when_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("tools.archive_changelog.ACCEPTANCE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_changelog.CHANGELOG", tmp_path / "CHANGELOG.md")
    _make_acceptance(tmp_path, "20250101_000000",
                     totals={"passed": 5, "failed": 2, "errored": 1, "skipped": 0, "ran_ratio": "5/8", "files": 8})

    rc = append_changelog_line()
    assert rc == 0
    out = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "# tests-archive/" in out
    assert "ran_ratio 5/8" in out
    assert "passed 5" in out


def test_append_dedupes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("tools.archive_changelog.ACCEPTANCE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_changelog.CHANGELOG", tmp_path / "CHANGELOG.md")
    _make_acceptance(tmp_path, "20250101_000000",
                     totals={"passed": 5, "failed": 2, "errored": 1, "skipped": 0, "ran_ratio": "5/8", "files": 8})

    append_changelog_line()
    # 第二次应当 skip
    rc = append_changelog_line()
    out = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    # 应只有一行（不重复）
    assert out.count("ran_ratio 5/8") == 1


def test_append_returns_1_when_no_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("tools.archive_changelog.ACCEPTANCE_DIR", tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    monkeypatch.setattr("tools.archive_changelog.CHANGELOG", tmp_path / "CHANGELOG.md")
    rc = append_changelog_line()
    err = capsys.readouterr().err
    assert rc == 1
    assert "no acceptance summary" in err


def test_append_prune_old_lines(tmp_path, monkeypatch):
    """prune_days 应该删除超过 N 天的行。"""
    monkeypatch.setattr("tools.archive_changelog.ACCEPTANCE_DIR", tmp_path)
    target = tmp_path / "CHANGELOG.md"
    monkeypatch.setattr("tools.archive_changelog.CHANGELOG", target)

    # 预先写一份 CHANGELOG，包含一行 2020 的旧记录
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# tests-archive/ Changelog\n\n## 历次跑\n"
        "- **2020-01-01 00:00** `ran_ratio 1/1`  passed 1, failed 0, errored 0, skipped 0\n",
        encoding="utf-8",
    )

    # 然后写一份新 summary 并 append
    _make_acceptance(tmp_path, "20250101_000000",
                     totals={"passed": 5, "failed": 0, "errored": 0, "skipped": 0, "ran_ratio": "5/5", "files": 5})

    # today 真实时间是 2026-07-26 左右。
    # 2020-01-01 远超 30 天前 → 必 prune
    # 2025-01-01 距今约 1.5 年 → 在 2000 天之内，保留
    rc = append_changelog_line(prune_days=2000)
    assert rc == 0
    out = target.read_text(encoding="utf-8")
    # 旧的 2020-01-01 应被 prune，新 2025-01-01 应保留
    assert "2025-01-01" in out
    assert "2020-01-01" not in out


# ---- main CLI ----

def test_main_with_prune(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_changelog.ACCEPTANCE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_changelog.CHANGELOG", tmp_path / "CHANGELOG.md")
    _make_acceptance(tmp_path, "20250101_000000",
                     totals={"passed": 5, "failed": 0, "errored": 0, "skipped": 0, "ran_ratio": "5/5", "files": 5})
    from tools.archive_changelog import main
    rc = main(["--prune-days", "30"])
    assert rc == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))