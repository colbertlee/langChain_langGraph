"""
tests-archive/ 过夜验收（Day 17）。

每个 release 前跑一次，量化"还能跑"多少：

- 把 archive 目录当 rootdir 跑 ``pytest -m legacy --no-cov -q``
- 收集每个文件的 pass/fail/errored/skip 计数
- 生成 REPORT：``tests-archive/ACCEPTANCE.md`` + JSON
- 把结果接到 ``/api/evals/history`` 类似形态，存 ``tests-archive/acceptance/<ts>/``

用法::

    # 真的跑（每个文件大约 30s 总耗时，archive 里 33 文件 ≈ 几分钟）
    python tools/archive_acceptance.py

    # 仅扫描（不实际跑 pytest），看哪些该清理
    python tools/archive_acceptance.py --scan-only

    # 严格模式：任何 failure / errored → 非零退出
    python tools/archive_acceptance.py --strict

JSON 输出::

    {
      "started_at": "...",
      "finished_at": "...",
      "totals": {
        "files": 33,
        "passed": 18,
        "failed": 5,
        "errored": 8,
        "skipped": 2,
        "ran_ratio": "18/20"   # 仅统计能跑的（= passed + skipped）
      },
      "files": [
        {"file": "test_bug_fixes.py", "passed": 5, "failed": 0, "errored": 0, "skipped": 0, "status": "pass"}
      ]
    }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


ARCHIVE_DIR = ROOT / "tests-archive" / "tests"
ACCEPTANCE_DIR = ROOT / "tests-archive" / "acceptance"
REPORT_DOC = ROOT / "tests-archive" / "ACCEPTANCE.md"


@dataclass
class FileRun:
    file: str
    passed: int = 0
    failed: int = 0
    errored: int = 0
    skipped: int = 0
    status: str = "unknown"  # pass / partial / fail / error / no_tests

    @property
    def ran(self) -> int:
        return self.passed + self.failed + self.errored + self.skipped


@dataclass
class AcceptanceReport:
    started_at: str
    finished_at: str
    totals: Dict[str, Any] = field(default_factory=dict)
    files: List[FileRun] = field(default_factory=list)
    raw_pytest_log: str = ""


# ============================================================
# 跑 pytest（archive 模式）
# ============================================================

PYTEST_PATTERN = re.compile(
    r"(?P<file>[\w/.\-]+\.py)::[\w\[\]\-]+"
    r"(?:\s+(?P<status>PASS|FAIL|ERROR|SKIP))?",
    re.IGNORECASE,
)

SUMMARY_PATTERN = re.compile(
    r"(?P<n_passed>\d+) passed|\b(?P<n_failed>\d+) failed|\b(?P<n_error>\d+) error",
    re.IGNORECASE,
)

COLLECT_ERROR_PATTERN = re.compile(
    r"ERROR\s+(?P<file>[\w\-/\.]+?\.py)\s+collecting",
    re.IGNORECASE,
)


def run_pytest_on_archive(timeout: int = 120) -> str:
    """跑 ``pytest tests-archive/tests/ -m legacy`` 并返回原始输出。

    关键 flags：
    - ``--rootdir=tests-archive`` 让 pytest 不读 ``pyproject.toml`` 的 addopts
      （archive 自身 ``pytest.ini`` 起效）；
    - ``-p no:cacheprovider`` 跳过 cache（archive 文件 import 缓存会脏）；
    - ``-p no:asyncio`` 规避 pytest 9.x + Python 3.14 + asyncio 插件冲突；
    - ``--continue-on-collection-errors`` 让一个文件 import 错不影响其他；
    - ``AI_AGENT_RUN_LEGACY=1`` 让 archive conftest 把 legacy 标记显式打开。

    注意：pytest 9.x + Python 3.14 + pluggy 1.6 在大批量 collect 时可能整体
    ``SystemExit`` 而不出 PASS/FAIL 行。所以我们**逐文件**跑，便于统计。
    """
    files = sorted(ARCHIVE_DIR.glob("test_*.py"))
    aggregated: List[str] = []
    overall_timeout = timeout
    per_file_timeout = max(20, overall_timeout // max(1, len(files)))

    for f in files:
        cmd = [
            sys.executable,
            "-m", "pytest",
            f"tests-archive/tests/{f.name}",
            "-m", "legacy",
            "-v",
            "--tb=line",
            "--rootdir=tests-archive",
            "-p", "no:cacheprovider",
            "-p", "no:asyncio",
            "--continue-on-collection-errors",
        ]
        try:
            cp = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=per_file_timeout,
                cwd=str(ROOT),
                check=False,
                env={**os.environ, "AI_AGENT_RUN_LEGACY": "1"},
            )
            out = (cp.stdout or "") + (cp.stderr or "")
        except subprocess.TimeoutExpired:
            out = f"\n[{f.name}] TIMEOUT > {per_file_timeout}s\n"
        aggregated.append(f"\n=== {f.name} ===\n{out}")

    return "\n".join(aggregated)


def parse_pytest_output(out: str) -> List[FileRun]:
    """从 pytest -v 输出里抽每个文件 pass/fail/errored/skip 数。

    模式::

        tests/test_xxx.py::test_a PASSED
        tests/test_xxx.py::test_b FAILED
        tests/test_xxx.py::test_c ERROR
        tests/test_xxx.py::test_d SKIPPED
        ERROR tests/test_xxx.py collecting          ← collect 阶段失败

    用正则按文件聚合。
    """
    line_re = re.compile(
        r"(?P<file>[\w\-/\.]+?\.py)::[^\s]+(?:\s+(?P<status>PASSED|FAILED|ERROR|SKIPPED))?",
    )

    by_file: Dict[str, FileRun] = {}
    # 1. PASS/FAIL/ERROR/SKIPPED 行
    for m in line_re.finditer(out):
        file = m.group("file")
        status = m.group("status")
        if status is None:
            continue
        file = file.split("/")[-1]
        run = by_file.setdefault(file, FileRun(file=file))
        if status == "PASSED":
            run.passed += 1
        elif status == "FAILED":
            run.failed += 1
        elif status == "ERROR":
            run.errored += 1
        elif status == "SKIPPED":
            run.skipped += 1

    # 2. ERROR <file> collecting —— collect 阶段错
    for m in COLLECT_ERROR_PATTERN.finditer(out):
        file = m.group("file").split("/")[-1]
        run = by_file.setdefault(file, FileRun(file=file))
        run.errored += 1

    for r in by_file.values():
        if r.errored > 0:
            r.status = "error"
        elif r.failed > 0:
            r.status = "fail"
        elif r.passed == 0 and r.skipped == 0:
            r.status = "no_tests"
        elif r.passed > 0 and r.failed == 0 and r.errored == 0:
            r.status = "pass"
        else:
            r.status = "partial"
    return list(by_file.values())


# ============================================================
# 报告
# ============================================================

def render_report(rep: AcceptanceReport) -> str:
    lines: List[str] = []
    lines.append("# tests-archive/ 过夜验收报告\n\n")
    lines.append(f"> 起始：{rep.started_at}\n")
    lines.append(f"> 结束：{rep.finished_at}\n\n")

    totals = rep.totals
    lines.append("## 汇总\n\n")
    lines.append(f"- **文件数**：{totals.get('files', 0)}\n")
    lines.append(f"- **完全 pass**：{totals.get('passed', 0)}\n")
    lines.append(f"- **失败**：{totals.get('failed', 0)}\n")
    lines.append(f"- **异常**：{totals.get('errored', 0)}\n")
    lines.append(f"- **跳过**：{totals.get('skipped', 0)}\n")
    lines.append(f"- **可跑率**：**{totals.get('ran_ratio', '-')}** （pass + skipped vs 能跑的总数）\n\n")

    lines.append("## 文件明细\n\n")
    lines.append("| 文件 | passed | failed | errored | skipped | 状态 |\n")
    lines.append("|------|--------|--------|---------|---------|------|\n")
    for r in sorted(rep.files, key=lambda x: x.file):
        lines.append(
            f"| `{r.file}` | {r.passed} | {r.failed} | {r.errored} | {r.skipped} | "
            f"`{r.status}` |\n"
        )

    lines.append("\n## 处置建议\n\n")
    lines.append("- `pass` 状态文件 → 保留，按 release 节奏手动 review\n")
    lines.append("- `fail` / `error` 状态文件 → 下次 release 直接归档（迁出或删）\n")
    lines.append("- `no_tests` 文件 → 检查：可能用 Class 而非 test_ 命名\n")
    lines.append("- `partial` → 部分通过；可能要拆开\n")
    return "".join(lines)


def cmd_run(args: argparse.Namespace) -> int:
    started = datetime.now().isoformat(timespec="seconds")

    if args.scan_only:
        # 不真跑，只列文件
        rows: List[FileRun] = []
        for p in sorted(ARCHIVE_DIR.glob("test_*.py")):
            rows.append(FileRun(file=p.name, status="no_run"))
        finished = datetime.now().isoformat(timespec="seconds")
        rep = AcceptanceReport(
            started_at=started,
            finished_at=finished,
            totals={"files": len(rows), "passed": 0, "failed": 0,
                    "errored": 0, "skipped": 0, "ran_ratio": "0/0"},
            files=rows,
        )
        _save_report(rep, args.json_output)
        return 0

    print(f"[acceptance] running pytest on {ARCHIVE_DIR}", file=sys.stderr)
    out = run_pytest_on_archive(timeout=args.timeout)
    finished = datetime.now().isoformat(timespec="seconds")

    files = parse_pytest_output(out)
    if not files:
        # 没有任何 PASS/FAIL/ERROR/SKIP，可能 archive conftest 没生效
        # → 退回"全部未跑"
        for p in sorted(ARCHIVE_DIR.glob("test_*.py")):
            files.append(FileRun(file=p.name, status="no_tests"))

    totals: Dict[str, Any] = {
        "files": len(files),
        "passed": sum(1 for f in files if f.status == "pass"),
        "failed": sum(1 for f in files if f.failed > 0),
        "errored": sum(1 for f in files if f.errored > 0),
        "skipped": sum(f.skipped for f in files),
    }
    # 至少有一次实际运行的（pass / fail / error / skip）总数
    ran = sum(1 for f in files if f.ran > 0)
    if ran > 0:
        good = sum(1 for f in files if f.status == "pass")
        totals["ran_ratio"] = f"{good}/{ran}"
    else:
        totals["ran_ratio"] = "0/0"

    rep = AcceptanceReport(
        started_at=started,
        finished_at=finished,
        totals=totals,
        files=files,
        raw_pytest_log=out[-3000:],  # 最近 3KB
    )
    rc = _save_report(rep, args.json_output)

    if args.strict:
        bad = sum(1 for f in files if f.status in {"fail", "error"})
        if bad:
            return 1
    return rc


def _save_report(rep: AcceptanceReport, json_output: bool) -> int:
    """写到 tests-archive/ACCEPTANCE.md + acceptance/<ts>/json"""
    # 1. 主报告：Markdown
    md = render_report(rep)
    REPORT_DOC.write_text(md, encoding="utf-8")
    # 在 tmp_path 测试时 relative_to(ROOT) 会抛；用 try/except 兜底
    try:
        rel = REPORT_DOC.relative_to(ROOT)
    except ValueError:
        rel = REPORT_DOC
    print(f"[ok] wrote {rel}", file=sys.stderr)

    # 2. ts 目录：JSON
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sub = ACCEPTANCE_DIR / ts
    sub.mkdir(parents=True, exist_ok=True)
    json_path = sub / "summary.json"
    json_path.write_text(
        json.dumps(
            {
                "started_at": rep.started_at,
                "finished_at": rep.finished_at,
                "totals": rep.totals,
                "files": [asdict(f) for f in rep.files],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    # 3. raw log
    (sub / "pytest.log").write_text(rep.raw_pytest_log, encoding="utf-8")

    # 4. JSON 输出模式（CLI 用户友好）
    if json_output:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(json.dumps(
            {
                "started_at": rep.started_at,
                "finished_at": rep.finished_at,
                "totals": rep.totals,
                "files": [asdict(f) for f in rep.files],
            },
            ensure_ascii=False,
            indent=2,
        ))

    print(
        f"[summary] {rep.totals.get('passed', 0)} pass / {rep.totals.get('failed', 0)} fail / "
        f"{rep.totals.get('errored', 0)} error ;  ran_ratio={rep.totals.get('ran_ratio', '?')}",
        file=sys.stderr,
    )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="archive_acceptance",
        description="tests-archive/ 过夜验收（量化可跑率）",
    )
    parser.add_argument("--scan-only", action="store_true", help="只列文件不跑")
    parser.add_argument("--strict", action="store_true", help="任意 fail/error → 退出 1")
    parser.add_argument("--json", dest="json_output", action="store_true", help="JSON 输出到 stdout")
    parser.add_argument("--timeout", type=int, default=120, help="pytest timeout (秒)")
    args = parser.parse_args(argv)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())