"""
v2.0 slim — 老 multi_agent.py 的 LEGACY 兜底

透传老 multi_agent 的符号（OrchestrationMode / AgentOrchestrator / Task / Workflow ...）。
已裁剪的 PARALLEL/HIERARCHICAL/FANOUT 调用点保留 5 种枚举值，但 run_parallel 等函数
由 multi_agent_v2.frozen 抛 NotImplementedError。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from multi_agent import (  # type: ignore
        OrchestrationMode,
        TaskStatus,
        Task,
        Workflow,
        TaskDelegate,
        AgentOrchestrator,
        get_orchestrator as _legacy_get_orchestrator,
        reset_orchestrator as _legacy_reset_orchestrator,
    )
    _HAS_LEGACY = True
except Exception as e:  # pragma: no cover
    logger.warning("LEGACY multi_agent 不可用：%s", e)
    _HAS_LEGACY = False


def get_orchestrator(*args, **kwargs):
    if not _HAS_LEGACY:
        logger.warning("LEGACY multi_agent 不可用，建议切到 v2_slim.multi_agent_v2")
        return None
    return _legacy_get_orchestrator(*args, **kwargs)


def reset_orchestrator(*args, **kwargs):
    if not _HAS_LEGACY:
        return
    _legacy_reset_orchestrator(*args, **kwargs)


__all__ = [
    "OrchestrationMode", "TaskStatus", "Task", "Workflow",
    "TaskDelegate", "AgentOrchestrator", "get_orchestrator", "reset_orchestrator",
]