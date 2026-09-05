"""
v2.0 slim — 老 permission.py 的 LEGACY 兜底

老 permission.py 中的 RBAC 模型（Role / Policy / PermissionGuard）已并入 approval.py。
本模块仅作为兼容层存在：当 config.LEGACY_MODE=True 时透传老符号；
否则请从 v2_slim.approval 导入 Role / Policy。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from permission import (  # type: ignore
        Role,
        Policy,
        PermissionDecision,
        PermissionGuard,
        get_permission_guard as _legacy_get_permission_guard,
    )
    _HAS_LEGACY = True
except Exception as e:  # pragma: no cover
    logger.warning("LEGACY permission 不可用：%s", e)
    _HAS_LEGACY = False


def get_permission_guard(*args, **kwargs):
    if not _HAS_LEGACY:
        logger.warning("LEGACY permission_guard 不可用，建议切到 v2_slim.approval")
        return None
    return _legacy_get_permission_guard(*args, **kwargs)


__all__ = ["Role", "Policy", "PermissionDecision", "PermissionGuard", "get_permission_guard"]