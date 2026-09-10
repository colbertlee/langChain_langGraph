"""ai_agent.v21_tools — v2.1 新增工具 + LangChain StructuredTool 封装。

为什么单独建包：
  - 旧 ai_agent/tools.py（顶层模块）已存在大量工具实现；
    包名 v21_tools 避免与模块同名导致 Python import 歧义。

对外暴露：
  - web_search(query: str, max_results: int = 5) -> str
  - python_interpreter(code: str, timeout: int = 10) -> dict
  - format_result_md(result: dict) -> str
  - get_langchain_tools(tool_names: Optional[List[str]] = None)
       返回 LangChain StructuredTool 列表；None 表示全部。

StructuredTool.from_function 缺失时优雅降级：返回带 _run/_arun 的
最小 BaseTool 子类（不让 LangChain 链断掉）。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional

from .search_tool import web_search
from .code_interpreter import python_interpreter, format_result_md

# v2.3.1 — OTel Span 包裹的 python_interpreter；优先使用，无 SDK 时降级
try:
    from .python_sandbox import python_interpreter_with_trace

    _TRACED_PY_INTERPRETER = python_interpreter_with_trace
except Exception:  # pragma: no cover
    _TRACED_PY_INTERPRETER = None

logger = logging.getLogger(__name__)

# ============================================================
# 注册表：tool_id → (callable, 描述, args schema)
# ============================================================

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "web_search": {
        "func": web_search,
        "name": "web_search",
        "description": (
            "联网搜索给定关键词，返回前 N 条结果的标题/摘要/URL。"
            "当用户问题涉及实时信息、最新事件或你不熟悉的具体数据时调用。"
        ),
        "args_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {
                    "type": "integer",
                    "description": "最多返回结果数（默认 5）",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["query"],
        },
    },
    "python_interpreter": {
        "func": _TRACED_PY_INTERPRETER or python_interpreter,
        "name": "python_interpreter",
        "description": (
            "在受限沙箱中执行 Python 代码。返回 stdout / stderr / 生成的图片 URL。"
            "支持 matplotlib 等图片输出（自动捕获为 /uploads/... 静态资源）。"
            "有 10 秒超时限制。"
        ),
        "args_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "要执行的 Python 源代码"},
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数（默认 10）",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 30,
                },
            },
            "required": ["code"],
        },
        # v2.2.1: HITL 风险标记 —— python_interpreter 在沙箱里执行任意 Python 代码，
        # 虽受 subprocess 隔离 + 10s timeout，但仍属"在用户机器上运行代码"的高风险操作，
        # 默认要求人工审批。其它工具（如 web_search）若需标记，可同样加 requires_approval=True。
        "requires_approval": True,
    },
}


ALL_TOOL_NAMES = list(TOOL_REGISTRY.keys())


# ============================================================
# StructuredTool 构造（容错）
# ============================================================


def _build_structured_tool(entry: dict[str, Any]):
    """从 registry entry 构造 LangChain StructuredTool。

    优先用 langchain_core.tools.StructuredTool；缺失时降级为最小 BaseTool。
    """
    try:
        from langchain_core.tools import StructuredTool  # type: ignore

        def _invoke(**kwargs) -> str:
            try:
                result = entry["func"](**kwargs)
            except TypeError:
                # 兼容：忽略多余 kwargs
                result = entry["func"](kwargs.get("query") or kwargs.get("code") or "")
            # python_interpreter 返回 dict，转 Markdown 便于注入
            if isinstance(result, dict):
                return format_result_md(result)
            return str(result)

        return StructuredTool.from_function(
            func=_invoke,
            name=entry["name"],
            description=entry["description"],
        )
    except Exception as e:
        logger.warning(f"StructuredTool unavailable, falling back to BaseTool: {e}")
        return _build_minimal_tool(entry)


def _build_minimal_tool(entry: dict[str, Any]):
    """不依赖 langchain 的最小 Tool 实现——足够让 ReAct loop 不崩。"""
    from typing import Optional as _Opt

    class _MinimalTool:
        name = entry["name"]
        description = entry["description"]
        args_schema = entry["args_schema"]

        def _run(self, **kwargs) -> str:
            try:
                result = entry["func"](**kwargs)
            except TypeError:
                result = entry["func"](
                    kwargs.get("query") or kwargs.get("code") or ""
                )
            if isinstance(result, dict):
                return format_result_md(result)
            return str(result)

        async def _arun(self, **kwargs) -> str:
            return self._run(**kwargs)

    return _MinimalTool()


# ============================================================
# 对外接口
# ============================================================


def get_langchain_tools(tool_names: Optional[List[str]] = None) -> List[Any]:
    """根据 tool_names 返回对应的 LangChain Tool 实例。

    Args:
        tool_names: 工具 id 列表（如 ['web_search', 'python_interpreter']）；
                    None / 空 → 返回全部已注册工具。
    Returns:
        Tool 实例列表（可能为空）。
    """
    if not tool_names:
        names = list(TOOL_REGISTRY.keys())
    else:
        names = [n for n in tool_names if n in TOOL_REGISTRY]
    return [_build_structured_tool(TOOL_REGISTRY[n]) for n in names]


def get_tool_specs(tool_names: Optional[List[str]] = None) -> List[dict]:
    """返回工具的 JSON Schema 描述（不需要构造 Tool 实例，便于跨进程透传）。"""
    if not tool_names:
        names = list(TOOL_REGISTRY.keys())
    else:
        names = [n for n in tool_names if n in TOOL_REGISTRY]
    return [
        {
            "name": TOOL_REGISTRY[n]["name"],
            "description": TOOL_REGISTRY[n]["description"],
            "args_schema": TOOL_REGISTRY[n]["args_schema"],
        }
        for n in names
    ]


# ============================================================
# v2.2.2 — Session 工具集（含 RAG knowledge_search）
# ============================================================


# v2.2.2 专用 tool 列表（需要 session 上下文，不进 TOOL_REGISTRY）
SESSION_AWARE_TOOLS = ("knowledge_search",)


def build_session_tools(tool_names: Optional[List[str]] = None) -> List[Any]:
    """v2.2.2 — 给当前 session 构造工具列表（含 knowledge_search 等）。

    Args:
      tool_names: 工具 id 列表
        - 普通工具（web_search / python_interpreter）走 TOOL_REGISTRY
        - knowledge_search 由 rag_tool 单独构造（StructuredTool）
    """
    if not tool_names:
        names = list(TOOL_REGISTRY.keys()) + list(SESSION_AWARE_TOOLS)
    else:
        names = list(tool_names)
    out: List[Any] = []
    for n in names:
        if n in TOOL_REGISTRY:
            out.append(_build_structured_tool(TOOL_REGISTRY[n]))
        elif n == "knowledge_search":
            try:
                from .rag_tool import get_knowledge_search_tool

                out.append(get_knowledge_search_tool())
            except Exception as e:
                logger.warning(f"knowledge_search unavailable: {e}")
        # else: 忽略未知 tool
    return out


__all__ = [
    "web_search",
    "python_interpreter",
    "format_result_md",
    "get_langchain_tools",
    "get_tool_specs",
    "TOOL_REGISTRY",
    "ALL_TOOL_NAMES",
    "build_session_tools",
    "SESSION_AWARE_TOOLS",
]
