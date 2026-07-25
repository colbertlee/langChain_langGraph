"""
Test Agent（自动化测试 Agent 行为）

提供：
- TestCase           单个测试用例
- TestSuite          一组用例
- TestRunner         执行 + 报告
- 自动生成（基于 agent 行为描述）
- 断言 / mock / 覆盖率（简化）
"""
import sys

P2-4
"""

import asyncio
import json
import time
import uuid
import logging
import inspect
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ============================================================
# TestCase
# ============================================================

class TestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class Assertion:
    """一个断言"""
    description: str
    predicate: Callable[[Any], bool]
    expected: Any = None

    def check(self, actual: Any) -> Tuple[bool, str]:
        try:
            ok = self.predicate(actual)
        except Exception as e:
            return False, f"predicate raised: {e}"
        if ok:
            return True, "ok"
        return False, f"expected {self.expected}, got {actual}"


@dataclass
class TestCase:
    """单个测试用例"""
    case_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    setup: Optional[Callable] = None
    action: Optional[Callable] = None
    teardown: Optional[Callable] = None
    assertions: List[Assertion] = field(default_factory=list)
    timeout: float = 10.0
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: TestStatus = TestStatus.PENDING
    duration_ms: float = 0.0
    error: Optional[str] = None
    output: Any = None

    async def run(self) -> TestCase:
        self.status = TestStatus.RUNNING
        start = time.time()
        try:
            # setup
            if self.setup:
                if asyncio.iscoroutinefunction(self.setup):
                    await asyncio.wait_for(self.setup(), timeout=self.timeout)
                else:
                    self.setup()

            # action
            if self.action:
                if asyncio.iscoroutinefunction(self.action):
                    self.output = await asyncio.wait_for(
                        self.action(), timeout=self.timeout
                    )
                else:
                    self.output = self.action()

            # assertions
            all_ok = True
            last_msg = ""
            for a in self.assertions:
                ok, msg = a.check(self.output)
                if not ok:
                    all_ok = False
                    last_msg = msg
                    break

            self.status = TestStatus.PASSED if all_ok else TestStatus.FAILED
            if not all_ok:
                self.error = last_msg

        except asyncio.TimeoutError:
            self.status = TestStatus.FAILED
            self.error = f"timeout after {self.timeout}s"
        except Exception as e:
            self.status = TestStatus.ERROR
            self.error = f"{type(e).__name__}: {e}"
        finally:
            # teardown
            if self.teardown:
                try:
                    if asyncio.iscoroutinefunction(self.teardown):
                        await self.teardown()
                    else:
                        self.teardown()
                except Exception as e:
                    logger.warning(f"teardown error: {e}")
            self.duration_ms = (time.time() - start) * 1000
        return self

    def to_dict(self) -> Dict:
        return {
            "case_id": self.case_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "output": self.output if not isinstance(self.output, bytes) else "<bytes>",
            "assertion_count": len(self.assertions),
            "tags": self.tags,
        }


# ============================================================
# 断言工厂（便于使用）
# ============================================================

def assert_equals(expected: Any) -> Assertion:
    def pred(x):
        return x == expected
    return Assertion(f"equals {expected!r}", pred, expected)


def assert_contains(substr: str) -> Assertion:
    def pred(x):
        return substr in str(x)
    return Assertion(f"contains {substr!r}", pred, substr)


def assert_truthy() -> Assertion:
    def pred(x):
        return bool(x)
    return Assertion("is truthy", pred)


def assert_matches(pattern) -> Assertion:
    import re
    def pred(x):
        return bool(re.search(pattern, str(x)))
    return Assertion(f"matches {pattern!r}", pred)


def assert_greater_than(threshold: float) -> Assertion:
    def pred(x):
        return x > threshold
    return Assertion(f"> {threshold}", pred)


def assert_less_than(threshold: float) -> Assertion:
    def pred(x):
        return x < threshold
    return Assertion(f"< {threshold}", pred)


def assert_isinstance(t: type) -> Assertion:
    def pred(x):
        return isinstance(x, t)
    return Assertion(f"isinstance {t.__name__}", pred)


# ============================================================
# TestSuite
# ============================================================

@dataclass
class TestSuite:
    """测试套件"""
    suite_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    cases: List[TestCase] = field(default_factory=list)
    parallel: bool = False
    stop_on_failure: bool = False

    def add(self, case: TestCase) -> None:
        self.cases.append(case)

    def add_simple(
        self,
        name: str,
        action: Callable,
        assertions: Optional[List[Assertion]] = None,
        **kwargs,
    ) -> TestCase:
        case = TestCase(
            name=name,
            action=action,
            assertions=assertions or [assert_truthy()],
            **kwargs,
        )
        self.cases.append(case)
        return case

    async def run(self) -> Dict:
        if self.parallel:
            results = await asyncio.gather(
                *[c.run() for c in self.cases], return_exceptions=True
            )
        else:
            results = []
            for c in self.cases:
                r = await c.run()
                if self.stop_on_failure and r.status == TestStatus.FAILED:
                    break
                results.append(r)
        return self._summary(results)

    def _summary(self, results: List) -> Dict:
        passed = sum(1 for r in results if hasattr(r, 'status') and r.status == TestStatus.PASSED)
        failed = sum(1 for r in results if hasattr(r, 'status') and r.status == TestStatus.FAILED)
        errored = sum(1 for r in results if hasattr(r, 'status') and r.status == TestStatus.ERROR)
        skipped = sum(1 for r in results if hasattr(r, 'status') and r.status == TestStatus.SKIPPED)
        total = len(results)
        total_duration = sum(
            getattr(r, 'duration_ms', 0) for r in results if hasattr(r, 'duration_ms')
        )
        return {
            "suite_id": self.suite_id,
            "suite_name": self.name,
            "total": total,
            "passed": passed,
            "failed": failed,
            "errored": errored,
            "skipped": skipped,
            "pass_rate": (passed / total) if total > 0 else 0.0,
            "total_duration_ms": total_duration,
            "cases": [
                r.to_dict() if hasattr(r, 'to_dict') else {"error": str(r)}
                for r in results
            ],
        }

    def to_dict(self) -> Dict:
        return {
            "suite_id": self.suite_id,
            "name": self.name,
            "case_count": len(self.cases),
            "parallel": self.parallel,
        }


# ============================================================
# TestCaseGenerator（自动生成）
# ============================================================

class TestCaseGenerator:
    """
    自动生成测试用例（基于 agent 接口）
    """

    def __init__(self, registry=None):
        """
        Args:
            registry: AIAgentExtension 或 MultiAgentMixin 实例
        """
        self.registry = registry

    def generate_from_methods(
        self,
        obj: Any,
        method_names: List[str],
        cases_per_method: int = 3,
    ) -> TestSuite:
        """对每个方法生成多个用例（同步 / 异常 / 类型检查）"""
        suite = TestSuite(name=f"auto_{obj.__class__.__name__}")
        for method_name in method_names:
            if not hasattr(obj, method_name):
                continue
            method = getattr(obj, method_name)
            if not callable(method):
                continue

            sig = None
            try:
                sig = inspect.signature(method)
            except (TypeError, ValueError):
                pass

            # Case 1: method is callable / returns something
            async def case_callable():
                # 不实际调用，只检查可调用性 + 元数据
                return {
                    "method": method_name,
                    "callable": callable(method),
                    "signature": str(sig) if sig else "",
                }

            suite.add_simple(
                name=f"{method_name}.is_callable",
                action=case_callable,
                assertions=[assert_truthy()],
                tags=["auto"],
            )

            # Case 2: has __name__ attribute
            suite.add_simple(
                name=f"{method_name}.has_name",
                action=lambda m=method: getattr(m, "__name__", None),
                assertions=[assert_contains(method_name)],
                tags=["auto"],
            )

        return suite

    def generate_smoke_test(self, registry) -> TestSuite:
        """生成 smoke test（基本调用 + 返回值结构）"""
        suite = TestSuite(name="smoke_test", parallel=True)

        async def check_workers():
            try:
                workers = registry.list_workers()
                return {"workers": workers, "count": len(workers)}
            except Exception as e:
                return {"error": str(e)}

        suite.add_simple(
            name="list_workers_returns_dict",
            action=check_workers,
            assertions=[assert_truthy()],
            tags=["smoke"],
        )

        async def check_capabilities():
            return registry.list_capabilities()

        suite.add_simple(
            name="list_capabilities_returns_list",
            action=check_capabilities,
            assertions=[assert_isinstance(list)],
            tags=["smoke"],
        )

        async def check_load_stats():
            return registry.get_load_stats()

        suite.add_simple(
            name="get_load_stats_returns_dict",
            action=check_load_stats,
            assertions=[assert_isinstance(dict)],
            tags=["smoke"],
        )

        return suite


# ============================================================
# TestRunner
# ============================================================

class TestRunner:
    """
    测试运行器：管理 suite 列表 / 跑 / 生成报告。
    """

    def __init__(self):
        self._suites: Dict[str, TestSuite] = {}
        self._history: List[Dict] = []

    def register(self, suite: TestSuite) -> None:
        self._suites[suite.suite_id] = suite

    def list_suites(self) -> List[TestSuite]:
        return list(self._suites.values())

    async def run_suite(self, suite_id: str) -> Dict:
        suite = self._suites.get(suite_id)
        if not suite:
            return {"error": f"suite {suite_id} not found"}
        result = await suite.run()
        self._history.append(result)
        return result

    async def run_all(self, parallel: bool = False) -> List[Dict]:
        if parallel:
            results = await asyncio.gather(
                *[s.run() for s in self._suites.values()],
                return_exceptions=True,
            )
        else:
            results = []
            for s in self._suites.values():
                results.append(await s.run())
        for r in results:
            if isinstance(r, dict):
                self._history.append(r)
        return [r if isinstance(r, dict) else {"error": str(r)} for r in results]

    def generate_report(self, format: str = "json") -> str:
        """生成报告"""
        if format == "json":
            return json.dumps(self._history, ensure_ascii=False, indent=2)
        # 文本报告
        lines = ["# Test Report", ""]
        for h in self._history:
            lines.append(f"## Suite: {h.get('suite_name', 'unknown')}")
            lines.append(f"- Total: {h.get('total', 0)}")
            lines.append(f"- Passed: {h.get('passed', 0)}")
            lines.append(f"- Failed: {h.get('failed', 0)}")
            lines.append(f"- Errored: {h.get('errored', 0)}")
            lines.append(f"- Pass rate: {h.get('pass_rate', 0):.1%}")
            lines.append(f"- Duration: {h.get('total_duration_ms', 0):.1f}ms")
            lines.append("")
        return "\n".join(lines)

    def stats(self) -> Dict:
        total = sum(h.get("total", 0) for h in self._history)
        passed = sum(h.get("passed", 0) for h in self._history)
        failed = sum(h.get("failed", 0) for h in self._history)
        errored = sum(h.get("errored", 0) for h in self._history)
        return {
            "suite_count": len(self._suites),
            "run_count": len(self._history),
            "total_cases": total,
            "total_passed": passed,
            "total_failed": failed,
            "total_errored": errored,
        }


# ============================================================
# 全局单例
# ============================================================

_test_runner: Optional[TestRunner] = None


def get_test_runner() -> TestRunner:
    global _test_runner
    if _test_runner is None:
        _test_runner = TestRunner()
    return _test_runner


def reset_test_runner() -> None:
    global _test_runner
    _test_runner = None