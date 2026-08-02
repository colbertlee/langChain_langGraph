"""
Dashboard Hub（Day 25）。

生成一个 HTML 把所有 dashboard SVG 聚合到一个页面：
- archive dashboard (tests-archive/dashboard.svg)
- doctor dashboard (tests-archive/doctor.svg，可选)
- evals dashboard (tests-archive/evals.svg，可选)

输出：tests-archive/dashboard_hub.html

特点：
- **零硬依赖**：纯 HTML + iframe（SVG inline 也行，但 iframe 让各 dashboard 独立）
- **responsive**：iframe 宽度 100%，高度自适应
- **可被 GitHub Pages serve**：HTML 在 repo 内
- **tabs 切换**：用户可点击切换 dashboard

用法::

    python tools/dashboard_hub.py  # 默认路径
    python tools/dashboard_hub.py --title "My Agent"
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


DEFAULT_OUTPUT = ROOT / "tests-archive" / "dashboard_hub.html"


def _file_size(p: Path) -> str:
    """友好显示文件大小。"""
    if not p.exists():
        return "(missing)"
    sz = p.stat().st_size
    if sz < 1024:
        return f"{sz} B"
    if sz < 1024 * 1024:
        return f"{sz / 1024:.1f} KB"
    return f"{sz / 1024 / 1024:.1f} MB"


def _file_mtime(p: Path) -> str:
    if not p.exists():
        return "—"
    return datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def discover_dashboards(
    base_dir: Path,
    paths: Optional[List[str]] = None,
) -> List[Tuple[str, Path]]:
    """扫描可用 dashboard。

    Args:
        base_dir: 基础目录（tests-archive/）
        paths: 用户指定的路径列表（relative to base_dir），如 ``["dashboard.svg"]``

    Returns:
        List of (title, absolute path)
    """
    if paths is None:
        paths = [
            "dashboard.svg",      # archive
            "doctor.svg",         # doctor (Day 16+)
            "evals.svg",          # evals (Day 15+)
            "chat.svg",           # chat latency
            "business.svg",       # business
        ]

    out: List[Tuple[str, Path]] = []
    for rel in paths:
        p = base_dir / rel
        # 标题：去掉 .svg 后缀，按 - 或 _ 分词大写
        title = rel.replace(".svg", "").replace("-", " ").replace("_", " ").title()
        out.append((title, p))
    return out


def render_hub(
    dashboards: List[Tuple[str, Path]],
    *,
    title: str = "AI Agent Observability",
    embed: bool = False,
) -> str:
    """渲染 dashboard hub HTML。

    Args:
        dashboards: List of (title, path)
        title: 页面标题
        embed: True = 把 SVG 内容 inline 到 HTML；False = 用 iframe 引用
    """
    parts: List[str] = []

    # HTML head
    parts.append(f"<!DOCTYPE html>")
    parts.append(f'<html lang="en">')
    parts.append(
        f'<head>'
        f'<meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f'<title>{title}</title>'
        f'<style>'
        f'body{{font-family:-apple-system,system-ui,sans-serif;margin:0;padding:0;'
        f'background:#f5f5f7;color:#1c1c1e}}'
        f'.header{{padding:16px 24px;background:#fff;border-bottom:1px solid #d1d1d6;'
        f'display:flex;justify-content:space-between;align-items:center}}'
        f'.header h1{{margin:0;font-size:18px;font-weight:600}}'
        f'.meta{{font-size:11px;color:#6c6c70}}'
        f'.tabs{{display:flex;gap:0;background:#fff;border-bottom:1px solid #d1d1d6;'
        f'padding:0 24px;overflow-x:auto}}'
        f'.tab{{padding:12px 16px;cursor:pointer;border:none;background:none;'
        f'font-size:14px;font-weight:500;color:#6c6c70;border-bottom:2px solid transparent}}'
        f'.tab:hover{{color:#1c1c1e}}'
        f'.tab.active{{color:#007aff;border-bottom-color:#007aff}}'
        f'.panel{{display:none;padding:16px 24px;background:#fff;margin:16px 24px;'
        f'border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.05)}}'
        f'.panel.active{{display:block}}'
        f'.panel-header{{display:flex;justify-content:space-between;'
        f'align-items:center;margin-bottom:12px;padding-bottom:8px;'
        f'border-bottom:1px solid #e5e5ea}}'
        f'.panel-header h2{{margin:0;font-size:14px;font-weight:600}}'
        f'.panel-meta{{font-size:11px;color:#6c6c70;font-family:ui-monospace,monospace}}'
        f'.dashboard-frame{{width:100%;border:none;min-height:400px;'
        f'background:#fff}}'
        f'.missing{{padding:40px;text-align:center;color:#8e8e93;font-size:13px}}'
        f'</style>'
        f'</head>'
    )

    parts.append(f'<body>')

    # Header
    parts.append(
        f'<div class="header">'
        f'<h1>{title}</h1>'
        f'<div class="meta">Updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>'
        f'</div>'
    )

    # Tabs
    parts.append(f'<div class="tabs">')
    for i, (t, _) in enumerate(dashboards):
        active_cls = "active" if i == 0 else ""
        parts.append(
            f'<button class="tab {active_cls}" data-tab="tab-{i}">{t}</button>'
        )
    parts.append(f'</div>')

    # Panels
    parts.append(
        f'<script>'
        f'document.querySelectorAll(".tab").forEach(tab => {{'
        f'  tab.addEventListener("click", () => {{'
        f'    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));'
        f'    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));'
        f'    tab.classList.add("active");'
        f'    const target = tab.dataset.tab;'
        f'    document.getElementById(target).classList.add("active");'
        f'  }});'
        f'}});'
        f'</script>'
    )

    for i, (t, p) in enumerate(dashboards):
        active_cls = "active" if i == 0 else ""
        parts.append(f'<div id="tab-{i}" class="panel {active_cls}">')
        parts.append(
            f'<div class="panel-header">'
            f'<h2>{t}</h2>'
            f'<div class="panel-meta">{_file_size(p)} · {_file_mtime(p)}</div>'
            f'</div>'
        )
        if p.exists():
            if embed:
                # 把 SVG 内容 inline
                svg_content = p.read_text(encoding="utf-8")
                parts.append(svg_content)
            else:
                # 用 iframe 引用
                rel_path = p.name  # 同目录
                parts.append(
                    f'<iframe class="dashboard-frame" '
                    f'src="{rel_path}" '
                    f'title="{t}">'
                    f'</iframe>'
                )
        else:
            parts.append(
                f'<div class="missing">Dashboard not generated yet: '
                f'<code>{p.name}</code><br>'
                f'<small>Run the relevant generator to create this dashboard.</small>'
                f'</div>'
            )
        parts.append(f'</div>')

    parts.append(f'</body></html>')

    return "\n".join(parts)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="dashboard_hub")
    parser.add_argument("--output", help="HTML 输出路径")
    parser.add_argument("--title", default="AI Agent Observability")
    parser.add_argument("--embed", action="store_true", help="SVG inline 到 HTML")
    parser.add_argument(
        "--include",
        nargs="+",
        help="指定要包含的 SVG 文件名列表",
    )
    args = parser.parse_args(argv)

    base_dir = ROOT / "tests-archive"
    dashboards = discover_dashboards(base_dir, paths=args.include)

    html = render_hub(
        dashboards,
        title=args.title,
        embed=args.embed,
    )

    # Day 25：每次根据当前 ROOT 算默认输出（支持测试 monkeypatch）
    default_output = ROOT / "tests-archive" / "dashboard_hub.html"
    target = Path(args.output) if args.output else default_output
    if not target.is_absolute():
        target = (ROOT / target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    try:
        rel = target.relative_to(ROOT)
    except ValueError:
        rel = target
    print(f"[ok] wrote {rel} ({len(html)} bytes, {len(dashboards)} dashboards)")
    return 0


if __name__ == "__main__":
    sys.exit(main())