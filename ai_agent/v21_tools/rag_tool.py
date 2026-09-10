"""
v2.2.2 — knowledge_search Tool (Milestone 2.2.2)

LangChain StructuredTool 形式的知识库检索工具。
让 Agent 在 ReAct 循环中自主调用本地 Chroma KB。

设计：
  - 入参：query (str) + top_k (int, default 3)
  - 行为：从当前 session_id 筛选向量切片（强隔离）→ 重构 Markdown 结果 → 注入
  - 依赖：rag_service.get_rag_service()（单例）
  - session_id 解析顺序：
      1) kwargs 中显式传入 session_id（测试友好）
      2) kwargs 中含 thread_id（LangGraph 风格）
      3) config["configurable"]["thread_id"]（agent invoke 上下文）
      4) fallback "default"
  - 不进入 TOOL_REGISTRY（因为它需要 session_id）；agent.py 单独通过 v21_tools.get_langchain_tools(...)
    或 build_session_tools(...) 注册到 per-session tool 列表。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 1) 核心检索函数（供 tool 调用 + 测试直接 import）
# ============================================================


def _extract_session_id(
    *,
    explicit: Optional[str] = None,
    kwargs: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """v2.2.2 — 从 kwargs / config 中提取 session_id（多层兼容）。"""
    if explicit:
        return str(explicit)
    if kwargs:
        for k in ("session_id", "thread_id"):
            v = kwargs.get(k)
            if v:
                return str(v)
    if isinstance(config, dict):
        cfg = config.get("configurable") or {}
        for k in ("thread_id", "session_id"):
            v = cfg.get(k)
            if v:
                return str(v)
    return "default"


def knowledge_search_impl(
    query: str,
    top_k: int = 3,
    *,
    session_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    min_score: float = 0.15,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """v2.2.2 — 直接调用入口。

    Args:
      query: 用户问题
      top_k: top-k
      session_id: 显式 session（优先）
      config: LangGraph config（含 configurable.thread_id）
      min_score: 相似度下限（默认 0.05，过滤低质量匹配）
      **kwargs: 兼容从 tool _invoke 传进来的 thread_id / session_id

    Returns:
      list of {text, file_id, file_name, chunk_id, score, page}
    """
    sid = _extract_session_id(
        explicit=session_id, kwargs=kwargs, config=config
    )
    if not query or not str(query).strip():
        return []
    try:
        from rag_service import get_rag_service

        svc = get_rag_service()
        results = svc.search(
            session_id=sid, query=str(query), top_k=int(top_k), min_score=float(min_score)
        )
    except Exception as e:
        logger.warning(f"knowledge_search_impl failed: {e}")
        return []
    return results


# ============================================================
# 2) Markdown 渲染
# ============================================================


def render_results_markdown(
    results: List[Dict[str, Any]], query: str = ""
) -> str:
    """v2.2.2 — 把检索结果列表渲染成 Markdown（供 Agent 注入到 context）。"""
    if not results:
        return (
            f"[knowledge_search] 未找到与 '{query}' 相关的知识库内容。"
            if query
            else "[knowledge_search] 无结果。"
        )
    lines: List[str] = [
        f"[knowledge_search] 检索到 {len(results)} 条相关片段（按相似度排序）："
    ]
    for i, r in enumerate(results, 1):
        file_name = r.get("file_name") or r.get("file_id") or "unknown"
        score = r.get("score", 0.0)
        page = r.get("page")
        page_str = f" (p.{page})" if page is not None else ""
        chunk_id = r.get("chunk_id", -1)
        text = (r.get("text") or "").strip()
        if len(text) > 800:
            text = text[:800] + "..."
        lines.append(
            f"\n--- [{i}] {file_name}{page_str} · chunk#{chunk_id} · "
            f"score={float(score):.3f} ---\n{text}"
        )
    return "\n".join(lines)


# ============================================================
# 3) StructuredTool 构造
# ============================================================


_KNOWLEDGE_SEARCH_DESCRIPTION = (
    "检索当前会话已索引的本地知识库（PDF / DOCX / TXT / Markdown / CSV 等）。"
    "基于 ChromaDB 向量相似度 + 强 session 隔离。"
    "返回 top_k 条最相关的文档片段（含来源文件名 / chunk_id / 相似度）。"
    "当用户问题涉及已上传附件的知识库内容时，优先调用本工具。"
    "注意：不会跨 session 检索——只能看到当前会话已索引的文件。"
)

_KNOWLEDGE_SEARCH_ARGS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索关键词或问题（中文/英文均可）",
        },
        "top_k": {
            "type": "integer",
            "description": "返回前 N 条（默认 3，最大 10）",
            "default": 3,
            "minimum": 1,
            "maximum": 10,
        },
    },
    "required": ["query"],
}


def knowledge_search_func(
    query: str,
    top_k: int = 3,
    *,
    config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> str:
    """v2.2.2 — StructuredTool 调用的入口。返回 Markdown 字符串。"""
    # 从 config / kwargs 提 session_id（避免重复传）
    sid = _extract_session_id(kwargs=kwargs, config=config)
    # 移除 kwargs 中的 session_id / thread_id，避免传给 knowledge_search_impl 时冲突
    passthrough = {
        k: v for k, v in kwargs.items()
        if k not in ("session_id", "thread_id")
    }
    results = knowledge_search_impl(
        query=query, top_k=top_k, session_id=sid, config=config, **passthrough
    )
    return render_results_markdown(results, query=query)


def build_knowledge_search_tool() -> Any:
    """v2.2.2 — 构造 StructuredTool 形式的 knowledge_search 工具。

    优先用 langchain_core.tools.StructuredTool.from_function；缺失时降级为
    _MinimalKnowledgeSearch（让 ReAct 循环不崩）。
    """
    name = "knowledge_search"
    description = _KNOWLEDGE_SEARCH_DESCRIPTION
    args_schema = _KNOWLEDGE_SEARCH_ARGS_SCHEMA

    # 优先 StructuredTool
    try:
        from langchain_core.tools import StructuredTool  # type: ignore

        def _invoke(**kwargs) -> str:
            # StructuredTool.from_function 调用形式：kwargs 包含 query / top_k
            return knowledge_search_func(
                query=kwargs.get("query", ""),
                top_k=int(kwargs.get("top_k", 3) or 3),
            )

        tool = StructuredTool.from_function(
            func=_invoke,
            name=name,
            description=description,
        )
        # 挂载 args_schema
        if args_schema and hasattr(tool, "args"):
            try:
                tool.args = args_schema
            except Exception:
                pass
        return tool
    except Exception as e:
        logger.warning(
            f"StructuredTool unavailable for knowledge_search, fallback to minimal: {e}"
        )

    # 降级：最小 BaseTool-like
    class _MinimalKnowledgeSearch:
        name = name
        description = description
        args_schema = args_schema

        def _run(self, **kwargs) -> str:
            return knowledge_search_func(
                query=kwargs.get("query", ""),
                top_k=int(kwargs.get("top_k", 3) or 3),
            )

        async def _arun(self, **kwargs) -> str:
            return self._run(**kwargs)

    return _MinimalKnowledgeSearch()


# ============================================================
# 4) module-level 单例（避免重复构造）
# ============================================================


_TOOL_INSTANCE: Any = None
_TOOL_LOCK = threading.Lock()


def get_knowledge_search_tool() -> Any:
    """v2.2.2 — 单例 StructuredTool。"""
    global _TOOL_INSTANCE
    with _TOOL_LOCK:
        if _TOOL_INSTANCE is None:
            _TOOL_INSTANCE = build_knowledge_search_tool()
        return _TOOL_INSTANCE


def reset_knowledge_search_tool_instance() -> None:
    """v2.2.2 — 测试辅助。"""
    global _TOOL_INSTANCE
    with _TOOL_LOCK:
        _TOOL_INSTANCE = None


__all__ = [
    "knowledge_search_impl",
    "render_results_markdown",
    "knowledge_search_func",
    "build_knowledge_search_tool",
    "get_knowledge_search_tool",
    "reset_knowledge_search_tool_instance",
]
