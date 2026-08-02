"""Day 23：check_pr_title 单测。"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.check_pr_title import check_title, fetch_pr_title, main, TITLE_PATTERN


# ---- check_title ----

def test_check_title_valid():
    passed, errors = check_title("auto-archive: clean errored files")
    assert passed is True
    assert errors == []


def test_check_title_valid_with_tag():
    passed, errors = check_title("auto-archive(v1.2.3): clean errored files")
    assert passed is True
    assert errors == []


def test_check_title_valid_verbs():
    """所有允许 verbs 都应通过"""
    for verb in [
        "clean", "restore", "backfill", "migrate", "prune", "cleanup",
        # Day 24：新增 verbs
        "revert", "archive", "rebase", "upgrade", "downgrade", "consolidate",
    ]:
        title = f"auto-archive: {verb} 3 test files"
        passed, _ = check_title(title)
        assert passed is True, f"verb '{verb}' should pass"


def test_check_title_uppercase_prefix_rejected():
    passed, errors = check_title("Auto-archive: clean files")
    assert passed is False
    # regex 大小写敏感，大写前缀不匹配
    assert any("must match" in e for e in errors)


def test_check_title_missing_prefix():
    passed, errors = check_title("clean files")
    assert passed is False
    assert any("must match" in e for e in errors)


def test_check_title_wrong_verb():
    passed, errors = check_title("auto-archive: delete everything")
    assert passed is False


def test_check_title_day24_new_verbs():
    """Day 24：revert/archive/rebase 等新 verbs"""
    for verb, desc in [
        ("revert", "auto-archive: revert recent changes"),
        ("archive", "auto-archive: archive legacy tests"),
        ("rebase", "auto-archive: rebase onto v2.0"),
        ("upgrade", "auto-archive: upgrade pytest config"),
        ("downgrade", "auto-archive: downgrade old tests"),
        ("consolidate", "auto-archive: consolidate 3 files"),
    ]:
        passed, _ = check_title(desc)
        assert passed is True, f"{verb} should pass"


def test_check_title_description_too_short():
    """description 必须 ≥ 5 字符"""
    passed, errors = check_title("auto-archive: clean x")  # "x" 太短
    assert passed is False


def test_check_title_description_too_long():
    """description 必须 ≤ 100 字符"""
    long_desc = "a" * 101
    passed, errors = check_title(f"auto-archive: clean {long_desc}")
    assert passed is False


def test_check_title_empty():
    passed, errors = check_title("")
    assert passed is False
    assert "empty" in errors[0]


# ---- TITLE_PATTERN 编译 ----

def test_title_pattern_simple():
    m = TITLE_PATTERN.match("auto-archive: clean x")
    assert m is None  # "x" < 5 字符


def test_title_pattern_with_tag():
    m = TITLE_PATTERN.match("auto-archive(v1.2.3): clean some files")
    assert m is not None


# ---- fetch_pr_title ----

def test_fetch_pr_title_parses_json():
    import json as _json
    fake_proc = type("P", (), {"returncode": 0, "stdout": _json.dumps({"title": "auto-archive: clean x"}), "stderr": ""})()
    with patch("subprocess.run", return_value=fake_proc):
        title = fetch_pr_title("foo/bar", 42)
    assert title == "auto-archive: clean x"


def test_fetch_pr_title_handles_gh_failure():
    fake_proc = type("P", (), {"returncode": 1, "stdout": "", "stderr": "auth error"})()
    with patch("subprocess.run", return_value=fake_proc):
        with pytest.raises(RuntimeError):
            fetch_pr_title("foo/bar", 42)


# ---- CLI main ----

def test_main_returns_0_when_valid():
    import json as _json
    fake_proc = type("P", (), {"returncode": 0, "stdout": _json.dumps({"title": "auto-archive: clean files"}), "stderr": ""})()
    with patch("subprocess.run", return_value=fake_proc):
        rc = main(["--repo", "foo/bar", "--pr", "42"])
    assert rc == 0


def test_main_returns_1_when_invalid():
    import json as _json
    fake_proc = type("P", (), {"returncode": 0, "stdout": _json.dumps({"title": "wrong format"}), "stderr": ""})()
    with patch("subprocess.run", return_value=fake_proc):
        rc = main(["--repo", "foo/bar", "--pr", "42"])
    assert rc == 1


def test_main_returns_2_when_gh_fails(capsys):
    fake_proc = type("P", (), {"returncode": 1, "stdout": "", "stderr": "auth error"})()
    with patch("subprocess.run", return_value=fake_proc):
        rc = main(["--repo", "foo/bar", "--pr", "42"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "gh pr view failed" in err


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))