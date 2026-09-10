"""P0-3 — Tools 单一真相（Single Source of Truth）

历史背景：
  - ai_agent/tools.py（顶层模块，v1）定义 7 个细粒度工具；
  - ai_agent/v2_slim/tools_v2.py 定义 6 个复合工具，是当前 LangGraph 主 agent 入口；
  - ai_agent/v21_tools/__init__.py 里 TOOL_REGISTRY 又把 web_search / python_interpreter
    注册成 StructuredTool，用于 per-session bind_tools_for_session；
  - ai_agent/app.py:1015 /api/tools 端点读 proxy.get_tools_list()，与 v21_tools.TOOL_REGISTRY
    并不同源。

问题：
  - "前端 /api/tools 列表" vs "实际 LangGraph agent 工具" 不同源；
  - 测试断言 'tools.py:get_all_tools()' 含 7 个，但运行时 agent 已迁到 v2_slim，
    老入口成"死代码 + 误用风险"。

本模块职责：
  1) 收口：所有「我能用哪些工具」的查询都走本模块；
     - resolve_tools_for_runtime()：返回 LangGraph 主 agent 的 Tool 实例
       （= v2_slim 的 6 个复合工具 + knowledge_search（按 session 注入））
     - get_tool_specs()：返回 {name, description, args_schema, source, requires_approval}
       给前端 /api/tools + 测试断言
     - get_knowledge_search_tool()：统一从 v21_tools.rag_tool 取
  2) 废弃标记：
     - ai_agent/tools.py:get_all_tools() 仍保留但加 deprecation warning，
       在 v2.4 / v2.5 移除。
  3) 测试钩子：
     - reset_for_tests() 清空所有 module-level 单例。

设计原则：
  - 不引入新依赖（仅复用现有 v21_tools / v2_slim / rag_service）；
  - 同步所有入口 (agent.py / app.py /api/tools / api.py / AgentProxy.get_tools_list)
    都走本模块；
  - 前端契约不变（{tools:[{name, description}]}）。

⚠️ 严禁再添加「第二条真相」：新增工具请改 v2_slim/tools_v2.py 或 v21_tools.TOOL_REGISTRY，
   然后本模块的 resolve_* 会自动覆盖到。
"""
from __future__ import annotations

import logging
import threading
import warnings
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================
# 内部：延迟 import + 缓存（避免循环依赖）
# ============================================================
_IMPORT_LOCK = threading.RLock()
_V2_TOOLS_CACHE: Optional[List[Any]] = None
_KNOWLEDGE_SEARCH_CACHE: Optional[Any] = None


def _load_v2_tools() -> List[Any]:
    """加载 v2_slim 的 6 个复合工具（LangGraph 主 agent 用的入口）。"""
    global _V2_TOOLS_CACHE
    with _IMPORT_LOCK:
        if _V2_TOOLS_CACHE is None:
            from v2_slim.tools_v2 import get_all_tools_v2
            _V2_TOOLS_CACHE = list(get_all_tools_v2() or [])
        return _V2_TOOLS_CACHE


def _load_knowledge_search_tool() -> Any:
    """加载 knowledge_search（per-session KB 工具，依赖 rag_service）。"""
    global _KNOWLEDGE_SEARCH_CACHE
    with _IMPORT_LOCK:
        if _KNOWLEDGE_SEARCH_CACHE is None:
            try:
                from v21_tools.rag_tool import get_knowledge_search_tool
                _KNOWLEDGE_SEARCH_CACHE = get_knowledge_search_tool()
            except Exception as e:  # pragma: no cover
                logger.warning(f"knowledge_search tool unavailable: {e}")
                _KNOWLEDGE_SEARCH_CACHE = None
        return _KNOWLEDGE_SEARCH_CACHE


# ============================================================
# P0-3 对外 API
# ============================================================


def resolve_tools_for_runtime(*, with_knowledge_search: bool = True) -> List[Any]:
    """返回 LangGraph 主 agent 运行时实际可用的 LangChain Tool 实例列表。

    Args:
      with_knowledge_search: 是否把 knowledge_search 一起注入（默认 True；
        per-session bind 场景下保持向后兼容；如果只想要 v2 复合工具可传 False）。

    Returns:
      list[Tool] —— 去重、按 v2 复合工具 + knowledge_search 顺序。
    """
    out: List[Any] = []
    seen_names: set = set()
    for t in _load_v2_tools():
        n = getattr(t, "name", None)
        if n and n in seen_names:
            continue
        out.append(t)
        if n:
            seen_names.add(n)

    if with_knowledge_search:
        ks = _load_knowledge_search_tool()
        if ks is not None:
            n = getattr(ks, "name", None)
            if n and n not in seen_names:
                out.append(ks)
                seen_names.add(n)
    return out


def get_tool_names() -> List[str]:
    """当前 runtime 注册的工具名列表（与 resolve_tools_for_runtime 同源）。"""
    return [getattr(t, "name", "") for t in resolve_tools_for_runtime() if getattr(t, "name", None)]


def get_tool_specs() -> List[Dict[str, Any]]:
    """返回 {name, description, args_schema, source, requires_approval} 列表。

    单一真相：
      - v2_slim.tools_v2 的 6 个复合工具 → source="v2_slim"
      - knowledge_search → source="v21_tools.rag_tool"
    """
    out: List[Dict[str, Any]] = []
    seen: set = set()

    # 1) v2_slim 复合工具
    for t in _load_v2_tools():
        name = getattr(t, "name", None)
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(
            {
                "name": name,
                "description": (getattr(t, "description", "") or "").strip(),
                "args_schema": getattr(t, "args", None) or getattr(t, "args_schema", None),
                "source": "v2_slim",
                "requires_approval": False,
            }
        )

    # 2) knowledge_search
    ks = _load_knowledge_search_tool()
    if ks is not None:
        name = getattr(ks, "name", None)
        if name and name not in seen:
            seen.add(name)
            out.append(
                {
                    "name": name,
                    "description": (getattr(ks, "description", "") or "").strip(),
                    "args_schema": getattr(ks, "args", None) or getattr(ks, "args_schema", None),
                    "source": "v21_tools.rag_tool",
                    "requires_approval": False,
                }
            )

    return out


def resolve_tool_by_name(name: str) -> Optional[Any]:
    """按名字取单个 Tool 实例（找不到返回 None）。

    与 agent_tool_router.resolve_tools 的区别：本函数查的是 v2_slim + knowledge_search
    这条「主链路」（agent_tool_router 查的是 v21_tools.TOOL_REGISTRY 那条辅助链路，
    用于 bind_tools_for_session 时追加 web_search / python_interpreter）。
    """
    if not name:
        return None
    for t in resolve_tools_for_runtime():
        if getattr(t, "name", None) == name:
            return t
    return None


# ============================================================
# 测试钩子
# ============================================================


def reset_for_tests() -> None:  # pragma: no cover
    """清空 module-level 缓存，便于单测隔离。"""
    global _V2_TOOLS_CACHE, _KNOWLEDGE_SEARCH_CACHE
    with _IMPORT_LOCK:
        _V2_TOOLS_CACHE = None
        _KNOWLEDGE_SEARCH_CACHE = None


# ============================================================
# 旧入口兼容（deprecated）
# ============================================================


def get_legacy_tools_deprecated() -> List[Any]:  # pragma: no cover
    """兼容层：旧的 tools.py:get_all_tools()。

    ⚠️ 仅供向后兼容；新代码请用 resolve_tools_for_runtime()。
    行为差异：旧入口返回 7 个细粒度工具（query_kb / load_kb / read_file / ...），
    这些是 v1 历史实现；运行时 LangGraph 主 agent 已迁到 v2_slim，
    所以这条路径实际不再被 agent.py / app.py 调用。
    """
    warnings.warn(
        "tools.py:get_all_tools() / tools_registry.get_legacy_tools_deprecated() "
        "已废弃，请改用 tools_registry.resolve_tools_for_runtime() 或 get_tool_specs(). "
        "计划在 v2.5 移除。",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        from tools import get_all_tools as _legacy_get_all_tools
        return list(_legacy_get_all_tools() or [])
    except Exception as e:  # pragma: no cover
        logger.warning(f"legacy tools unavailable: {e}")
        return []


__all__ = [
    "resolve_tools_for_runtime",
    "get_tool_names",
    "get_tool_specs",
    "resolve_tool_by_name",
    "reset_for_tests",
    "get_legacy_tools_deprecated",
]
