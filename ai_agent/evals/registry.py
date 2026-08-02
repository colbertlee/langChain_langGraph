"""eval runner 注册中心（独立模块）—— 让 ``evals.builtin_runners`` 不必
``from evals.runner import EvalRegistry``，绕开 ``python -m evals.runner``
模式下的 self-import 路径冲突。

Day 13-14
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class CaseResult:
    name: str
    category: str
    passed: bool
    duration_ms: float
    detail: str = ""
    observed: Any = None


class EvalRegistry:
    """评测函数注册中心：``category`` -> runner(callable)。

    与 ``evals.runner`` 不耦合：本模块只存 (category -> callable) 字典，
    不引 runner / 不引 builtin_runners——builtin_runners 只能 import 本模块。
    """

    _RUNNERS: Dict[str, Callable] = {}

    @classmethod
    def register(cls, category: str):
        def deco(fn):
            cls._RUNNERS[category] = fn
            return fn
        return deco

    @classmethod
    def get(cls, category: str) -> Optional[Callable]:
        return cls._RUNNERS.get(category)

    @classmethod
    def all_categories(cls) -> List[str]:
        return sorted(cls._RUNNERS.keys())


__all__ = ["EvalRegistry", "CaseResult"]