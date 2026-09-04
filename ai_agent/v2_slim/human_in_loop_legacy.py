"""
v2.0 slim — 老 human_in_loop.py 的 LEGACY 兜底

已并入 v2_slim.approval.ApprovalGate。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from human_in_loop import (  # type: ignore
        HookPoint,
        HITLPolicy,
        ApprovalDecision,
        ApprovalRequest,
        HITLGuard,
        get_hitl_guard as _legacy_get_hitl_guard,
    )
    _HAS_LEGACY = True
except Exception as e:  # pragma: no cover
    logger.warning("LEGACY human_in_loop 不可用：%s", e)
    _HAS_LEGACY = False


def get_hitl_guard(*args, **kwargs):
    if not _HAS_LEGACY:
        logger.warning("LEGACY hitl_guard 不可用，建议切到 v2_slim.approval")
        return None
    return _legacy_get_hitl_guard(*args, **kwargs)


__all__ = [
    "HookPoint", "HITLPolicy", "ApprovalDecision",
    "ApprovalRequest", "HITLGuard", "get_hitl_guard",
]