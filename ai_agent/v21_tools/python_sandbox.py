"""v21_tools.python_sandbox — Milestone 2.3.1 OTel Span 包裹的 Python 沙箱执行

设计目标
----
  - 把现有 ``v21_tools.code_interpreter.python_interpreter`` 的执行过程包成 OTel Span，
    暴露以下属性 / 事件：
        * tool.name    = "python_interpreter"
        * code.length  = 代码长度
        * timeout      = 超时秒数
        * sandbox.workdir
        * exit_code    = 返回码
        * timed_out    = 是否被 timeout 拦截
        * images.count = 生成的图片数
        * duration_ms  = 耗时
  - 同时调用 ``record_sandbox_execution`` 把耗时 / 超时状态写到
    Prometheus 指标 ``sandbox_execution_duration_seconds``。

兼容策略
----
  - 复用 ``v21_tools.code_interpreter.python_interpreter`` 的全部实现；
  - 不破坏既有 ``requires_approval=True`` 的 HITL 行为
    （HITL 拦截发生在 Tool 调用前的 HITLWrappedTool 层，不在此处）。
  - OTel SDK / 指标 SDK 不可用时整套埋点降级为 NoOp，不抛异常。
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _get_tracer() -> Any:
    """惰性获取 OTel Tracer；不可用时返回 _NoOpTracer。"""
    try:
        from observability.otel_exporter import get_tracer

        return get_tracer("ai_agent.v21_tools.python_sandbox")
    except Exception:
        try:
            from opentelemetry import trace  # type: ignore

            return trace.get_tracer("ai_agent.v21_tools.python_sandbox")
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

                        def set_status(self_inner, *a, **kw):
                            return None

                        def end(self_inner, *a, **kw):
                            return None

                        def record_exception(self_inner, *a, **kw):
                            return None

                    return _S()

            return _NoOp()


def _record_sandbox_metric(
    tool: str,
    duration_seconds: float,
    *,
    timed_out: bool,
    exit_code: int,
    status: str,
) -> None:
    """把沙箱执行耗时写入 OTel Meter + Prometheus。"""
    try:
        from observability.otel_exporter import record_sandbox_execution

        record_sandbox_execution(
            tool=tool,
            duration_seconds=duration_seconds,
            status=status,
            timed_out=timed_out,
        )
    except Exception as e:
        logger.debug(f"_record_sandbox_metric failed: {e}")


def python_interpreter_with_trace(
    code: str, timeout: int = 10, workdir: Optional[Path] = None
) -> dict:
    """与 v21_tools.code_interpreter.python_interpreter 同语义，附加 OTel Span + 指标。

    Returns:
        dict: 与原 ``python_interpreter`` 完全一致。
    """
    from .code_interpreter import python_interpreter as _orig_python_interpreter

    tracer = _get_tracer()
    started = time.time()
    # OTel API 兼容：tracer.start_as_current_span 是 contextmanager；
    # NoOpTracer 也实现了 __enter__/__exit__。
    span_cm = tracer.start_span(
        "python_interpreter.execute",
        attributes={
            "tool.name": "python_interpreter",
            "code.length": len(code or ""),
            "timeout": int(timeout),
        },
    )
    try:
        with span_cm as span:
            # 添加 sandbox 元数据
            try:
                if workdir is None:
                    from tempfile import mkdtemp

                    workdir = Path(mkdtemp(prefix="pyexec-trace-"))
                span.set_attribute("sandbox.workdir", str(workdir))
            except Exception:
                pass

            try:
                result = _orig_python_interpreter(
                    code=code, timeout=timeout, workdir=workdir
                )
            except Exception as e:
                try:
                    span.record_exception(e)
                except Exception:
                    pass
                try:
                    span.set_attribute("status", "error")
                except Exception:
                    pass
                duration = time.time() - started
                _record_sandbox_metric(
                    "python_interpreter",
                    duration,
                    timed_out=False,
                    exit_code=-1,
                    status="error",
                )
                raise

            try:
                span.set_attribute("exit_code", int(result.get("exit_code", -1)))
                span.set_attribute(
                    "timed_out", bool(result.get("timed_out", False))
                )
                span.set_attribute(
                    "images.count", len(result.get("images", []) or [])
                )
                span.set_attribute(
                    "duration_ms", int(result.get("duration_ms", 0))
                )
            except Exception:
                pass

            duration = time.time() - started
            status = "ok"
            if result.get("timed_out"):
                status = "timeout"
            elif int(result.get("exit_code", 0)) != 0:
                status = "error"
            _record_sandbox_metric(
                "python_interpreter",
                duration,
                timed_out=bool(result.get("timed_out")),
                exit_code=int(result.get("exit_code", 0)),
                status=status,
            )
            try:
                span.set_attribute("status", status)
            except Exception:
                pass
            return result
    except Exception:
        raise


__all__ = ["python_interpreter_with_trace"]