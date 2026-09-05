"""
v2.0 slim — telemetry.py（合并 observability.py + monitor.py + json_log.py）

合并后只暴露一个 TelemetrySink：
- metrics       来自 monitor.py（incr / observe / gauge）
- tracing       来自 observability.py（span 上下文管理器）
- structured log 来自 json_log.py（emit / flush）

设计上保持三个旧模块的对外 API 子集，避免破坏 api.py 中的调用点；
新增统一门面 TelemetrySink.snapshot()，用于 Insights 页拉取数据。
"""
from __future__ import annotations

import json
import logging
import os
import time
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# TelemetrySink — 统一门面
# ============================================================

class TelemetrySink:
    """合并的指标 + 链路 + 结构化日志。"""

    _instance: Optional["TelemetrySink"] = None

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._events: List[Dict[str, Any]] = []  # 来自 json_log 的最近 N 条
        self._max_events = 1000
        self._spans: List[Dict[str, Any]] = []   # 来自 observability 的 span 落盘
        self._max_spans = 500

    @classmethod
    def instance(cls) -> "TelemetrySink":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ---------- 来自 monitor.py ----------
    def incr(self, name: str, value: int = 1, **tags: Any) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = float(value)

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            self._histograms.setdefault(name, []).append(value)
            # 限制内存：每条直方图最多 5000 个点
            if len(self._histograms[name]) > 5000:
                self._histograms[name] = self._histograms[name][-5000:]

    # ---------- 来自 observability.py ----------
    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[Dict[str, Any]]:
        ctx: Dict[str, Any] = {
            "name": name,
            "start": time.time(),
            "attrs": attrs,
            "events": [],
        }
        try:
            yield ctx
            ctx["status"] = "ok"
        except Exception as e:  # noqa: BLE001
            ctx["status"] = "error"
            ctx["error"] = str(e)
            raise
        finally:
            ctx["duration_ms"] = (time.time() - ctx["start"]) * 1000
            with self._lock:
                self._spans.append(ctx)
                if len(self._spans) > self._max_spans:
                    self._spans = self._spans[-self._max_spans:]

    def record_event(self, span_ctx: Dict[str, Any], event: str, **attrs: Any) -> None:
        span_ctx.setdefault("events", []).append({
            "event": event,
            "ts": time.time(),
            "attrs": attrs,
        })

    # ---------- 来自 json_log.py ----------
    def emit(self, event: str, **fields: Any) -> None:
        rec = {"event": event, "ts": time.time(), **fields}
        with self._lock:
            self._events.append(rec)
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events:]
        # 同时输出到标准 logger（INFO）
        logger.info(json.dumps(rec, ensure_ascii=False, default=str))

    def flush(self, path: str) -> int:
        """将内存中的 events + spans 落盘到 JSONL 文件。"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        n = 0
        with self._lock:
            with open(path, "a", encoding="utf-8") as f:
                for rec in self._events:
                    f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                    n += 1
                for sp in self._spans:
                    f.write(json.dumps({"span": sp}, ensure_ascii=False, default=str) + "\n")
                    n += 1
        return n

    # ---------- Insights 页统一快照 ----------
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms_summary": {
                    k: {
                        "count": len(v),
                        "p50": _pct(v, 0.5),
                        "p95": _pct(v, 0.95),
                        "p99": _pct(v, 0.99),
                    }
                    for k, v in self._histograms.items()
                },
                "recent_events": list(self._events[-20:]),
                "recent_spans": [
                    {"name": s["name"], "duration_ms": s.get("duration_ms"), "status": s.get("status")}
                    for s in self._spans[-20:]
                ],
            }


def _pct(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(p * (len(s) - 1))))
    return float(s[idx])


# ============================================================
# 顶层门面 + 向后兼容旧模块 API
# ============================================================

def get_telemetry() -> TelemetrySink:
    return TelemetrySink.instance()


# —— 兼容 monitor.py ——
def monitor_record(name: str, value: float = 1.0) -> None:
    get_telemetry().incr(name, int(value))


# —— 兼容 json_log.py ——
def json_log_emit(event: str, **fields: Any) -> None:
    get_telemetry().emit(event, **fields)


# —— 兼容 observability.py ——
@contextmanager
def observability_span(name: str, **attrs: Any) -> Iterator[Dict[str, Any]]:
    with get_telemetry().span(name, **attrs) as ctx:
        yield ctx


__all__ = [
    "TelemetrySink",
    "get_telemetry",
    "monitor_record",
    "json_log_emit",
    "observability_span",
]