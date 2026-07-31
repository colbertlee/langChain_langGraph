"""evals/harness_api.py — Harness 评测 API 层（PR2）。

设计目标
--------

- **不破坏** ``evals/registry.py`` 与 ``evals/runner.py`` 的现有形态。
- 给 tests / CI / dashboard 一个稳定的"程序化"入口
  （``run_case`` / ``run_suite`` / ``score``），与 CLI 解耦。
- 复用 ``EvalRegistry`` 的派发；不在 API 层引入新的 runner 概念。

调用方式
~~~~~~~~

::

    from evals.harness_api import run_case, run_suite, score
    from agent import Hooks, Budget

    case = {"name": "calc_basic", "category": "calculator",
            "input": "1+2", "expected_output": 3}
    cr = run_case(case, hooks=Hooks(), budget=Budget(timeout_s=10))
    summary = run_suite(cases, out_dir="evals/runs/harness_demo")

未来扩展
~~~~~~~~

- PR5 会接入 ``evals.runner`` 的落盘逻辑（``runs/<ts>/summary.json``）。
- 接入 deep eval / langfuse：实现 ``EvalRegistry.register("llm_qa", runner_fn)``
  即可，harness API 不需要重新设计。

PR6 升级
~~~~~~~~

- ``run_case`` / ``run_suite`` 增加 ``agent`` 形参（旧协议 runner 不消费也不会报错）。
- 与 ``_accept`` 适配器组合后，signature 是：
  ``runner(case, hooks=None, budget=None, agent=None)``。

PR11 升级
~~~~~~~~~

- 环境变量 ``HARNESS_DRY_RUN=1`` 时，``run_case`` / ``run_suite`` 把
  ``dry_run=True`` 透传给 runner；runner 负责走 dry 路径（agent_end_to_end
  委托 ``agent.run_task(dry_run=True)``）。
- 优先级：调用方显式传入 ``dry_run=...`` 形参（未来 PR） > 环境变量。
"""
from __future__ import annotations

import json
import os
import time
import traceback
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# PR11：环境变量 → dry_run 标志。默认 0；CI 把 HARNESS_DRY_RUN=1 就能跑 dry。
def _env_dry_run() -> bool:
    return os.environ.get("HARNESS_DRY_RUN", "0").lower() in ("1", "true", "yes")

# 让 evals/ 内的脚本能 import ai_agent/*
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
import sys
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evals.registry import CaseResult, EvalRegistry  # noqa: E402

# 复用 builtin_runners（注册所有内置 category 的 runner）。
# 这是 idempotent 的：重复 import 不会重复注册。
from evals import builtin_runners  # noqa: E402, F401
from evals.builtin_runners import _accept  # noqa: E402  协议适配器（PR3）

# PR16：注册 agent_end_to_end runner（独立模块，避免 builtin_runners 膨胀）。
from evals.runners import agent_end_to_end  # noqa: E402, F401


# ============================================================
# 工具函数
# ============================================================

def _validate_case(case: Dict[str, Any]) -> Optional[str]:
    """返回 None 表示合法；否则返回错误说明。"""
    if not isinstance(case, dict):
        return "case must be a dict"
    if "category" not in case:
        return "case missing 'category'"
    if not EvalRegistry.get(str(case["category"])):
        return f"no runner registered for category={case['category']!r}"
    return None


# ============================================================
# 单条用例
# ============================================================

def run_case(
    case: Dict[str, Any],
    *,
    hooks: Optional[Any] = None,
    budget: Optional[Any] = None,
    agent: Optional[Any] = None,
    dry_run: Optional[bool] = None,
) -> CaseResult:
    """跑一条 case；返回 :class:`CaseResult`。

    参数
    ~~~~

    - ``case``：dict，至少含 ``category``；其余字段由 runner 解释。
    - ``hooks``：可选 ``agent.Hooks`` 实例（PR7 才会真正消费）。
    - ``budget``：可选 ``agent.Budget`` 实例（PR10 timeout 路径已消费）。
    - ``agent``：可选 ``AIAgent`` 实例；不传则新协议 runner 内部自建（PR6 接入）。
    - ``dry_run``：可选 ``bool``。``None`` 表示跟随环境变量 ``HARNESS_DRY_RUN``；
      显式 ``True``/``False`` 优先于环境变量。

    行为契约
    ~~~~~~~~

    - runner 抛异常 → 返回 ``passed=False`` + ``detail="runner raised: ..."``，**不向上抛**。
    - 用例 schema 不合法 → 返回 ``passed=False`` + ``detail="invalid case: ..."``。
    - 旧 runner 已被 ``_accept`` 包装，``hooks`` / ``budget`` / ``agent`` / ``dry_run``
      被安全 pass-through（旧 runner 签名不接 ``dry_run`` → 走 ``_accept`` 包装稳健丢弃）。
    """
    name = str(case.get("name", "unknown"))
    category = str(case.get("category", "unknown"))

    err = _validate_case(case)
    if err is not None:
        return CaseResult(
            name=name,
            category=category,
            passed=False,
            duration_ms=0.0,
            detail=f"invalid case: {err}",
        )

    runner = EvalRegistry.get(category)
    # PR3：统一走 _accept 适配器；旧 runner(case) 自动包成新协议。
    runner = _accept(runner)
    # PR11：dry_run 解析
    if dry_run is None:
        dry_run = _env_dry_run()
    t0 = time.monotonic()
    try:
        # 新协议：runner(case, hooks=None, budget=None, agent=None, dry_run=False)
        # 旧 runner 已被 _accept 包装，未接 dry_run 的会被丢弃。
        result = runner(case, hooks, budget, agent, dry_run)  # type: ignore[misc]
    except Exception as exc:  # noqa: BLE001 — harness 不允许抛
        return CaseResult(
            name=name,
            category=category,
            passed=False,
            duration_ms=(time.monotonic() - t0) * 1000,
            detail=f"runner raised: {exc}",
            observed={"trace": traceback.format_exc(limit=3)},
        )

    # 规整：runner 内部已经填过 name/category/passed/duration_ms；
    # 即便 runner 没填，我们也补一份。
    if not result.name:
        result.name = name
    if not result.category:
        result.category = category
    if result.duration_ms <= 0:
        result.duration_ms = (time.monotonic() - t0) * 1000
    return result


# ============================================================
# 套件
# ============================================================

def run_suite(
    cases: List[Dict[str, Any]],
    *,
    hooks: Optional[Any] = None,
    budget: Optional[Any] = None,
    agent: Optional[Any] = None,
    dry_run: Optional[bool] = None,
    out_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """跑一组 case，返回 dict 形式的 summary + cases 列表。

    ``out_dir`` 给出时，把 ``summary.json`` + ``cases.jsonl`` 写到那里
    （兼容 ``evals.runner`` 现有落盘结构，便于 dashboard / archive 复用）。

    注入的 ``agent`` 被所有 case 共享（典型用法：注入 fake agent，
    跑全 agent_end_to_end 时不发真实请求）。
    ``dry_run`` 视同 run_case 形参，None 跟随环境变量。
    """
    results: List[CaseResult] = []
    for c in cases:
        results.append(run_case(
            c, hooks=hooks, budget=budget, agent=agent, dry_run=dry_run,
        ))

    summary = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "cases_total": len(results),
        "cases_passed": sum(1 for r in results if r.passed),
        "cases_failed": sum(1 for r in results if not r.passed),
        "cases_errored": 0,
        "cases": [asdict(r) for r in results],
    }

    if out_dir:
        d = Path(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        summary_file = d / "summary.json"
        cases_file = d / "cases.jsonl"
        summary_file.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        cases_file.write_text(
            "\n".join(json.dumps(asdict(r), ensure_ascii=False) for r in results),
            encoding="utf-8",
        )

    return summary


# ============================================================
# 评分函数
# ============================================================

def score(
    trajectory: Any,
    expected: Dict[str, Any],
) -> CaseResult:
    """纯函数：把 ``Trajectory`` 评成 ``CaseResult``。

    用途：PR3 引入 ``agent_end_to_end`` runner 后，runner 内部调用本函数
    即可完成评分；harness 用户自己写评测函数时也能直接复用。

    当前支持的评分维度（按 expected 字段识别）：

    - ``expected_output``（str 或数值）：与 ``trajectory.final`` 做包含/相等比较。
    - ``expected_intent``（str）：与 ``trajectory.events`` 中 ``intent`` 字段匹配。
    - ``expect_blocked``（bool）：与 ``trajectory.error`` 是否非空匹配。
    - ``expect_error``（bool）：与 ``trajectory.error`` 是否非空匹配。
    - ``max_duration_ms``（float）：与 ``trajectory.used.elapsed_s * 1000`` 比较。

    不匹配即 ``passed=False``，``detail`` 记录具体差距。
    """
    name = str(expected.get("name", "unknown"))
    category = str(expected.get("category", "agent_end_to_end"))

    # 提取 observed
    final_text = getattr(trajectory, "final", "") or ""
    error = getattr(trajectory, "error", None)
    used = getattr(trajectory, "used", None)
    elapsed_ms = (used.elapsed_s * 1000.0) if used else 0.0

    # 错误类断言
    if "expect_error" in expected:
        want_error = bool(expected["expect_error"])
        got_error = bool(error)
        if want_error != got_error:
            return CaseResult(
                name=name, category=category, passed=False, duration_ms=elapsed_ms,
                detail=f"expect_error={want_error} got_error={got_error}",
                observed={"error": error, "final": final_text},
            )

    if "expect_blocked" in expected:
        want_blocked = bool(expected["expect_blocked"])
        # blocked 表现：error 非空 或 final 是 graceful 错误骨架
        is_blocked = bool(error) or "错误" in final_text[:20]
        if want_blocked != is_blocked:
            return CaseResult(
                name=name, category=category, passed=False, duration_ms=elapsed_ms,
                detail=f"expect_blocked={want_blocked} got_blocked={is_blocked}",
                observed={"error": error, "final": final_text[:200]},
            )

    # PR13：意图断言。
    # 优先看 trajectory.events 里 kind="intent"（payload 中带 intent 字段）；
    # 兜底看 trajectory.payload.get("intent")（runner 兜底注入的位置）。
    if "expected_intent" in expected:
        want_intent = str(expected["expected_intent"])
        got_intent = None
        # 1) 先从 events 找
        for ev in getattr(trajectory, "events", []) or []:
            p = getattr(ev, "payload", None)
            if isinstance(p, dict) and "intent" in p:
                got_intent = str(p["intent"])
                break
        # 2) 兜底：trajectory.payload.get("intent")
        if got_intent is None:
            p = getattr(trajectory, "payload", None)
            if isinstance(p, dict) and "intent" in p:
                got_intent = str(p["intent"])
        if got_intent != want_intent:
            return CaseResult(
                name=name, category=category, passed=False, duration_ms=elapsed_ms,
                detail=f"expected_intent={want_intent} got_intent={got_intent!r}",
                observed={"final": final_text[:200]},
            )

    # 输出内容断言
    if "expected_output" in expected:
        want = expected["expected_output"]
        if isinstance(want, (int, float)):
            # 数值：用正则抽数字
            import re
            m = re.search(r"-?\d+(?:\.\d+)?", final_text)
            if not m:
                return CaseResult(
                    name=name, category=category, passed=False, duration_ms=elapsed_ms,
                    detail=f"no number in final: {final_text!r}",
                    observed=final_text,
                )
            got_num = float(m.group(0))
            tol = float(expected.get("tolerance", 0))
            if abs(got_num - float(want)) > tol:
                return CaseResult(
                    name=name, category=category, passed=False, duration_ms=elapsed_ms,
                    detail=f"expected_num={want} got={got_num} tol={tol}",
                    observed=got_num,
                )
        else:
            want_str = str(want)
            if want_str not in final_text:
                return CaseResult(
                    name=name, category=category, passed=False, duration_ms=elapsed_ms,
                    detail=f"expected_output substring not found: {want_str!r}",
                    observed=final_text[:200],
                )

    # 时延断言
    if "max_duration_ms" in expected:
        max_ms = float(expected["max_duration_ms"])
        if elapsed_ms > max_ms:
            return CaseResult(
                name=name, category=category, passed=False, duration_ms=elapsed_ms,
                detail=f"duration {elapsed_ms:.1f}ms > max {max_ms:.1f}ms",
                observed={"elapsed_ms": elapsed_ms},
            )

    # 全通过
    return CaseResult(
        name=name, category=category, passed=True, duration_ms=elapsed_ms,
        detail="ok",
        observed={"final": final_text[:200], "elapsed_ms": elapsed_ms},
    )


# ============================================================
# 显式导出
# ============================================================

__all__ = ["run_case", "run_suite", "score"]
