"""测试 agent.run_stream 产出的结构化事件（阶段 A3/A4/A5）。

策略：使用 monkeypatch 把 invoker.stream 替换为 fake 生成器，
验证事件结构而不依赖真实 LLM 调用。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from types import SimpleNamespace
from typing import Iterator, List, Tuple

import pytest

from agent import AIAgent


class _FakeInvoker:
    """替代 agent.invoker.stream 的最小 stub。"""

    def __init__(self, events: List[Tuple[str, object]]):
        self._events = events

    def stream(self, *args, **kwargs) -> Iterator[Tuple[str, object]]:
        for ev, val in self._events:
            yield ev, val


def _make_agent(monkeypatch) -> AIAgent:
    """构造一个不依赖真实 LLM 的 AIAgent。"""
    # 跳过 init_checkpointer（避免 SQLite 副作用）
    monkeypatch.setattr(AIAgent, "_init_checkpointer", lambda self: None)
    agent = AIAgent()
    # 直接把 invoker 换成可控的 fake
    agent._fake_events: List[Tuple[str, object]] = []
    agent.invoker = SimpleNamespace(stream=lambda *a, **k: iter([]))
    return agent


def _patched_stream(agent, events):
    """让 agent.invoker.stream 返回可控序列。"""
    agent.invoker = SimpleNamespace(stream=lambda *a, **k: iter(events))


def test_stream_yields_start_event(monkeypatch):
    agent = _make_agent(monkeypatch)
    _patched_stream(agent, [
        ("chunk", {"messages": []}),
        ("complete", {}),
    ])
    out = list(agent.run_stream("hi"))
    types = [e["type"] for e in out]
    assert "start" in types
    assert types[-1] == "complete"


def test_stream_emits_chunk_event(monkeypatch):
    agent = _make_agent(monkeypatch)
    _patched_stream(agent, [
        ("chunk", {"messages": [_ai_msg("hello")]}),  # text "hello"
        ("complete", {}),
    ])
    out = list(agent.run_stream("hi"))
    chunks = [e for e in out if e["type"] == "chunk"]
    assert chunks, "expected at least one chunk event"
    # 第一个 chunk 应至少含 "hello" 中的一部分
    joined = "".join(c["data"] for c in chunks)
    assert "hello" in joined


def test_stream_emits_safety_event_when_blocked(monkeypatch):
    agent = _make_agent(monkeypatch)
    # 让 _check_safety 返回拦截
    monkeypatch.setattr(agent, "_check_safety", lambda x: "❌ blocked")
    _patched_stream(agent, [])
    out = list(agent.run_stream("rm -rf /"))
    types = [e["type"] for e in out]
    assert "start" in types
    assert "safety" in types
    # safety 事件应在前，stream 内容不应被发出


def test_stream_safety_for_output(monkeypatch):
    agent = _make_agent(monkeypatch)
    # 构造一个完整输出但 security.check_output 报 blocked
    monkeypatch.setattr(agent.security, "check_output", lambda x: {"blocked": True})
    _patched_stream(agent, [
        ("chunk", {"messages": [_ai_msg("正常回答")]}),  # 正常
        ("complete", {}),
    ])
    out = list(agent.run_stream("hi"))
    # 由于 _sanitize_for_output 在 run_stream 中由最终 safety 触发，
    # 期望看到一个 safety 事件
    types = [e["type"] for e in out]
    assert "safety" in types


def test_stream_extracts_tool_name(monkeypatch):
    agent = _make_agent(monkeypatch)

    # 构造一个 AIMessage 含 tool_calls
    class FakeAIMsg:
        tool_calls = [{"name": "calculate", "args": {}}]
        name = "ai"

        def __init__(self, content="", tool_calls=None):
            self.content = content
            if tool_calls is not None:
                self.tool_calls = tool_calls

    _patched_stream(agent, [
        ("chunk", {"messages": [FakeAIMsg()]}),  # 无文本，但有 tool_call
        ("complete", {}),
    ])
    out = list(agent.run_stream("calc 1+1"))
    tool_events = [e for e in out if e["type"] == "tool_call"]
    assert tool_events, "expected tool_call event"
    assert tool_events[0]["name"] == "calculate"


def test_stream_cot_split(monkeypatch):
    agent = _make_agent(monkeypatch)
    _patched_stream(agent, [
        ("chunk", {"messages": [_ai_msg("## 思考\n先排序\n## 回答\n答：已排好")]}),  # 完整回答
        ("complete", {}),
    ])
    out = list(agent.run_stream("explain"))
    # 预期会出现 thinking 事件与 chunk 事件
    types = [e["type"] for e in out]
    assert "thinking" in types or "chunk" in types  # 至少有内容事件


def test_stream_handles_degraded(monkeypatch):
    agent = _make_agent(monkeypatch)
    _patched_stream(agent, [
        ("degraded", "⚠️ 当前所有模型都不可用"),
    ])
    out = list(agent.run_stream("hi"))
    # degraded 时应推一个 chunk + complete
    types = [e["type"] for e in out]
    assert "chunk" in types
    assert "complete" in types


# ----- helper -----

def _ai_msg(text: str):
    from langchain_core.messages import AIMessage
    return AIMessage(content=text)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))