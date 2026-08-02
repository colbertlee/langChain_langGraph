"""evals/runner.py — 评测执行与报告（Day 13-14）。

子命令
~~~~~~

- ``run``：执行一份用例集，写入 ``runs/<ts>/`` 目录
- ``history``：列出最近 N 次跑的概要
- ``diff <prev> <curr>``：对比两次结果

调用方式
~~~~~~~~

::

    python -m evals.runner run --case intent_routing
    python -m evals.runner run --all
    python -m evals.runner history

未来扩展
~~~~~~~~

- 接入 deep eval / langfuse：实现 ``EvalRegistry.register("llm_qa", runner_fn)``
- 增量跑：对比 ``runs/<prev>/summary.json`` only diff'd cases
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# 让 evals/ 内的脚本能 import ai_agent/*
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))


CASES_DIR = _HERE / "cases"
RUNS_DIR = _HERE / "runs"


# ============================================================
# 数据结构
# ============================================================

@dataclass
class RunSummary:
    started_at: str
    finished_at: str
    cases_total: int
    cases_passed: int
    cases_failed: int
    cases_errored: int
    cases: List[CaseResult] = field(default_factory=list)


# ============================================================
# Runner Registry
# ============================================================

# Day 13-14：CaseResult 放到独立模块，builtin_runners 不必 import runner.py
from evals.registry import EvalRegistry, CaseResult  # noqa: E402, F401


# ============================================================
# 实用工具
# ============================================================

def _load_cases(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """读取 ``cases/<name>.json``，返回统一格式的列表。

    过滤策略：传 ``category`` 时：
    - 先按文件名 stem 全匹配（如 ``safety_detection``）；
    - 若全文件名不匹配，再按 ``case["category"]`` 字段过滤（支持 "safety" 匹配 "safety_detection"）；
    """
    if not CASES_DIR.exists():
        return []
    out: List[Dict[str, Any]] = []
    for path in sorted(CASES_DIR.glob("*.json")):
        stem = path.stem
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[WARN] {path} JSON 不合法: {e}", file=sys.stderr)
            continue
        if not isinstance(data, list):
            continue
        for c in data:
            if not isinstance(c, dict):
                continue
            if "category" not in c:
                c["category"] = stem
            # 分类过滤：stem 完全匹配，或 category 字段等于 target，或 target 是 stem 的前缀
            if category is not None:
                if stem != category and c["category"] != category:
                    # 兼容："safety" 这种短名匹配 "safety_detection"
                    if not (
                        stem.startswith(category + "_")
                        or stem.startswith(category + "-")
                    ):
                        continue
            out.append(c)
    return out


def _now_dir() -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    p = RUNS_DIR / ts
    p.mkdir(parents=False, exist_ok=False)
    return p


def _ensure_builtin_runners() -> None:
    """确保 ``EvalRegistry`` 已注册内置 runner。

    ``python -m evals.runner`` 这种模式下 ``evals/__init__.py`` 副作用可能
    未触发（runpy 提前 import 包但不执行），所以这里兜底。
    """
    # idempotent：已注册就返回
    if EvalRegistry.all_categories():
        return

    # 直接 import 一次。这是标准做法：
    # 在正常的 pytest / `from evals import builtin_runners` 调用下，模块体
    # 会执行并通过 @EvalRegistry.register() 完成注册。
    try:
        from evals import builtin_runners  # noqa: F401
    except ImportError:
        return

    if EvalRegistry.all_categories():
        return

    # 仍空？说明 builtin_runners 在某个时刻被 reload 或新进程里没执行 module body。
    # 最后兜底：手动注册三个内置（与 builtin_runners.py 中装饰器等价）。
    import importlib
    mod = importlib.import_module("evals.builtin_runners")
    # 强制 reload 模块体（装饰器再次执行，幂等覆盖原注册）
    importlib.reload(mod)


def _write_summary(d: Path, summary: RunSummary) -> None:
    (d / "summary.json").write_text(
        json.dumps(asdict(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_cases_jsonl(d: Path, summary: RunSummary) -> None:
    lines = [json.dumps(asdict(c), ensure_ascii=False) for c in summary.cases]
    (d / "cases.jsonl").write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# Run sub-command
# ============================================================

def _execute_case(case: Dict[str, Any]) -> CaseResult:
    """dispatch 一条 case 到对应 runner runner；内部异常转成失败 result。"""
    name = str(case.get("name", "unknown"))
    category = str(case.get("category", "unknown"))
    # 兜底：再触发一次注册（防止 -m 调用时 __init__.py 的副作用未生效）
    _ensure_builtin_runners()
    runner = EvalRegistry.get(category)
    if runner is None:
        return CaseResult(
            name=name,
            category=category,
            passed=False,
            duration_ms=0.0,
            detail=f"no runner registered for category={category!r}",
        )
    t0 = time.monotonic()
    try:
        result = runner(case)
    except Exception as e:
        return CaseResult(
            name=name,
            category=category,
            passed=False,
            duration_ms=(time.monotonic() - t0) * 1000,
            detail=f"runner raised: {e}",
            observed={"trace": traceback.format_exc(limit=3)},
        )
    result.duration_ms = (time.monotonic() - t0) * 1000
    return result


def cmd_run(args: argparse.Namespace) -> int:
    # 注册内置 runner（idempotent：重复 import 不会重复注册）
    _ensure_builtin_runners()
    if args.all:
        cases = _load_cases()
    elif args.case:
        cases = _load_cases(args.case)
        if not cases:
            print(f"[ERROR] 找不到分类: {args.case}", file=sys.stderr)
            return 1
    else:
        print("传 --case <name> 或 --all", file=sys.stderr)
        return 2

    run_dir = _now_dir()
    started = datetime.now().isoformat(timespec="seconds")
    print(f"[evals] run dir: {run_dir}")
    summary = RunSummary(
        started_at=started,
        finished_at="",
        cases_total=len(cases),
        cases_passed=0,
        cases_failed=0,
        cases_errored=0,
    )

    for c in cases:
        result = _execute_case(c)
        summary.cases.append(result)
        if result.passed:
            summary.cases_passed += 1
            marker = "[OK]"
        else:
            summary.cases_failed += 1
            marker = "[FAIL]"
        print(
            f"  {marker:6s} {result.category:18s} {result.name:32s} "
            f"{result.duration_ms:7.1f}ms  {result.detail}"
        )

    summary.finished_at = datetime.now().isoformat(timespec="seconds")
    _write_summary(run_dir, summary)
    _write_cases_jsonl(run_dir, summary)

    print()
    print(
        f"[evals] {summary.cases_passed}/{summary.cases_total} passed "
        f"({summary.cases_errored} errored)"
    )
    # 失败用例：退出 1（CI 友好）
    return 0 if summary.cases_failed == 0 else 1


def cmd_history(args: argparse.Namespace) -> int:
    if not RUNS_DIR.exists():
        print("尚无历史")
        return 0
    runs = sorted([d for d in RUNS_DIR.iterdir() if d.is_dir()], reverse=True)
    limit = args.limit or 10
    for r in runs[:limit]:
        s = r / "summary.json"
        if not s.exists():
            continue
        try:
            data = json.loads(s.read_text(encoding="utf-8"))
            total = data.get("cases_total", 0)
            passed = data.get("cases_passed", 0)
            failed = data.get("cases_failed", 0)
        except Exception:
            total = passed = failed = 0
        print(f"  {r.name}  {passed}/{total} passed, {failed} failed")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    a = RUNS_DIR / args.prev / "summary.json"
    b = RUNS_DIR / args.curr / "summary.json"
    if not a.exists() or not b.exists():
        print(f"[ERROR] 缺少 summary: {args.prev} 或 {args.curr}", file=sys.stderr)
        return 1
    ja = json.loads(a.read_text(encoding="utf-8"))
    jb = json.loads(b.read_text(encoding="utf-8"))
    a_pass = {c["name"] for c in ja["cases"] if c["passed"]}
    b_pass = {c["name"] for c in jb["cases"] if c["passed"]}
    only_a = a_pass - b_pass
    only_b = b_pass - a_pass
    print(f"[diff] 之前通过 {len(a_pass)}；现在通过 {len(b_pass)}")
    if only_a:
        print(f"[diff] 回归（之前通过，现在失败）: {sorted(only_a)}")
    if only_b:
        print(f"[diff] 修复（之前失败，现在通过）: {sorted(only_b)}")
    return 0


# ============================================================
# CLI 入口
# ============================================================

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.runner", description="AI Agent 评测运行器")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="跑一份用例集")
    p_run.add_argument("--case", help="单个 case 分类名")
    p_run.add_argument("--all", action="store_true", help="跑全部分类")
    p_run.set_defaults(func=cmd_run)

    p_hist = sub.add_parser("history", help="查看历史")
    p_hist.add_argument("--limit", type=int, help="最近 N 次")
    p_hist.set_defaults(func=cmd_history)

    p_diff = sub.add_parser("diff", help="对比两次跑结果")
    p_diff.add_argument("prev")
    p_diff.add_argument("curr")
    p_diff.set_defaults(func=cmd_diff)

    # 默认注册内置 runner（避免循环 import）
    from evals import builtin_runners  # noqa: F401
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
