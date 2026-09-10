"""v2.1 — Agent Tool Router

负责：
  1) 根据 v2.1 tool 名字列表返回对应的 LangChain StructuredTool 实例
  2) 缓存：同一组 names 只解析一次（同进程内）
  3) 容错：未知名字直接跳过（旧版 tool 名 / 已删除工具）

设计原则：
  - 强依赖 v21_tools.TOOL_REGISTRY；不引入额外元数据
  - 线程安全（用 RLock 保护缓存）
  - 解析结果可被快速清空（clear_cache），便于单测隔离
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional


_CACHE_LOCK = threading.RLock()
_CACHE: Dict[str, Any] = {}  # tool_name -> StructuredTool


def _build_tool_entry(name: str) -> Optional[Any]:
    """从 v21_tools.TOOL_REGISTRY 构造一个 LangChain StructuredTool-like 对象。"""
    try:
        from v21_tools import TOOL_REGISTRY

        meta = TOOL_REGISTRY.get(name)
    except Exception:
        meta = None
    if not meta:
        return None
    try:
        from langchain_core.tools import StructuredTool

        func = meta.get("func") if isinstance(meta, dict) else None
        if not callable(func):
            return None
        args_schema = meta.get("args_schema") if isinstance(meta, dict) else None

        def _wrapped_invoke(**kwargs):
            """统一走 v21_tools 的 _invoke 风格：dict 结果走 format_result_md 转为 markdown。"""
            try:
                result = func(**kwargs)
            except TypeError:
                # 兼容：忽略多余 kwargs
                result = func(
                    kwargs.get("query") or kwargs.get("code") or ""
                )
            if isinstance(result, dict):
                try:
                    from v21_tools import format_result_md
                    return format_result_md(result)
                except Exception:
                    # v21_tools 无 format_result_md 时降级为 JSON
                    import json as _json
                    try:
                        return _json.dumps(result, ensure_ascii=False, default=str)
                    except Exception:
                        return str(result)
            return str(result)

        return StructuredTool.from_function(
            func=_wrapped_invoke,
            name=meta.get("name", name),
            description=meta.get("description", ""),
            args_schema=args_schema,
        )
    except Exception:
        return None


def _resolve_one(name: str) -> Optional[Any]:
    """解析单个 tool 名（命中缓存直接返回）。"""
    name = str(name or "").strip()
    if not name:
        return None
    with _CACHE_LOCK:
        if name in _CACHE:
            return _CACHE[name]
    # v2.2.2 — session 感知工具（knowledge_search）走独立路径
    if name == "knowledge_search":
        try:
            from v21_tools.rag_tool import get_knowledge_search_tool

            entry = get_knowledge_search_tool()
            if entry is not None:
                with _CACHE_LOCK:
                    _CACHE[name] = entry
            return entry
        except Exception:
            return None
    entry = _build_tool_entry(name)
    if entry is not None:
        with _CACHE_LOCK:
            _CACHE[name] = entry
    return entry


def resolve_tools(names: Optional[List[str]]) -> List[Any]:
    """v2.1 — 根据 names 列表解析 LangChain tool 实例。

    - 未知名字静默跳过
    - 重复名字只返回一次
    - 命中缓存：直接复用同一个 StructuredTool 对象
    - v2.2.2 — 支持 knowledge_search（session-aware tool）
    """
    out: List[Any] = []
    seen: set = set()
    for raw in names or []:
        n = str(raw or "").strip()
        if not n or n in seen:
            continue
        seen.add(n)
        tool = _resolve_one(n)
        if tool is not None:
            out.append(tool)
    return out


def clear_cache() -> None:
    """v2.1 — 测试辅助：清空解析缓存。"""
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = {}


__all__ = ["resolve_tools", "clear_cache"]
