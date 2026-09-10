"""observability.metrics_registry — Milestone 2.3.1 MetricsRegistry

简单的标签化计数器注册表（与 prometheus_client 桥接，但支持 ``value(**labels)`` 反查），
给 ``harness_observability`` 适配层调用。

API
---
  - ``MetricsRegistry().counter(name, help_text="")``
        返回 ``Counter``；同名复用。
  - ``Counter.inc(amount=1.0, **labels)``
        累加；首次出现某 label 组合时初始化。
  - ``Counter.value(**labels)``
        反查当前值；找不到返回 0.0。

设计
----
  - 数据结构 ``{labels_tuple: float}`` 存于 Counter 内部；
    无标签时 key 为 ``()``，兼容单值使用场景。
  - 线程安全（lock 保护）。
  - 测试友好：可单测断言 counter 值变化。
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Tuple


class _Counter:
    def __init__(self, name: str, help_text: str = "") -> None:
        self.name = name
        self.help_text = help_text or ""
        self._lock = threading.Lock()
        self._values: Dict[Tuple[Tuple[str, Any], ...], float] = {}

    @staticmethod
    def _key(labels: Dict[str, Any]) -> Tuple[Tuple[str, Any], ...]:
        return tuple(sorted((str(k), labels[k]) for k in labels))

    def inc(self, amount: float = 1.0, **labels: Any) -> None:
        if amount is None:
            amount = 0.0
        try:
            v = float(amount)
        except (TypeError, ValueError):
            v = 0.0
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + v

    def value(self, **labels: Any) -> float:
        key = self._key(labels)
        with self._lock:
            return float(self._values.get(key, 0.0))

    def reset(self) -> None:
        with self._lock:
            self._values.clear()


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, _Counter] = {}

    def counter(self, name: str, help_text: str = "") -> _Counter:
        key = str(name)
        with self._lock:
            if key not in self._counters:
                self._counters[key] = _Counter(key, help_text or "")
            return self._counters[key]

    def reset(self) -> None:
        with self._lock:
            for c in self._counters.values():
                c.reset()


__all__ = ["MetricsRegistry", "_Counter"]