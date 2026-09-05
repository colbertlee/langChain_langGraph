"""
v2.0 slim — 老 memory_store.py 的 LEGACY 兜底

当 config.LEGACY_MODE=True 时，透传老 memory_store 的符号（4 类型）；
否则所有调用由 memory_store_v2 接管（2 类型）。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from memory_store import (  # type: ignore
        MemoryType,
        MemoryImportance,
        MemoryItem,
        MemoryDatabase,
        ShortTermMemory,
        LongTermMemory,
        EpisodicMemory,
        ProceduralMemory,
        MemoryStore,
        get_memory_store as _legacy_get_memory_store,
        reset_memory_store as _legacy_reset_memory_store,
    )
    _HAS_LEGACY = True
except Exception as e:  # pragma: no cover
    logger.warning("LEGACY memory_store 不可用：%s", e)
    _HAS_LEGACY = False


def get_memory_store(*args, **kwargs):
    if not _HAS_LEGACY:
        logger.warning("LEGACY memory_store 不可用，建议切换到 memory_store_v2")
        return None
    return _legacy_get_memory_store(*args, **kwargs)


def reset_memory_store(*args, **kwargs):
    if not _HAS_LEGACY:
        return
    _legacy_reset_memory_store(*args, **kwargs)


__all__ = [
    "MemoryType", "MemoryImportance", "MemoryItem", "MemoryDatabase",
    "ShortTermMemory", "LongTermMemory", "EpisodicMemory", "ProceduralMemory",
    "MemoryStore", "get_memory_store", "reset_memory_store",
]