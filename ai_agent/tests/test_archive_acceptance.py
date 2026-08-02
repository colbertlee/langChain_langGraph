"""tools/archive_acceptance.py 单测（Day 17）。"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.archive_acceptance import (
    parse_pytest_output,
    render_report,
    cmd_run,
    FileRun,
    AcceptanceReport,
    ARCHIVE_DIR,
    ACCEPTANCE_DIR,
    REPORT_DOC,
)


# ---- parse_pytest_output ----

def test_parse_pass_lines():
    out = """
    tests-archive/tests/test_a.py::test_x PASSED     [ 20%]
    tests-archive/tests/test_a.py::test_y PASSED     [ 40%]
    tests-archive/tests/test_a.py::test_z SKIPPED    [ 60%]
    """
    runs = parse_pytest_output(out)
    assert len(runs) == 1
    r = runs[0]
    assert r.file == "test_a.py"
    assert r.passed == 2
    assert r.skipped == 1
    assert r.failed == 0
    assert r.status == "pass"


def test_parse_fail_lines():
    out = """
    tests-archive/tests/test_b.py::test_x FAILED     [ 20%]
    tests-archive/tests/test_b.py::test_y PASSED     [ 40%]
    """
    runs = parse_pytest_output(out)
    assert runs[0].failed == 1
    assert runs[0].passed == 1
    assert runs[0].status == "fail"


def test_parse_collect_error():
    out = """
    ERROR tests-archive/tests/test_c.py collecting
    """
    runs = parse_pytest_output(out)
    assert runs[0].errored == 1
    assert runs[0].status == "error"


def test_parse_empty_returns_empty():
    assert parse_pytest_output("") == []


def test_parse_mixed_status():
    """同文件里 pass + fail + error → status 应为 fail（failed 优先于 errored 状态检测？）"""
    out = """
    tests-archive/tests/test_m.py::test_x PASSED
    tests-archive/tests/test_m.py::test_y FAILED
    """
    runs = parse_pytest_output(out)
    r = runs[0]
    # failed > 0 → status=fail
    assert r.status == "fail"


def test_parse_error_only_status():
    out = """
    tests-archive/tests/test_e.py::test_x ERROR
    """
    runs = parse_pytest_output(out)
    assert runs[0].status == "error"


# ---- render_report ----

def test_render_report_includes_summary():
    rep = AcceptanceReport(
        started_at="2025-01-01T00:00:00",
        finished_at="2025-01-01T00:01:00",
        totals={"files": 3, "passed": 1, "failed": 2, "errored": 0, "skipped": 0, "ran_ratio": "1/3"},
        files=[
            FileRun(file="a.py", passed=1, status="pass"),
            FileRun(file="b.py", failed=2, status="fail"),
        ],
    )
    md = render_report(rep)
    assert "# tests-archive/" in md
    assert "1/3" in md
    assert "| 文件" in md
    assert "a.py" in md


# ---- cmd_run scan-only ----

def test_cmd_run_scan_only_writes_report(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.archive_acceptance.ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_acceptance.REPORT_DOC", tmp_path / "ACCEPTANCE.md")
    (tmp_path / "test_a.py").write_text("# empty", encoding="utf-8")
    (tmp_path / "test_b.py").write_text("# empty", encoding="utf-8")

    import argparse
    ns = argparse.Namespace(scan_only=True, strict=False, json_output=False, timeout=60)
    rc = cmd_run(ns)
    assert rc == 0
    out = (tmp_path / "ACCEPTANCE.md").read_text(encoding="utf-8")
    assert "test_a.py" in out


# ---- cmd_run 真跑（mock subprocess） ----

def test_cmd_run_mock_subprocess(tmp_path, monkeypatch):
    """Mock subprocess.run 返回固定 PASSED 行，看 cmd_run 是否正确统计。"""
    monkeypatch.setattr("tools.archive_acceptance.ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_acceptance.REPORT_DOC", tmp_path / "ACCEPTANCE.md")
    monkeypatch.setattr("tools.archive_acceptance.ACCEPTANCE_DIR", tmp_path / "acceptance")
    (tmp_path / "test_a.py").write_text("# empty", encoding="utf-8")

    fake_out = "tests-archive/tests/test_a.py::test_x PASSED [100%]\n=== 1 passed ==="

    with patch("tools.archive_acceptance.run_pytest_on_archive", return_value=fake_out):
        import argparse
        ns = argparse.Namespace(scan_only=False, strict=False, json_output=False, timeout=60)
        rc = cmd_run(ns)
    assert rc == 0
    out = (tmp_path / "ACCEPTANCE.md").read_text(encoding="utf-8")
    assert "test_a.py" in out


def test_cmd_run_no_tests_in_output(tmp_path, monkeypatch):
    """subprocess 输出空 → fallback 给 no_tests 状态"""
    monkeypatch.setattr("tools.archive_acceptance.ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_acceptance.REPORT_DOC", tmp_path / "ACCEPTANCE.md")
    monkeypatch.setattr("tools.archive_acceptance.ACCEPTANCE_DIR", tmp_path / "acceptance")
    (tmp_path / "test_a.py").write_text("# empty", encoding="utf-8")

    with patch("tools.archive_acceptance.run_pytest_on_archive", return_value=""):
        import argparse
        ns = argparse.Namespace(scan_only=False, strict=False, json_output=False, timeout=60)
        rc = cmd_run(ns)
    assert rc == 0
    out = (tmp_path / "ACCEPTANCE.md").read_text(encoding="utf-8")
    assert "no_tests" in out


# ---- strict mode ----

def test_cmd_run_strict_returns_1_on_fail(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("tools.archive_acceptance.ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr("tools.archive_acceptance.REPORT_DOC", tmp_path / "ACCEPTANCE.md")
    monkeypatch.setattr("tools.archive_acceptance.ACCEPTANCE_DIR", tmp_path / "acceptance")
    (tmp_path / "test_a.py").write_text("# empty", encoding="utf-8")

    fake_out = "tests-archive/tests/test_a.py::test_x FAILED"

    with patch("tools.archive_acceptance.run_pytest_on_archive", return_value=fake_out):
        import argparse
        ns = argparse.Namespace(scan_only=False, strict=True, json_output=False, timeout=60)
        rc = cmd_run(ns)
    assert rc == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))