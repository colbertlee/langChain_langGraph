"""concurrency.run_with_timeout 单元测试（Day 3 回归用）。

验证项：
- 正常完成返回 (True, value, None)
- 超时返回 (False, None, FTimeout)
- 函数抛异常返回 (False, None, <原异常>)
- timeout <= 0 立即返回
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from concurrency import run_with_timeout, shutdown_default_pool
from concurrent.futures import TimeoutError as FTimeout


def teardown_module(_):
    # 测试结束后关掉默认池，避免悬挂线程影响其他测试
    shutdown_default_pool(wait=False)


def test_normal_completion():
    def f():
        return 42

    ok, val, err = run_with_timeout(f, timeout=5.0)
    assert ok is True
    assert val == 42
    assert err is None


def test_with_arguments_via_closure():
    def f(x, y):
        return x + y

    ok, val, err = run_with_timeout(lambda: f(1, 2), timeout=5.0)
    assert ok and val == 3


def test_timeout_returns_timeout_error():
    """真超时：函数里 sleep 5s，timeout=0.3 应立即返回。"""
    def slow():
        time.sleep(5)

    start = time.monotonic()
    ok, val, err = run_with_timeout(slow, timeout=0.3)
    elapsed = time.monotonic() - start

    assert ok is False
    assert val is None
    assert isinstance(err, FTimeout)
    # 真超时：不应该等满 5s；留 0.5s 余量
    assert elapsed < 1.0, f"expected <1s, got {elapsed:.2f}s"


def test_exception_propagates():
    def boom():
        raise ValueError("kaboom")

    ok, val, err = run_with_timeout(boom, timeout=5.0)
    assert ok is False
    assert val is None
    assert isinstance(err, ValueError)
    assert "kaboom" in str(err)


def test_zero_timeout_rejected():
    ok, val, err = run_with_timeout(lambda: 1, timeout=0)
    assert ok is False
    assert val is None
    assert isinstance(err, FTimeout)


def test_negative_timeout_rejected():
    ok, val, err = run_with_timeout(lambda: 1, timeout=-1.0)
    assert ok is False


def test_concurrent_execution():
    """3 个并发任务应都完成，总时间 ≈ 单任务时间（不是 3 倍）。"""
    def task(i):
        time.sleep(0.3)
        return i * 10

    start = time.monotonic()
    results = []
    for i in range(3):
        ok, v, _ = run_with_timeout(lambda i=i: task(i), timeout=5.0)
        if ok:
            results.append(v)
    elapsed = time.monotonic() - start

    assert sorted(results) == [0, 10, 20]
    # 串行：3 * 0.3 = 0.9s；并发：≈ 0.3s + 调度开销
    assert elapsed < 1.5, f"too slow: {elapsed:.2f}s"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))
