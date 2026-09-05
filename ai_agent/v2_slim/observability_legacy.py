"""
v2.0 slim — 老 observability / monitor / json_log 的 LEGACY 兜底

已并入 v2_slim.telemetry.TelemetrySink。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _safe_import(name: str):
    try:
        mod = __import__(name)
        return mod
    except Exception as e:  # pragma: no cover
        logger.warning("LEGACY %s 不可用：%s", name, e)
        return None


_observability = _safe_import("observability")
_monitor = _safe_import("monitor")
_json_log = _safe_import("json_log")


def get_observability():
    return _observability


def get_monitor():
    return _monitor


def get_json_log():
    return _json_log


__all__ = ["get_observability", "get_monitor", "get_json_log"]