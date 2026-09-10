"""observability.hitl_span — Milestone 2.3.1 HITL 审批 Span 挂起 / 恢复

设计
----
  当 code_worker 触发 HITL（approval_required）时：
    1) Worker 节点创建一个 ``hitl.approval`` Span（kind=internal）；
    2) 设置 ``approval.request_id`` / ``tool.name`` / ``status=pending``；
    3) 把 ``(request_id → Span 实例)`` 缓存到本模块的全局 registry；
    4) 用户 Approve / Reject 后（通过 app.py 路由）→ ``resume_hitl_span`` 把
       那个 Span 取出，记录 ``status`` / ``duration_ms``，然后 end。

兼容
----
  - 旧版（OTel SDK 缺失）下用 NoOp Span，registry 仍可工作（只是不上报）；
  - app.py 在审批路由里调 ``resume_hitl_span``；超时由 ``hitl_langgraph.HITLStore`` 单独处理。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 全局 registry（request_id → (started_at, span)）
# ============================================================


_LOCK = threading.Lock()
_PENDING: Dict[str, Dict[str, Any]] = {}


def _get_tracer() -> Any:
    try:
        from observability.otel_exporter import get_tracer

        return get_tracer("ai_agent.hitl")
    except Exception:
        try:
            from opentelemetry import trace  # type: ignore

            return trace.get_tracer("ai_agent.hitl")
        except Exception:
            class _NoOp:
                def start_span(self, *a, **kw):
                    class _S:
                        def __enter__(self_inner):
                            return self_inner

                        def __exit__(self_inner, *a):
                            return False

                        def set_attribute(self_inner, *a, **kw):
                            return None

                        def end(self_inner, *a, **kw):
                            return None

                    return _S()

            return _NoOp()


def _record_hitl_metric(decision: str, tool: str = "") -> None:
    try:
        from observability.otel_exporter import record_hitl_decision

        record_hitl_decision(decision=decision, tool=tool)
    except Exception as e:
        logger.debug(f"_record_hitl_metric failed: {e}")


def start_hitl_span(
    request_id: str,
    *,
    tool_name: str = "",
    session_id: str = "",
    agent_name: str = "",
    extra_attrs: Optional[Dict[str, Any]] = None,
) -> Any:
    """创建并挂起一个 HITL approval Span。

    Returns:
        OTel Span 实例（NoOpTracer 下也是合法对象）；失败/SDK 不可用时降级。
    """
    tracer = _get_tracer()
    started = time.time()
    attrs: Dict[str, Any] = {
        "hitl.request_id": str(request_id or ""),
        "hitl.status": "pending",
        "tool.name": tool_name or "unknown_tool",
    }
    if session_id:
        attrs["session_id"] = session_id
    if agent_name:
        attrs["agent.name"] = agent_name
    if extra_attrs:
        for k, v in extra_attrs.items():
            attrs[str(k)] = v

    span_cm = tracer.start_span("hitl.approval", attributes=attrs)
    span = span_cm.__enter__()
    with _LOCK:
        _PENDING[str(request_id)] = {
            "started_at": started,
            "span": span,
            "span_cm": span_cm,
            "tool": tool_name or "",
            "session_id": session_id or "",
            "agent": agent_name or "",
        }
    logger.debug(f"hitl.approval span started: request_id={request_id}")
    return span


def resume_hitl_span(
    request_id: str,
    decision: str,
    *,
    tool_name: Optional[str] = None,
    extra_attrs: Optional[Dict[str, Any]] = None,
) -> Optional[float]:
    """结束挂起的 HITL Span（Approve / Reject / Timeout）。

    Returns:
        duration_seconds（float），无 pending 时返回 None。
    """
    key = str(request_id or "")
    with _LOCK:
        entry = _PENDING.pop(key, None)
    if entry is None:
        return None

    span = entry.get("span")
    span_cm = entry.get("span_cm")
    duration = max(0.0, time.time() - float(entry.get("started_at") or 0.0))

    tool = tool_name or entry.get("tool", "")
    try:
        if span is not None:
            span.set_attribute("hitl.status", decision)
            span.set_attribute("duration_ms", int(duration * 1000))
            if extra_attrs:
                for k, v in extra_attrs.items():
                    span.set_attribute(str(k), v)
    except Exception:
        pass
    try:
        if span_cm is not None:
            span_cm.__exit__(None, None, None)
    except Exception:
        pass

    _record_hitl_metric(decision=decision, tool=tool)
    logger.debug(
        f"hitl.approval span ended: request_id={key} decision={decision} dur={duration:.3f}s"
    )
    return duration


def cancel_hitl_span(
    request_id: str, *, reason: str = "cancelled"
) -> Optional[float]:
    """挂起的 Span 取消（异常路径）。"""
    return resume_hitl_span(
        request_id, "cancelled", extra_attrs={"cancel_reason": reason}
    )


def pending_count() -> int:
    """当前挂起中的 HITL Span 数（用于监控）。"""
    with _LOCK:
        return len(_PENDING)


def _reset_for_tests() -> None:
    with _LOCK:
        for entry in _PENDING.values():
            try:
                cm = entry.get("span_cm")
                if cm is not None:
                    cm.__exit__(None, None, None)
            except Exception:
                pass
        _PENDING.clear()


__all__ = [
    "start_hitl_span",
    "resume_hitl_span",
    "cancel_hitl_span",
    "pending_count",
    "_reset_for_tests",
]