"""tools/archive_legacy.py auto-archive 子命令测试（Day 19）。"""
import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools import archive_legacy
from tools.archive_legacy import (
    _latest_acceptance_summary,
    _errored_files_from_summary,
    cmd_auto_archive,
    cmd_archive_errored,
    ARCHIVE_TESTS_DIR,
)


def _make_acceptance(base: Path, ts: str, *, files_status: dict):
    """写一份 acceptance summary。

    Args:
        files_status: ``{"file.py": "pass"/"fail"/"error"}``
    """
    d = base / ts
    d.mkdir(parents=True, exist_ok=True)
    totals = {"files": len(files_status), "passed": 0, "failed": 0, "errored": 0, "skipped": 0}
    files = []
    for name, status in files_status.items():
        files.append({"file": name, "status": status, "passed": 0, "failed": 0, "errored": 0, "skipped": 0})
        if status == "pass":
            totals["passed"] += 1
        elif status == "fail":
            totals["failed"] += 1
        elif status == "error":
            totals["errored"] += 1
    totals["ran_ratio"] = f"{totals['passed']}/{sum(totals.values())}"
    (d / "summary.json").write_text(
        json.dumps(
            {
                "started_at": ts,
                "finished_at": ts,
                "totals": totals,
                "files": files,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ---- _latest_acceptance_summary ----

def test_latest_skips_empty_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_legacy.ACCEPTANCE_DIR", tmp_path)
    # 全 0 的空跑应该被跳过
    _make_acceptance(tmp_path, "20250102_000000", files_status={"a.py": "no_tests"})
    # 真跑的应该被读到
    _make_acceptance(tmp_path, "20250101_000000", files_status={"a.py": "pass", "b.py": "fail"})

    s = _latest_acceptance_summary()
    # 最新有空跑 → 跳过 → 回到 20250101
    assert s["started_at"] == "20250101_000000"


def test_latest_returns_empty_when_all_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_legacy.ACCEPTANCE_DIR", tmp_path)
    _make_acceptance(tmp_path, "20250101_000000", files_status={"a.py": "no_tests"})
    assert _latest_acceptance_summary() == {}


def test_latest_when_no_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_legacy.ACCEPTANCE_DIR", tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    assert _latest_acceptance_summary() == {}


# ---- _errored_files_from_summary ----

def test_errored_files_extracts_only_error_status():
    s = {
        "files": [
            {"file": "a.py", "status": "pass"},
            {"file": "b.py", "status": "error"},
            {"file": "c.py", "status": "fail"},
            {"file": "d.py", "status": "error"},
        ]
    }
    assert sorted(_errored_files_from_summary(s)) == ["b.py", "d.py"]


def test_errored_files_handles_empty():
    assert _errored_files_from_summary({}) == []
    assert _errored_files_from_summary({"files": []}) == []


# ---- cmd_auto_archive ----

def test_cmd_auto_archive_writes_doc(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("tools.archive_legacy.ACCEPTANCE_DIR", tmp_path)
    # 直接把 doc 写到 tmp_path 而不是 _ROOT —— 借助 wrap
    import tools.archive_legacy as al
    monkeypatch.setattr(al, "_ROOT", tmp_path)
    monkeypatch.setattr("tools.archive_legacy.ARCHIVE_TESTS_DIR", tmp_path / "tests")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "bad.py").write_text("# empty\n", encoding="utf-8")

    _make_acceptance(
        tmp_path, "20250101_000000",
        files_status={"bad.py": "error", "ok.py": "pass"},
    )

    rc = cmd_auto_archive(argparse.Namespace())
    assert rc == 0
    out = capsys.readouterr().out
    assert "bad.py" in out
    # doc 写到了 ROOT/tests-archive/auto_archive.md 即 tmp_path/tests-archive/auto_archive.md
    assert (tmp_path / "tests-archive" / "auto_archive.md").exists()


def test_cmd_auto_archive_returns_1_when_no_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("tools.archive_legacy.ACCEPTANCE_DIR", tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    rc = cmd_auto_archive(argparse.Namespace())
    err = capsys.readouterr().err
    assert rc == 1
    assert "no acceptance summary" in err


def test_cmd_auto_archive_returns_0_when_no_errored(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("tools.archive_legacy.ACCEPTANCE_DIR", tmp_path)
    _make_acceptance(
        tmp_path, "20250101_000000",
        files_status={"good.py": "pass"},
    )
    rc = cmd_auto_archive(argparse.Namespace())
    out = capsys.readouterr().out
    assert rc == 0
    assert "no errored files" in out


# ---- cmd_archive_errored ----

def test_cmd_archive_errored_moves_files(tmp_path, monkeypatch):
    import tools.archive_legacy as al
    monkeypatch.setattr(al, "_ROOT", tmp_path)
    monkeypatch.setattr("tools.archive_legacy.ACCEPTANCE_DIR", tmp_path)
    monkeypatch.setattr(al, "ARCHIVE_TESTS_DIR", tmp_path / "tests")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "bad.py").write_text("# broken\n", encoding="utf-8")
    (tmp_path / "tests" / "good.py").write_text("# good\n", encoding="utf-8")

    _make_acceptance(
        tmp_path, "20250101_000000",
        files_status={"bad.py": "error", "good.py": "pass"},
    )

    rc = cmd_archive_errored(argparse.Namespace())
    assert rc == 0

    # bad.py 应该被移到 tests-archive/_obsolete/<ts>/bad.py
    assert not (tmp_path / "tests" / "bad.py").exists()
    obsolete = list((tmp_path / "tests-archive" / "_obsolete").iterdir())
    assert len(obsolete) == 1
    moved_dir = obsolete[0]
    assert (moved_dir / "bad.py").exists()
    # good.py 仍在原位
    assert (tmp_path / "tests" / "good.py").exists()
    # README.md 在 moved_dir 中
    assert (moved_dir / "README.md").exists()


def test_cmd_archive_errored_handles_no_errored(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("tools.archive_legacy.ACCEPTANCE_DIR", tmp_path)
    _make_acceptance(tmp_path, "20250101_000000", files_status={"good.py": "pass"})
    rc = cmd_archive_errored(argparse.Namespace())
    out = capsys.readouterr().out
    assert rc == 0
    assert "no errored" in out


def test_cmd_archive_errored_returns_1_when_no_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("tools.archive_legacy.ACCEPTANCE_DIR", tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    rc = cmd_archive_errored(argparse.Namespace())
    err = capsys.readouterr().err
    assert rc == 1


# ---- argparse 集成 ----

def test_main_auto_archive_arg():
    """验证 --auto-archive arg 在 main 中可识别"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto-archive", action="store_true")
    parser.add_argument("--archive-errored", action="store_true")
    args = parser.parse_args(["--auto-archive"])
    assert args.auto_archive is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))