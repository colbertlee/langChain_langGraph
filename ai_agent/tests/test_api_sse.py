"""api_sse.py 单测：用 TestClient 验证挂载、SSE 帧格式、心跳。"""
from __future__ import annotations

from typing import Any, Iterator

import pytest

from headless_events import HeadlessEvent, HeadlessEventType


# ---------- fake agent ----------

class _FakeAgent:
    """模拟 AIAgent：run_stream 返回固定 chunk。"""

    def __init__(self, chunks: list[dict]) -> None:
        self._chunks = chunks
        self.set_session_calls: list[str | None] = []

    def set_session(self, sid: str) -> None:
        self.set_session_calls.append(sid)

    def run_stream(self, user_input: str, session_id: Any = None) -> Iterator[dict]:
        for c in self._chunks:
            yield c


def _make_app(chunks: list[dict]):
    from fastapi import FastAPI
    from api_sse import mount_sse_routes

    app = FastAPI()
    fake = _FakeAgent(chunks)
    mount_sse_routes(app, agent_factory=lambda: fake)
    return app, fake


# ---------- fixtures ----------

@pytest.fixture
def client_basic():
    chunks = [
        {"type": "chunk", "data": "Hi"},
        {"type": "chunk", "data": " there"},
        {"type": "complete", "data": "Hi there"},
    ]
    app, fake = _make_app(chunks)
    from fastapi.testclient import TestClient
    return TestClient(app), fake


# ---------- tests ----------

def test_health_returns_sse_frame() -> None:
    app, _ = _make_app([])
    from fastapi.testclient import TestClient
    c = TestClient(app)
    r = c.get("/api/sse/health")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    assert body.startswith("event: ping")


def test_chat_emits_sse_stream(client_basic) -> None:
    client, fake = client_basic
    r = client.get("/api/sse/chat?message=hello")
    assert r.status_code == 200
    body = r.text
    # 至少一个 SSE 块（每个 event 以空行结尾）
    assert "event: token" in body
    assert "Hi" in body or "Hi there" in body
    assert body.endswith("\n\n") or "\n\n" in body


def test_chat_rejects_empty_message() -> None:
    app, _ = _make_app([])
    from fastapi.testclient import TestClient
    c = TestClient(app)
    r = c.get("/api/sse/chat?message=")
    assert r.status_code == 400


def test_chat_passes_session_id_to_agent(client_basic) -> None:
    client, fake = client_basic
    r = client.get("/api/sse/chat?message=hi&session_id=abc-123")
    assert r.status_code == 200
    assert "abc-123" in fake.set_session_calls


def test_custom_prefix() -> None:
    """mount_sse_routes 支持自定义前缀。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api_sse import mount_sse_routes

    app = FastAPI()
    mount_sse_routes(app, prefix="/sse/v2", agent_factory=lambda: _FakeAgent([]))
    c = TestClient(app)
    assert c.get("/sse/v2/health").status_code == 200
    # 旧前缀不再挂载
    assert c.get("/api/sse/health").status_code == 404