"""ai-agent-harness CLI 入口。

用法示例:
    ai-agent-harness --set evals/sets/smoke_v1.jsonl
    ai-agent-harness --set evals/sets/smoke_v1.jsonl --threshold 0.8 --tag ci
    ai-agent-harness --set-dir evals/sets/ --dry-run --threshold 0.5

设计目标:
- 与 ai_agent/cli.py 风格一致(简单 argparse,无强依赖)
- 失败/未达阈值返回非零退出码,可被 CI 直接判定
- --dry-run 只跑流程、不调 Agent,用于 CI 缓存命中后的快速校验
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# 让 ai_agent/ 下的 sibling 模块可导入
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


# 评分器在 import harness_runner 时已自动注册
from harness_runner import HarnessConfig, HarnessRunner, ScorerRegistry  # noqa: E402
from harness_storage import CaseLoader, Storage  # noqa: E402

logging.basicConfig(
    level=os.getenv("HARNESS_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("harness.cli")


def _load_agent():
    """延迟加载 AIAgent,失败时给清晰错误。"""
    try:
        from agent import AIAgent  # type: ignore
    except ImportError as e:
        print(f"[harness] FATAL: cannot import AIAgent: {e}", file=sys.stderr)
        print("[harness] hint: run from project root with PYTHONPATH including ai_agent/",
              file=sys.stderr)
        sys.exit(2)
    try:
        return AIAgent()
    except Exception as e:  # noqa: BLE001
        print(f"[harness] FATAL: failed to construct AIAgent: {e}", file=sys.stderr)
        sys.exit(2)


def _run_dry(cases, cfg: HarnessConfig) -> "Any":
    """dry-run:不打分不调 Agent,只把 set 跑成全部通过(用于 CI 缓存后快速判定)。"""
    from harness_runner import CaseResult, RunResult, SubScore
    from datetime import datetime
    now = datetime.utcnow().isoformat(timespec="seconds")
    results = []
    for c in cases:
        sub = SubScore("keyword", 1.0, {"dry_run": True})
        results.append(CaseResult(
            case_id=c.id, category=c.category, passed=True,
            score=1.0, sub_scores={"keyword": sub},
            observed={"final": "[dry-run]", "elapsed_ms": 0.0},
            error=None,
        ))
    return RunResult(
        run_id="harness_dry_" + now.replace(":", "").replace("-", ""),
        started_at=now, finished_at=now,
        cases_total=len(results), cases_passed=len(results),
        cases_failed=0, cases_errored=0,
        pass_rate=1.0, mean_score=1.0,
        p50_latency_ms=0.0, p95_latency_ms=0.0,
        set_path="(dry-run)", config={"dry_run": True},
        cases=results,
    )


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="ai-agent-harness",
        description="Run Eval Harness against AIAgent.",
    )
    p.add_argument("--list-scorers", action="store_true",
                   help="打印可用评分器并退出")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--set", help="JSONL 用例集文件路径")
    src.add_argument("--set-dir", help="用例集目录,合并所有 .jsonl")
    p.add_argument("--out", default="evals/runs", help="结果输出根目录")
    p.add_argument("--tag", default="local", help="运行标签(进入目录名)")
    p.add_argument("--threshold", type=float, default=0.6, help="pass_rate 阈值")
    p.add_argument("--scorer-weights", default=None,
                   help='JSON 字符串,例如 \'{"keyword":1,"embed":2}\'')
    p.add_argument("--extra-tags", default=None,
                   help='JSON 字符串,例如 \'{"commit":"abc123"}\'')
    p.add_argument("--dry-run", action="store_true",
                   help="不调 Agent,只校验用例集与默认通过")
    args = p.parse_args(argv)

    if args.list_scorers:
        print(json.dumps({"scorers": ScorerRegistry.names()}, ensure_ascii=False, indent=2))
        return 0

    if not (args.set or args.set_dir):
        p.error("one of the arguments --set --set-dir is required (除非使用 --list-scorers)")

    # 1) 加载用例集
    try:
        if args.set:
            cases = CaseLoader.load(args.set)
            set_path = str(args.set)
        else:
            cases = CaseLoader.load_dir(args.set_dir)
            set_path = str(args.set_dir)
    except (FileNotFoundError, NotADirectoryError, ValueError) as e:
        # FileNotFoundError: 路径不存在
        # NotADirectoryError: --set-dir 给的是文件
        # ValueError: 用例集为空 / 缺 prompt / id 重复
        print(f"[harness] FATAL: {e}", file=sys.stderr)
        return 2
    print(f"[harness] loaded {len(cases)} cases from {set_path}")

    # 2) 构造 config
    cfg = HarnessConfig(pass_threshold=args.threshold)
    if args.scorer_weights:
        try:
            cfg.aggregate_weights = json.loads(args.scorer_weights)
        except json.JSONDecodeError as e:
            print(f"[harness] FATAL: --scorer-weights invalid JSON: {e}", file=sys.stderr)
            return 2
    if args.extra_tags:
        try:
            cfg.extra_tags = json.loads(args.extra_tags)
        except json.JSONDecodeError as e:
            print(f"[harness] FATAL: --extra-tags invalid JSON: {e}", file=sys.stderr)
            return 2

    # 3) 跑用例
    if args.dry_run:
        result = _run_dry(cases, cfg)
    else:
        agent = _load_agent()
        runner = HarnessRunner(agent=agent, config=cfg)
        result = runner.run(cases)
    result.set_path = set_path

    # 4) 写盘
    out_dir = Storage.write(result, root=args.out, tag=args.tag)

    # 5) 控制台输出 + 退出码
    print(f"[harness] run_id   : {result.run_id}")
    print(f"[harness] passed   : {result.cases_passed}/{result.cases_total}")
    print(f"[harness] pass_rate: {result.pass_rate:.2%}")
    print(f"[harness] artifacts: {out_dir}")

    if not args.dry_run and result.pass_rate < args.threshold:
        print(f"[harness] FAIL: pass_rate {result.pass_rate:.2%} < threshold {args.threshold:.2%}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())