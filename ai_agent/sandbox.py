"""
Agent 沙箱（Sandbox）

提供：
- SandboxPolicy  策略（白名单 / 黑名单 / 资源限制）
- SandboxRunner  隔离执行（subprocess / restricted python）
- SandboxResult  执行结果

支持的隔离级别：
- "thread"        在线程中执行（仅 API 白名单）
- "subprocess"    在子进程中执行（Python 解释器受限）
- "docker"        在 Docker 中执行（未实现，需要 docker SDK）

P2-6
"""

import ast
import asyncio
import json
import os
import sys
import time
import uuid
import signal
import tempfile
import logging
import multiprocessing
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ============================================================
# 策略 / 结果
# ============================================================

class SandboxLevel(str, Enum):
    THREAD = "thread"           # 线程 + API 白名单
    SUBPROCESS = "subprocess"   # 子进程 + 受限 Python
    DOCKER = "docker"           # Docker 容器


class SandboxVerdict(str, Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
    ERROR = "error"
    RESOURCE_EXCEEDED = "resource_exceeded"


@dataclass
class SandboxPolicy:
    """沙箱策略"""
    name: str = "default"
    level: SandboxLevel = SandboxLevel.THREAD
    # 允许调用的 builtin / 函数名
    allowed_builtins: Set[str] = field(default_factory=lambda: {
        "print", "len", "range", "str", "int", "float", "bool", "list",
        "dict", "tuple", "set", "frozenset", "abs", "min", "max", "sum",
        "sorted", "reversed", "enumerate", "zip", "map", "filter",
        "all", "any", "isinstance", "type", "repr", "hex", "oct",
        "round", "pow", "divmod", "enumerate", "next", "iter", "hasattr",
        "getattr", "setattr", "delattr", "issubclass", "callable",
        "__import__",  # 受控
    })
    # 禁止调用的 builtin
    blocked_builtins: Set[str] = field(default_factory=lambda: {
        "exec", "eval", "compile", "open", "input",  # 危险
        "globals", "locals", "vars",
        "__build_class__",
    })
    # 允许 import 的模块
    allowed_modules: Set[str] = field(default_factory=lambda: {
        "math", "json", "datetime", "re", "collections", "itertools",
        "functools", "operator", "string", "random",
        "typing", "dataclasses", "enum",
    })
    # 禁止 import 的模块
    blocked_modules: Set[str] = field(default_factory=lambda: {
        "os", "sys", "subprocess", "socket", "urllib", "http",
        "requests", "ftplib", "smtplib", "ctypes", "multiprocessing",
        "threading", "asyncio",
        "pickle", "shelve",  # 反序列化风险
    })
    # 资源限制
    timeout_seconds: float = 5.0
    max_memory_mb: Optional[int] = 256
    max_output_chars: int = 100_000
    # 网络
    allow_network: bool = False
    # 文件系统
    allow_file_read: bool = False
    allow_file_write: bool = False

    def to_dict(self) -> Dict:
        d = {
            "name": self.name,
            "level": self.level.value,
            "timeout_seconds": self.timeout_seconds,
            "max_memory_mb": self.max_memory_mb,
            "max_output_chars": self.max_output_chars,
            "allow_network": self.allow_network,
            "allow_file_read": self.allow_file_read,
            "allow_file_write": self.allow_file_write,
        }
        d["allowed_builtin_count"] = len(self.allowed_builtins)
        d["allowed_module_count"] = len(self.allowed_modules)
        return d


@dataclass
class SandboxResult:
    """执行结果"""
    verdict: SandboxVerdict = SandboxVerdict.ALLOWED
    stdout: str = ""
    stderr: str = ""
    return_value: Any = None
    exception: Optional[str] = None
    duration_ms: float = 0.0
    blocked_reasons: List[str] = field(default_factory=list)
    policy_name: str = ""

    def to_dict(self) -> Dict:
        return {
            "verdict": self.verdict.value,
            "stdout": self.stdout[:1000],
            "stderr": self.stderr[:1000],
            "return_value": self.return_value,
            "exception": self.exception,
            "duration_ms": self.duration_ms,
            "blocked_reasons": self.blocked_reasons,
            "policy_name": self.policy_name,
        }


# ============================================================
# 静态检查：分析代码是否符合 policy
# ============================================================

class StaticChecker(ast.NodeVisitor):
    """静态分析 Python 代码，检测是否违反 policy"""
    def __init__(self, policy: SandboxPolicy):
        self.policy = policy
        self.violations: List[str] = []

    def visit_Call(self, node: ast.Call):
        # 检查函数名（builtin 调用）
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name in self.policy.blocked_builtins:
                self.violations.append(f"blocked builtin: {name}")
            elif name not in self.policy.allowed_builtins and not name.startswith("_"):
                # 不在白名单也算可疑
                self.violations.append(f"unknown builtin: {name}")

        # 检查属性访问（如 os.system）
        if isinstance(node.func, ast.Attribute):
            full_name = self._full_attr_name(node.func)
            if full_name:
                # 模块前缀黑名单
                for blocked in self.policy.blocked_modules:
                    if full_name.startswith(blocked + "."):
                        self.violations.append(
                            f"blocked module access: {full_name}"
                        )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            module = alias.name.split(".")[0]
            if module in self.policy.blocked_modules:
                self.violations.append(f"blocked import: {module}")
            elif module not in self.policy.allowed_modules and not module.startswith("_"):
                self.violations.append(f"unknown import: {module}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = (node.module or "").split(".")[0]
        if module in self.policy.blocked_modules:
            self.violations.append(f"blocked from-import: {module}")
        elif module and module not in self.policy.allowed_modules and not module.startswith("_"):
            self.violations.append(f"unknown from-import: {module}")
        self.generic_visit(node)

    def _full_attr_name(self, node) -> Optional[str]:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
            return ".".join(reversed(parts))
        return None


def static_check(code: str, policy: SandboxPolicy) -> List[str]:
    """静态检查代码，返回违规列表"""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax_error: {e}"]
    checker = StaticChecker(policy)
    checker.visit(tree)
    return checker.violations


# ============================================================
# Thread Sandbox
# ============================================================

class ThreadSandbox:
    """
    线程级沙箱（最少隔离，最快）。
    仅 API 白名单 + 静态检查。
    """

    def __init__(self, policy: SandboxPolicy):
        self.policy = policy

    def execute(self, code: str) -> SandboxResult:
        # 静态检查
        violations = static_check(code, self.policy)
        if violations:
            return SandboxResult(
                verdict=SandboxVerdict.BLOCKED,
                blocked_reasons=violations,
                policy_name=self.policy.name,
            )

        # 创建受限 builtins
        import builtins as _bi
        safe_builtins = {
            name: getattr(_bi, name)
            for name in self.policy.allowed_builtins
            if hasattr(_bi, name) and name not in self.policy.blocked_builtins
        }

        # 受限 __import__
        def safe_import(name, *args, **kwargs):
            module_root = name.split(".")[0]
            if module_root in self.policy.blocked_modules:
                raise ImportError(f"module blocked by policy: {name}")
            if module_root not in self.policy.allowed_modules:
                raise ImportError(f"module not in whitelist: {name}")
            return _bi.__import__(name, *args, **kwargs)
        safe_builtins["__import__"] = safe_import

        # 限制文件系统
        if not self.policy.allow_file_read:
            safe_builtins.pop("open", None)

        # 准备 globals
        safe_globals = {"__builtins__": safe_builtins, "__name__": "__sandbox__"}

        start = time.time()
        try:
            exec(code, safe_globals)
        except Exception as e:
            return SandboxResult(
                verdict=SandboxVerdict.ERROR,
                exception=f"{type(e).__name__}: {e}",
                duration_ms=(time.time() - start) * 1000,
                policy_name=self.policy.name,
            )

        # 提取返回值（如果有 __return__）
        return_value = safe_globals.get("__return__", None)
        return SandboxResult(
            verdict=SandboxVerdict.ALLOWED,
            return_value=return_value,
            duration_ms=(time.time() - start) * 1000,
            policy_name=self.policy.name,
        )


# ============================================================
# Subprocess Sandbox
# ============================================================

class SubprocessSandbox:
    """
    子进程沙箱：在新 Python 进程中执行代码。
    隔离更强，但慢一点（启动开销）。
    """

    def __init__(self, policy: SandboxPolicy):
        self.policy = policy

    async def execute(self, code: str) -> SandboxResult:
        # 静态检查
        violations = static_check(code, self.policy)
        if violations:
            return SandboxResult(
                verdict=SandboxVerdict.BLOCKED,
                blocked_reasons=violations,
                policy_name=self.policy.name,
            )

        # 在临时文件中写代码
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            # 启动子进程
            start = time.time()
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, tmp_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.policy.timeout_seconds,
                )
                duration = (time.time() - start) * 1000

                stdout_str = stdout.decode("utf-8", errors="replace")[:self.policy.max_output_chars]
                stderr_str = stderr.decode("utf-8", errors="replace")[:self.policy.max_output_chars]

                if proc.returncode != 0:
                    return SandboxResult(
                        verdict=SandboxVerdict.ERROR,
                        stdout=stdout_str,
                        stderr=stderr_str,
                        exception=f"exit_code={proc.returncode}",
                        duration_ms=duration,
                        policy_name=self.policy.name,
                    )
                return SandboxResult(
                    verdict=SandboxVerdict.ALLOWED,
                    stdout=stdout_str,
                    stderr=stderr_str,
                    duration_ms=duration,
                    policy_name=self.policy.name,
                )
            except asyncio.TimeoutError:
                # 杀进程
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                return SandboxResult(
                    verdict=SandboxVerdict.TIMEOUT,
                    duration_ms=self.policy.timeout_seconds * 1000,
                    policy_name=self.policy.name,
                    exception=f"timeout after {self.policy.timeout_seconds}s",
                )
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ============================================================
# SandboxRunner（顶层入口）
# ============================================================

class SandboxRunner:
    """
    沙箱运行器：根据 policy 选择 Thread 或 Subprocess。
    """

    def __init__(self, policy: Optional[SandboxPolicy] = None):
        self.policy = policy or SandboxPolicy()

    async def run(self, code: str) -> SandboxResult:
        if self.policy.level == SandboxLevel.SUBPROCESS:
            return await SubprocessSandbox(self.policy).execute(code)
        # 默认 THREAD
        # 但 thread 是同步的，用 to_thread
        result = await asyncio.to_thread(ThreadSandbox(self.policy).execute, code)
        return result

    async def run_function(
        self,
        func: Callable,
        *args,
        **kwargs,
    ) -> SandboxResult:
        """直接执行 Python callable（线程隔离）"""
        start = time.time()
        try:
            # 模拟一个 timeout：用 asyncio.wait_for
            result = await asyncio.wait_for(
                asyncio.to_thread(func, *args, **kwargs),
                timeout=self.policy.timeout_seconds,
            )
            return SandboxResult(
                verdict=SandboxVerdict.ALLOWED,
                return_value=result,
                duration_ms=(time.time() - start) * 1000,
                policy_name=self.policy.name,
            )
        except asyncio.TimeoutError:
            return SandboxResult(
                verdict=SandboxVerdict.TIMEOUT,
                duration_ms=self.policy.timeout_seconds * 1000,
                policy_name=self.policy.name,
                exception="timeout",
            )
        except Exception as e:
            return SandboxResult(
                verdict=SandboxVerdict.ERROR,
                exception=f"{type(e).__name__}: {e}",
                duration_ms=(time.time() - start) * 1000,
                policy_name=self.policy.name,
            )

    def check(self, code: str) -> List[str]:
        """只做静态检查，不执行"""
        return static_check(code, self.policy)


# ============================================================
# 全局单例
# ============================================================

_sandbox_runner: Optional[SandboxRunner] = None


def get_sandbox_runner(policy: Optional[SandboxPolicy] = None) -> SandboxRunner:
    global _sandbox_runner
    if _sandbox_runner is None:
        _sandbox_runner = SandboxRunner(policy or SandboxPolicy())
    return _sandbox_runner


def reset_sandbox_runner() -> None:
    global _sandbox_runner
    _sandbox_runner = None