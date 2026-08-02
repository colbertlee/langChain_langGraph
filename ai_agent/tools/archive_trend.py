"""
archive 量化趋势（Day 18）。

把 ``tests-archive/acceptance/<ts>/summary.json`` 视为历史时间序列：
- 每次跑 archive_acceptance 都留一份；
- 本工具读取最后 N 份 → 渲染 Markdown 趋势表 + 跨次 diff；
- CI 跑完后用本工具出一份"趋势报告"，与上次的对比写到 ``TREND.md``；
- 推 ``git commit tests-archive/acceptance/<ts>/summary.json`` 让趋势"沉淀"。

用法::

    # 默认读最近 10 份
    python tools/archive_trend.py

    # 指定对比"上一份"
    python tools/archive_trend.py --diff

    # 仅渲染趋势
    python tools/archive_trend.py --render --output tests-archive/TREND.md

    # Git push CI 用（返回非零 if 退步）
    python tools/archive_trend.py --strict
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


ACCEPTANCE_DIR = ROOT / "tests-archive" / "acceptance"
TREND_DOC = ROOT / "tests-archive" / "TREND.md"


# ============================================================
# 历史读取
# ============================================================

def _read_summary(p: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads((p / "summary.json").read_text(encoding="utf-8"))
        return data
    except Exception:
        return None


def list_runs(limit: int = 10) -> List[Tuple[Path, Dict[str, Any]]]:
    """按 ts 倒序读最近 N 份。"""
    if not ACCEPTANCE_DIR.exists():
        return []
    out: List[Tuple[Path, Dict[str, Any]]] = []
    for d in sorted(ACCEPTANCE_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        s = _read_summary(d)
        if s is None:
            continue
        out.append((d, s))
        if len(out) >= limit:
            break
    return out


# ============================================================
# diff 渲染
# ============================================================

def diff_summary(
    old: Dict[str, Any], new: Dict[str, Any]
) -> Dict[str, Dict[str, int]]:
    """计算两个 summary 的字段差异。"""
    out: Dict[str, Dict[str, int]] = {}
    old_t = old.get("totals", {})
    new_t = new.get("totals", {})
    keys = {"passed", "failed", "errored", "skipped"}
    for k in keys:
        out[k] = {"old": old_t.get(k, 0), "new": new_t.get(k, 0), "delta": new_t.get(k, 0) - old_t.get(k, 0)}

    # ran_ratio string
    out["ran_ratio"] = {
        "old_str": old_t.get("ran_ratio", "?"),
        "new_str": new_t.get("ran_ratio", "?"),
    }
    return out


def render_trend(runs: List[Tuple[Path, Dict[str, Any]]]) -> str:
    """渲染 Markdown 趋势表。"""
    lines: List[str] = []
    lines.append("# tests-archive/ 验收趋势\n\n")
    lines.append(f"> 报告时间：{datetime.now().isoformat(timespec='seconds')}\n")
    lines.append(f"> 抽样数：{len(runs)}（最近 {len(runs)} 次跑）\n\n")

    lines.append("## 历史趋势\n\n")
    lines.append("| 时间 | files | passed | failed | errored | skipped | ran_ratio |\n")
    lines.append("|------|------:|-------:|-------:|--------:|--------:|-----------|\n")
    # 倒序变正序展示（oldest → newest）
    for d, s in reversed(runs):
        ts = d.name
        t = s.get("totals", {})
        lines.append(
            f"| {ts} | {t.get('files', 0)} | {t.get('passed', 0)} | "
            f"{t.get('failed', 0)} | {t.get('errored', 0)} | "
            f"{t.get('skipped', 0)} | `{t.get('ran_ratio', '?')}` |\n"
        )

    if len(runs) >= 2:
        lines.append("\n## 最近一次 vs 上一次\n\n")
        latest = runs[0][1]
        prev = runs[1][1]
        d = diff_summary(prev, latest)

        for k in ("passed", "failed", "errored", "skipped"):
            delta = d[k]["delta"]
            arrow = "🟢" if (k == "passed" and delta > 0) or (k in {"failed", "errored"} and delta < 0) else \
                    "🔴" if (k == "passed" and delta < 0) or (k in {"failed", "errored"} and delta > 0) else \
                    "⚪"
            lines.append(
                f"- {arrow} **{k}**: {d[k]['old']} → {d[k]['new']} "
                f"({'+' if delta > 0 else ''}{delta})\n"
            )

        lines.append(
            f"- ran_ratio: `{d['ran_ratio']['old_str']}` → `{d['ran_ratio']['new_str']}`\n"
        )
    else:
        lines.append("\n## 最近一次 vs 上一次\n\n_需要至少 2 次跑才能对比。_\n")

    return "".join(lines)


# ============================================================
# CLI
# ============================================================

def cmd_render(args: argparse.Namespace) -> int:
    runs = list_runs(limit=args.limit)
    if not runs:
        print("[warn] no acceptance runs yet", file=sys.stderr)
        return 0
    md = render_trend(runs)
    if args.output:
        target = Path(args.output)
        if not target.is_absolute():
            target = (ROOT / target).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(md, encoding="utf-8")
        try:
            rel = target.relative_to(ROOT)
        except ValueError:
            rel = target
        print(f"[ok] wrote {rel}", file=sys.stderr)
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(md)
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """--strict：当 ran_ratio 下降 → 非零退出。"""
    runs = list_runs(limit=2)
    if len(runs) < 2:
        print("[warn] need >= 2 runs for --diff", file=sys.stderr)
        return 0
    diff = diff_summary(runs[1][1], runs[0][1])
    passed_delta = diff["passed"]["delta"]
    failed_delta = diff["failed"]["delta"]
    errored_delta = diff["errored"]["delta"]

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(
        json.dumps(
            {
                "passed_delta": passed_delta,
                "failed_delta": failed_delta,
                "errored_delta": errored_delta,
                "old_ratio": diff["ran_ratio"]["old_str"],
                "new_ratio": diff["ran_ratio"]["new_str"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.strict:
        # 退步：passed 下降 或 failed/errored 上升
        if passed_delta < 0 or failed_delta > 0 or errored_delta > 0:
            print("[FAIL] archive acceptance regression", file=sys.stderr)
            return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="archive_trend",
        description="archive acceptance 趋势分析（Day 18）",
    )
    parser.add_argument("--limit", type=int, default=10, help="最近 N 次跑")
    parser.add_argument("--output", help="写到文件（默认 stdout）")
    parser.add_argument("--diff", action="store_true", help="JSON diff（最近 vs 上次）")
    parser.add_argument("--strict", action="store_true", help="退步 → 退出 1")
    args = parser.parse_args(argv)

    if args.diff:
        return cmd_diff(args)
    return cmd_render(args)


if __name__ == "__main__":
    sys.exit(main())