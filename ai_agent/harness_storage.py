"""
Eval Harness 持久化与用例加载。

- CaseLoader: 从 JSONL 读用例(支持 comments / 空行 / # 注释)
- Storage: 把 RunResult 写到 evals/runs/<run_id>/
  - summary.json   与既有 harness_pr*_local/ 结构兼容
  - cases.jsonl    每行一条 CaseResult(扁平,方便 grep/diff)
  - metrics.json   pass_rate / mean_score / p50 / p95 / 按 category 维度
  - report.md      自动生成的可贴 PR 报表
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from harness_runner import CaseResult, HarnessCase, RunResult

logger = logging.getLogger(__name__)


# ============================================================
# CaseLoader
# ============================================================

class CaseLoader:
    """从 JSONL 加载用例。支持 # 开头注释行与空行。"""

    @classmethod
    def load(cls, path: str | os.PathLike) -> List[HarnessCase]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"harness case file not found: {p}")
        cases: List[HarnessCase] = []
        seen_ids: set[str] = set()
        with p.open("r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f, 1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"{p}:{lineno} invalid JSON: {e}") from e
                if not isinstance(obj, dict) or "prompt" not in obj:
                    raise ValueError(f"{p}:{lineno} missing 'prompt' field")
                case = HarnessCase.from_dict(obj)
                if case.id in seen_ids:
                    raise ValueError(f"{p}:{lineno} duplicate case id '{case.id}'")
                seen_ids.add(case.id)
                cases.append(case)
        if not cases:
            raise ValueError(f"{p}: no valid cases loaded")
        logger.info("[harness] loaded %d cases from %s", len(cases), p)
        return cases

    @classmethod
    def load_dir(cls, dir_path: str | os.PathLike) -> List[HarnessCase]:
        """加载目录下所有 .jsonl 文件,顺序拼接。"""
        d = Path(dir_path)
        if not d.is_dir():
            raise NotADirectoryError(f"{d} is not a dir")
        all_cases: List[HarnessCase] = []
        for f in sorted(d.glob("*.jsonl")):
            all_cases.extend(cls.load(f))
        return all_cases


# ============================================================
# Storage
# ============================================================

class Storage:
    """把 RunResult 写到 evals/runs/<run_id>/。"""

    @classmethod
    def write(
        cls,
        result: RunResult,
        root: str | os.PathLike = "evals/runs",
        tag: str = "local",
    ) -> Path:
        """目录名格式:harness_<UTC时间戳>_<tag>(与既有 harness_pr*_local/ 风格接近)"""
        root_p = Path(root)
        # 用 result.run_id 去掉前缀 'harness_',避免目录名重复
        suffix = result.run_id[len("harness_"):] if result.run_id.startswith("harness_") else result.run_id
        dir_name = f"harness_{suffix}_{tag}"
        out_dir = root_p / dir_name
        out_dir.mkdir(parents=True, exist_ok=True)

        # 1) summary.json(兼容 evals/runs 既有结构)
        summary = {
            "run_id": result.run_id,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "cases_total": result.cases_total,
            "cases_passed": result.cases_passed,
            "cases_failed": result.cases_failed,
            "cases_errored": result.cases_errored,
            "cases": [cls._legacy_case(c) for c in result.cases],
        }
        (out_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 2) cases.jsonl(扁平,每行一条)
        with (out_dir / "cases.jsonl").open("w", encoding="utf-8") as f:
            for c in result.cases:
                f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")

        # 3) metrics.json
        metrics = {
            "run_id": result.run_id,
            "pass_rate": result.pass_rate,
            "mean_score": result.mean_score,
            "p50_latency_ms": result.p50_latency_ms,
            "p95_latency_ms": result.p95_latency_ms,
            "by_category": cls._by_category(result.cases),
            "set_path": result.set_path,
            "config": result.config,
        }
        (out_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 4) report.md
        (out_dir / "report.md").write_text(
            cls.render_report(result, metrics), encoding="utf-8",
        )

        logger.info("[harness] wrote run artifacts to %s", out_dir)
        return out_dir

    # ---- 兼容既有 evals/runs/<dir>/summary.json 字段 ----
    @staticmethod
    def _legacy_case(c: CaseResult) -> Dict[str, Any]:
        return {
            "name": c.case_id,                    # 兼容 harness_pr*_local/
            "category": c.category,
            "passed": c.passed,
            "duration_ms": float(c.observed.get("elapsed_ms", 0.0)),
            "detail": "ok" if c.passed else ("error" if c.error else "fail"),
            "score": c.score,
            "observed": {"final": c.observed.get("final", ""),
                         "elapsed_ms": c.observed.get("elapsed_ms", 0.0)},
            "error": c.error,
        }

    @staticmethod
    def _by_category(cases: List[CaseResult]) -> Dict[str, Dict[str, float]]:
        bucket: Dict[str, List[CaseResult]] = defaultdict(list)
        for c in cases:
            bucket[c.category].append(c)
        return {
            cat: {
                "total": float(len(cs)),
                "passed": float(sum(1 for x in cs if x.passed)),
                "pass_rate": (sum(1 for x in cs if x.passed) / len(cs)) if cs else 0.0,
                "mean_score": (sum(x.score for x in cs) / len(cs)) if cs else 0.0,
            }
            for cat, cs in bucket.items()
        }

    @staticmethod
    def render_report(result: RunResult, metrics: Dict[str, Any]) -> str:
        lines: List[str] = []
        lines.append(f"# Harness Report — `{result.run_id}`")
        lines.append("")
        lines.append(f"- Started:  `{result.started_at}`")
        lines.append(f"- Finished: `{result.finished_at}`")
        lines.append(f"- Set path: `{result.set_path}`")
        lines.append("")
        lines.append("## Overall")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---:|")
        lines.append(f"| Cases total | {result.cases_total} |")
        lines.append(f"| Cases passed | {result.cases_passed} |")
        lines.append(f"| Cases failed | {result.cases_failed} |")
        lines.append(f"| Cases errored | {result.cases_errored} |")
        lines.append(f"| Pass rate | {result.pass_rate:.2%} |")
        lines.append(f"| Mean score | {result.mean_score:.3f} |")
        lines.append(f"| P50 latency | {result.p50_latency_ms:.1f} ms |")
        lines.append(f"| P95 latency | {result.p95_latency_ms:.1f} ms |")
        lines.append("")
        if metrics.get("by_category"):
            lines.append("## By Category")
            lines.append("")
            lines.append("| Category | Total | Passed | Pass Rate | Mean Score |")
            lines.append("|---|---:|---:|---:|---:|")
            for cat, m in metrics["by_category"].items():
                lines.append(
                    f"| {cat} | {int(m['total'])} | {int(m['passed'])} | "
                    f"{m['pass_rate']:.2%} | {m['mean_score']:.3f} |"
                )
            lines.append("")
        lines.append("## Cases")
        lines.append("")
        lines.append("| ID | Category | Passed | Score | Latency (ms) | Error |")
        lines.append("|---|---|:-:|---:|---:|---|")
        for c in result.cases:
            err = (c.error or "")[:60].replace("|", "\\|") if c.error else ""
            lines.append(
                f"| {c.case_id} | {c.category} | "
                f"{'✅' if c.passed else '❌'} | {c.score:.3f} | "
                f"{c.observed.get('elapsed_ms', 0.0):.1f} | {err} |"
            )
        lines.append("")
        lines.append("---")
        lines.append(f"_Generated at {datetime.utcnow().isoformat(timespec='seconds')}Z_")
        return "\n".join(lines) + "\n"