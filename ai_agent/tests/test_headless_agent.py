"""Headless Agent MVP 单测。

覆盖：
1. 导入 headless_agent 不引入 Web 依赖（fastapi/uvicorn/websockets）；
2. AutoHITL 对低风险工具放行、对 deny 集合中的工具拒绝；
3. 事件流协议：所有 7 类事件可构造、字段完整；
4. HeadlessAgent.stream() 走 fake run_stream，产出符合协议的事件序列；
5. HeadlessAgent.run() 拼接 TOKEN.delta 返回最终文本；
6. 错误路径：stream 至少发出一个 DONE。

说明：
- 不调真实 LLM；用 ``monkeypatch`` 替换 ``AIAgent.run_stream`` 返回固定 chunk 列表。
"""
from __future__ import annotations

import sys
from typing import Any, Iterator, List

import pytest

from headless_agent import (
    AutoHITL,
    HeadlessAgent,
    NoHITL,
    PermissionRequest,
    PermissionResponse,
)
from headless_events import HeadlessEvent, HeadlessEventType


# ============================================================
# 1. 零 Web 依赖
# ============================================================


def test_headless_does_not_import_web_frameworks() -> None:
    """headless_agent 源码不得出现 fastapi/uvicorn/websockets/starlette 的 import 语句。"""
    import headless_agent as mod

    src_file = mod.__file__
    assert src_file is not None
    with open(src_file, "r", encoding="utf-8") as f:
        source = f.read()

    # 只检测 import 语句（避免 docstring / 注释里的字面字符串误伤）
    import re

    import_re = re.compile(
        r"^\s*(?:from\s+(\S+)|import\s+(\S+))",
        re.MULTILINE,
    )
    imported: list[str] = []
    for m in import_re.finditer(source):
        mod_name = (m.group(1) or m.group(2) or "").split(".")[0]
        if mod_name:
            imported.append(mod_name)

    forbidden = {"fastapi", "uvicorn", "websockets", "starlette"}
    leaked = forbidden & set(imported)
    assert not leaked, (
        f"headless_agent 不得依赖 {sorted(leaked)}（实际 import 列表含这些模块）"
    )


# ============================================================
# 2. AutoHITL 决策
# ============================================================


class _FakeGuard:
    """最小化 PermissionGuard 替身，避免引入真实权限系统副作用。"""

    def __init__(self, allow: bool, rule: str = "allowed") -> None:
        self._allow = allow
        self._rule = rule
        self.last_caller: str | None = None
        self.last_tool: str | None = None

    def check_tool(self, caller_id: str, tool_name: str):  # noqa: D401
        self.last_caller = caller_id
        self.last_tool = tool_name

        class _D:
            def __init__(self, granted: bool, rule_: str) -> None:
                self.granted = granted
                self.matched_rule = rule_
                self.reason = rule_

        return _D(self._allow, self._rule)


def test_auto_hitl_extra_deny_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """构造时指定的 deny 集合强制拒绝。"""
    monkeypatch.setitem(sys.modules, "permission", _FakePermissionModule(allow=True))
    hitl = AutoHITL(deny_tools={"shell_exec"})
    import asyncio

    resp = asyncio.run(hitl.decide(PermissionRequest(tool="shell_exec", args={})))
    assert resp.approved is False
    assert resp.rule == "extra_deny"


def test_auto_hitl_default_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    """未命中 deny / require_approval / guard.deny → 默认放行。"""
    monkeypatch.setitem(sys.modules, "permission", _FakePermissionModule(allow=True))
    hitl = AutoHITL()
    import asyncio

    resp = asyncio.run(hitl.decide(PermissionRequest(tool="web_search", args={"q": "x"})))
    assert resp.approved is True
    assert resp.rule in ("allowed", "default_allow", "allowed_tools")


# ============================================================
# 3. 事件数据类
# ============================================================


def test_event_type_is_str_compatible() -> None:
    """HeadlessEventType 继承 str，可直接序列化。"""
    import json

    for t in HeadlessEventType:
        # 既是 Enum 也是 str
        assert isinstance(t, str)
        assert json.dumps({"t": t}) == f'{{"t": "{t.value}"}}'


def test_event_factory_methods() -> None:
    """所有便利构造器都产出正确 type + data。"""
    assert HeadlessEvent.token("hi").data == {"delta": "hi"}
    assert HeadlessEvent.tool_call("t", {"a": 1}).data["name"] == "t"
    assert HeadlessEvent.tool_result("t", result="ok").data["result"] == "ok"
    assert HeadlessEvent.permission_request("t", {}).type == HeadlessEventType.PERMISSION_REQUEST
    pr = HeadlessEvent.permission_response("t", True, "ok")
    assert pr.data["approved"] is True and pr.data["reason"] == "ok"
    assert HeadlessEvent.error("boom").data["message"] == "boom"
    done = HeadlessEvent.done("final", {"tokens": 10})
    assert done.data["final_text"] == "final" and done.data["usage"]["tokens"] == 10


# ============================================================
# 4. HeadlessAgent.stream() 协议顺序
# ============================================================


class _FakeAgent:
    """最小 AIAgent 替身：run_stream 返回固定 chunk 序列。"""

    def __init__(self, chunks: List[dict]) -> None:
        self._chunks = chunks
        self.calls: list[str] = []

    def run_stream(self, user_input: str, session_id: Any = None) -> Iterator[dict]:
        self.calls.append(user_input)
        for c in self._chunks:
            yield c


class _FakePermissionModule:
    """伪装成 permission 模块的占位对象。"""

    def __init__(self, allow: bool = True) -> None:
        self._guard = _FakeGuard(allow=allow)

    def get_permission_guard(self):  # noqa: D401
        return self._guard

    def is_require_approval(self, tool_name: str) -> bool:  # noqa: D401
        return False


@pytest.mark.asyncio
async def test_stream_emits_full_event_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    """stream() 走 fake run_stream，按协议顺序产出 7 类事件，且以 DONE 收尾。"""
    monkeypatch.setitem(sys.modules, "permission", _FakePermissionModule(allow=True))

    chunks = [
        {"type": "start", "data": "hi"},
        {"type": "chunk", "data": "你好"},
        {"type": "chunk", "data": "，"},
        {"type": "chunk", "data": "世界"},
        {
            "type": "tool_call",
            "data": "",
            "name": "web_search",
            "args": {"q": "langchain"},
        },
        {"type": "chunk", "data": "。done"},
        {"type": "complete", "data": "你好，世界。done"},
    ]
    fake = _FakeAgent(chunks)
    agent = HeadlessAgent(agent=fake)

    events = [ev async for ev in agent.stream("hi")]

    # 至少一个 DONE
    assert any(ev.type == HeadlessEventType.DONE for ev in events)

    # 7 类事件协议覆盖（这里期望出现的类型子集）
    types = {ev.type for ev in events}
    assert HeadlessEventType.TOKEN in types
    assert HeadlessEventType.TOOL_CALL in types
    assert HeadlessEventType.PERMISSION_REQUEST in types
    assert HeadlessEventType.PERMISSION_RESPONSE in types
    assert HeadlessEventType.DONE in types

    # TOKEN 拼接结果等于最终文本
    token_text = "".join(
        ev.data.get("delta", "") for ev in events if ev.type == HeadlessEventType.TOKEN
    )
    assert token_text == "你好，世界。done"

    # tool_call 后紧跟 PERMISSION_REQUEST/RESPONSE
    tool_call_idx = next(
        i for i, ev in enumerate(events) if ev.type == HeadlessEventType.TOOL_CALL
    )
    assert events[tool_call_idx + 1].type == HeadlessEventType.PERMISSION_REQUEST
    assert events[tool_call_idx + 2].type == HeadlessEventType.PERMISSION_RESPONSE

    # DONE 是最后一个
    assert events[-1].type == HeadlessEventType.DONE


@pytest.mark.asyncio
async def test_run_concatenates_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """run() 把 TOKEN.delta 拼成最终字符串返回。"""
    monkeypatch.setitem(sys.modules, "permission", _FakePermissionModule(allow=True))
    chunks = [
        {"type": "chunk", "data": "A"},
        {"type": "chunk", "data": "B"},
        {"type": "chunk", "data": "C"},
        {"type": "complete", "data": "ABC"},
    ]
    agent = HeadlessAgent(agent=_FakeAgent(chunks))
    text = await agent.run("anything")
    assert text == "ABC"


@pytest.mark.asyncio
async def test_stream_error_path_still_emits_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_stream 抛异常时：先 ERROR 再 DONE（不漏 DONE）。"""
    monkeypatch.setitem(sys.modules, "permission", _FakePermissionModule(allow=True))

    class _Boom(_FakeAgent):
        def run_stream(self, user_input: str, session_id: Any = None) -> Iterator[dict]:
            raise RuntimeError("boom")
            yield  # pragma: no cover -- 让它成为生成器

    agent = HeadlessAgent(agent=_Boom([]))
    events = [ev async for ev in agent.stream("x")]
    assert any(ev.type == HeadlessEventType.ERROR for ev in events)
    assert events[-1].type == HeadlessEventType.DONE


# ============================================================
# 5. NoHITL 兜底
# ============================================================


def test_no_hitl_always_denies() -> None:
    import asyncio

    resp = asyncio.run(NoHITL().decide(PermissionRequest(tool="anything", args={})))
    assert resp.approved is False
    assert resp.rule == "no_hitl"