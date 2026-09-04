"""
Harness 用的 Observability 适配层。

问题:ai_agent/observability.py 的真实 API 是
- obs.metrics.counter(name, help).inc(amount, **labels)
- obs.publish_event(event_type, source, trace_id, payload)
而一些测试 fake 或第三方实现可能暴露:
- obs.record_metric(name, value, tags=None)

本模块用 duck typing 探测,统一一个入口:
    record_metric(obs, name, value, tags=None, help="")
    record_event(obs, event_type, source, trace_id=None, payload=None)

约定:
- 全部用 try/except 包裹,失败仅记 debug,绝不抛出
- 返回 bool 表示是否成功上报(便于测试断言)
- 不引入新的第三方依赖
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def record_metric(
    obs: Any,
    name: str,
    value: float = 1.0,
    tags: Optional[Dict[str, Any]] = None,
    help_text: str = "",
) -> bool:
    """往 observability 上报一个 metric。成功返回 True,失败或没匹配 API 返回 False。

    探测顺序:
    1. obs.record_metric(name, value, tags=...)  ← 测试 fake / 第三方兼容接口
    2. obs.metrics.counter(name, help).inc(value, **tags)  ← ai_agent/observability.py 真实 API
    3. obs.counter(name, help).inc(value, **tags)         ← 简化封装(如果存在)
    4. 兜底:不报错,返回 False
    """
    if obs is None:
        return False
    tags = tags or {}

    # 路径 1:测试 fake 的简化接口
    if hasattr(obs, "record_metric"):
        try:
            obs.record_metric(name, value, tags=tags)
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug("[harness.obs] obs.record_metric failed: %s", e)

    # 路径 2:真实 ObservabilityLayer
    metrics = getattr(obs, "metrics", None)
    if metrics is not None and hasattr(metrics, "counter"):
        try:
            counter = metrics.counter(name, help_text)
            # Counter.inc(amount=1.0, **labels)
            counter.inc(float(value), **tags)
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug("[harness.obs] metrics.counter().inc failed: %s", e)

    # 路径 3:某些封装直接在 obs 上暴露 counter/gauge/histogram
    if hasattr(obs, "counter"):
        try:
            c = obs.counter(name, help_text)
            c.inc(float(value), **tags)
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug("[harness.obs] obs.counter().inc failed: %s", e)

    logger.debug("[harness.obs] record_metric: no compatible API on %r", obs)
    return False


def record_event(
    obs: Any,
    event_type: str,
    source: str,
    trace_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> bool:
    """往 observability 事件总线发一个事件。

    探测顺序:
    1. obs.publish_event(event_type, source, trace_id, payload)  ← 真实 API
    2. obs.events.publish(event_type, source, trace_id, payload)  ← 直接暴露 EventBus
    3. 兜底:返回 False
    """
    if obs is None:
        return False
    payload = payload or {}

    # 路径 1:ObservabilityLayer 上的便捷方法
    if hasattr(obs, "publish_event"):
        try:
            obs.publish_event(event_type, source, trace_id, payload)
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug("[harness.obs] obs.publish_event failed: %s", e)

    # 路径 2:直接暴露 EventBus
    events = getattr(obs, "events", None)
    if events is not None and hasattr(events, "publish"):
        try:
            events.publish(event_type, source, trace_id, payload)
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug("[harness.obs] events.publish failed: %s", e)

    logger.debug("[harness.obs] record_event: no compatible API on %r", obs)
    return False


def get_metric_value(obs: Any, name: str, **labels: Any) -> Optional[float]:
    """读取一个 counter 的当前值(用于测试断言)。找不到返回 None。

    探测:
    1. obs.metrics.counter(name).value(**labels)
    """
    if obs is None:
        return None
    metrics = getattr(obs, "metrics", None)
    if metrics is None or not hasattr(metrics, "counter"):
        return None
    try:
        return float(metrics.counter(name).value(**labels))
    except Exception:  # noqa: BLE001
        return None


def get_event_count(obs: Any, event_type: str) -> int:
    """读取某类事件的累计计数(用于测试断言)。"""
    if obs is None:
        return 0
    events = getattr(obs, "events", None)
    if events is None:
        return 0
    try:
        return len(events.list_events(event_type=event_type))
    except Exception:  # noqa: BLE001
        return 0