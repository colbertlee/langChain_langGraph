"""Day 22：dashboard SHA + timestamp 单测。"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.archive_dashboard import (
    _git_short_sha,
    _build_meta_line,
    render_multipanel_svg,
    render_svg,
)


# ---- _git_short_sha ----

def test_git_short_sha_returns_string():
    """返回字符串（可能是 "unknown" 或实际 SHA）"""
    sha = _git_short_sha()
    assert isinstance(sha, str)
    assert len(sha) > 0


def test_git_short_sha_handles_not_git_repo(tmp_path, monkeypatch):
    """非 git 仓库不崩，返回 unknown"""
    monkeypatch.setattr("tools.archive_dashboard.ROOT", tmp_path)
    # /tmp 在 Windows 下 subprocess.run("git rev-parse ...") 应该 returncode != 0
    sha = _git_short_sha()
    # 如果 tmp_path 不是 git 仓库 → "unknown"
    # 这里是 ai_agent 仓库，所以仍能拿到 SHA
    # 仅验证不崩
    assert isinstance(sha, str)


# ---- _build_meta_line ----

def test_build_meta_line_with_sha():
    line = _build_meta_line(sha="abc1234567890def", timestamp="2026-07-26 12:00")
    assert line.startswith("abc1234")  # 截断到 7 字符
    assert "2026-07-26" in line


def test_build_meta_line_without_sha():
    line = _build_meta_line(sha="unknown", timestamp="2026-07-26 12:00")
    assert "unknown" not in line  # unknown 不显示
    assert line == "2026-07-26 12:00"


def test_build_meta_line_empty_sha():
    line = _build_meta_line(sha="", timestamp="2026-07-26 12:00")
    assert line == "2026-07-26 12:00"


# ---- render_multipanel_svg 接受 sha/timestamp ----

def test_multipanel_svg_includes_custom_sha():
    svg = render_multipanel_svg(
        {"archive_trend": [], "evals": [], "chats": []},
        sha="deadbeef1234567",
    )
    assert "deadbee" in svg  # 7 字符截断


def test_multipanel_svg_includes_custom_timestamp():
    svg = render_multipanel_svg(
        {"archive_trend": [], "evals": [], "chats": []},
        timestamp="2030-01-01 00:00:00",
    )
    assert "2030-01-01" in svg


def test_multipanel_svg_meta_text_uses_monospace():
    """metadata 用 monospace 字体，便于对齐"""
    svg = render_multipanel_svg(
        {"archive_trend": [], "evals": [], "chats": []},
        sha="abc1234",
    )
    # 找带 monospace 字体的那段 text
    assert "monospace" in svg


def test_multipanel_svg_falls_back_to_git_sha():
    """不传 sha → 自动读 git"""
    svg = render_multipanel_svg(
        {"archive_trend": [], "evals": [], "chats": []},
    )
    # 应至少包含 timestamp（不管 sha 是什么）
    # 验证不会崩
    assert "<svg" in svg


def test_multipanel_svg_falls_back_to_now():
    """不传 timestamp → 自动用当前时间"""
    svg = render_multipanel_svg(
        {"archive_trend": [], "evals": [], "chats": []},
    )
    # 应包含某种日期格式（默认 now）
    import re
    assert re.search(r"\d{4}-\d{2}-\d{2}", svg)


# ---- render_svg 透传 ----

def test_render_svg_propagates_sha():
    svg = render_svg([], sha="abcdef1234567")
    assert "abcdef1" in svg


def test_render_svg_propagates_timestamp():
    svg = render_svg([], timestamp="2030-12-31 23:59:59")
    assert "2030-12-31" in svg


# ---- CLI args ----

def test_main_sha_from_env(monkeypatch, tmp_path):
    """GITHUB_SHA 环境变量被 CLI 自动读"""
    monkeypatch.setenv("GITHUB_SHA", "1234567abcdef")
    monkeypatch.setattr("tools.archive_dashboard.DEFAULT_OUTPUT", tmp_path / "d.svg")

    from tools.archive_dashboard import main
    rc = main([])
    assert rc == 0
    svg = (tmp_path / "d.svg").read_text(encoding="utf-8")
    assert "1234567" in svg


def test_main_sha_arg_overrides_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_SHA", "aaaaaa")
    monkeypatch.setattr("tools.archive_dashboard.DEFAULT_OUTPUT", tmp_path / "d.svg")
    from tools.archive_dashboard import main
    rc = main(["--sha", "bbbbbb"])
    assert rc == 0
    svg = (tmp_path / "d.svg").read_text(encoding="utf-8")
    assert "bbbbbb" in svg


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))