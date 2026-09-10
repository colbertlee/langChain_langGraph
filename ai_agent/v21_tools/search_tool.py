"""search_tool — v2.1 联网搜索工具

依赖：
  - duckduckgo_search  —— 默认后端，零配置、免费
  - tavily             —— 可选，TAVILY_API_KEY 启用

接口：
  web_search(query: str, max_results: int = 5) -> str
    返回 Markdown 形式的搜索结果摘要（前 N 条），便于注入 Agent context。

设计：
  - 强容错：依赖缺失 / 网络错误 / 超时 → 返回简短错误信息而非抛栈
  - 单函数即可直接当作 Tool 暴露；如需 LangChain StructuredTool 包装，
    调用方自行包一层
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)


def _try_duckduckgo():
    """duckduckgo_search ≥ 4.x 接口；缺依赖返回 None。"""
    try:
        from duckduckgo_search import DDGS  # type: ignore

        return DDGS
    except Exception:
        try:
            # 兼容旧版本（duckduckgo < 4.x）
            from duckduckgo_search import ddg  # type: ignore

            return ddg
        except Exception:
            return None


def _search_duckduckgo(query: str, max_results: int) -> List[dict]:
    DDGS = _try_duckduckgo()
    if DDGS is None:
        raise RuntimeError(
            "duckduckgo_search 未安装：pip install duckduckgo-search"
        )
    out: List[dict] = []
    # duckduckgo_search 5.x 用 __enter__；4.x 用 context manager
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                out.append(
                    {
                        "title": r.get("title") or "",
                        "snippet": r.get("body") or r.get("snippet") or "",
                        "url": r.get("href") or r.get("url") or "",
                    }
                )
    except Exception as e:
        # 兜底：旧 API
        try:
            results = DDGS.text(query, max_results=max_results)
            for r in results:
                out.append(
                    {
                        "title": r.get("title") or "",
                        "snippet": r.get("body") or r.get("snippet") or "",
                        "url": r.get("href") or r.get("url") or "",
                    }
                )
        except Exception:
            raise e
    return out


def _search_tavily(query: str, max_results: int, api_key: str) -> List[dict]:
    """Tavily API：要求 requests。"""
    try:
        import requests  # type: ignore
    except Exception:
        raise RuntimeError("tavily 模式需要 requests：pip install requests")
    r = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        },
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    out: List[dict] = []
    for item in data.get("results", []):
        out.append(
            {
                "title": item.get("title") or "",
                "snippet": item.get("content") or "",
                "url": item.get("url") or "",
            }
        )
    return out


def _format_markdown(results: List[dict], query: str) -> str:
    if not results:
        return f"(无搜索结果: {query})"
    lines = [f"## 搜索结果: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title") or "(无标题)"
        url = r.get("url") or ""
        snippet = (r.get("snippet") or "").strip().replace("\n", " ")
        if len(snippet) > 280:
            snippet = snippet[:280] + "..."
        lines.append(f"### {i}. {title}")
        if url:
            lines.append(f"- 来源: {url}")
        if snippet:
            lines.append(f"- 摘要: {snippet}")
        lines.append("")
    return "\n".join(lines).strip()


def web_search(query: str, max_results: int = 5, backend: Optional[str] = None) -> str:
    """联网搜索：返回 Markdown 摘要。

    Args:
        query: 搜索关键词
        max_results: 最多返回结果数（默认 5）
        backend: 'duckduckgo' | 'tavily' | None（自动）
                 None 时优先 tavily（若 TAVILY_API_KEY）否则 duckduckgo

    Returns:
        Markdown 字符串；任何错误都被包装为带 [search error] 前缀的提示，
        不会向上抛异常（避免拖垮 Agent 主循环）。
    """
    if not query or not query.strip():
        return "(空 query，跳过搜索)"

    # 选择后端
    if backend is None:
        if os.environ.get("TAVILY_API_KEY"):
            backend = "tavily"
        else:
            backend = "duckduckgo"

    try:
        if backend == "tavily":
            api_key = os.environ.get("TAVILY_API_KEY", "")
            if not api_key:
                return "[search error] TAVILY_API_KEY 未设置"
            results = _search_tavily(query, max_results, api_key)
        else:
            results = _search_duckduckgo(query, max_results)
        return _format_markdown(results, query)
    except Exception as e:
        logger.warning(f"web_search failed: {e}")
        return f"[search error] {type(e).__name__}: {e}"


__all__ = ["web_search"]
