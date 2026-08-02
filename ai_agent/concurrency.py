"""
带真超时的同步执行工具（替代 ``threading.Thread.join(timeout=)`` 的伪超时）。

为什么需要
~~~~~~~~~
旧 ``threading.Thread(target=...).start(); t.join(timeout=30)`` 的隐患：

1. ``daemon=True`` 时线程继续运行，下一次调用可能撞上"上一次还在跑"的脏状态；
2. ``daemon=False`` 时线程不终止，进程退出时被卡住；
3. 无法真正取消 IO（``akshare`` / ``requests`` 阻塞），只能"剪断 wait"。

新实现
~~~~~~
- 用 ``concurrent.futures.ThreadPoolExecutor`` + ``Future.result(timeout=)``
  + ``Future.cancel()`` 兜底；
- 真正超时时返回 ``(False, None, TimeoutError)``，调用方按业务兜底；
- 所有需要外网/重 IO 的工具（akshare、requests）都应走它。

并发安全
~~~~~~~
- 一次只起一个 worker 池（``_DEFAULT_POOL``），线程大小 = ``min(32, 4*cpu)``；
- pool 永不关闭（daemon 模式），随进程退出；
- 调用频率高时可通过 ``run_with_timeout(..., pool=...)`` 共享池 / 独享池。
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FTimeout
from typing import Any, Callable, Optional, Tuple, TypeVar

T = TypeVar("T")

# 默认线程池（按需扩大，不主动关闭）
_DEFAULT_POOL: Optional[ThreadPoolExecutor] = None
_POOL_LOCK = threading.Lock()


def _get_default_pool() -> ThreadPoolExecutor:
    global _DEFAULT_POOL
    if _DEFAULT_POOL is None:
        with _POOL_LOCK:
            if _DEFAULT_POOL is None:
                cpu = os.cpu_count() or 4
                size = min(32, max(8, cpu * 4))
                _DEFAULT_POOL = ThreadPoolExecutor(
                    max_workers=size,
                    thread_name_prefix="ai_agent_io",
                )
    return _DEFAULT_POOL


def run_with_timeout(
    func: Callable[[], T],
    *,
    timeout: float = 30.0,
    pool: Optional[ThreadPoolExecutor] = None,
) -> Tuple[bool, Optional[T], Optional[BaseException]]:
    """在独立线程里跑 ``func``，真超时立即返回。

    Args:
        func: 无参 callable。
        timeout: 秒。<=0 表示立即返回（不进入函数）。
        pool: 指定共享池；为空则使用默认池。

    Returns:
        ``(ok, value, error)`` 三元组：
        - ``ok=True, value=func 返回值, error=None`` 正常完成
        - ``ok=False, value=None, error=TimeoutError(...)`` 真超时
        - ``ok=False, value=None, error=<原始异常>`` 抛出
        - ``ok=False, value=None, error=None`` 超时且未起线程

    Notes:
        - 超时后线程继续在后台跑，下次同池里可能撞脏状态；如要严格隔离，
          给 ``pool=ThreadPoolExecutor(max_workers=1)`` 用独享池。
    """
    if timeout <= 0:
        return False, None, TimeoutError("timeout <= 0")

    pool = pool or _get_default_pool()
    future: Future = pool.submit(func)
    try:
        value = future.result(timeout=timeout)
        return True, value, None
    except FTimeout as e:
        # 真超时：取消（已运行则 cancel() 返回 False，无关紧要）
        future.cancel()
        return False, None, e
    except BaseException as e:  # noqa: BLE001
        return False, None, e


def shutdown_default_pool(wait: bool = False) -> None:
    """关闭默认池（一般只在测试 / 进程退出时用）。"""
    global _DEFAULT_POOL
    if _DEFAULT_POOL is not None:
        _DEFAULT_POOL.shutdown(wait=wait, cancel_futures=True)
        _DEFAULT_POOL = None


__all__ = ["run_with_timeout", "shutdown_default_pool"]
