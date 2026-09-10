"""observability.event_bus — Milestone 2.3.1 EventBus

简单的内存事件总线，给 ``harness_observability`` 适配层调用。

API
---
  - ``EventBus().publish(event_type, source, trace_id, payload)``
        发送一个事件到内部 list。
  - ``EventBus().list_events(event_type=None)``
        返回当前所有事件（或按 event_type 过滤）。
  - ``EventBus().clear()``
        清空（测试隔离）。

设计
----
  - 这是一个轻量 shim，专门补齐 ``harness_observability`` 测试期望的 surface；
    实际生产监控走 Prometheus / OTel，本类仅用于单元测试断言。
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, List, Optional


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []

    def publish(
        self,
        event_type: str,
        source: str,
        trace_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ev: Dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "event_type": str(event_type or ""),
            "source": str(source or ""),
            "trace_id": trace_id,
            "payload": payload or {},
            "ts": time.time(),
        }
        with self._lock:
            self._events.append(ev)
        return ev

    def list_events(self, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if event_type is None:
                return list(self._events)
            return [e for e in self._events if e.get("event_type") == event_type]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


__all__ = ["EventBus"]