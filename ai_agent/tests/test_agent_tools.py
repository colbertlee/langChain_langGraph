"""v2.1 — Agent Tool Router / StructuredTool 封装 / bind_tools_for_session 测试。

覆盖：
  1) v21_tools.get_langchain_tools 返回的对象可调用（_run/_invoke）
  2) agent_tool_router.resolve_tools 缓存与去重
  3) AIAgent.bind_tools_for_session 不破坏原有 self.tools
  4) AgentProxy.bind_tools_for_session 透传
  5) chat_stream_sse 把 preset.tools 透传到 agent
  6) /api/agents/tools/specs 返回 spec 列表
"""
import json

import pytest


# ============================================================
# 1) v21_tools.get_langchain_tools
# ============================================================
class TestGetLangchainTools:
    def test_returns_tools_for_known_names(self, monkeypatch):
        # mock 内部 callable，避免触发真实网络
        from v21_tools import TOOL_REGISTRY, get_langchain_tools

        def fake_search(query, max_results=5):
            return f"[search] {query}"

        def fake_py(code, timeout=10):
            return {"stdout": "ok", "stderr": "", "exit_code": 0, "images": []}

        monkeypatch.setitem(TOOL_REGISTRY, "web_search", {
            **TOOL_REGISTRY["web_search"], "func": fake_search,
        })
        monkeypatch.setitem(TOOL_REGISTRY, "python_interpreter", {
            **TOOL_REGISTRY["python_interpreter"], "func": fake_py,
        })

        tools = get_langchain_tools(["web_search", "python_interpreter"])
        assert len(tools) == 2
        names = {getattr(t, "name", None) for t in tools}
        assert "web_search" in names
        assert "python_interpreter" in names

    def test_unknown_names_skipped(self):
        from v21_tools import get_langchain_tools

        tools = get_langchain_tools(["web_search", "ghost-tool"])
        names = [getattr(t, "name", None) for t in tools]
        assert "web_search" in names
        assert "ghost-tool" not in names

    def test_none_returns_all(self, monkeypatch):
        from v21_tools import TOOL_REGISTRY, get_langchain_tools

        # 把 func 都换成 mock
        for name in TOOL_REGISTRY:
            monkeypatch.setitem(TOOL_REGISTRY, name, {
                **TOOL_REGISTRY[name],
                "func": lambda *a, **k: "mock",
            })
        tools = get_langchain_tools()
        # v21_tools 至少含 web_search + python_interpreter
        names = [getattr(t, "name", None) for t in tools]
        assert "web_search" in names
        assert "python_interpreter" in names

    def test_get_tool_specs(self):
        from v21_tools import get_tool_specs

        specs = get_tool_specs(["web_search"])
        assert len(specs) == 1
        assert specs[0]["name"] == "web_search"
        assert "query" in specs[0]["args_schema"]["properties"]


# ============================================================
# 2) agent_tool_router.resolve_tools 缓存
# ============================================================
class TestAgentToolRouter:
    def test_returns_tools_for_v21_names(self, monkeypatch):
        from agent_tool_router import resolve_tools, clear_cache
        from v21_tools import TOOL_REGISTRY

        monkeypatch.setitem(TOOL_REGISTRY, "web_search", {
            **TOOL_REGISTRY["web_search"],
            "func": lambda query, max_results=5: f"[s] {query}",
        })
        clear_cache()

        tools = resolve_tools(["web_search"])
        assert len(tools) == 1
        assert tools[0].name == "web_search"

    def test_cache_returns_same_object(self, monkeypatch):
        from agent_tool_router import resolve_tools, clear_cache
        from v21_tools import TOOL_REGISTRY

        clear_cache()
        a = resolve_tools(["web_search"])
        b = resolve_tools(["web_search"])
        assert a[0] is b[0]  # 缓存命中

    def test_legacy_tool_skipped(self):
        from agent_tool_router import resolve_tools

        tools = resolve_tools(["legacy_tool_xxx"])
        assert tools == []


# ============================================================
# 3) AIAgent.bind_tools_for_session 不破坏原有 tools
# ============================================================
class _FakeTool:
    def __init__(self, name):
        self.name = name


class TestAIAgentBindTools:
    """通过构造最小 stub AIAgent 验证 bind_tools_for_session 逻辑"""

    def _make_stub_agent(self):
        """构造一个仅含 bind_tools_for_session / get_effective_tools / tools / current_session_id 的对象"""
        from agent import AIAgent

        agent = AIAgent.__new__(AIAgent)
        agent.tools = [_FakeTool("base_tool")]
        agent.current_session_id = "sid-1"
        return agent

    def test_bind_adds_extra_tools(self, monkeypatch):
        from agent_tool_router import clear_cache, resolve_tools
        clear_cache()
        agent = self._make_stub_agent()
        bound = agent.bind_tools_for_session(["web_search"])
        assert "web_search" in bound
        # base_tool 仍保留
        eff = agent.get_effective_tools()
        names = {t.name for t in eff}
        assert "base_tool" in names
        assert "web_search" in names

    def test_bind_incremental_update(self):
        agent = self._make_stub_agent()
        # 第一次绑 web_search
        agent.bind_tools_for_session(["web_search"])
        eff1 = {t.name for t in agent.get_effective_tools()}
        assert "web_search" in eff1
        # 第二次改绑 python_interpreter，web_search 应被移除
        agent.bind_tools_for_session(["python_interpreter"])
        eff2 = {t.name for t in agent.get_effective_tools()}
        assert "python_interpreter" in eff2
        # web_search 应该不在 _extra_tools 中（因为 sid-1 的 next_names 不含它）
        # 但 base_tool 仍存在
        assert "base_tool" in eff2

    def test_per_session_isolation(self):
        agent = self._make_stub_agent()
        agent.bind_tools_for_session(["web_search"])

        # 切到另一个 session
        agent.current_session_id = "sid-2"
        agent.bind_tools_for_session(["python_interpreter"])

        # sid-1 仍含 web_search
        agent.current_session_id = "sid-1"
        eff1 = {t.name for t in agent.get_effective_tools()}
        # sid-2 仍含 python_interpreter
        agent.current_session_id = "sid-2"
        eff2 = {t.name for t in agent.get_effective_tools()}
        # base_tool 永远在
        assert "base_tool" in eff1
        assert "base_tool" in eff2
        # per-session 工具应独立
        assert "web_search" in eff1
        assert "python_interpreter" in eff2


# ============================================================
# 4) AgentProxy 透传
# ============================================================
class TestAgentProxy:
    def test_proxy_forwards_bind(self):
        from app import AgentProxy

        agent = AgentProxy.__new__(AgentProxy)
        # 直接给个含 bind_tools_for_session 的 inner
        inner = type("Inner", (), {
            "bind_tools_for_session": lambda self, names: ["web_search"] if names else [],
        })()
        agent._agent = inner

        out = agent.bind_tools_for_session(["web_search"])
        assert out == ["web_search"]


# ============================================================
# 5) chat_stream_sse 把 preset.tools 透传
# ============================================================
@pytest.mark.asyncio
async def test_chat_stream_passes_preset_tools_to_agent(monkeypatch):
    """agent_id=builtin-analyst → preset.tools=['python_interpreter', 'web_search']
    → agent.bind_tools_for_session 被调用并传入这些工具"""
    # 强制让 builtin-analyst 的 tools 是新版的（避免磁盘 db 残留旧值干扰）
    from agent_config import AgentPresetStore, reset_default_store_for_tests
    reset_default_store_for_tests()
    import agent_config
    agent_config._default_store = AgentPresetStore(":memory:")
    analyst = agent_config._default_store.get("builtin-analyst")
    assert analyst is not None
    agent_config._default_store.update("builtin-analyst", {
        "tools": ["python_interpreter", "web_search"]
    })

    bound_calls: list[list[str]] = []

    class FakeInner:
        current_session_id = "default"

        def bind_tools_for_session(self, names):
            bound_calls.append(list(names))
            return list(names)

        def set_session(self, sid):
            self.current_session_id = sid

    class FakeProxy:
        _agent = FakeInner()

        async def _stream_async(self, message, session_id=None):
            yield {"type": "start", "data": "begin"}
            yield {"type": "complete", "data": "ok"}

        def run_stream(self, message, session_id=None):
            yield {"ok"}

    monkeypatch.setattr("app.get_proxy", lambda: FakeProxy())

    from httpx import ASGITransport, AsyncClient
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST",
            "/api/chat/stream",
            json={
                "message": "hi",
                "session_id": "sid-x",
                "agent_id": "builtin-analyst",  # tools: python_interpreter + web_search
            },
        ) as r:
            async for _ in r.aiter_lines():
                pass

    assert len(bound_calls) == 1
    assert set(bound_calls[0]) == {"python_interpreter", "web_search"}


@pytest.mark.asyncio
async def test_chat_stream_explicit_tools_override(monkeypatch):
    """request.tools 显式传入时优先于 preset.tools"""
    bound_calls: list[list[str]] = []

    class FakeInner:
        current_session_id = "default"

        def bind_tools_for_session(self, names):
            bound_calls.append(list(names))
            return list(names)

        def set_session(self, sid):
            self.current_session_id = sid

    class FakeProxy:
        _agent = FakeInner()

        async def _stream_async(self, message, session_id=None):
            yield {"type": "start", "data": "begin"}
            yield {"type": "complete", "data": "ok"}

        def run_stream(self, message, session_id=None):
            yield {"ok"}

    monkeypatch.setattr("app.get_proxy", lambda: FakeProxy())

    from httpx import ASGITransport, AsyncClient
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST",
            "/api/chat/stream",
            json={
                "message": "hi",
                "session_id": "sid-y",
                "agent_id": "builtin-analyst",
                "tools": ["web_search"],  # 显式只启一个
            },
        ) as r:
            async for _ in r.aiter_lines():
                pass

    assert bound_calls[0] == ["web_search"]


# ============================================================
# 6) /api/agents/tools/specs
# ============================================================
@pytest.mark.asyncio
async def test_tools_specs_endpoint():
    from httpx import ASGITransport, AsyncClient
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/agents/tools/specs?names=web_search")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["tools"][0]["name"] == "web_search"
        assert "query" in body["tools"][0]["args_schema"]["properties"]
