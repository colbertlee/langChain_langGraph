"""evals/harness/_fixtures.py — 测试/评测共享的 fixtures（PR4 + PR8）。

目标
----

- 给 ``tests/conftest.py`` 提供权威的 ``isolated_env`` 实现；
- 给 ``evals/harness_api.py`` / ``evals/builtin_runners.py`` / CI workflows
  提供 ``FakeAgent`` / ``FakeLLM`` / ``make_trajectory``；
- **不**依赖 pytest——提供 ``isolated_env_func`` 原生函数，让 evals 也能调用。

为什么不去 pytest 化？
~~~~~~~~~~~~~~~~~~~~~~

- pytest fixture 依赖 ``pytest.MonkeyPatch``；直接 ``from _fixtures import isolated_env``
  在 pytest 上下文里能跑，但脱离 pytest（harness 工具脚本）就废了。
- 因此本模块同时提供：
  - ``isolated_env_func(environ=None) -> Dict[str, str]``：纯函数，返回 fake keys。
  - ``isolated_env(monkeypatch)``：pytest adapter，直接 monkeypatch。

PR8 扩展
~~~~~~~~

新增 fake agent / fake LLM / 便捷构造，让：
- CI dry-run 套件直接 ``from evals.harness._fixtures import FakeAgent``；
- 单测中也能直接用 ``make_trajectory(final="...")`` 构造预期对象。
"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterator, Optional


# 单一真相源：测试与评测共用。
DEFAULT_FAKE_KEYS: Dict[str, str] = {
    "OPENAI_API_KEY": "sk-test-fake-key-for-tests-only",
    "ANTHROPIC_API_KEY": "sk-ant-test-fake-key",
    "SERPAPI_API_KEY": "test-serpapi-key",
    "DASHSCOPE_API_KEY": "test-dashscope-key",
    "OPENAI_API_BASE": "https://mock-openai.example.com/v1",
}


def isolated_env_func(environ: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """纯函数：返回一组 fake API key，调用方决定怎么注入。

    参数
    ~~~~

    - ``environ``：可选。传 ``os.environ`` 时直接修改；不传则返回新 dict。

    返回
    ~~~~

    一个 dict，``environ`` 已被就地修改（如果传了）。
    """
    keys = dict(DEFAULT_FAKE_KEYS)
    if environ is None:
        return keys
    for k, v in keys.items():
        environ[k] = v
    return keys


def isolated_env(monkeypatch: Any) -> Iterator[None]:
    """pytest fixture 形态：monkeypatch 注入 env，测试结束自动还原。

    用法（pytest）::

        def test_something(isolated_env):
            # env 已就绪
            ...
    """
    for k, v in DEFAULT_FAKE_KEYS.items():
        monkeypatch.setenv(k, v)
    yield


# ============================================================
# PR8: fake agent / fake LLM / make_trajectory
# ------------------------------------------------------------
# 这些实现刻意 **不** 在 module 顶部 import `agent`；
# 改成延迟 import，减小"被无关链路 import 进 agent"的风险。
# 同时让本 fixture 模块在 CI 启动期（agent.py 还没就绪）也能被 import。
# ============================================================


def make_trajectory(
    final: str = "",
    *,
    events: Optional[list] = None,
    elapsed_s: float = 0.0,
    error: Optional[str] = None,
) -> Any:
    """便捷构造一个 ``Trajectory``，用于测试 / 单测断言。

    参数
    ~~~~

    - ``final``：final 文本（默认空）。
    - ``events``：可选事件列表；不传则自动构造 ``[Event("final")]``（成功路径）。
    - ``elapsed_s``：用时；默认 0。
    - ``error``：错误字符串；非空表示失败路径。
    """
    from agent import Event, Trajectory, Used  # 延迟 import

    if events is None:
        events = [Event(kind="final", name="run", payload=final)]
    return Trajectory(
        events=events,
        final=final,
        used=Used(elapsed_s=elapsed_s),
        error=error,
    )


class FakeAgent:
    """最小 fake agent：实现 ``run_task`` 即可。

    默认行为：``run_task`` 返回 ``make_trajectory("echo: <input>")``。
    可通过 ``response_map`` 自定义输入 → 输出 映射；
    通过 ``raise_exc`` 让 ``run_task`` 抛异常（用于测试错误路径）。
    """

    def __init__(
        self,
        response_map: Optional[Dict[str, str]] = None,
        raise_exc: Optional[BaseException] = None,
        elapsed_s: float = 0.01,
    ) -> None:
        self.response_map = response_map or {}
        self.raise_exc = raise_exc
        self.elapsed_s = elapsed_s

    def run_task(
        self,
        text: str,
        *,
        hooks: Optional[Any] = None,
        budget: Optional[Any] = None,
        session_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> Any:
        if self.raise_exc is not None:
            raise self.raise_exc
        if hooks is not None and hooks.on_event is not None:
            # 与真实 run_task 行为对齐：先发 turn_start，再发 final
            from agent import Event
            try:
                hooks.on_event(Event(kind="turn_start", name="run_task",
                                     payload={"input": text}, ts_ms=0.0))
            except Exception:
                pass
        out = self.response_map.get(text, f"echo: {text}")
        if hooks is not None and hooks.on_event is not None:
            from agent import Event
            try:
                hooks.on_event(Event(kind="final", name="run", payload=out, ts_ms=self.elapsed_s * 1000.0))
            except Exception:
                pass
        return make_trajectory(out, elapsed_s=self.elapsed_s)


class FakeLLM:
    """最小 fake LLM：仅记录被调用的次数 + 入参，**不**真发请求。

    适用场景：替换 ``AIAgent`` 内部的 ``ChatOpenAI``／model factory，
    让端到端跑分时完全离线。

    目前只暴露 ``invoke(prompt)`` 形式的接口（适配 hooks 注入路径）；
    真实替换需要在 ``agent.py`` 里引入绑定点（PR 后续）。
    """

    def __init__(self, response: str = "fake llm response") -> None:
        self.response = response
        self.calls: list[Dict[str, Any]] = []

    def invoke(self, prompt: Any) -> str:
        self.calls.append({"input": prompt})
        return self.response


__all__ = [
    "DEFAULT_FAKE_KEYS",
    "isolated_env_func",
    "isolated_env",
    "make_trajectory",
    "FakeAgent",
    "FakeLLM",
]

