"""Day 22：check_pr_metadata 单测。"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.check_pr_metadata import (
    REQUIRED_PHRASES,
    check_body,
    fetch_pr_body,
    main,
)


SAMPLE_BODY_OK = """
## 🚨 Maintainer Review Required

> 本 PR 由 release-build 自动生成

## Summary

自动归档 errored 测试文件

## 涉及文件

| file | size |
|------|------|
| a.py | 100 |

## Checklist

- [x] 应清理 ✅ 必填
- [x] 旧 history 可用 ✅ 必填
- [x] 无误杀 ✅ 必填
- [x] 恢复路径 ✅ 必填
"""


SAMPLE_BODY_MISSING_CHECKLIST = """
## 🚨 Maintainer Review Required

## Summary

归档 errored

## 涉及文件

| file | size |
|------|------|
| a.py | 100 |

## 风险评估

无
"""


# ---- check_body ----

def test_check_body_all_phrases_present():
    passed, missing = check_body(SAMPLE_BODY_OK)
    assert passed is True
    assert missing == []


def test_check_body_missing_checklist():
    passed, missing = check_body(SAMPLE_BODY_MISSING_CHECKLIST)
    assert passed is False
    assert "## Checklist" in missing


def test_check_body_missing_multiple():
    body = "## Summary\n"
    passed, missing = check_body(body)
    assert passed is False
    # 应缺 3 个（maintainer/summary/涉及文件/Checklist）
    assert "🚨 Maintainer Review Required" in missing
    assert "## 涉及文件" in missing
    assert "## Checklist" in missing


def test_check_body_empty():
    passed, missing = check_body("")
    assert passed is False
    assert len(missing) == len(REQUIRED_PHRASES)


def test_required_phrases_count():
    """必须 ≥ 4 个核心 section"""
    assert len(REQUIRED_PHRASES) >= 4


# ---- fetch_pr_body mocked ----

def test_fetch_pr_body_parses_json():
    import json as _json
    fake_json = _json.dumps({"body": SAMPLE_BODY_OK})
    fake_proc = type("P", (), {"returncode": 0, "stdout": fake_json, "stderr": ""})()
    with patch("subprocess.run", return_value=fake_proc):
        body = fetch_pr_body("foo/bar", 42)
    assert "Maintainer Review" in body


def test_fetch_pr_body_handles_gh_failure():
    fake_proc = type("P", (), {"returncode": 1, "stdout": "", "stderr": "auth required"})()
    with patch("subprocess.run", return_value=fake_proc):
        with pytest.raises(RuntimeError):
            fetch_pr_body("foo/bar", 42)


# ---- CLI main ----

def test_main_returns_0_when_passed():
    """main: body 含全短语 → exit 0"""
    import json as _json
    fake_json = _json.dumps({"body": SAMPLE_BODY_OK})
    fake_proc = type("P", (), {"returncode": 0, "stdout": fake_json, "stderr": ""})()
    with patch("subprocess.run", return_value=fake_proc):
        rc = main(["--repo", "foo/bar", "--pr", "42"])
    assert rc == 0


def test_main_returns_1_when_missing():
    import json as _json
    fake_json = _json.dumps({"body": "## Summary"})
    fake_proc = type("P", (), {"returncode": 0, "stdout": fake_json, "stderr": ""})()
    with patch("subprocess.run", return_value=fake_proc):
        rc = main(["--repo", "foo/bar", "--pr", "42"])
    assert rc == 1


def test_main_returns_2_when_gh_fails(capsys):
    fake_proc = type("P", (), {"returncode": 1, "stdout": "", "stderr": "gh error"})()
    with patch("subprocess.run", return_value=fake_proc):
        rc = main(["--repo", "foo/bar", "--pr", "42"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "gh pr view failed" in err


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))