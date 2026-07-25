"""
rate_limit - 简单的内存级令牌桶限流器（C2）

背景：
- 13.4.3 多用户并发压测需要"恶意/失控客户端"无法把后端打爆；
- 现有 fastapi 中间件层没有限流；本模块提供：
    1) TokenBucket：单 key 的令牌桶（线程安全）
    2) RateLimiter：多 key 的简单注册表（按 client_id / session_id / ip 限流）
    3) FastAPI 装饰器 + 中间件挂载（可选）

设计原则：
- 纯内存实现（不依赖 Redis），适用于单实例部署；
- 失败安全（Redis 不可用 → 放行）；
- 单例 + 可重置（便于测试）。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from functools import wraps
from typing import Any, Callable, Dict, Optional


class TokenBucket:
    """单 key 令牌桶。

    算法：
    - 每秒补充 rate 个令牌（线性增长，cap=capacity）；
    - 每次 acquire(cost) 消耗 cost 个令牌；
    - 不足时返回 False（不阻塞）。
    """

    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)  # tokens per second
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, cost: float = 1.0) -> bool:
        if cost <= 0:
            return True
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now
            if self.tokens >= cost:
                self.tokens -= cost
                return True
            return False

    def reset(self) -> None:
        with self._lock:
            self.tokens = self.capacity
            self.last_refill = time.monotonic()


class RateLimiter:
    """多 key 限流注册表。

    Args:
        capacity: 单 key 桶容量（默认 60）
        refill_rate: 单 key 每秒补充令牌数（默认 1）
        max_keys: 最多跟踪的 key 数（超过则清理最久未用）
    """

    def __init__(
        self,
        capacity: float = 60.0,
        refill_rate: float = 1.0,
        max_keys: int = 10000,
    ):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.max_keys = max_keys
        self._buckets: Dict[str, TokenBucket] = {}
        self._last_used: Dict[str, float] = {}
        self._lock = threading.Lock()
        # 简单统计
        self._allowed = 0
        self._denied = 0

    def _evict_if_needed(self) -> None:
        if len(self._buckets) <= self.max_keys:
            return
        # 淘汰最久未用的 10%
        target = int(self.max_keys * 0.9)
        if target <= 0:
            return
        sorted_keys = sorted(self._last_used.items(), key=lambda x: x[1])
        for k, _ in sorted_keys[: len(self._buckets) - target]:
            self._buckets.pop(k, None)
            self._last_used.pop(k, None)

    def _get_bucket(self, key: str) -> TokenBucket:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(self.capacity, self.refill_rate)
                self._buckets[key] = bucket
            self._last_used[key] = time.monotonic()
            self._evict_if_needed()
            return bucket

    def allow(self, key: str, cost: float = 1.0) -> bool:
        bucket = self._get_bucket(key)
        ok = bucket.acquire(cost)
        with self._lock:
            if ok:
                self._allowed += 1
            else:
                self._denied += 1
        return ok

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._allowed + self._denied
            return {
                "allowed": self._allowed,
                "denied": self._denied,
                "deny_rate": (self._denied / total) if total else 0.0,
                "tracked_keys": len(self._buckets),
            }

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
            self._last_used.clear()
            self._allowed = 0
            self._denied = 0


# ============================================================
# 单例 + FastAPI 装饰器
# ============================================================

_rate_limiter_instance: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter_instance
    if _rate_limiter_instance is None:
        _rate_limiter_instance = RateLimiter()
    return _rate_limiter_instance


def reset_rate_limiter() -> None:
    global _rate_limiter_instance
    _rate_limiter_instance = None


def rate_limited(
    key_fn: Callable[..., str],
    cost: float = 1.0,
    on_denied: Optional[Callable[[str], Any]] = None,
):
    """限流装饰器。

    Args:
        key_fn: 从函数参数中提取限流 key（如 lambda req: req.client.host）
        cost: 每次调用消耗令牌数

    Example:
        @app.post("/api/chat")
        @rate_limited(key_fn=lambda req: req.client.host, cost=5)
        async def chat(req: Request, ...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            limiter = get_rate_limiter()
            key = key_fn(*args, **kwargs) if callable(key_fn) else key_fn
            if not limiter.allow(key, cost=cost):
                if on_denied is not None:
                    return on_denied(key)
                # 默认拒绝：抛 429（FastAPI 风格）
                from fastapi import HTTPException
                raise HTTPException(status_code=429, detail="Too Many Requests")
            return await func(*args, **kwargs)
        return wrapper
    return decorator


__all__ = [
    "TokenBucket",
    "RateLimiter",
    "get_rate_limiter",
    "reset_rate_limiter",
    "rate_limited",
]