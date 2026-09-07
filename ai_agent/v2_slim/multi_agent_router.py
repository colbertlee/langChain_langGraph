"""
v2.0 slim — multi_agent 统一入口（v2.10+ 不再支持 LEGACY_MODE 切换）

历史：本模块曾作为"多 Agent 入口"统一门面，根据 LEGACY_MODE 在
v2_slim.multi_agent_v2 与 老 multi_agent.AgentOrchestrator 间切换。
v2.10 起，LEGACY 路径与 _legacy.py 模块已全部移除；仅保留 v2 slim。

编排模式：
  - SEQUENTIAL / SUPERVISOR → 走 v2_slim.multi_agent_v2（LangGraph StateGraph）
  - PARALLEL / HIERARCHICAL / FANOUT → 抛 NotImplementedError（frozen in v2 slim）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def create_sequential_agent(*args, **kwargs):
    """v2 slim 顺序编排器。"""
    from v2_slim.multi_agent_v2 import create_sequential_agent as _impl
    return _impl(*args, **kwargs)


def create_supervisor_agent(*args, **kwargs):
    """v2 slim Supervisor 编排器。"""
    from v2_slim.multi_agent_v2 import create_supervisor_agent as _impl
    return _impl(*args, **kwargs)


def run_workflow(mode: str, tasks: List[Dict[str, Any]], **kwargs) -> Any:
    """统一工作流入口（v2 slim only）。

    Args:
        mode: OrchestrationMode 字符串值（"sequential" / "supervisor" /
              "parallel" / "hierarchical" / "fanout"）。
        tasks: 任务列表（dict 列表，结构依 mode 而异）。
    """
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
    "run_workflow",
]
