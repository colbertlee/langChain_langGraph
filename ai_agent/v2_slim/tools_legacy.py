"""
v2.0 slim — 老 tools.py 的 LEGACY 兜底

当 config.LEGACY_MODE=True 时，本模块透传老 tools.py 的全部符号；
否则所有调用统一走 v2_slim.tools_v2 的 6 个复合工具。

为什么不在 tools.py 顶层用 if/else 切换？
→ tools.py 已经被 agent.py 大量 import（在 from tools import ... 处直接拿符号），
  在顶层加 if 会带来 sys.modules 缓存污染。独立 legacy 模块 + agent.py 入口切换
  是更干净的方案。
"""
from __future__ import annotations

import logging
from typing import List, Any

logger = logging.getLogger(__name__)

try:
    from tools import (  # type: ignore
        get_all_tools as _legacy_get_all_tools,
        set_rag_instance as _legacy_set_rag_instance,
        get_rag_instance as _legacy_get_rag_instance,
    )
    _HAS_LEGACY = True
except Exception as e:  # pragma: no cover
    logger.warning("LEGACY tools 不可用：%s", e)
    _HAS_LEGACY = False
    def _legacy_get_all_tools(): return []
    def _legacy_set_rag_instance(_): pass
    def _legacy_get_rag_instance(): return None


def get_all_tools() -> List[Any]:
    """LEGACY 入口：直接返回老 tools 列表（18+ 个）。"""
    if not _HAS_LEGACY:
        logger.warning("LEGACY tools 不可用，返回空列表")
    return _legacy_get_all_tools()


def set_rag_instance(rag):
    _legacy_set_rag_instance(rag)


def get_rag_instance():
    return _legacy_get_rag_instance()


__all__ = ["get_all_tools", "set_rag_instance", "get_rag_instance"]