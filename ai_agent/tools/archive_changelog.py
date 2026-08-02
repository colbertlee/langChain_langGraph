"""
archive 跑完自动追加一行 changelog（Day 19）。

每次跑 archive_acceptance 后，调用本工具：
1. 读最新一份 summary；
2. 把一行 ``## YYYY-MM-DD HH:MM ran_ratio X/Y (passed P, failed F, errored E)``
   追加到 ``tests-archive/CHANGELOG.md``；
3. 提供 ``--prune`` 删除超过 90 天的旧行（可让 CHANGELOG.md 不无限增长）。

CI 接入
~~~~~~~

``release-build.yml`` archive-acceptance job 的最后一步::

    python tools/archive_changelog.py --prune-days 90

Wiring
~~~~~~

通过 ``archive_acceptance.py`` 末尾追加调用最简单：

.. code-block:: python

    # in archive_acceptance.py after _save_report:
    from tools.archive_changelog import append_changelog_line
    append_changelog_line()

用法::

    python tools/archive_changelog.py
    python tools/archive_changelog.py --prune-days 90
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


ACCEPTANCE_DIR = ROOT / "tests-archive" / "acceptance"
CHANGELOG = ROOT / "tests-archive" / "CHANGELOG.md"


def _read_latest_summary() -> Optional[dict]:
    """读最近一次 *有真实结果* 的 acceptance summary（与 archive_legacy 同款）。"""
    if not ACCEPTANCE_DIR.exists():
        return None
    runs = sorted(
        [d for d in ACCEPTANCE_DIR.iterdir() if d.is_dir()], reverse=True
    )
    import json
    for d in runs:
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
        return data
    return None


def _read_two_latest_summaries() -> tuple[Optional[dict], Optional[dict]]:
    """读最近两次有真实结果的 summary：``(latest, prev)``。

    任一不存在时返回 ``None``。
    """
    if not ACCEPTANCE_DIR.exists():
        return None, None
    runs = sorted(
        [d for d in ACCEPTANCE_DIR.iterdir() if d.is_dir()], reverse=True
    )
    import json
    picked: list[dict] = []
    for d in runs:
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
        picked.append(data)
        if len(picked) == 2:
            break
    if len(picked) == 2:
        return picked[0], picked[1]
    if len(picked) == 1:
        return picked[0], None
    return None, None


def _regression_emoji(
    latest: dict,
    prev: Optional[dict],
    *,
    threshold_pct: float = 5.0,
    err_min_abs: int = 1,
) -> str:
    """对比 latest vs prev，返回退化 emoji 串。

    Day 21：阈值过滤（避免小幅抖动触发 emoji）。

    规则：
    - passed_delta < 0 且 ``|p_delta| / prev_passed * 100 >= threshold_pct``
      → ⚠️
    - failed_delta > 0 且 ``f_delta / prev_failed * 100 >= threshold_pct``
      → 🚨
    - errored_delta >= err_min_abs（绝对值门槛，因为 prev 可能为 0）→ 🚨
    - 都无退化 → 🟢

    返回："⚠️ " 或 "🚨🚨 " 或 "🟢 "（emoji 后带一个空格）。
    """
    if prev is None:
        return ""

    lt = latest.get("totals", {})
    pt = prev.get("totals", {})

    p_delta = lt.get("passed", 0) - pt.get("passed", 0)
    f_delta = lt.get("failed", 0) - pt.get("failed", 0)
    e_delta = lt.get("errored", 0) - pt.get("errored", 0)

    # 计算变化比例（百分比）；prev 字段为 0 时用 1 避免除零
    p_pct = abs(p_delta) / max(pt.get("passed", 0), 1) * 100
    f_pct = abs(f_delta) / max(pt.get("failed", 0), 1) * 100

    flags: List[str] = []
    if p_delta < 0 and p_pct >= threshold_pct:
        flags.append("⚠️")
    if f_delta > 0 and f_pct >= threshold_pct:
        flags.append("🚨")
    if e_delta >= err_min_abs:
        flags.append("🚨")

    if not flags:
        return "🟢 "

    return "".join(flags) + " "


def build_line(
    summary: dict,
    prev: Optional[dict] = None,
    *,
    threshold_pct: float = 5.0,
    err_min_abs: int = 1,
) -> str:
    """生成一行 changelog 内容。

    Day 20：若 prev 不为 None，自动加 emoji 退化信号。
    Day 21：阈值过滤（``threshold_pct``）—— 小幅抖动不报警。
    """
    ts_dir = summary.get("started_at", datetime.now().isoformat(timespec="seconds"))
    try:
        d = datetime.fromisoformat(ts_dir)
        date_label = d.strftime("%Y-%m-%d %H:%M")
    except Exception:
        date_label = ts_dir

    t = summary.get("totals", {})

    # 退化信号
    if prev is not None:
        emoji = _regression_emoji(
            summary, prev, threshold_pct=threshold_pct, err_min_abs=err_min_abs
        )
    else:
        emoji = ""

    return (
        f"- {emoji}**{date_label}** "
        f"`ran_ratio {t.get('ran_ratio', '?')}`  "
        f"passed {t.get('passed', 0)}, "
        f"failed {t.get('failed', 0)}, "
        f"errored {t.get('errored', 0)}, "
        f"skipped {t.get('skipped', 0)}"
    )


def append_changelog_line(
    prune_days: int = 0,
    *,
    threshold_pct: float = 5.0,
    err_min_abs: int = 1,
) -> int:
    """追加一行；可选 prune 旧行。

    Day 20：自动对比"上次 summary"加 emoji 退化信号。
    Day 21：阈值过滤（默认 ≥5% 才报警）。
    """
    latest, prev = _read_two_latest_summaries()
    if not latest:
        print("[warn] no acceptance summary yet", file=sys.stderr)
        return 1

    line = build_line(
        latest,
        prev=prev,
        threshold_pct=threshold_pct,
        err_min_abs=err_min_abs,
    )

    # 文件不存在时创建 header
    if not CHANGELOG.exists():
        CHANGELOG.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "# tests-archive/ Changelog\n\n"
            "> 每次 `archive_acceptance.py` 跑完追加一行。\n"
            "> 字段：时间 / ran_ratio / 各计数。\n\n"
            "## 历次跑\n\n"
        )
        CHANGELOG.write_text(header, encoding="utf-8")

    # 读取 + 追加
    text = CHANGELOG.read_text(encoding="utf-8")

    # 简单去重：已有同一时间戳 → 跳过
    if line in text:
        print(f"[skip] line already present: {line!r}")
        return 0

    new_text = text.rstrip() + "\n" + line + "\n"

    # 可选 prune
    if prune_days > 0:
        cutoff = datetime.now().timestamp() - prune_days * 86400
        lines = new_text.splitlines()
        kept: list[str] = []
        for ln in lines:
            # 只 prune changelog 行：``- **YYYY-MM-DD HH:MM** ...``
            if ln.startswith("- **"):
                try:
                    # 形如 ``- **2026-07-26 17:38** `ran_ratio...``
                    inside = ln.split("**", 2)[1]  # "2026-07-26 17:38"
                    date_str = inside.split(" ")[0]  # "2026-07-26"
                    dt = datetime.fromisoformat(date_str)
                    if dt.timestamp() < cutoff:
                        continue
                except (IndexError, ValueError):
                    pass
            kept.append(ln)
        new_text = "\n".join(kept) + "\n"

    CHANGELOG.write_text(new_text, encoding="utf-8")
    try:
        rel = CHANGELOG.relative_to(ROOT)
    except ValueError:
        rel = CHANGELOG
    print(f"[ok] appended to {rel}: {line}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="archive_changelog",
        description="archive acceptance changelog 追加器（Day 19/20/21）",
    )
    parser.add_argument(
        "--prune-days",
        type=int,
        default=0,
        help="删除超过 N 天的行（默认 0 = 不 prune）",
    )
    parser.add_argument(
        "--threshold-pct",
        type=float,
        default=5.0,
        help="退化阈值（默认 5.0%%，passed/failed 变化比例低于此不报警）",
    )
    parser.add_argument(
        "--err-min-abs",
        type=int,
        default=1,
        help="errored 绝对值门槛（默认 1，因 prev 经常为 0）",
    )
    args = parser.parse_args(argv)
    return append_changelog_line(
        prune_days=args.prune_days,
        threshold_pct=args.threshold_pct,
        err_min_abs=args.err_min_abs,
    )


if __name__ == "__main__":
    sys.exit(main())