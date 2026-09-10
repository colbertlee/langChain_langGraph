"""observability.langsmith_config — Milestone 2.3.1 LangSmith 链路追踪

职责
----
  - 集中初始化 LangChain LangSmithTracer，并暴露成 LangChain callbacks；
  - 通过环境变量 ``LANGCHAIN_TRACING_V2=true`` 控制是否启用；
  - 给 supervisor_agent / agent.py 提供 ``get_langsmith_callbacks()``，
    在调用 LangGraph ``.invoke(..., config={"callbacks": [...]})`` 时挂载。

API
---
  - ``init_langsmith_tracer(project_name=None, endpoint=None)``
       主动初始化；幂等。返回 (enabled, tracer_or_None)。
  - ``get_langsmith_tracer()`` —— 懒初始化（首次调用时检查 env）；
       返回 LangChainTracer 实例或 None。
  - ``is_langsmith_enabled()`` —— bool，反映当前全局开关状态。
  - ``get_langsmith_callbacks()`` —— list[BaseCallbackHandler]；
       启用时含 LangChainTracer，禁用时返回空 list。
  - ``_reset_for_tests()`` —— 单测间清空全局缓存。

设计要点
----
  1) LangChainTracer 需要 LANGSMITH_API_KEY（或 LANGCHAIN_API_KEY）才能上报；
     没配置时仍可构造，但实际 trace 不会上报（langsmith 客户端自身 fallback）。
  2) 与 langchain_core.tracers.LangChainTracer 集成；
     该类会自动从环境变量读 LANGCHAIN_TRACING_V2 / LANGCHAIN_API_KEY / LANGCHAIN_PROJECT。
  3) 在测试里 ``LANGCHAIN_TRACING_V2=true`` 但未提供 LANGSMITH_API_KEY 时，
     我们仍返回 tracer —— 单测只验证"挂载成功"，不需要真实上报。
"""
from __future__ import annotations

import logging
import os
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 全局懒加载单例（线程不敏感：测试串行执行即可）
# ============================================================

_LANGCHAIN_TRACER: Optional[Any] = None
_INITIALIZED: bool = False
_ENABLE_OVERRIDE: Optional[bool] = None  # 手动覆盖（测试用）


def _env_tracing_enabled() -> bool:
    """判断 LANGCHAIN_TRACING_V2 / LANGCHAIN_TRACING 是否为 truthy。"""
    v = (
        os.environ.get("LANGCHAIN_TRACING_V2")
        or os.environ.get("LANGCHAIN_TRACING")
        or ""
    ).lower().strip()
    return v in ("1", "true", "yes", "on")


def _env_project_name() -> str:
    """从 LANGCHAIN_PROJECT / LANGCHAIN_TRACING_PROJECT 读 project。"""
    return (
        os.environ.get("LANGCHAIN_PROJECT")
        or os.environ.get("LANGCHAIN_TRACING_PROJECT")
        or "trae-agent-system"
    )


def is_langsmith_enabled() -> bool:
    """是否启用 LangSmith 追踪。

    优先级：
      1) 测试强制覆盖（``_ENABLE_OVERRIDE``）；
      2) 环境变量 LANGCHAIN_TRACING_V2 / LANGCHAIN_TRACING。
    """
    if _ENABLE_OVERRIDE is not None:
        return _ENABLE_OVERRIDE
    return _env_tracing_enabled()


def init_langsmith_tracer(
    project_name: Optional[str] = None,
    endpoint: Optional[str] = None,
    *,
    enabled: Optional[bool] = None,
) -> Tuple[bool, Optional[Any]]:
    """初始化 LangSmith Tracer；幂等。

    Args:
        project_name: LangSmith project 名；None 时读 env LANGCHAIN_PROJECT，
                      默认 "trae-agent-system"。
        endpoint: LangSmith endpoint；None 时读 env LANGCHAIN_ENDPOINT。
        enabled: 手动覆盖启用；None 时按 env 自动判断。

    Returns:
        (enabled: bool, tracer_or_None)
    """
    global _LANGCHAIN_TRACER, _INITIALIZED, _ENABLE_OVERRIDE

    if enabled is not None:
        _ENABLE_OVERRIDE = enabled

    if not is_langsmith_enabled():
        logger.info(
            "LangSmith tracing disabled (set LANGCHAIN_TRACING_V2=true to enable)"
        )
        _INITIALIZED = True
        return (False, None)

    try:
        from langchain_core.tracers import LangChainTracer  # type: ignore
    except Exception as e:
        logger.warning(f"LangChainTracer import failed, LangSmith disabled: {e}")
        _INITIALIZED = True
        return (False, None)

    # 把 project / endpoint 写入环境变量（LangChainTracer 从 env 读取）
    proj = project_name or _env_project_name()
    if proj:
        os.environ.setdefault("LANGCHAIN_PROJECT", proj)
    if endpoint:
        os.environ.setdefault("LANGCHAIN_ENDPOINT", endpoint)

    try:
        tracer = LangChainTracer(project_name=proj)
    except Exception as e:
        logger.warning(f"LangChainTracer init failed: {e}")
        _INITIALIZED = True
        return (False, None)

    _LANGCHAIN_TRACER = tracer
    _INITIALIZED = True
    logger.info(f"LangSmith tracing enabled (project={proj})")
    return (True, tracer)


def get_langsmith_tracer() -> Optional[Any]:
    """懒加载：首次调用时初始化。返回 LangChainTracer 或 None。"""
    global _LANGCHAIN_TRACER, _INITIALIZED
    if _INITIALIZED:
        return _LANGCHAIN_TRACER
    enabled, tracer = init_langsmith_tracer()
    return tracer


def get_langsmith_callbacks() -> List[Any]:
    """返回 LangChain callbacks 列表；可在 LangGraph ``.invoke(..., config={"callbacks": ...})`` 挂载。

    启用时返回 ``[LangChainTracer()]``；禁用或 SDK 不可用时返回 ``[]``（不抛异常）。
    """
    tracer = get_langsmith_tracer()
    return [tracer] if tracer is not None else []


def _reset_for_tests() -> None:
    """单测间清空缓存（恢复默认 env 行为）。"""
    global _LANGCHAIN_TRACER, _INITIALIZED, _ENABLE_OVERRIDE
    _LANGCHAIN_TRACER = None
    _INITIALIZED = False
    _ENABLE_OVERRIDE = None


__all__ = [
    "init_langsmith_tracer",
    "get_langsmith_tracer",
    "is_langsmith_enabled",
    "get_langsmith_callbacks",
    "_reset_for_tests",
]