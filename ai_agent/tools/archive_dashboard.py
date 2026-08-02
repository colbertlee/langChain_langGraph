"""
archive 趋势 SVG 仪表板（Day 20）。

把 ``tests-archive/acceptance/<ts>/summary.json`` 历史序列渲染成 SVG 图表，
便于：
- 嵌入 GitHub Pages 站点；
- 上传到 Slack 作为 image（``files.upload``）；
- 嵌入 release notes；
- 存成静态资源（无 matplotlib / plotly 依赖时也能用）。

特性
~~~~
- **零硬依赖**：纯 stdlib（仅 Python 3.9+ 用 ``zoneinfo`` 可选）；
- 输出 SVG（vector，矢量），可在任何现代浏览器 / Slack 显示；
- 三条线：passed / failed / errored，叠加 ``ran_ratio`` 折线；
- 时间轴：横坐标是 ts；纵坐标是计数；
- 颜色语义：passed=green / failed=orange / errored=red / ran_ratio=blue。

用法
~~~~

.. code-block:: bash

    # 默认写到 tests-archive/dashboard.svg
    python tools/archive_dashboard.py

    # 指定输出
    python tools/archive_dashboard.py --output path/to/dashboard.svg

    # 限制最近 N 次跑
    python tools/archive_dashboard.py --limit 12

    # 同时调用 Slack 把 SVG 上传成 image（files.upload v2）
    python tools/archive_dashboard.py --slack-upload "$SLACK_BOT_TOKEN" "#daily-health"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


ACCEPTANCE_DIR = ROOT / "tests-archive" / "acceptance"
DEFAULT_OUTPUT = ROOT / "tests-archive" / "dashboard.svg"


# ============================================================
# 数据读取
# ============================================================

def load_runs(limit: int = 20) -> List[dict]:
    """读最近 N 次 *有真实结果* 的 summary（按 ts 升序）。

    ``limit`` 是"目标返回数"的上限：从最新目录往前扫，跳过空跑（0/0/0），
    直到凑够 ``limit`` 条或扫完。返回值不超过 ``limit`` 条。
    """
    if not ACCEPTANCE_DIR.exists():
        return []
    runs = sorted(
        [d for d in ACCEPTANCE_DIR.iterdir() if d.is_dir()],
        reverse=False,  # 升序 → 横轴时间从左到右
    )
    out: List[dict] = []
    # 从尾部（最新）往前扫：凑够 limit 条有效数据
    for d in reversed(runs):
        if len(out) >= limit:
            break
        s = d / "summary.json"
        if not s.exists():
            continue
        try:
            data = json.loads(s.read_text(encoding="utf-8"))
        except Exception:
            continue
        t = data.get("totals", {})
        # 跳过 0/0 空跑
        if t.get("passed", 0) == 0 and t.get("failed", 0) == 0 and t.get("errored", 0) == 0:
            continue
        out.append(data)
    # 还原为时间升序（横轴左到右）
    out.sort(key=lambda x: x.get("started_at", ""))
    return out


# ============================================================
# Day 22：时间桶（period bucketing）
# ============================================================

def _bucket_ts(ts: str, period: str) -> str:
    """把 ``YYYYMMDD_HHMMSS`` 桶到对应 period 的 key。

    - ``daily`` → ``YYYY-MM-DD``
    - ``weekly`` → ``YYYY-Www`` (ISO 周)
    - ``monthly`` → ``YYYY-MM``
    - ``none`` / 其他 → 原样
    """
    if period == "none" or period not in ("daily", "weekly", "monthly"):
        return ts

    try:
        # ts 是 ``YYYYMMDD_HHMMSS``；先转成 datetime
        ts_clean = ts.replace("_", "")
        # ts_clean 是 ``YYYYMMDDHHMMSS`` → 取前 8 位
        d = datetime.strptime(ts_clean[:8], "%Y%m%d").date()
    except Exception:
        return ts

    if period == "daily":
        return d.isoformat()

    if period == "weekly":
        iso_cal = d.isocalendar()
        # iso_cal.week 1-53
        return f"{d.isocalendar()[0]}-W{iso_cal[1]:02d}"

    if period == "monthly":
        return f"{d.year}-{d.month:02d}"

    return ts


def bucket_runs(runs: List[dict], period: str) -> List[dict]:
    """把 runs 按 period 分桶，**每个桶保留 latest 一条**。

    Args:
        runs: 升序排序的 summary list
        period: ``daily`` / ``weekly`` / ``monthly`` / ``none``

    Returns:
        桶化后的 summary list（按 bucket key 升序）
    """
    if period == "none" or not period:
        return runs

    buckets = {}
    for r in runs:
        ts = r.get("started_at", "")
        key = _bucket_ts(ts, period)
        if not key:
            continue
        buckets[key] = r  # latest 一条覆盖前面的（runs 升序）

    # 按 key 升序输出
    out = []
    for k in sorted(buckets.keys()):
        r = dict(buckets[k])
        r["started_at"] = k  # 标签替换成桶 key
        out.append(r)
    return out


def _bucket_ts_from_iso(ts: str, period: str) -> str:
    """类似 _bucket_ts，但接受 ISO 格式 ``YYYY-MM-DDTHH:MM:SS`` 或 ``YYYY-MM-DD HH:MM``。"""
    if period == "none" or period not in ("daily", "weekly", "monthly"):
        return ts

    if not ts:
        return ts

    # 先用 fromisoformat（更宽容）
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        # 试其他格式
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                d = datetime.strptime(ts, fmt).date()
                break
            except ValueError:
                continue
        else:
            # 试 YYYYMMDD_HHMMSS
            try:
                d = datetime.strptime(ts[:8], "%Y%m%d").date()
            except Exception:
                return ts

    if period == "daily":
        return d.isoformat()
    if period == "weekly":
        return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
    if period == "monthly":
        return f"{d.year}-{d.month:02d}"
    return ts


def bucket_evals(evals: List[dict], period: str) -> List[dict]:
    """Day 23：把 evals 按 period 分桶，每个桶保留 latest 一条。

    Args:
        evals: List[{"ts", "pass_rate", "total", "latency_ms"}]
        period: ``daily`` / ``weekly`` / ``monthly`` / ``none``

    Returns:
        桶化后的 evals（按 bucket key 升序）
    """
    if period == "none" or not period:
        return evals

    buckets = {}
    for e in evals:
        ts = e.get("ts", "")
        key = _bucket_ts_from_iso(ts, period)
        if not key:
            continue
        buckets[key] = e

    out = []
    for k in sorted(buckets.keys()):
        item = dict(buckets[k])
        item["ts"] = k
        out.append(item)
    return out


def bucket_chats(
    chats: List[dict],
    period: str,
    *,
    agg: str = "avg",
) -> List[dict]:
    """Day 23/24：把 chats 按 period 分桶，每个桶**聚合**。

    Day 24：支持多种聚合策略（``agg``）：
    - ``avg``（默认）：算术平均
    - ``max``：桶内最大
    - ``min``：桶内最小
    - ``median``：桶内中位数
    - ``p95`` / ``p99``：第 95/99 百分位（最大~最大，性能 SLA 用）

    Args:
        chats: List[{"ts", "latency_ms"}]
        period: ``daily`` / ``weekly`` / ``monthly`` / ``none``
        agg: 聚合策略

    Returns:
        桶化后的 chats（按 bucket key 升序，每个桶是聚合 latency）
    """
    if period == "none" or not period:
        return chats

    bucket_lat: dict = {}
    for c in chats:
        ts = c.get("ts", "")
        key = _bucket_ts_from_iso(ts, period)
        if not key:
            continue
        bucket_lat.setdefault(key, []).append(c.get("latency_ms", 0.0))

    out = []
    for k in sorted(bucket_lat.keys()):
        vals = bucket_lat[k]
        out.append({"ts": k, "latency_ms": _aggregate(vals, agg)})
    return out


def _aggregate(values: List[float], agg: str) -> float:
    """Day 24：聚合 helper（避免 import statistics）。"""
    if not values:
        return 0.0

    if agg == "avg" or agg == "mean":
        return sum(values) / len(values)

    if agg == "max":
        return max(values)

    if agg == "min":
        return min(values)

    if agg == "median":
        s = sorted(values)
        n = len(s)
        if n % 2 == 1:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2.0

    if agg.startswith("p"):
        try:
            pct = float(agg[1:])  # "p95" → 95.0
        except ValueError:
            return sum(values) / len(values)
        if pct < 0 or pct > 100:
            return sum(values) / len(values)
        # 线性插值 percentile
        s = sorted(values)
        k = (len(s) - 1) * (pct / 100.0)
        f = int(k)
        c = min(f + 1, len(s) - 1)
        if f == c:
            return s[f]
        return s[f] + (s[c] - s[f]) * (k - f)

    # fallback: avg
    return sum(values) / len(values)


# ============================================================
# SVG 渲染
# ============================================================

COLOR_PASSED = "#34c759"   # green
COLOR_FAILED = "#ff9500"   # orange
COLOR_ERRORED = "#ff3b30"  # red
COLOR_RATIO = "#0a84ff"    # blue
COLOR_GRID = "#d1d1d6"
COLOR_TEXT = "#1c1c1e"
COLOR_BG = "#ffffff"


def _short_ts(ts: str) -> str:
    """``20260726_174125`` → ``07-26 17:41``"""
    if not isinstance(ts, str) or len(ts) < 13:
        return str(ts)
    try:
        d = ts[:8]
        t = ts[9:13]
        return f"{d[4:6]}-{d[6:8]} {t[:2]}:{t[2:]}"
    except Exception:
        return str(ts)


def render_svg(
    runs: List[dict],
    *,
    width: int = 760,
    height: int = 360,
    sha: str = "",
    timestamp: str = "",
) -> str:
    """Day 21：渲染单 panel SVG（向后兼容）。

    Day 22：转发 ``sha`` / ``timestamp`` 到多 panel 模板。
    """
    return render_multipanel_svg(
        {"archive_trend": runs},
        width=width,
        height=height,
        sha=sha,
        timestamp=timestamp,
    )


def _render_archive_trend_panel(
    runs: List[dict],
    x: float,
    y: float,
    w: float,
    h: float,
    parts: List[str],
) -> None:
    """Panel 1：archive trend（passed/failed/errored + ran_ratio%）。"""
    # 标题（即使空也显示）
    parts.append(
        f'<text x="{x + 6}" y="{y + 18}" font-size="12" font-weight="600" fill="{COLOR_TEXT}">'
        f'archive trend ({len(runs)} runs)'
        f'</text>'
    )

    if not runs:
        parts.append(
            f'<text x="{x + w / 2:.1f}" y="{y + h / 2:.1f}" font-size="11" '
            f'fill="{COLOR_TEXT}" text-anchor="middle">no archive data</text>'
        )
        return

    n = len(runs)
    passed = [r.get("totals", {}).get("passed", 0) for r in runs]
    failed = [r.get("totals", {}).get("failed", 0) for r in runs]
    errored = [r.get("totals", {}).get("errored", 0) for r in runs]
    ratio_pcts: List[float] = []
    for r in runs:
        t = r.get("totals", {})
        ran = t.get("passed", 0) + t.get("failed", 0) + t.get("errored", 0)
        if ran == 0:
            ratio_pcts.append(0.0)
        else:
            ratio_pcts.append(t.get("passed", 0) / ran * 100)

    max_y = max(passed + failed + errored + [10])
    ts_labels = [_short_ts(r.get("started_at", "?")) for r in runs]

    margin_l = x + 36
    margin_r = x + w - 14
    margin_t = y + 30
    margin_b = y + h - 22
    plot_w = margin_r - margin_l
    plot_h = margin_b - margin_t

    def x_at(i: int) -> float:
        if n == 1:
            return margin_l + plot_w / 2
        return margin_l + plot_w * i / (n - 1)

    def y_at(value: float, max_v: float) -> float:
        return margin_t + plot_h * (1 - value / max_v)

    # Grid
    for v in [0, 0.25, 0.5, 0.75, 1.0]:
        yy = margin_t + plot_h * (1 - v)
        parts.append(
            f'<line x1="{margin_l}" y1="{yy:.1f}" x2="{margin_r}" y2="{yy:.1f}" '
            f'stroke="{COLOR_GRID}" stroke-dasharray="2 2"/>'
        )
        parts.append(
            f'<text x="{margin_l - 6}" y="{yy + 3:.1f}" font-size="9" fill="{COLOR_TEXT}" '
            f'text-anchor="end">{int(v * max_y)}</text>'
        )

    # X labels
    label_every = max(1, n // 6)
    for i, label in enumerate(ts_labels):
        if i % label_every == 0 or i == n - 1:
            parts.append(
                f'<text x="{x_at(i):.1f}" y="{margin_b + 12}" font-size="8" '
                f'fill="{COLOR_TEXT}" text-anchor="middle">{label}</text>'
            )

    def polyline(values: List[int], color: str) -> None:
        pts = " ".join(f"{x_at(i):.1f},{y_at(values[i], max_y):.1f}" for i in range(n))
        parts.append(
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        for i in range(n):
            parts.append(
                f'<circle cx="{x_at(i):.1f}" cy="{y_at(values[i], max_y):.1f}" r="2.5" '
                f'fill="{color}"/>'
            )

    polyline(passed, COLOR_PASSED)
    polyline(failed, COLOR_FAILED)
    polyline(errored, COLOR_ERRORED)

    # ran_ratio dashed
    ratio_pts = " ".join(
        f"{x_at(i):.1f},{y_at(ratio_pcts[i], 100):.1f}" for i in range(n)
    )
    parts.append(
        f'<polyline points="{ratio_pts}" fill="none" stroke="{COLOR_RATIO}" '
        f'stroke-width="1.5" stroke-dasharray="4 3" opacity="0.7"/>'
    )


def _render_evals_panel(
    evals: List[dict],
    x: float,
    y: float,
    w: float,
    h: float,
    parts: List[str],
) -> None:
    """Panel 2：最近 N 次 evals（pass rate / total / latency）。"""
    parts.append(
        f'<text x="{x + 6}" y="{y + 18}" font-size="12" font-weight="600" fill="{COLOR_TEXT}">'
        f'evals (last {len(evals)} runs)'
        f'</text>'
    )
    if not evals:
        parts.append(
            f'<text x="{x + w / 2:.1f}" y="{y + h / 2:.1f}" font-size="11" '
            f'fill="{COLOR_TEXT}" text-anchor="middle">no evals data</text>'
        )
        return

    n = len(evals)
    # evals item: {"ts": "...", "pass_rate": float(0..1), "total": int, "latency_ms": float}
    pass_rates = [e.get("pass_rate", 0.0) * 100 for e in evals]
    latencies = [e.get("latency_ms", 0.0) for e in evals]
    totals = [e.get("total", 0) for e in evals]

    margin_l = x + 36
    margin_r = x + w - 14
    margin_t = y + 30
    margin_b = y + h - 22
    plot_w = margin_r - margin_l
    plot_h = margin_b - margin_t

    max_pass = 100.0
    max_lat = max(latencies + [1.0])

    def x_at(i: int) -> float:
        if n == 1:
            return margin_l + plot_w / 2
        return margin_l + plot_w * i / (n - 1)

    def y_pass(v: float) -> float:
        return margin_t + plot_h * (1 - v / max_pass)

    def y_lat(v: float) -> float:
        return margin_t + plot_h * (1 - v / max_lat)

    # Grid (pass_rate scale)
    for v in [0, 25, 50, 75, 100]:
        yy = y_pass(v)
        parts.append(
            f'<line x1="{margin_l}" y1="{yy:.1f}" x2="{margin_r}" y2="{yy:.1f}" '
            f'stroke="{COLOR_GRID}" stroke-dasharray="2 2"/>'
        )
        parts.append(
            f'<text x="{margin_l - 6}" y="{yy + 3:.1f}" font-size="9" fill="{COLOR_TEXT}" '
            f'text-anchor="end">{int(v)}%</text>'
        )

    # pass_rate line
    pts = " ".join(f"{x_at(i):.1f},{y_pass(pass_rates[i]):.1f}" for i in range(n))
    parts.append(
        f'<polyline points="{pts}" fill="none" stroke="{COLOR_PASSED}" stroke-width="2"/>'
    )
    for i in range(n):
        parts.append(
            f'<circle cx="{x_at(i):.1f}" cy="{y_pass(pass_rates[i]):.1f}" r="2.5" '
            f'fill="{COLOR_PASSED}"/>'
        )

    # latency bars (right scale, on same plot)
    bar_w = max(2.0, plot_w / max(n, 1) * 0.3)
    for i, lat in enumerate(latencies):
        bh = (lat / max_lat) * plot_h * 0.7
        bx = x_at(i) - bar_w / 2
        parts.append(
            f'<rect x="{bx:.1f}" y="{margin_b - bh:.1f}" width="{bar_w:.1f}" '
            f'height="{bh:.1f}" fill="{COLOR_FAILED}" opacity="0.45"/>'
        )

    # Legend inside
    leg_y = margin_t + 8
    parts.append(
        f'<rect x="{margin_r - 100}" y="{leg_y - 7}" width="10" height="10" rx="2" fill="{COLOR_PASSED}"/>'
    )
    parts.append(
        f'<text x="{margin_r - 86}" y="{leg_y + 2}" font-size="9" fill="{COLOR_TEXT}">pass_rate</text>'
    )
    parts.append(
        f'<rect x="{margin_r - 30}" y="{leg_y - 7}" width="10" height="10" rx="2" fill="{COLOR_FAILED}" opacity="0.5"/>'
    )
    parts.append(
        f'<text x="{margin_r - 16}" y="{leg_y + 2}" font-size="9" fill="{COLOR_TEXT}">latency</text>'
    )


def _render_business_panel(
    business: List[dict],
    x: float,
    y: float,
    w: float,
    h: float,
    parts: List[str],
) -> None:
    """Day 25 Panel 4：业务 metrics（chat count / user count / revenue）。"""
    parts.append(
        f'<text x="{x + 6}" y="{y + 18}" font-size="12" font-weight="600" fill="{COLOR_TEXT}">'
        f'business ({len(business)} days)'
        f'</text>'
    )
    if not business:
        parts.append(
            f'<text x="{x + w / 2:.1f}" y="{y + h / 2:.1f}" font-size="11" '
            f'fill="{COLOR_TEXT}" text-anchor="middle">no business data</text>'
        )
        return

    n = len(business)
    chats = [b.get("chat_count", 0) for b in business]
    users = [b.get("user_count", 0) for b in business]
    revenues = [b.get("revenue_usd", 0.0) for b in business]

    margin_l = x + 36
    margin_r = x + w - 14
    margin_t = y + 30
    margin_b = y + h - 22
    plot_w = margin_r - margin_l
    plot_h = margin_b - margin_t

    max_chat = max(chats + [1])
    max_rev = max(revenues + [1.0])

    def x_at(i: int) -> float:
        if n == 1:
            return margin_l + plot_w / 2
        return margin_l + plot_w * i / (n - 1)

    def y_chat(v: int) -> float:
        return margin_t + plot_h * (1 - v / max_chat)

    def y_rev(v: float) -> float:
        return margin_t + plot_h * (1 - v / max_rev)

    # Grid
    for v in [0, 0.25, 0.5, 0.75, 1.0]:
        yy = margin_t + plot_h * (1 - v)
        parts.append(
            f'<line x1="{margin_l}" y1="{yy:.1f}" x2="{margin_r}" y2="{yy:.1f}" '
            f'stroke="{COLOR_GRID}" stroke-dasharray="2 2"/>'
        )

    # chat_count line (green)
    pts = " ".join(f"{x_at(i):.1f},{y_chat(chats[i]):.1f}" for i in range(n))
    parts.append(
        f'<polyline points="{pts}" fill="none" stroke="{COLOR_PASSED}" stroke-width="2"/>'
    )

    # revenue bars (orange)
    bar_w = max(2.0, plot_w / max(n, 1) * 0.5)
    for i, rev in enumerate(revenues):
        bh = (rev / max_rev) * plot_h * 0.8
        bx = x_at(i) - bar_w / 2
        parts.append(
            f'<rect x="{bx:.1f}" y="{margin_b - bh:.1f}" width="{bar_w:.1f}" '
            f'height="{bh:.1f}" fill="{COLOR_FAILED}" opacity="0.4"/>'
        )

    # Legend
    leg_y = margin_t + 8
    parts.append(
        f'<rect x="{margin_l}" y="{leg_y - 7}" width="10" height="10" rx="2" fill="{COLOR_PASSED}"/>'
    )
    parts.append(
        f'<text x="{margin_l + 14}" y="{leg_y + 2}" font-size="9" fill="{COLOR_TEXT}">chat_count</text>'
    )
    parts.append(
        f'<rect x="{margin_l + 80}" y="{leg_y - 7}" width="10" height="10" rx="2" fill="{COLOR_FAILED}" opacity="0.5"/>'
    )
    parts.append(
        f'<text x="{margin_l + 94}" y="{leg_y + 2}" font-size="9" fill="{COLOR_TEXT}">revenue</text>'
    )

    # 显示最新 user_count 在右上
    if users:
        latest_users = users[-1]
        parts.append(
            f'<text x="{margin_r}" y="{leg_y + 2}" font-size="10" fill="{COLOR_RATIO}" '
            f'text-anchor="end" font-weight="600">'
            f'users {latest_users:,}'
            f'</text>'
        )


def _render_latency_panel(
    chats: List[dict],
    x: float,
    y: float,
    w: float,
    h: float,
    parts: List[str],
) -> None:
    """Panel 3：chat latency 最近 N 次（ms）。"""
    parts.append(
        f'<text x="{x + 6}" y="{y + 18}" font-size="12" font-weight="600" fill="{COLOR_TEXT}">'
        f'chat latency ({len(chats)} samples)'
        f'</text>'
    )
    if not chats:
        parts.append(
            f'<text x="{x + w / 2:.1f}" y="{y + h / 2:.1f}" font-size="11" '
            f'fill="{COLOR_TEXT}" text-anchor="middle">no chat data</text>'
        )
        return

    n = len(chats)
    # chats item: {"ts": "...", "latency_ms": float}
    latencies = [c.get("latency_ms", 0.0) for c in chats]

    margin_l = x + 36
    margin_r = x + w - 14
    margin_t = y + 30
    margin_b = y + h - 22
    plot_w = margin_r - margin_l
    plot_h = margin_b - margin_t

    max_lat = max(latencies + [1.0])

    def x_at(i: int) -> float:
        if n == 1:
            return margin_l + plot_w / 2
        return margin_l + plot_w * i / (n - 1)

    def y_lat(v: float) -> float:
        return margin_t + plot_h * (1 - v / max_lat)

    # Grid
    for v in [0.0, 0.25, 0.5, 0.75, 1.0]:
        yy = y_lat(v * max_lat)
        parts.append(
            f'<line x1="{margin_l}" y1="{yy:.1f}" x2="{margin_r}" y2="{yy:.1f}" '
            f'stroke="{COLOR_GRID}" stroke-dasharray="2 2"/>'
        )
        parts.append(
            f'<text x="{margin_l - 6}" y="{yy + 3:.1f}" font-size="9" fill="{COLOR_TEXT}" '
            f'text-anchor="end">{int(v * max_lat)}ms</text>'
        )

    # Bars
    bar_w = max(2.0, plot_w / max(n, 1) * 0.7)
    for i, lat in enumerate(latencies):
        bh = (lat / max_lat) * plot_h
        bx = x_at(i) - bar_w / 2
        # 按阈值上色
        if lat > max_lat * 0.75:
            color = COLOR_ERRORED
        elif lat > max_lat * 0.5:
            color = COLOR_FAILED
        else:
            color = COLOR_PASSED
        parts.append(
            f'<rect x="{bx:.1f}" y="{margin_b - bh:.1f}" width="{bar_w:.1f}" '
            f'height="{bh:.1f}" fill="{color}"/>'
        )

    # 平均线
    avg = sum(latencies) / n
    y_avg = y_lat(avg)
    parts.append(
        f'<line x1="{margin_l}" y1="{y_avg:.1f}" x2="{margin_r}" y2="{y_avg:.1f}" '
        f'stroke="{COLOR_TEXT}" stroke-dasharray="3 2" opacity="0.5"/>'
    )
    parts.append(
        f'<text x="{margin_r - 4}" y="{y_avg - 4:.1f}" font-size="9" fill="{COLOR_TEXT}" '
        f'text-anchor="end">avg {avg:.0f}ms</text>'
    )


def _git_short_sha() -> str:
    """读当前 git short SHA（7 字符）；非 git 仓库或出错时返回 ``unknown``。"""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(ROOT),
        )
        if out.returncode == 0:
            sha = out.stdout.strip()
            if sha:
                return sha
    except Exception:
        pass
    return "unknown"


def _build_meta_line(*, sha: str, timestamp: str) -> str:
    """构造右上角 metadata 文本：``SHA · timestamp``。"""
    if sha and sha != "unknown":
        return f"{sha[:7]} · {timestamp}"
    return timestamp


def render_multipanel_svg(
    panels_data: dict,
    *,
    width: int = 1440,  # Day 25：4 panel 拉宽
    height: int = 360,
    sha: str = "",
    timestamp: str = "",
) -> str:
    """Day 21/25：渲染多 panel SVG（最多 4 panel）。

    ``panels_data`` 接受键：
    - ``archive_trend``：List[summary]
    - ``evals``：List[{"ts", "pass_rate", "total", "latency_ms"}]
    - ``chats``：List[{"ts", "latency_ms"}]
    - ``business``（Day 25）：List[{"ts", "chat_count", "user_count", "revenue_usd"}]

    Day 22：右上角显示 ``commit SHA · timestamp``。

    横向并排；缺失 panel 用 ``no xxx data`` 占位。
    """
    parts: List[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" font-family="-apple-system, system-ui, sans-serif">'
    )

    # 背景
    parts.append(f'<rect width="{width}" height="{height}" fill="{COLOR_BG}"/>')

    # 顶部标题
    from datetime import datetime
    if not timestamp:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not sha:
        sha = _git_short_sha()
    meta = _build_meta_line(sha=sha, timestamp=timestamp)

    parts.append(
        f'<text x="16" y="16" font-size="12" font-weight="600" fill="{COLOR_TEXT}">'
        f'agent observability dashboard (multi-panel)'
        f'</text>'
    )
    parts.append(
        f'<text x="{width - 16}" y="16" font-size="10" fill="{COLOR_TEXT}" '
        f'text-anchor="end" font-family="ui-monospace, SFMono-Regular, Menlo, monospace">'
        f'{meta}'
        f'</text>'
    )

    # 4 panel 横向均分（带间隔；Day 25：加 business panel）
    gap = 8
    active_panels = [
        ("archive_trend", _render_archive_trend_panel),
        ("evals", _render_evals_panel),
        ("chats", _render_latency_panel),
        ("business", _render_business_panel),
    ]
    n = len(active_panels)
    panel_w = (width - gap * (n - 1)) / n
    panel_y = 28
    panel_h = height - panel_y - 10

    for i, (key, fn) in enumerate(active_panels):
        x = i * (panel_w + gap)
        fn(panels_data.get(key, []), x, panel_y, panel_w, panel_h, parts)

    parts.append('</svg>')
    return "\n".join(parts)


def _empty_svg(msg: str, w: int, h: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}">'
        f'<rect width="{w}" height="{h}" fill="{COLOR_BG}"/>'
        f'<text x="{w/2}" y="{h/2}" font-size="14" fill="{COLOR_TEXT}" text-anchor="middle">'
        f'{msg}'
        f'</text></svg>'
    )


# ============================================================
# Slack 上传（files.upload v2）
# ============================================================

def upload_to_slack(token: str, channel: str, svg_path: Path, title: str = "archive trend") -> int:
    """把 SVG 上传到 Slack channel，返回响应码。"""
    import urllib.request
    import urllib.error

    boundary = "----archive-dashboard"
    with svg_path.open("rb") as f:
        svg_bytes = f.read()

    # multipart/form-data
    body = b""
    # 字段 1：channels
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"channels\"\r\n\r\n{channel}\r\n".encode()
    # 字段 2：title
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n{title}\r\n".encode()
    # 字段 3：file
    body += (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"dashboard.svg\"\r\n"
        f"Content-Type: image/svg+xml\r\n\r\n"
    ).encode() + svg_bytes + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        "https://slack.com/api/files.upload",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.getcode() or 0
    except urllib.error.HTTPError as e:
        print(f"[warn] slack upload HTTP {e.code}", file=sys.stderr)
        return e.code
    except Exception as e:
        print(f"[warn] slack upload failed: {e}", file=sys.stderr)
        return 0


# ============================================================
# CLI
# ============================================================

def load_evals(limit: int = 10, path: Optional[Path] = None) -> List[dict]:
    """读最近 N 次 evals。期望每个 entry: ``{"ts", "pass_rate", "total", "latency_ms"}``。

    来源：默认 ``tests-archive/evals_history.json``（任意 JSON 数组）。
    """
    p = path or (ROOT / "tests-archive" / "evals_history.json")
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return data[-limit:]
    except Exception:
        return []


def load_chats(limit: int = 20, path: Optional[Path] = None) -> List[dict]:
    """读最近 N 次 chat latency。期望每个 entry: ``{"ts", "latency_ms"}``。"""
    p = path or (ROOT / "tests-archive" / "chat_latency.json")
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return data[-limit:]
    except Exception:
        return []


def load_business(limit: int = 30, path: Optional[Path] = None) -> List[dict]:
    """Day 25：读业务 metrics。

    期望每个 entry: ``{"ts", "chat_count", "user_count", "revenue_usd"}``。
    来源：``tests-archive/business_metrics.json``（默认）。
    """
    p = path or (ROOT / "tests-archive" / "business_metrics.json")
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return data[-limit:]
    except Exception:
        return []


def bucket_business(business: List[dict], period: str) -> List[dict]:
    """Day 25：业务 metrics 按 period 分桶聚合。

    策略：
    - ``chat_count`` / ``revenue_usd`` → sum（每天求和）
    - ``user_count`` → last（累计值）
    """
    if period == "none" or not period:
        return business

    bucket_data: dict = {}
    for b in business:
        ts = b.get("ts", "")
        key = _bucket_ts_from_iso(ts, period)
        if not key:
            continue
        if key not in bucket_data:
            bucket_data[key] = {"ts": key, "_sum": {}, "_last": {}}
        bk = bucket_data[key]
        for f in ("chat_count", "revenue_usd"):
            if f in b:
                bk["_sum"][f] = bk["_sum"].get(f, 0) + b[f]
        for f in ("user_count",):
            if f in b:
                bk["_last"][f] = b[f]

    out = []
    for k in sorted(bucket_data.keys()):
        bk = bucket_data[k]
        merged = {"ts": k}
        merged.update(bk["_sum"])
        merged.update(bk["_last"])
        out.append(merged)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="archive_dashboard",
        description="archive 多 panel SVG 仪表板（Day 20/21）",
    )
    parser.add_argument("--output", help="SVG 输出路径（默认 tests-archive/dashboard.svg）")
    parser.add_argument("--limit", type=int, default=20, help="archive trend 最近 N 次跑")
    parser.add_argument(
        "--panels",
        default="all",
        choices=["all", "archive", "evals", "chats", "business"],
        help="选择渲染哪些 panel",
    )
    parser.add_argument(
        "--evals-path",
        help="evals 历史 JSON 路径（默认 tests-archive/evals_history.json）",
    )
    parser.add_argument(
        "--chats-path",
        help="chat latency 历史 JSON 路径（默认 tests-archive/chat_latency.json）",
    )
    parser.add_argument(
        "--business-path",
        help="业务 metrics 历史 JSON 路径（默认 tests-archive/business_metrics.json）",
    )
    parser.add_argument("--slack-token", help="Slack bot token（开启 Slack 上传）")
    parser.add_argument("--slack-channel", help="Slack channel（如 '#daily-health'）")
    parser.add_argument("--title", default="agent observability dashboard", help="Slack 上传标题")
    parser.add_argument(
        "--period",
        default="none",
        choices=["none", "daily", "weekly", "monthly"],
        help="archive trend 时间桶（默认 none = 不分桶）",
    )
    parser.add_argument(
        "--chats-agg",
        default="avg",
        choices=["avg", "max", "min", "median", "p95", "p99"],
        help="chat latency 聚合策略（默认 avg）",
    )
    parser.add_argument(
        "--sha",
        default=os.environ.get("GITHUB_SHA", "") or os.environ.get("GIT_SHA", ""),
        help="git short SHA（默认从 GITHUB_SHA / GIT_SHA 环境变量读）",
    )
    parser.add_argument(
        "--timestamp",
        default=os.environ.get("RUN_DATE", "") or os.environ.get("DASHBOARD_TS", ""),
        help="dashboard 时间戳（默认从 RUN_DATE / DASHBOARD_TS 环境变量读）",
    )
    args = parser.parse_args(argv)

    # 选择 panel
    panels_data: dict = {}
    if args.panels in ("all", "archive"):
        panels_data["archive_trend"] = bucket_runs(
            load_runs(limit=args.limit),
            args.period,
        )
    if args.panels in ("all", "evals"):
        ep = Path(args.evals_path) if args.evals_path else None
        panels_data["evals"] = bucket_evals(load_evals(path=ep), args.period)
    if args.panels in ("all", "chats"):
        cp = Path(args.chats_path) if args.chats_path else None
        panels_data["chats"] = bucket_chats(
            load_chats(path=cp), args.period, agg=args.chats_agg
        )
    if args.panels in ("all", "business"):
        bp = Path(args.business_path) if args.business_path else None
        panels_data["business"] = bucket_business(
            load_business(path=bp), args.period
        )

    # 单 panel 时用窄画布；多 panel 时用宽画布
    sha = args.sha
    ts = args.timestamp
    if args.panels == "all":
        svg = render_multipanel_svg(panels_data, width=1440, height=360, sha=sha, timestamp=ts)
    else:
        # 单 panel 仍用原 render_svg（archive）或单 panel 模板
        if args.panels == "archive":
            svg = render_svg(panels_data.get("archive_trend", []), sha=sha, timestamp=ts)
        elif args.panels == "evals":
            svg = render_multipanel_svg(
                {"evals": panels_data.get("evals", [])}, sha=sha, timestamp=ts
            )
        elif args.panels == "chats":
            svg = render_multipanel_svg(
                {"chats": panels_data.get("chats", [])}, sha=sha, timestamp=ts
            )
        else:  # business (Day 25)
            svg = render_multipanel_svg(
                {"business": panels_data.get("business", [])}, sha=sha, timestamp=ts
            )

    target = Path(args.output) if args.output else DEFAULT_OUTPUT
    if not target.is_absolute():
        target = (ROOT / target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(svg, encoding="utf-8")
    try:
        rel = target.relative_to(ROOT)
    except ValueError:
        rel = target
    print(f"[ok] wrote {rel} (panels={args.panels})", file=sys.stderr)

    # Slack 上传（可选）
    if args.slack_token and args.slack_channel:
        rc = upload_to_slack(args.slack_token, args.slack_channel, target, args.title)
        print(f"[ok] slack upload: HTTP {rc}")
        if rc >= 400:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())