"""v2.1 — file_parser 单元测试。"""
import io
import os

import pytest

from file_parser import (
    ParsedFile,
    build_attached_context,
    parse_file,
    EXT_MAP,
)


# ============================================================
# build_attached_context
# ============================================================
class TestBuildAttachedContext:
    def test_empty_files_returns_empty(self):
        assert build_attached_context([]) == ""

    def test_single_file(self):
        ctx = build_attached_context([
            {"file_name": "a.txt", "file_type": "txt", "text": "hello"}
        ])
        assert '<attached_files>' in ctx
        assert '</attached_files>' in ctx
        assert '<attached_context filename="a.txt" type="txt">' in ctx
        assert "hello" in ctx

    def test_multiple_files_preserved_order(self):
        ctx = build_attached_context([
            {"file_name": "a.txt", "file_type": "txt", "text": "AAA"},
            {"file_name": "b.md", "file_type": "md", "text": "BBB"},
        ])
        assert ctx.find("AAA") < ctx.find("BBB")

    def test_truncates_oversized_text(self):
        ctx = build_attached_context([
            {"file_name": "big.txt", "file_type": "txt", "text": "x" * 20000}
        ])
        assert "截断" in ctx
        # 8000 字符阈值
        assert "x" * 9000 not in ctx

    def test_missing_text_becomes_placeholder(self):
        ctx = build_attached_context([
            {"file_name": "x.bin", "file_type": "bin", "text": ""}
        ])
        assert "(无法提取文本内容" in ctx


# ============================================================
# parse_file 调度
# ============================================================
class TestParseFileDispatch:
    def test_unknown_ext_falls_back_to_text(self, tmp_path):
        p = tmp_path / "weird.xyz"
        p.write_text("fallback content", encoding="utf-8")
        parsed = parse_file(str(p), filename="weird.xyz")
        assert parsed.kind in ("text", "unknown")
        if parsed.kind == "text":
            assert parsed.text == "fallback content"

    def test_not_found(self, tmp_path):
        parsed = parse_file(str(tmp_path / "ghost.txt"))
        assert parsed.kind == "unknown"
        assert "不存在" in parsed.text

    def test_extension_map_includes_common_types(self):
        for ext in (".pdf", ".docx", ".csv", ".xlsx", ".txt", ".md", ".json", ".png", ".jpg"):
            assert ext in EXT_MAP


# ============================================================
# _parse_text / _parse_json / _parse_markdown
# ============================================================
class TestTextParsers:
    def test_text_utf8(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("hello 世界", encoding="utf-8")
        parsed = parse_file(str(p))
        assert parsed.kind == "text"
        assert parsed.text == "hello 世界"

    def test_markdown_passthrough(self, tmp_path):
        p = tmp_path / "a.md"
        p.write_text("# Title\n\nbody", encoding="utf-8")
        parsed = parse_file(str(p))
        assert parsed.kind == "markdown"
        assert "# Title" in parsed.text

    def test_json_valid_pretty(self, tmp_path):
        p = tmp_path / "a.json"
        p.write_text('{"k":"v","n":1}', encoding="utf-8")
        parsed = parse_file(str(p))
        assert parsed.kind == "json"
        assert '"k": "v"' in parsed.text  # pretty
        assert parsed.meta.get("valid") is True

    def test_json_invalid_falls_back_to_text(self, tmp_path):
        p = tmp_path / "broken.json"
        p.write_text("{not json", encoding="utf-8")
        parsed = parse_file(str(p))
        # kind = text（无效 JSON 兜底）
        assert parsed.kind == "text"
        assert parsed.meta.get("invalid_json") is True


# ============================================================
# CSV
# ============================================================
class TestCsv:
    def test_basic_csv(self, tmp_path):
        p = tmp_path / "a.csv"
        p.write_text("name,age\nAlice,30\nBob,25\n", encoding="utf-8")
        parsed = parse_file(str(p))
        assert parsed.kind == "csv"
        assert "Alice" in parsed.text
        assert "| name | age |" in parsed.markdown
        assert "| Alice | 30 |" in parsed.markdown

    def test_csv_truncation(self, tmp_path):
        p = tmp_path / "big.csv"
        # header + 500 行
        rows = ["h1,h2"]
        rows.extend(f"{i},v{i}" for i in range(500))
        p.write_text("\n".join(rows), encoding="utf-8")
        parsed = parse_file(str(p), max_rows=50)
        assert parsed.kind == "csv"
        assert parsed.meta.get("truncated") is True
        # markdown 不应包含第 500 行
        assert "v499" not in parsed.markdown

    def test_csv_handles_pipe_escape(self, tmp_path):
        p = tmp_path / "p.csv"
        p.write_text("a,b\nx|y,z\n", encoding="utf-8")
        parsed = parse_file(str(p))
        assert "\\|" in parsed.markdown  # 转义


# ============================================================
# DOCX / PDF / XLSX —— 依赖缺失时优雅降级
# ============================================================
class TestOptionalParsers:
    def test_docx_missing_dependency(self, tmp_path):
        # 写一个伪 docx，依赖缺失时返回 unknown + 提示安装
        p = tmp_path / "fake.docx"
        p.write_bytes(b"PK\x03\x04 fake docx")
        parsed = parse_file(str(p))
        # 如果环境装了 python-docx，结果可能是 docx / unknown；测试不强依赖
        assert parsed.kind in ("docx", "unknown")

    def test_pdf_missing_dependency(self, tmp_path):
        p = tmp_path / "fake.pdf"
        p.write_bytes(b"%PDF-1.4 fake")
        parsed = parse_file(str(p))
        assert parsed.kind in ("pdf", "unknown")

    def test_xlsx_missing_dependency(self, tmp_path):
        p = tmp_path / "fake.xlsx"
        p.write_bytes(b"PK\x03\x04 fake xlsx")
        parsed = parse_file(str(p))
        assert parsed.kind in ("xlsx", "unknown")


# ============================================================
# 图片
# ============================================================
class TestImage:
    def test_image_basic_png(self, tmp_path):
        # 1x1 透明 PNG
        import base64
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        )
        p = tmp_path / "tiny.png"
        p.write_bytes(png_bytes)
        parsed = parse_file(str(p))
        assert parsed.kind == "image"
        assert "[图片附件]" in parsed.text
        # meta 应含 size_bytes
        assert parsed.meta.get("size_bytes") == len(png_bytes)


# ============================================================
# FastAPI endpoint（upload + 自动 parse）
# ============================================================
@pytest.mark.asyncio
async def test_files_upload_endpoint_parses_text(tmp_path, monkeypatch):
    """上传一个 txt 文件，/api/files/upload 应返回 parsed.text。"""
    from httpx import ASGITransport, AsyncClient
    from app import app
    import os

    # 把 _UPLOAD_ROOT 临时改成 tmp_path
    import app as app_mod
    monkeypatch.setattr(app_mod, "_UPLOAD_ROOT", tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 构造一个简单 txt 文件
        content = b"hello world from upload"
        r = await ac.post(
            "/api/files/upload",
            files={"file": ("hello.txt", io.BytesIO(content), "text/plain")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["file_type"] == "txt"
        assert body["file_name"] == "hello.txt"
        assert "parsed" in body
        assert body["parsed"]["kind"] == "text"
        assert "hello world" in body["parsed"]["text"]


@pytest.mark.asyncio
async def test_files_upload_endpoint_parses_csv(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from app import app
    import app as app_mod

    monkeypatch.setattr(app_mod, "_UPLOAD_ROOT", tmp_path)

    csv_content = "name,age\nAlice,30\nBob,25\n".encode("utf-8")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/files/upload",
            files={"file": ("data.csv", io.BytesIO(csv_content), "text/csv")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["file_type"] == "csv"
        assert body["parsed"]["kind"] == "csv"
        assert "Alice" in body["parsed"]["text"]
        # markdown 表格
        assert "| name | age |" in body["parsed"]["text"] or "Alice" in body["parsed"]["text"]


# ============================================================
# chat_stream_sse 注入
# ============================================================
@pytest.mark.asyncio
async def test_chat_stream_injects_attached_context(tmp_path, monkeypatch):
    """files 参数含 parsed_text 时，注入到 user message。"""
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
                "message": "请总结这个文件",
                "session_id": "s1",
                "files": [
                    {
                        "file_id": "fid-1",
                        "file_name": "doc.txt",
                        "file_type": "txt",
                        "parsed_text": "Hello injected world.",
                    }
                ],
            },
        ) as r:
            raw = ""
            async for line in r.aiter_lines():
                raw += line + "\n"

    # 必须含 <attached_context> 标签
    assert "<attached_context" in captured.get("message", "")
    assert 'filename="doc.txt"' in captured["message"]
    assert "Hello injected world." in captured["message"]
