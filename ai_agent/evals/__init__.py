"""evals/ — 轻量回归评估框架（Day 13-14）。

设计目标
~~~~~~~~
- **零外部依赖**：不强制装 deepeval / langfuse，跑框架本身只需 pytest。
- **每个能力一条 JSONL/JSON**：每个 ``cases/<category>.json`` 是用例集。
- **跑 × 报告 × 上报告** 三阶段：
  - ``evals.runner run --case intent_routing``：执行
  - ``evals.runner report runs/2025-...``：生成可读报告
  - ``evals.runner history``：跨次回归趋势

跑法
~~~~
::

    python -m evals.runner run --case intent_routing
    python -m evals.runner run --all                # 跑全部用例
    python -m evals.runner history                 # 跨次趋势

目录约定
~~~~~~~
::

    evals/
        cases/<category>.json   # 用例集（数组）
        runs/<timestamp>/       # 单次跑结果：summary.json + per-case.jsonl
        README.md

用例 schema
~~~~~~~~~~~
::

    {
      "name": "intent_greet_zh",
      "category": "intent_routing",
      "input": "你好",
      "expected_intent": "greeting"
    }

注：每个 ``runner`` 内部通过 ``category`` 路由到具体的评测函数；
增加新维度只要：
1. 加 ``cases/<new>.json``
2. 在 ``EvalRegistry`` 注册 ``category`` → runner 函数

自动加载内置 runner
~~~~~~~~~~~~~~~~~~~

``builtin_runners`` 在 import 这个包时自动 import → 注册生效，避免手工漏 import。
"""

# 让 ``from evals import builtin_runners`` 在外部显式 / 隐式 import 时都触发注册
# （runner.py 中即便显式 import，注册函数也已经跑过。）
__all__ = ["builtin_runners", "runner"]


def _ensure_builtin_runners_loaded() -> None:
    """确保 builtin_runners 已 import（注册 EvalRegistry）。"""
    import sys

    if "evals.builtin_runners" in sys.modules:
        return
    from evals import builtin_runners  # noqa: F401


_ensure_builtin_runners_loaded()
