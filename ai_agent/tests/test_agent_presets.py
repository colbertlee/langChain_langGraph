"""v2.1 — Agent Preset CRUD + chat_stream_sse agent_id 注入回归测试。

覆盖：
  1) AgentPresetStore SQLite 持久化（CRUD / 校验 / builtin 不可删）
  2) /api/agents/presets CRUD endpoints
  3) /api/agents GET 兼容返回 presets + workers
  4) /api/chat/stream 的 start 事件注入 agent_name / agent_id / temperature
"""
import pytest
from httpx import ASGITransport, AsyncClient

from agent_config import (
    AgentPreset,
    AgentPresetStore,
    get_preset_store,
    reset_default_store_for_tests,
)
from app import app


# ============================================================
# 1) SQLite 存储层
# ============================================================
class TestAgentPresetStore:
    def test_seed_has_three_builtins(self):
        with AgentPresetStore(":memory:") as store:
            presets = store.list()
            builtin = [p for p in presets if p.builtin]
            assert len(builtin) == 3
            names = {p.name for p in builtin}
            assert "通用助手" in names
            assert "代码重构专家" in names
            assert "数据分析师" in names

    def test_create_and_get(self):
        with AgentPresetStore(":memory:") as store:
            p = store.create({
                "name": "我的客服",
                "description": "面向用户的客服 agent",
                "avatar": "🎧",
                "system_prompt": "你是一名客服。",
                "temperature": 0.4,
                "tools": ["python_exec"],
            })
            assert not p.builtin
            assert p.id.startswith("u-")
            assert p.temperature == 0.4
            assert p.tools == ["python_exec"]
            fetched = store.get(p.id)
            assert fetched is not None
            assert fetched.name == "我的客服"

    def test_create_validates_temperature_range(self):
        with AgentPresetStore(":memory:") as store:
            with pytest.raises(ValueError):
                store.create({"name": "X", "temperature": 3.5})
            with pytest.raises(ValueError):
                store.create({"name": "X", "temperature": -0.1})

    def test_create_validates_name(self):
        with AgentPresetStore(":memory:") as store:
            with pytest.raises(ValueError):
                store.create({"name": "   "})
            with pytest.raises(ValueError):
                store.create({"name": ""})

    def test_create_with_explicit_id(self):
        with AgentPresetStore(":memory:") as store:
            p = store.create({"id": "my-custom-id", "name": "Custom"})
            assert p.id == "my-custom-id"
            # 重复 id 抛错
            with pytest.raises(ValueError):
                store.create({"id": "my-custom-id", "name": "dup"})

    def test_update_partial(self):
        with AgentPresetStore(":memory:") as store:
            p = store.create({"name": "Old", "temperature": 0.5})
            updated = store.update(p.id, {"temperature": 0.9, "description": "new"})
            assert updated.name == "Old"           # 未改字段保留
            assert updated.temperature == 0.9
            assert updated.description == "new"
            assert updated.builtin is False

    def test_update_nonexistent_raises(self):
        with AgentPresetStore(":memory:") as store:
            with pytest.raises(KeyError):
                store.update("ghost-id", {"name": "x"})

    def test_cannot_downgrade_builtin_on_update(self):
        """update() 必须静默忽略 patch 里的 builtin 字段（保护系统预设）。"""
        with AgentPresetStore(":memory:") as store:
            p = store.update("builtin-general", {"builtin": False, "name": "Renamed"})
            # builtin 仍为 True
            assert p.builtin is True
            # name 正常被改
            assert p.name == "Renamed"

    def test_delete_user_preset(self):
        with AgentPresetStore(":memory:") as store:
            p = store.create({"name": "to-delete"})
            assert store.delete(p.id) is True
            assert store.get(p.id) is None

    def test_delete_builtin_rejected(self):
        with AgentPresetStore(":memory:") as store:
            with pytest.raises(PermissionError):
                store.delete("builtin-general")
            with pytest.raises(PermissionError):
                store.delete("builtin-refactor")

    def test_delete_nonexistent_returns_false(self):
        with AgentPresetStore(":memory:") as store:
            assert store.delete("nope") is False

    def test_tools_persists_as_json(self, tmp_path):
        """验证 SQLite 持久化：tools 数组正确 round-trip 到磁盘文件。"""
        db_file = str(tmp_path / "presets.db")
        with AgentPresetStore(db_file) as store:
            p = store.create({"name": "X", "tools": ["a", "b", "c"]})
        # 重新打开同一个 db 文件验证持久化
        with AgentPresetStore(db_file) as store2:
            fetched = store2.get(p.id)
            assert fetched is not None
            assert fetched.tools == ["a", "b", "c"]

    def test_dataclass_to_from_dict_roundtrip(self):
        p = AgentPreset(
            id="x",
            name="X",
            description="d",
            avatar="🦊",
            system_prompt="sys",
            temperature=0.8,
            tools=["t1"],
        )
        d = p.to_dict()
        p2 = AgentPreset.from_dict(d)
        assert p2.id == "x"
        assert p2.name == "X"
        assert p2.tools == ["t1"]


# ============================================================
# 2) FastAPI CRUD endpoints
# ============================================================
@pytest.fixture
def temp_store(monkeypatch):
    """每个测试用内存 db，避免污染磁盘文件。"""
    reset_default_store_for_tests()
    # 强制把全局 store 切换到内存 db
    import agent_config
    agent_config._default_store = AgentPresetStore(":memory:")
    yield
    agent_config._default_store.close()
    agent_config._default_store = None
    reset_default_store_for_tests()


@pytest.mark.asyncio
async def test_list_presets_returns_three_builtins(temp_store):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/agents/presets")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 3
        assert any(p["id"] == "builtin-general" for p in data["presets"])
        assert all(p["builtin"] is True for p in data["presets"] if p["id"].startswith("builtin-"))


@pytest.mark.asyncio
async def test_create_preset(temp_store):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/agents/presets",
            json={
                "name": "测试 Agent",
                "description": "单测用",
                "avatar": "🧪",
                "system_prompt": "你是测试 agent",
                "temperature": 0.5,
                "tools": ["python_exec"],
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "测试 Agent"
        assert body["builtin"] is False
        assert body["tools"] == ["python_exec"]


@pytest.mark.asyncio
async def test_create_preset_validates(temp_store):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/agents/presets",
            json={"name": "X", "temperature": 5.0},  # 越界
        )
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_preset(temp_store):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r1 = await ac.post(
            "/api/agents/presets",
            json={"name": "Original"},
        )
        pid = r1.json()["id"]

        r2 = await ac.put(
            f"/api/agents/presets/{pid}",
            json={"name": "Updated", "temperature": 1.2},
        )
        assert r2.status_code == 200
        body = r2.json()
        assert body["name"] == "Updated"
        assert body["temperature"] == 1.2


@pytest.mark.asyncio
async def test_update_nonexistent_returns_404(temp_store):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.put(
            "/api/agents/presets/ghost-id",
            json={"name": "x"},
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_builtin_returns_403(temp_store):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.delete("/api/agents/presets/builtin-general")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_user_preset(temp_store):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r1 = await ac.post("/api/agents/presets", json={"name": "tmp"})
        pid = r1.json()["id"]
        r2 = await ac.delete(f"/api/agents/presets/{pid}")
        assert r2.status_code == 200
        assert r2.json() == {"deleted": pid}
        # 再删 → 404
        r3 = await ac.delete(f"/api/agents/presets/{pid}")
        assert r3.status_code == 404


@pytest.mark.asyncio
async def test_legacy_get_agents_includes_presets(temp_store):
    """旧 /api/agents 接口同时返回 presets + agents（向后兼容）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/agents")
        assert r.status_code == 200
        body = r.json()
        assert "presets" in body
        assert "agents" in body
        assert body["count"] >= 3


# ============================================================
# 3) /api/chat/stream start 事件注入 agent metadata
# ============================================================
@pytest.mark.asyncio
async def test_chat_stream_injects_agent_metadata(temp_store, monkeypatch):
    """chat_stream_sse 的 start 事件必须包含 agent_id/agent_name/temperature。"""
    # 替换 _stream_async 让它只 yield 一个 start + end
    async def fake_stream(message, session_id=None):
        assert "[system]" in message  # system_prompt 已注入
        yield {"type": "start", "data": "begin"}
        yield {"type": "chunk", "data": "hello"}
        yield {"type": "complete", "data": "done"}

    class FakeProxy:
        _stream_async = staticmethod(fake_stream)

    monkeypatch.setattr("app.get_proxy", lambda: FakeProxy())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST",
            "/api/chat/stream",
            json={
                "message": "user says hi",
                "session_id": "test-sid",
                "agent_id": "builtin-refactor",  # 指定代码重构专家
            },
        ) as r:
            assert r.status_code == 200
            raw = ""
            async for line in r.aiter_lines():
                raw += line + "\n"

    # start 事件必须含 agent_name="代码重构专家"
    assert "代码重构专家" in raw, f"start event missing agent_name; raw={raw[:500]}"
    assert "builtin-refactor" in raw, f"start event missing agent_id; raw={raw[:500]}"
    assert '"temperature":0.3' in raw or '"temperature": 0.3' in raw, (
        f"start event missing temperature; raw={raw[:500]}"
    )


@pytest.mark.asyncio
async def test_chat_stream_fallback_to_builtin_general(temp_store, monkeypatch):
    """agent_id 不存在时回退到 builtin-general（前端不感知）。"""
    async def fake_stream(message, session_id=None):
        yield {"type": "start", "data": "begin"}
        yield {"type": "chunk", "data": "ok"}
        yield {"type": "complete", "data": "done"}

    class FakeProxy:
        _stream_async = staticmethod(fake_stream)

    monkeypatch.setattr("app.get_proxy", lambda: FakeProxy())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST",
            "/api/chat/stream",
            json={
                "message": "hi",
                "session_id": "test-sid",
                "agent_id": "ghost-id-xxx",  # 不存在
            },
        ) as r:
            raw = ""
            async for line in r.aiter_lines():
                raw += line + "\n"

    assert "通用助手" in raw, f"should fall back to builtin-general; raw={raw[:500]}"
    assert "builtin-general" in raw


@pytest.mark.asyncio
async def test_chat_stream_config_override(temp_store, monkeypatch):
    """config_override 临时覆盖 system_prompt / temperature。"""
    captured = {}

    async def fake_stream(message, session_id=None):
        captured["message"] = message
        yield {"type": "start", "data": "begin"}
        yield {"type": "complete", "data": "done"}

    class FakeProxy:
        _stream_async = staticmethod(fake_stream)

    monkeypatch.setattr("app.get_proxy", lambda: FakeProxy())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST",
            "/api/chat/stream",
            json={
                "message": "test",
                "session_id": "t",
                "agent_id": "builtin-general",
                "config_override": {
                    "system_prompt": "OVERRIDE-SYS",
                    "temperature": 0.1,
                },
            },
        ) as r:
            raw = ""
            async for line in r.aiter_lines():
                raw += line + "\n"

    # 注入的 message 必须含 override 的 system_prompt
    assert "OVERRIDE-SYS" in captured.get("message", "")
    # temperature 必须 override 成 0.1
    assert '"temperature":0.1' in raw or '"temperature": 0.1' in raw
