"""tools/verify_archive.py 单测（Day 16）。

不实际起子进程（浪费），改为 mock subprocess.run 让它返回受控 payload。
"""
import subprocess  # noqa: F401  全局 import，便于测试 patch
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

import tools.verify_archive as va
from tools.verify_archive import (
    _classify,
    scan,
    render_human,
    cmd_scan,
    ROOT as VA_ROOT,
    ARCHIVE_DIR,
    STATUS_DOC,
)


# ---- 关键路径：PASS / IMPORT_FAIL / ERROR_RUNTIME / SYNTAX_FAIL ----

def test_syntax_fail_returns_correct_status(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("x = 1\ny = (\n", encoding="utf-8")  # 真错：半边括号

    row = _classify(bad)
    assert row["status"] == "syntax_fail"
    assert "line" in row["detail"]


def test_pass_via_subprocess(tmp_path):
    good = tmp_path / "good.py"
    good.write_text("def test_a(): pass\ndef test_b(): pass\n", encoding="utf-8")

    fake_cp = MagicMock()
    fake_cp.returncode = 0
    fake_cp.stdout = b'{"test_count": 5, "names": ["a","b"]}'
    fake_cp.stderr = b""

    with patch("subprocess.run", return_value=fake_cp):
        row = _classify(good)

    assert row["status"] == "pass"
    assert row["test_count"] == 5


def test_import_fail_when_subprocess_nonzero(tmp_path):
    p = tmp_path / "x.py"
    p.write_text("def test_y(): pass\n", encoding="utf-8")

    fake_cp = MagicMock()
    fake_cp.returncode = 1
    fake_cp.stdout = b""
    fake_cp.stderr = b"ModuleNotFoundError: No module named 'foo'"

    with patch("subprocess.run", return_value=fake_cp):
        row = _classify(p)

    assert row["status"] == "import_fail"
    assert "foo" in row["detail"]


def test_timeout_returns_error_runtime(tmp_path):
    import subprocess as sp
    p = tmp_path / "slow.py"
    p.write_text("def test_s(): pass\n", encoding="utf-8")

    with patch(
        "subprocess.run",
        side_effect=sp.TimeoutExpired(cmd=["py"], timeout=10),
    ):
        row = _classify(p)

    assert row["status"] == "error_runtime"
    assert "10s" in row["detail"]


def test_probe_writes_tmp_file_is_cleaned(tmp_path):
    p = tmp_path / "clean.py"
    p.write_text("def test_z(): pass\n", encoding="utf-8")

    fake_cp = MagicMock()
    fake_cp.returncode = 0
    fake_cp.stdout = b'{"test_count": 1, "names": []}'
    fake_cp.stderr = b""

    with patch("subprocess.run", return_value=fake_cp):
        _classify(p)
    probe_path = VA_ROOT / "_probe.py"
    assert not probe_path.exists(), f"探测文件未清理: {probe_path}"


# ---- scan + render ----

def test_scan_returns_list(tmp_path, monkeypatch):
    # file name MUST start with ``test_`` AND end with ``.py`` to match the glob
    (tmp_path / "test_a.py").write_text("def test_a(): pass\n", encoding="utf-8")
    (tmp_path / "test_b.py").write_text("def test_b(): pass\n", encoding="utf-8")

    monkeypatch.setattr(va, "ARCHIVE_DIR", tmp_path)

    fake_cp = MagicMock()
    fake_cp.returncode = 0
    fake_cp.stdout = b'{"test_count": 1, "names": ["a"]}'
    fake_cp.stderr = b""

    with patch("subprocess.run", return_value=fake_cp):
        rows = scan()

    assert len(rows) == 2
    names = {r["file"] for r in rows}
    assert "test_a.py" in names


def test_render_human_includes_table():
    rows = [
        {"file": "good.py", "status": "pass", "test_count": 3, "tests": [], "detail": ""},
        {"file": "bad.py", "status": "syntax_fail", "detail": "line 1", "test_count": "-"},
    ]
    md = render_human(rows)
    assert "# tests-archive/" in md
    assert "pass" in md
    assert "syntax_fail" in md
    assert "| 文件" in md


def test_status_doc_written(tmp_path, monkeypatch):
    fake_rows = [
        {"file": "x.py", "status": "pass", "test_count": 2, "tests": ["a","b"], "detail": ""}
    ]
    import argparse
    ns = argparse.Namespace(json=False, strict=False)
    monkeypatch.setattr(va, "scan", lambda: fake_rows)
    target = tmp_path / "STATUS.md"
    monkeypatch.setattr(va, "STATUS_DOC", target)

    rc = cmd_scan(ns)
    out = target.read_text(encoding="utf-8")
    assert rc == 0
    assert "x.py" in out


def test_cmd_scan_strict_returns_1_on_import_fail(capsys, monkeypatch, tmp_path):
    import argparse
    ns = argparse.Namespace(json=False, strict=True)
    fake_rows = [
        {"file": "x.py", "status": "import_fail", "detail": "X"},
        {"file": "y.py", "status": "syntax_fail", "detail": "Y"},
    ]
    monkeypatch.setattr(va, "scan", lambda: fake_rows)
    monkeypatch.setattr(va, "STATUS_DOC", tmp_path / "STATUS.md")
    rc = cmd_scan(ns)
    err = capsys.readouterr().err
    assert rc == 1
    assert "FAIL" in err


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))
