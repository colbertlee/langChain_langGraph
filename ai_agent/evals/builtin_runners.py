"""内置 runner：把不同 category 的 case 映射到实际调用。

每个 runner 必须实现：

    def runner(case: Dict) -> CaseResult

约定：
- ``expected_*`` 字段是 JSON 里给定的期望值。
- 内部异常 → 已由 ``runner._execute_case`` 转成失败；这里专注于业务判断。
- 不允许在这里 import 真实 LLM / 网络；只用本地可重放的规则或真实 AI Agent 模块。

PR3 协议升级
~~~~~~~~~~~~

- 旧的 ``runner(case)`` 协议完全保留，向后兼容。
- 新协议允许 runner 形如 ``runner(case, hooks=None, budget=None, agent=None)``：
  harness 接到这种 runner 时会按新协议调用；
  旧 runner 会由 ``_accept`` 适配器自动包一层兼容。
- ``harness_api.run_case`` 通过 ``_accept`` 派发，新旧 runner 无差别。
"""
from __future__ import annotations

import inspect
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from evals.registry import EvalRegistry, CaseResult


# ============================================================
# 协议适配器（PR3）
# ============================================================

_RUNNER_NEW_PARAMS = ("hooks", "budget", "agent", "dry_run")


def _accept(runner):
    """把旧 runner(case) 适配成新协议 runner(case, hooks, budget, agent, dry_run)。

    规则：
    - 旧 runner：不接受新参数 → 包装成新协议，调用时把新参数全 pass-through。
    - 新 runner：已经接受 ``hooks`` / ``budget`` / ``agent`` / ``dry_run`` 中至少一个
      → 原样返回，由 harness 直接按新协议调用。
    """
    try:
        sig = inspect.signature(runner)
    except (TypeError, ValueError):
        # 没法 introspect（built-in 等）——按旧协议处理，最安全
        return _wrap_legacy(runner)

    accepts_new = any(p in sig.parameters for p in _RUNNER_NEW_PARAMS)
    if accepts_new:
        return runner
    return _wrap_legacy(runner)


def _wrap_legacy(runner):
    def wrapped(
        case: Dict[str, Any],
        hooks=None,
        budget=None,
        agent=None,
        dry_run: bool = False,
    ) -> CaseResult:
        return runner(case)
    return wrapped


# ============================================================
# intent_routing
# ============================================================

# 简化的意图识别（与 security.check_input 的输出对齐）。
# 这是"规则化"基线，不调用 LLM——保证 CI 跑得动。
_INTENT_RULES: list[tuple[str, list[str]]] = [
    ("greeting", ["你好", "hello", "hi", "嗨", "早上好", "晚上好", "在吗"]),
    ("compare", ["对比", "compare"]),
    ("calculate", ["算", "calculate", "=?", "等于", "1 +", "*", "+"]),
    ("analysis", ["分析", "analyze", "走势", "数据"]),
    ("command", ["执行", "shell", "命令", "run", "command", "exec"]),
    ("query", ["查", "weather", "天气", "查询", "搜索", "search", "query"]),
]


def _detect_intent_rules(text: str) -> str:
    s = (text or "").lower()
    for intent, keywords in _INTENT_RULES:
        for kw in keywords:
            if kw.lower() in s:
                return intent
    return "general"


@EvalRegistry.register("intent_routing")
def run_intent_routing(case: Dict[str, Any]) -> CaseResult:
    text = str(case.get("input", ""))
    expected = str(case.get("expected_intent", "general"))
    observed = _detect_intent_rules(text)
    passed = observed == expected
    return CaseResult(
        name=case.get("name", "unknown"),
        category="intent_routing",
        passed=passed,
        duration_ms=0,
        detail=f"expected={expected} got={observed}",
        observed=observed,
    )


# ============================================================
# safety
# ============================================================

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+previous", re.I),
    re.compile(r"忽略.{0,5}之前", re.I),
    re.compile(r"忽略.{0,5}指令", re.I),
    re.compile(r"忽略.{0,5}指示", re.I),
    re.compile(r"jailbreak", re.I),
    re.compile(r"DAN\s+mode", re.I),
    re.compile(r"<\|im_start\|>", re.I),
    re.compile(r"<system>", re.I),
    re.compile(r"reveal\s+system", re.I),
]

_SAFE_CONTEXT_KEYWORDS = [
    "关于", "论文", "paper", "document", "documentation",
]


def _is_prompt_injection(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    # 上下文含 "这是篇文档" 时降级为 false（避免误杀）
    s_low = s.lower()
    if any(k.lower() in s_low for k in _SAFE_CONTEXT_KEYWORDS):
        return False
    for pat in _INJECTION_PATTERNS:
        if pat.search(s):
            return True
    return False


@EvalRegistry.register("safety")
def run_safety(case: Dict[str, Any]) -> CaseResult:
    text = str(case.get("input", ""))
    expect_blocked = bool(case.get("expect_blocked", False))
    observed_blocked = _is_prompt_injection(text)
    passed = observed_blocked == expect_blocked
    return CaseResult(
        name=case.get("name", "unknown"),
        category="safety",
        passed=passed,
        duration_ms=0,
        detail=f"expect_blocked={expect_blocked} got={observed_blocked}",
        observed=blocked_status(observed_blocked),
    )


def blocked_status(flag: bool) -> str:
    return "blocked" if flag else "safe"


# ============================================================
# calculator
# ============================================================

@EvalRegistry.register("calculator")
def run_calculator(case: Dict[str, Any]) -> CaseResult:
    """直接调用 tools.calculate.invoke，验证算数与沙箱。

    期望：
    - ``expect_error=True`` → 不应非异常退出
    - 否则 ``result == expected_output``（带 tolerance）
    """
    from tools import calculate  # 真实 AI Agent 的工具函数
    text = str(case.get("input", ""))
    expect_error = bool(case.get("expect_error", False))
    expected = case.get("expected_output")
    tolerance = float(case.get("tolerance", 0))

    try:
        raw = calculate.invoke({"expression": text})
    except Exception as e:
        if expect_error:
            return CaseResult(
                name=case.get("name", "unknown"),
                category="calculator",
                passed=True,
                duration_ms=0,
                detail=f"raised={e!r} (expected)",
                observed={"error": repr(e)},
            )
        return CaseResult(
            name=case.get("name", "unknown"),
            category="calculator",
            passed=False,
            duration_ms=0,
            detail=f"raised={e!r}",
            observed={"error": repr(e)},
        )

    raw_s = str(raw)
    # ``tools.calculate`` 把错误以字符串形式返回（"计算错误: ..."），
    # 这也是"被拒绝"的合法形式。
    is_error_string = raw_s.startswith("计算错误") or raw_s.startswith("Error") or "不允许" in raw_s

    if expect_error or is_error_string:
        passed = expect_error  # 仅当 expect_error=true 视为通过
        return CaseResult(
            name=case.get("name", "unknown"),
            category="calculator",
            passed=passed,
            duration_ms=0,
            detail=f"expected_error={expect_error} got_raw={raw!r}",
            observed=raw_s,
        )

    # 抽数值：从 "结果是 X" 类字符串里抓
    match = re.search(r"(-?\d+(?:\.\d+)?)", str(raw))
    if not match:
        return CaseResult(
            name=case.get("name", "unknown"),
            category="calculator",
            passed=False,
            duration_ms=0,
            detail=f"no number in raw: {raw!r}",
            observed=raw,
        )
    observed_num = float(match.group(1))
    expected_num = float(expected)
    passed = abs(observed_num - expected_num) <= tolerance
    return CaseResult(
        name=case.get("name", "unknown"),
        category="calculator",
        passed=passed,
        duration_ms=0,
        detail=f"expected={expected_num} got={observed_num} tol={tolerance}",
        observed=observed_num,
    )


# ============================================================
# agent_end_to_end 已迁移到 evals/runners/agent_end_to_end.py（PR16）
# ============================================================


# ============================================================
# README 说明
# ============================================================

README_PATH = Path(__file__).resolve().parent / "README.md"


def write_evals_readme_if_missing() -> None:
    """初始化 evals/README.md（如缺失）。"""
    if README_PATH.exists():
        return
    README_PATH.write_text(
        """# evals/ — AI Agent 评测（Day 13-14）

## 跑

```bash
# 跑单个分类
python -m evals.runner run --case intent_routing
python -m evals.runner run --case safety
python -m evals.runner run --case calculator

# 跑全部
python -m evals.runner run --all

# 历史
python -m evals.runner history
python -m evals.runner history --limit 20

# 对比
python -m evals.runner diff 20250620_120000 20250620_180000
```

## 加入新维度

1. 在 ``cases/<name>.json`` 加用例集：
    ```json
    [{"name": "...", "category": "<new>", "input": "...", "expected_...": ...}]
    ```
2. 在 ``builtin_runners.py`` 注册 runner：
    ```python
    @EvalRegistry.register("<new>")
    def run_xxx(case): ...
    ```
3. ``python -m evals.runner run --case <new>`` 验证

## 设计

- 纯本地：默认不调用 LLM（CI 稳定）；
- 用例 schema 由各 category 自定义，runner 负责解释；
- 历史记录落到 ``runs/<timestamp>/``；
- 失败 → 非零退出（CI 报警）。
""",
        encoding="utf-8",
    )


write_evals_readme_if_missing()
