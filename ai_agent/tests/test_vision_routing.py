"""v2.1 — file_parser.build_image_multimodal_block + chat_stream_sse Vision 路由。"""
import base64
import io
import os
import tempfile
from pathlib import Path

import pytest


# ============================================================
# build_image_multimodal_block
# ============================================================
class TestBuildImageMultimodalBlock:
    def test_png_returns_block(self, tmp_path):
        from file_parser import build_image_multimodal_block

        p = tmp_path / "tiny.png"
        # 1x1 透明 PNG
        raw = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        )
        p.write_bytes(raw)
        block = build_image_multimodal_block(str(p), filename="tiny.png")
        assert block is not None
        assert block["type"] == "image"
        assert block["source_type"] == "base64"
        assert block["mime_type"] == "image/png"
        assert block["filename"] == "tiny.png"
        # base64 反解回去字节数等于 raw
        assert base64.b64decode(block["data"]) == raw

    def test_jpg_mime_mapping(self, tmp_path):
        from file_parser import build_image_multimodal_block

        p = tmp_path / "a.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0fake-jpg")
        block = build_image_multimodal_block(str(p), filename="a.jpg")
        assert block["mime_type"] == "image/jpeg"

    def test_nonexistent_path_returns_none(self):
        from file_parser import build_image_multimodal_block

        assert build_image_multimodal_block("/no/such/path.png") is None

    def test_oversized_returns_none(self, tmp_path):
        from file_parser import build_image_multimodal_block

        p = tmp_path / "big.png"
        # 写一个 5MB 的假文件
        p.write_bytes(b"\x89PNG" + b"x" * (5 * 1024 * 1024))
        block = build_image_multimodal_block(str(p), max_bytes=1024)
        assert block is None


# ============================================================
# chat_stream_sse vision routing
# ============================================================
@pytest.mark.asyncio
async def test_chat_stream_vision_disabled_no_image_block(tmp_path, monkeypatch):
    """vision_supported=False 时，不注入 <vision_attachments> 标签"""
    import app as app_mod

    monkeypatch.setattr(app_mod, "_UPLOAD_ROOT", tmp_path)
    # 准备一个假 png
    file_id = "fid-v1"
    (tmp_path / f"{file_id}_tiny.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    captured = {}

    async def fake_stream(message, session_id=None):
        captured["message"] = message
        yield {"type": "start", "data": "begin"}
        yield {"type": "complete", "data": "done"}

    class FakeProxy:
        _stream_async = staticmethod(fake_stream)

    monkeypatch.setattr("app.get_proxy", lambda: FakeProxy())

    from httpx import ASGITransport, AsyncClient
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST",
            "/api/chat/stream",
            json={
                "message": "看看这个图",
                "session_id": "sv1",
                "vision_supported": False,  # 关键
                "files": [
                    {
                        "file_id": file_id,
                        "file_name": "tiny.png",
                        "file_type": "png",
                        "content_type": "image/png",
                    }
                ],
            },
        ) as r:
            async for _ in r.aiter_lines():
                pass

    msg = captured["message"]
    assert "<vision_attachments>" not in msg
    # 但文本上下文仍注入（图片 fallback 文本）
    assert "[图片附件]" in msg or "tiny.png" in msg


@pytest.mark.asyncio
async def test_chat_stream_vision_enabled_injects_image_block(tmp_path, monkeypatch):
    """vision_supported=True 时，注入 <vision_attachments> + multimodal image block"""
    import app as app_mod

    monkeypatch.setattr(app_mod, "_UPLOAD_ROOT", tmp_path)
    file_id = "fid-v2"
    # 真实 png base64
    png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    (tmp_path / f"{file_id}_pixel.png").write_bytes(base64.b64decode(png_b64))

    captured = {}

    async def fake_stream(message, session_id=None):
        captured["message"] = message
        yield {"type": "start", "data": "begin"}
        yield {"type": "complete", "data": "done"}

    class FakeProxy:
        _stream_async = staticmethod(fake_stream)

    monkeypatch.setattr("app.get_proxy", lambda: FakeProxy())

    from httpx import ASGITransport, AsyncClient
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST",
            "/api/chat/stream",
            json={
                "message": "describe this",
                "session_id": "sv2",
                "vision_supported": True,
                "files": [
                    {
                        "file_id": file_id,
                        "file_name": "pixel.png",
                        "file_type": "png",
                        "content_type": "image/png",
                    }
                ],
            },
        ) as r:
            async for _ in r.aiter_lines():
                pass

    msg = captured["message"]
    assert "<vision_attachments>" in msg
    assert '<multimodal_image' in msg
    assert 'filename="pixel.png"' in msg
    assert 'mime="image/png"' in msg
    # 数据 b64 长度应 > 0
    import re as _re
    m = _re.search(r'data_b64_len="(\d+)"', msg)
    assert m is not None
    assert int(m.group(1)) > 0


@pytest.mark.asyncio
async def test_chat_stream_vision_non_image_not_blocked(tmp_path, monkeypatch):
    """vision_supported=True 时，非图片附件不应被当作 multimodal image"""
    import app as app_mod

    monkeypatch.setattr(app_mod, "_UPLOAD_ROOT", tmp_path)
    file_id = "fid-v3"
    (tmp_path / f"{file_id}_doc.txt").write_text("hello world", encoding="utf-8")

    captured = {}

    async def fake_stream(message, session_id=None):
        captured["message"] = message
        yield {"type": "start", "data": "begin"}
        yield {"type": "complete", "data": "done"}

    class FakeProxy:
        _stream_async = staticmethod(fake_stream)

    monkeypatch.setattr("app.get_proxy", lambda: FakeProxy())

    from httpx import ASGITransport, AsyncClient
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST",
            "/api/chat/stream",
            json={
                "message": "summarize",
                "session_id": "sv3",
                "vision_supported": True,
                "files": [
                    {
                        "file_id": file_id,
                        "file_name": "doc.txt",
                        "file_type": "txt",
                        "content_type": "text/plain",
                    }
                ],
            },
        ) as r:
            async for _ in r.aiter_lines():
                pass

    msg = captured["message"]
    # 没图片 → 没 multimodal block
    assert "<vision_attachments>" not in msg
    assert "<multimodal_image" not in msg
    # 但文本上下文注入
    assert "hello world" in msg


# ============================================================
# start 事件透出 vision_supported + tools
# ============================================================
@pytest.mark.asyncio
async def test_chat_stream_start_event_metadata(monkeypatch):
    """start 事件必须含 vision_supported + tools"""
    captured_starts = []

    async def fake_stream(message, session_id=None):
        yield {"type": "start", "data": "begin"}
        yield {"type": "complete", "data": "done"}

    class FakeProxy:
        _stream_async = staticmethod(fake_stream)

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
                "session_id": "smeta",
                "vision_supported": True,
                "tools": ["web_search", "python_interpreter"],
            },
        ) as r:
            raw = ""
            async for line in r.aiter_lines():
                raw += line + "\n"
                if line.startswith("data:"):
                    import json as _json
                    try:
                        captured_starts.append(_json.loads(line[5:].strip()))
                    except Exception:
                        pass

    # 找到 start 事件
    starts = [s for s in captured_starts if s.get("type") == "start"]
    assert len(starts) >= 1
    start = starts[0]
    assert start.get("vision_supported") is True
    assert set(start.get("tools") or []) == {"web_search", "python_interpreter"}
