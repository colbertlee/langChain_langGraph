"""
可靠性机制（Retry / Circuit Breaker / Dead Letter Queue）

提供：
1. RetryPolicy      指数退避重试策略 + 抖动
2. CircuitBreaker   closed/half-open/open 三态断路器
3. DeadLetterQueue  失败消息缓冲与重投
4. ReliabilityLayer 总控：把上述能力组合起来，提供给 MessageBus / WorkerAgent / AuctionManager

设计原则：
- 三个组件互相独立，可单独使用
- 默认配置保守，不引入延迟
- 所有事件可回调（on_failure / on_open / on_dead_letter）
"""

import asyncio
import time
import uuid
import random
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============================================================
# 重试策略
# ============================================================

class RetryBackoff(Enum):
    """退避算法"""
    FIXED = "fixed"                  # 固定间隔
    LINEAR = "linear"                # 线性递增
    EXPONENTIAL = "exponential"      # 指数退避（2^n）
    EXP_JITTER = "exp_jitter"        # 指数退避 + 随机抖动（推荐）


@dataclass
class RetryPolicy:
    """
    重试策略定义

    用法：
        policy = RetryPolicy(max_attempts=5, backoff=RetryBackoff.EXP_JITTER)
        async with policy.attempts() as attempt:
            ...
    """
    max_attempts: int = 3
    backoff: RetryBackoff = RetryBackoff.EXP_JITTER
    initial_delay: float = 0.1       # 初始延迟（秒）
    max_delay: float = 10.0          # 单次最大延迟
    jitter_factor: float = 0.2       # 抖动比例（±20%）
    retry_on_exceptions: Tuple[type, ...] = (Exception,)
    on_retry: Optional[Callable[[int, float], None]] = None  # (attempt, delay) -> None

    def compute_delay(self, attempt: int) -> float:
        """根据 attempt（0-indexed）计算下次重试的延迟"""
        if attempt < 0:
            return 0.0
        if self.backoff == RetryBackoff.FIXED:
            delay = self.initial_delay
        elif self.backoff == RetryBackoff.LINEAR:
            delay = self.initial_delay * (attempt + 1)
        elif self.backoff == RetryBackoff.EXPONENTIAL:
            delay = self.initial_delay * (2 ** attempt)
        else:  # EXP_JITTER
            delay = self.initial_delay * (2 ** attempt)
            # 加入随机抖动
            jitter = delay * self.jitter_factor * (random.random() * 2 - 1)
            delay = max(0.0, delay + jitter)

        return min(delay, self.max_delay)

    def attempts(self) -> "RetryContext":
        """返回重试上下文（同步方法，立即返回实例）"""
        return RetryContext(self)

    async def execute_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """便捷 API：直接执行+重试（无需上下文管理器）"""
        async with self.attempts() as ctx:
            return await ctx.execute(func, *args, **kwargs)


class RetryContext:
    """异步重试上下文"""
    def __init__(self, policy: RetryPolicy):
        self.policy = policy
        self.attempt = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # 不处理异常，只记录 attempt
        return False

    async def sleep(self) -> None:
        """睡眠到下一次重试"""
        delay = self.policy.compute_delay(self.attempt)
        if self.policy.on_retry:
            try:
                self.policy.on_retry(self.attempt, delay)
            except Exception:
                pass
        if delay > 0:
            await asyncio.sleep(delay)
        self.attempt += 1

    @property
    def exhausted(self) -> bool:
        return self.attempt >= self.policy.max_attempts

    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        """
        执行 async func，自动重试

        Raises:
            最后一次异常的副本；若 max_attempts=1 则不重试
        """
        last_exc = None
        for i in range(self.policy.max_attempts):
            self.attempt = i
            try:
                result = await func(*args, **kwargs)
                self.attempt = i + 1
                return result
            except self.policy.retry_on_exceptions as e:
                last_exc = e
                if i + 1 >= self.policy.max_attempts:
                    break
                # 计算并睡眠到下次重试
                delay = self.policy.compute_delay(i)
                if self.policy.on_retry:
                    try:
                        self.policy.on_retry(i, delay)
                    except Exception:
                        pass
                if delay > 0:
                    await asyncio.sleep(delay)
        if last_exc:
            raise last_exc
        return None


# ============================================================
# 断路器
# ============================================================

class CircuitState(Enum):
    CLOSED = "closed"          # 正常：请求直接通过
    OPEN = "open"              # 断开：直接拒绝
    HALF_OPEN = "half_open"    # 半开：放一个请求探测


@dataclass
class CircuitBreaker:
    """
    断路器

    工作原理：
    - CLOSED: 记录失败次数；达到阈值 -> OPEN
    - OPEN:   等待 recovery_timeout 后 -> HALF_OPEN
    - HALF_OPEN: 放一个请求进去；
                 成功 -> CLOSED（计数清零）
                 失败 -> OPEN（重新计时）

    用法：
        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30)

        if await breaker.allow():
            try:
                result = await call()
                await breaker.record_success()
            except Exception as e:
                await breaker.record_failure(str(e))
                ...
    """
    name: str = "default"
    failure_threshold: int = 5         # N 次连续失败 -> 打开
    recovery_timeout: float = 30.0     # OPEN 后多久进入 HALF_OPEN
    half_open_max_calls: int = 1       # HALF_OPEN 状态允许的探测次数
    state: CircuitState = CircuitState.CLOSED
    _failure_count: int = 0
    _success_count: int = 0
    _opened_at: Optional[float] = None
    _half_open_calls: int = 0

    # 事件回调
    on_state_change: Optional[Callable[[CircuitState, CircuitState, str], None]] = None
    on_open: Optional[Callable[[str], None]] = None

    async def allow(self) -> bool:
        """是否允许请求通过（async 是为了未来扩展）"""
        # 检查是否需要从 OPEN 转到 HALF_OPEN
        if self.state == CircuitState.OPEN:
            if self._opened_at and (time.time() - self._opened_at) >= self.recovery_timeout:
                await self._transition(CircuitState.HALF_OPEN, "recovery_timeout")
                self._half_open_calls = 0
            else:
                return False

        if self.state == CircuitState.HALF_OPEN:
            if self._half_open_calls >= self.half_open_max_calls:
                return False
            self._half_open_calls += 1

        return True

    async def record_success(self) -> None:
        """记录一次成功"""
        if self.state == CircuitState.HALF_OPEN:
            # 探测成功 -> 关闭断路器
            self._failure_count = 0
            self._half_open_calls = 0
            await self._transition(CircuitState.CLOSED, "probe_success")
        elif self.state == CircuitState.CLOSED:
            # 重置失败计数（连续成功的良性指标）
            if self._failure_count > 0:
                self._failure_count = max(0, self._failure_count - 1)

    async def record_failure(self, reason: str = "") -> None:
        """记录一次失败"""
        if self.state == CircuitState.HALF_OPEN:
            # 探测失败 -> 重新打开
            self._opened_at = time.time()
            await self._transition(CircuitState.OPEN, f"probe_failed: {reason}")
            return

        self._failure_count += 1
        if self.state == CircuitState.CLOSED and self._failure_count >= self.failure_threshold:
            self._opened_at = time.time()
            await self._transition(CircuitState.OPEN, f"threshold_reached: {self._failure_count}")

    async def force_open(self, reason: str = "manual") -> None:
        """强制打开"""
        self._opened_at = time.time()
        await self._transition(CircuitState.OPEN, reason)

    async def reset(self) -> None:
        """手动重置"""
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = None
        self._half_open_calls = 0
        await self._transition(CircuitState.CLOSED, "manual_reset")

    async def _transition(self, new_state: CircuitState, reason: str) -> None:
        old = self.state
        if old != new_state:
            self.state = new_state
            logger.info(f"[Circuit:{self.name}] {old.value} -> {new_state.value} ({reason})")
            if self.on_state_change:
                try:
                    if asyncio.iscoroutinefunction(self.on_state_change):
                        await self.on_state_change(old, new_state, reason)
                    else:
                        self.on_state_change(old, new_state, reason)
                except Exception:
                    pass
            if new_state == CircuitState.OPEN and self.on_open:
                try:
                    if asyncio.iscoroutinefunction(self.on_open):
                        await self.on_open(reason)
                    else:
                        self.on_open(reason)
                except Exception:
                    pass

    def stats(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "opened_at": self._opened_at,
        }


# ============================================================
# 死信队列
# ============================================================

@dataclass
class DeadLetter:
    """死信"""
    letter_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    msg_id: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    attempts: int = 0
    failed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "letter_id": self.letter_id,
            "msg_id": self.msg_id,
            "payload": self.payload,
            "reason": self.reason,
            "attempts": self.attempts,
            "failed_at": self.failed_at,
            "last_error": self.last_error,
        }


class DeadLetterQueue:
    """
    死信队列（DLQ）

    角色：
    - send 失败 / 重试耗尽 / 消息处理异常 -> 进 DLQ
    - DLQ 中的消息可以被：
        * 异步重投（retry 调度）
        * 检视（list / get / peek）
        * 清除（clear / drop）

    配置：
        max_size:        最大死信数（默认 1000）
        auto_retry:      自动重投的时间间隔（None 表示手动）
        retry_handler:   重投时调用的函数
    """
    def __init__(
        self,
        max_size: int = 1000,
        auto_retry_seconds: Optional[float] = None,
        retry_handler: Optional[Callable[[DeadLetter], None]] = None,
        on_dead_letter: Optional[Callable[[DeadLetter], None]] = None,
    ):
        self.max_size = max_size
        self._queue: List[DeadLetter] = []
        self._lock = asyncio.Lock()
        self.auto_retry_seconds = auto_retry_seconds
        self.retry_handler = retry_handler
        self.on_dead_letter = on_dead_letter

        # 用于自动重投的后台任务
        self._auto_retry_task: Optional[asyncio.Task] = None
        self._running = False

    def add(
        self,
        msg_id: str,
        payload: Dict[str, Any],
        reason: str,
        attempts: int = 0,
        last_error: Optional[str] = None,
    ) -> DeadLetter:
        """添加一条死信"""
        letter = DeadLetter(
            msg_id=msg_id,
            payload=payload,
            reason=reason,
            attempts=attempts,
            last_error=last_error,
        )
        self._queue.append(letter)
        # 超过最大容量 -> 丢弃最早的
        if len(self._queue) > self.max_size:
            self._queue = self._queue[-self.max_size:]
        logger.warning(f"[DLQ] Added {letter.letter_id} (reason={reason}, attempts={attempts})")
        if self.on_dead_letter:
            try:
                self.on_dead_letter(letter)
            except Exception:
                pass
        return letter

    async def start_auto_retry(self, interval: float = 30.0):
        """启动自动重投循环"""
        if self._running:
            return
        self._running = True
        self._auto_retry_task = asyncio.create_task(self._auto_retry_loop(interval))
        logger.info(f"[DLQ] Auto-retry started (interval={interval}s)")

    async def stop_auto_retry(self):
        """停止自动重投循环"""
        self._running = False
        if self._auto_retry_task:
            self._auto_retry_task.cancel()
            try:
                await self._auto_retry_task
            except (asyncio.CancelledError, Exception):
                pass
            self._auto_retry_task = None

    async def _auto_retry_loop(self, interval: float):
        while self._running:
            try:
                await asyncio.sleep(interval)
                if not self._running:
                    break
                if self.retry_handler:
                    async with self._lock:
                        snapshot = list(self._queue)
                    for letter in snapshot:
                        try:
                            if asyncio.iscoroutinefunction(self.retry_handler):
                                await self.retry_handler(letter)
                            else:
                                self.retry_handler(letter)
                            # 成功后从队列移除
                            async with self._lock:
                                self._queue = [
                                    l for l in self._queue if l.letter_id != letter.letter_id
                                ]
                        except Exception as e:
                            logger.debug(f"[DLQ] Auto-retry {letter.letter_id} failed: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[DLQ] Auto-retry loop error: {e}")

    def list(self, limit: int = 100) -> List[DeadLetter]:
        return self._queue[-limit:]

    def size(self) -> int:
        return len(self._queue)

    def clear(self) -> int:
        n = len(self._queue)
        self._queue.clear()
        return n

    def get(self, letter_id: str) -> Optional[DeadLetter]:
        for letter in self._queue:
            if letter.letter_id == letter_id:
                return letter
        return None

    def remove(self, letter_id: str) -> bool:
        before = len(self._queue)
        self._queue = [l for l in self._queue if l.letter_id != letter_id]
        return len(self._queue) < before


# ============================================================
# ReliabilityLayer（总控）
# ============================================================

class ReliabilityLayer:
    """
    可靠性层

    将 RetryPolicy / CircuitBreaker / DeadLetterQueue 组合起来，
    提供给 MessageBus、WorkerAgent、AuctionManager 使用。

    约定：
    - 任何"失败的 send" -> 进 DLQ + 标记失败计数
    - 任何"成功的 send" -> 断路器记录成功
    - 给定 agent_id / service_name 维护独立的断路器
    """

    def __init__(
        self,
        retry_policy: Optional[RetryPolicy] = None,
        dlq: Optional[DeadLetterQueue] = None,
        circuit_breaker_factory: Optional[Callable[[str], CircuitBreaker]] = None,
    ):
        self.retry_policy = retry_policy or RetryPolicy(
            max_attempts=3,
            backoff=RetryBackoff.EXP_JITTER,
            initial_delay=0.1,
            max_delay=5.0,
        )
        self.dlq = dlq or DeadLetterQueue(max_size=1000)
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._circuit_breaker_factory = circuit_breaker_factory or self._default_breaker_factory

        # 可观测性（可选）
        self._observability = None
        try:
            from observability import get_observability
            self._observability = get_observability()
        except Exception:
            pass

        # 订阅断路器事件
        self._subscribe_breaker_events()

    def _default_breaker_factory(self, name: str) -> CircuitBreaker:
        return CircuitBreaker(name=name, failure_threshold=5, recovery_timeout=30.0)

    def _subscribe_breaker_events(self):
        """订阅新创建的断路器，把状态变化发布为可观测性事件"""
        original_factory = self._circuit_breaker_factory
        outer = self

        def factory_with_hooks(name: str) -> CircuitBreaker:
            cb = original_factory(name)

            def on_state_change(old_state, new_state, reason):
                # on_state_change 可能是 sync 或 async，
                # 在 _transition 中会根据实际类型 await 或直接调用
                if not outer._observability:
                    return None
                # Gauge: 0=closed, 1=half_open, 2=open
                state_value = {"closed": 0, "half_open": 1, "open": 2}.get(new_state.value, 0)
                outer._observability.circuit_state.set(state_value, breaker=name)
                event_type = {
                    "closed": "circuit_closed",
                    "half_open": "circuit_half_open",
                    "open": "circuit_opened",
                }.get(new_state.value, "circuit_opened")
                outer._observability.publish_event(
                    event_type,
                    source="reliability",
                    payload={
                        "breaker": name,
                        "old_state": old_state.value,
                        "new_state": new_state.value,
                        "reason": reason,
                    },
                )

            cb.on_state_change = on_state_change
            return cb

        self._circuit_breaker_factory = factory_with_hooks

    def get_breaker(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = self._circuit_breaker_factory(name)
        return self._breakers[name]

    async def call_with_reliability(
        self,
        operation_name: str,
        func: Callable,
        *args,
        on_failure: Optional[Callable[[Exception], None]] = None,
        **kwargs,
    ) -> Any:
        """
        用可靠性策略包装一个 async 函数

        流程：
        1. 检查断路器是否允许
        2. 断路器允许 -> 执行（带重试）
        3. 成功 -> 断路器记录 success
        4. 失败 -> 断路器记录 failure + DLQ + on_failure 回调
        """
        breaker = self.get_breaker(operation_name)

        if not await breaker.allow():
            # 断路器打开：直接进 DLQ
            err = RuntimeError(f"Circuit breaker OPEN for {operation_name}")
            self.dlq.add(
                msg_id=str(uuid.uuid4()),
                payload={"op": operation_name, "args": str(args)[:200]},
                reason="circuit_open",
                attempts=0,
                last_error=str(err),
            )
            if self._observability:
                self._observability.publish_event(
                    "retry_exhausted",
                    source="reliability",
                    payload={"op": operation_name, "reason": "circuit_open"},
                )
            if on_failure:
                try:
                    on_failure(err)
                except Exception:
                    pass
            raise err

        # 跟踪重试次数
        attempt_holder = {"count": 0}
        original_inc = self._observability.retries_total.inc if self._observability else None

        async def wrapped():
            attempt_holder["count"] += 1
            if self._observability and attempt_holder["count"] > 1:
                self._observability.retries_total.inc(op=operation_name)
                self._observability.publish_event(
                    "retry_attempt",
                    source="reliability",
                    payload={"op": operation_name, "attempt": attempt_holder["count"]},
                )
            return await func(*args, **kwargs)

        try:
            result = await self.retry_policy.attempts().execute(wrapped)
            await breaker.record_success()
            return result
        except Exception as e:
            await breaker.record_failure(str(e))
            self.dlq.add(
                msg_id=str(uuid.uuid4()),
                payload={"op": operation_name, "args": str(args)[:200]},
                reason="max_retries_exceeded",
                attempts=self.retry_policy.max_attempts,
                last_error=str(e),
            )
            if self._observability:
                self._observability.publish_event(
                    "retry_exhausted",
                    source="reliability",
                    payload={
                        "op": operation_name,
                        "attempts": self.retry_policy.max_attempts,
                        "error": str(e)[:200],
                    },
                )
            if on_failure:
                try:
                    on_failure(e)
                except Exception:
                    pass
            raise

    def get_stats(self) -> Dict[str, Any]:
        return {
            "circuit_breakers": {
                name: cb.stats() for name, cb in self._breakers.items()
            },
            "dlq_size": self.dlq.size(),
            "retry_policy": {
                "max_attempts": self.retry_policy.max_attempts,
                "backoff": self.retry_policy.backoff.value,
                "initial_delay": self.retry_policy.initial_delay,
                "max_delay": self.retry_policy.max_delay,
            },
        }


# ============================================================
# 全局单例
# ============================================================

_reliability_layer: Optional[ReliabilityLayer] = None


def get_reliability() -> ReliabilityLayer:
    """获取全局可靠性层"""
    global _reliability_layer
    if _reliability_layer is None:
        _reliability_layer = ReliabilityLayer()
    return _reliability_layer


def reset_reliability():
    """重置全局单例（测试用）"""
    global _reliability_layer
    _reliability_layer = None
