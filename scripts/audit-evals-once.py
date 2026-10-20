"""Step A audit-evals：扫 ai_agent/evals/runs/**/summary.json，统计失败占比与趋势。"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"e:\langChain_langGraph")
OUT = REPO / "output" / "2026-10-20" / "audit-evals.md"
RUNS = REPO / "ai_agent" / "evals" / "runs"

NOW = datetime.now(timezone.utc)

buckets = {"ok": 0, "fail": 0, "other": 0}
per_run: list[tuple[str, str, str]] = []  # (run_id, status, mtime)
all_files = 0
fail_reasons: Counter[str] = Counter()
monthly: Counter[str] = Counter()
monthly_fail: Counter[str] = Counter()

if RUNS.exists():
    for run_dir in sorted(RUNS.iterdir()):
        if not run_dir.is_dir():
            continue
        summary = run_dir / "summary.json"
        if not summary.exists():
            continue
        all_files += 1
        try:
            data = json.loads(summary.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            per_run.append((run_dir.name, "parse_error", ""))
            buckets["other"] += 1
            continue
        status = str(data.get("status") or data.get("state") or "unknown").lower()
        if status not in {"ok", "fail", "passed", "failed"}:
            status = "unknown"
        if status in {"ok", "passed"}:
            buckets["ok"] += 1
        elif status in {"fail", "failed"}:
            buckets["fail"] += 1
        else:
            buckets["other"] += 1
        # 失败原因抽取（容错：字段名未知时不强求）
        for key in ("fail_reason", "error", "reason"):
            v = data.get(key)
            if isinstance(v, str) and v:
                fail_reasons[v[:80]] += 1
        mtime = datetime.fromtimestamp(summary.stat().st_mtime, tz=timezone.utc)
        month = mtime.strftime("%Y-%m")
        monthly[month] += 1
        if status in {"fail", "failed"}:
            monthly_fail[month] += 1
        per_run.append((run_dir.name, status, mtime.strftime("%Y-%m-%d")))

# 30 天趋势（基于 mtime）
recent_total = sum(1 for _, _, mt in per_run if mt and (NOW - datetime.strptime(mt + "T00:00:00+00:00", "%Y-%m-%dT%H:%M:%S%z")).days <= 30)
recent_fail = 0
for _, status, mt in per_run:
    if status in {"fail", "failed"} and mt:
        d = datetime.strptime(mt + "T00:00:00+00:00", "%Y-%m-%dT%H:%M:%S%z")
        if (NOW - d).days <= 30:
            recent_fail += 1

lines: list[str] = []
lines.append("# audit-evals")
lines.append("---")
lines.append(f"scope: ai_agent/evals/runs/**/summary.json")
lines.append(f"runs_scanned: {all_files}")
lines.append("")
lines.append("## 失败占比")
lines.append("")
total_classified = buckets["ok"] + buckets["fail"]
lines.append("| status | count | pct |")
lines.append("| --- | ---: | ---: |")
if total_classified:
    lines.append(f"| ok | {buckets['ok']} | {buckets['ok']/total_classified:.1%} |")
    lines.append(f"| fail | {buckets['fail']} | {buckets['fail']/total_classified:.1%} |")
else:
    lines.append("| ok | 0 | n/a |")
    lines.append("| fail | 0 | n/a |")
lines.append(f"| other/parse_error | {buckets['other']} | - |")
lines.append("")
lines.append("## 近 30 天")
lines.append("")
lines.append(f"- 近 30 天有 mtime 的 run 数: {recent_total}")
lines.append(f"- 其中失败: {recent_fail}")
if recent_total:
    lines.append(f"- 失败率: {recent_fail/recent_total:.1%}")
lines.append("")
lines.append("## 月度趋势（按 mtime）")
lines.append("")
lines.append("| month | total | fail |")
lines.append("| --- | ---: | ---: |")
for m in sorted(monthly.keys()):
    lines.append(f"| {m} | {monthly[m]} | {monthly_fail[m]} |")
lines.append("")
lines.append("## 失败原因 Top-10（按字段名 fail_reason/error/reason 抓）")
lines.append("")
if fail_reasons:
    for reason, n in fail_reasons.most_common(10):
        lines.append(f"- ({n}) `{reason}`")
else:
    lines.append("- （字段未提取到，原因结构未知；不影响占比统计）")
lines.append("")
lines.append("## RAG 回归风险面（按 run 名前缀归类）")
lines.append("")
buckets_prefix: Counter[str] = Counter()
buckets_prefix_fail: Counter[str] = Counter()
for run_id, status, _ in per_run:
    m = re.match(r"([a-z0-9_]+?)_", run_id)
    prefix = m.group(1) if m else run_id
    buckets_prefix[prefix] += 1
    if status in {"fail", "failed"}:
        buckets_prefix_fail[prefix] += 1
lines.append("| prefix | total | fail | fail_rate |")
lines.append("| --- | ---: | ---: | ---: |")
for prefix, n in buckets_prefix.most_common():
    fr = buckets_prefix_fail[prefix]
    rate = fr / n if n else 0
    lines.append(f"| `{prefix}` | {n} | {fr} | {rate:.0%} |")
lines.append("")
lines.append("_摸排口径：`summary.json.status` 字段；若不存在则记 `unknown`；30 天窗口以文件 mtime 落点。_")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {OUT} bytes={OUT.stat().st_size}")
