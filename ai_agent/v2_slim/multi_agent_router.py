"""
v2.0 slim — multi_agent 统一路由层

老 multi_agent.py 的 5 种 OrchestrationMode 编排器（SUPERVISOR / PARALLEL /
SEQUENTIAL / HIERARCHICAL / FANOUT）已并入 v2_slim.multi_agent_v2（保留
SEQUENTIAL / SUPERVISOR，其余三种抛 NotImplementedError）。

本模块作为"多 Agent 入口"统一门面：
- LEGACY_MODE=True  → 走老 multi_agent.AgentOrchestrator
- LEGACY_MODE=False → 走 v2_slim.multi_agent_v2 (LangGraph StateGraph)

调用方无需感知 LEGACY 切换。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from config import LEGACY_MODE

logger = logging.getLogger(__name__)


# ============================================================
# v2 slim 入口（无依赖 LEGACY）
# ============================================================

def create_sequential_agent(*args, **kwargs):
    """v2 slim 顺序编排器。"""
    from v2_slim.multi_agent_v2 import create_sequential_agent as _impl
    return _impl(*args, **kwargs)


def create_supervisor_agent(*args, **kwargs):
    """v2 slim Supervisor 编排器。"""
    from v2_slim.multi_agent_v2 import create_supervisor_agent as _impl
    return _impl(*args, **kwargs)


# ============================================================
# LEGACY 入口（透传老 Orchestrator）
# ============================================================

def get_orchestrator(*args, **kwargs):
    """LEGACY 入口：返回老 AgentOrchestrator 实例。"""
    from v2_slim.multi_agent_legacy import get_orchestrator as _impl
    return _impl(*args, **kwargs)


def reset_orchestrator(*args, **kwargs):
    """LEGACY 入口：重置老 Orchestrator 单例。"""
    from v2_slim.multi_agent_legacy import reset_orchestrator as _impl
    return _impl(*args, **kwargs)


# ============================================================
# 路由：根据 LEGACY_MODE 决定调用哪条路径
# ============================================================

def run_workflow(mode: str, tasks: List[Dict[str, Any]], **kwargs) -> Any:
    """统一工作流入口。

    Args:
        mode: OrchestrationMode 字符串值（"sequential" / "supervisor" /
              "parallel" / "hierarchical" / "fanout"）。
        tasks: 任务列表（dict 列表，结构依 mode 而异）。

    Returns:
        v2 slim 模式：CompiledStateGraph.invoke(...) 结果。
        LEGACY 模式：AgentOrchestrator.run_workflow(...) 结果。
    """
    if LEGACY_MODE:
        orch = get_orchestrator()
        if orch is None:
            logger.warning("LEGACY Orchestrator 不可用")
            return None
        return orch.run_workflow(mode, tasks, **kwargs)

    # v2 slim
    if mode == "sequential":
        nodes = [t.get("fn") for t in tasks if t.get("fn")]
        return create_sequential_agent(nodes).invoke({})
    if mode == "supervisor":
        supervisor_llm = kwargs.get("supervisor_llm")
        workers = kwargs.get("workers", {})
        return create_supervisor_agent(
            supervisor_llm=supervisor_llm, workers=workers
        ).invoke({})
    # PARALLEL / HIERARCHICAL / FANOUT：v2 slim 已冻结
    raise NotImplementedError(f"multi_agent mode '{mode}': Frozen in v2.0 slim")


__all__ = [
    "create_sequential_agent",
    "create_supervisor_agent",
    "get_orchestrator",
    "reset_orchestrator",
    "run_workflow",
]