"""Day 25：dashboard_hub 单测。"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.dashboard_hub import (
    _file_size,
    _file_mtime,
    discover_dashboards,
    render_hub,
    main,
)


SAMPLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">
  <rect width="100" height="50" fill="#34c759"/>
</svg>"""


# ---- _file_size ----

def test_file_size_bytes(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"x" * 100)
    assert _file_size(p) == "100 B"


def test_file_size_kb(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"x" * 2048)
    assert "KB" in _file_size(p)


def test_file_size_mb(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"x" * (1024 * 1024))
    assert "MB" in _file_size(p)


def test_file_size_missing(tmp_path):
    p = tmp_path / "missing.txt"
    assert _file_size(p) == "(missing)"


# ---- _file_mtime ----

def test_file_mtime_existing(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("hi")
    out = _file_mtime(p)
    # 形如 2026-07-26 12:34
    assert len(out) == 16
    assert "-" in out


def test_file_mtime_missing(tmp_path):
    p = tmp_path / "missing.txt"
    assert _file_mtime(p) == "—"


# ---- discover_dashboards ----

def test_discover_default_paths(tmp_path):
    dashboards = discover_dashboards(tmp_path)
    # 默认 5 个
    assert len(dashboards) == 5
    titles = [t for t, _ in dashboards]
    assert "Dashboard" in titles
    assert "Doctor" in titles
    assert "Evals" in titles


def test_discover_custom_paths(tmp_path):
    dashboards = discover_dashboards(tmp_path, paths=["custom.svg"])
    assert len(dashboards) == 1
    assert dashboards[0][0] == "Custom"


def test_discover_title_formatting():
    """下划线/横线 → 空格 + Title Case"""
    dashboards = discover_dashboards(Path("."), paths=["my-dash_v2.svg"])
    assert dashboards[0][0] == "My Dash V2"


# ---- render_hub ----

def test_render_hub_with_existing_dashboards(tmp_path):
    """存在的 SVG → iframe / inline"""
    # 准备一个 SVG
    (tmp_path / "a.svg").write_text(SAMPLE_SVG, encoding="utf-8")
    (tmp_path / "b.svg").write_text(SAMPLE_SVG, encoding="utf-8")

    dashboards = [
        ("A", tmp_path / "a.svg"),
        ("B", tmp_path / "b.svg"),
    ]
    html = render_hub(dashboards)

    assert "<!DOCTYPE html>" in html
    assert "<html" in html
    assert "AI Agent Observability" in html  # 默认标题
    assert ">A<" in html
    assert ">B<" in html
    # iframe 引用
    assert "iframe" in html
    assert "src=\"a.svg\"" in html


def test_render_hub_with_embed_mode(tmp_path):
    """--embed 模式：SVG 内容 inline"""
    (tmp_path / "a.svg").write_text(SAMPLE_SVG, encoding="utf-8")

    html = render_hub(
        [("A", tmp_path / "a.svg")],
        embed=True,
    )

    # SVG 内容应嵌入（不是 iframe）
    assert "iframe" not in html
    assert "<svg" in html
    assert 'fill="#34c759"' in html


def test_render_hub_with_missing_dashboards(tmp_path):
    """缺失的 SVG → 显示 'Dashboard not generated yet'"""
    dashboards = [
        ("Missing", tmp_path / "no_such.svg"),
    ]
    html = render_hub(dashboards)

    assert "Dashboard not generated yet" in html
    assert "iframe" not in html


def test_render_hub_custom_title(tmp_path):
    dashboards = [("A", tmp_path / "a.svg")]
    html = render_hub(dashboards, title="My Custom Hub")
    assert "My Custom Hub" in html


def test_render_hub_active_first_tab(tmp_path):
    """第一个 tab 默认 active"""
    (tmp_path / "a.svg").write_text(SAMPLE_SVG, encoding="utf-8")
    (tmp_path / "b.svg").write_text(SAMPLE_SVG, encoding="utf-8")
    html = render_hub([("A", tmp_path / "a.svg"), ("B", tmp_path / "b.svg")])
    # 'tab-0' 应有 active，'tab-1' 不应
    assert 'class="tab active"' in html
    assert 'id="tab-0"' in html
    assert 'id="tab-1"' in html


def test_render_hub_includes_javascript_tabs():
    """包含 tabs 切换的 JS"""
    html = render_hub([])
    assert "querySelectorAll" in html
    assert "addEventListener" in html


def test_render_hub_shows_file_size_and_mtime(tmp_path):
    (tmp_path / "a.svg").write_text(SAMPLE_SVG, encoding="utf-8")
    html = render_hub([("A", tmp_path / "a.svg")])
    # 应有 panel meta 显示文件大小
    assert "panel-meta" in html
    # 文件大小单位
    assert "B" in html or "KB" in html


def test_render_hub_empty_dashboards():
    """空 dashboards 列表也能渲染（虽然没什么内容）"""
    html = render_hub([])
    assert "<!DOCTYPE html>" in html
    # 无 tabs 内容
    assert 'class="tabs"' in html


# ---- CLI main ----

def test_main_writes_default_path(tmp_path, monkeypatch):
    """main 默认写到 tests-archive/dashboard_hub.html"""
    # 设置 ROOT 到 tmp_path，让默认路径在那里
    monkeypatch.setattr("tools.dashboard_hub.ROOT", tmp_path)
    # 创建 tests-archive 目录
    (tmp_path / "tests-archive").mkdir()

    rc = main([])
    assert rc == 0

    out = tmp_path / "tests-archive" / "dashboard_hub.html"
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content


def test_main_custom_output(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.dashboard_hub.ROOT", tmp_path)
    out = tmp_path / "custom.html"

    rc = main(["--output", str(out)])
    assert rc == 0
    assert out.exists()


def test_main_custom_title(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.dashboard_hub.ROOT", tmp_path)
    (tmp_path / "tests-archive").mkdir()

    rc = main(["--title", "My Dashboard"])
    assert rc == 0
    out = tmp_path / "tests-archive" / "dashboard_hub.html"
    assert "My Dashboard" in out.read_text(encoding="utf-8")


def test_main_include_specific(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.dashboard_hub.ROOT", tmp_path)
    (tmp_path / "tests-archive").mkdir()
    # 只创建一个 custom.svg
    (tmp_path / "tests-archive" / "custom.svg").write_text(SAMPLE_SVG, encoding="utf-8")

    rc = main(["--include", "custom.svg"])
    assert rc == 0
    out = tmp_path / "tests-archive" / "dashboard_hub.html"
    content = out.read_text(encoding="utf-8")
    # 包含 custom.svg
    assert "custom.svg" in content


def test_main_embed_mode(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.dashboard_hub.ROOT", tmp_path)
    (tmp_path / "tests-archive").mkdir()
    (tmp_path / "tests-archive" / "dashboard.svg").write_text(SAMPLE_SVG, encoding="utf-8")

    rc = main(["--embed"])
    assert rc == 0
    content = (tmp_path / "tests-archive" / "dashboard_hub.html").read_text(encoding="utf-8")
    # embed 模式：SVG 应被 inline（不是 iframe）
    assert "iframe" not in content
    assert "<svg" in content


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))