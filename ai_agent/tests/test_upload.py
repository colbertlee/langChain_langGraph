"""测试 /api/upload 端点（web_ui.py）。

测试不依赖 LangChain / LLM，只验证 FastAPI 路由 + 文件 I/O。
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _try_import_webui():
    """懒导入 web_ui；失败时跳过（环境缺少 langchain 等）。"""
    try:
        # 需要把 ai_agent 加到 sys.path
        ROOT = Path(__file__).resolve().parent.parent
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import web_ui  # noqa: F401

        return web_ui
    except ImportError as e:
        pytest.skip(f"web_ui.py 不能导入（缺少依赖）: {e}")


@pytest.fixture
def client():
    webui = _try_import_webui()
    return TestClient(webui.app)


class TestUpload:
    def test_upload_png_returns_url(self, client, tmp_path, monkeypatch):
        webui = _try_import_webui()
        # 重定向 UPLOAD_ROOT 到临时目录（避免污染真实目录）
        monkeypatch.setattr(webui, "UPLOAD_ROOT", tmp_path)
        # 1x1 PNG
        png_bytes = bytes.fromhex(
            "89504E470D0A1A0A0000000D49484452000000010000000108060000"
            "001F15C4890000000D49444154789C63000100000005000100050A2D"
            "B40000000049454E44AE426082"
        )
        res = client.post(
            "/api/upload",
            files={"file": ("test.png", io.BytesIO(png_bytes), "image/png")},
        )
        assert res.status_code == 200
        data = res.json()
        assert "url" in data
        assert data["url"].startswith("/api/files/")
        assert data["content_type"] == "image/png"
        assert data["size"] == len(png_bytes)

    def test_upload_empty_file_rejected(self, client, monkeypatch, tmp_path):
        webui = _try_import_webui()
        monkeypatch.setattr(webui, "UPLOAD_ROOT", tmp_path)
        res = client.post(
            "/api/upload",
            files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
        )
        assert res.status_code == 400

    def test_serve_uploaded_file(self, client, tmp_path, monkeypatch):
        webui = _try_import_webui()
        # 准备文件
        name = "test_file.txt"
        (tmp_path / name).write_text("hello")
        monkeypatch.setattr(webui, "UPLOAD_ROOT", tmp_path)

        res = client.get(f"/api/files/{name}")
        assert res.status_code == 200
        assert res.text == "hello"

    def test_serve_uploaded_file_path_traversal_blocked(self, client, tmp_path, monkeypatch):
        """验证 ../etc/passwd 这种攻击被阻止。"""
        webui = _try_import_webui()
        monkeypatch.setattr(webui, "UPLOAD_ROOT", tmp_path)
        for bad in ["../passwd", "..\\passwd", ".hidden"]:
            res = client.get(f"/api/files/{bad}")
            assert res.status_code in (400, 404), f"path traversal not blocked: {bad}"

    def test_serve_uploaded_file_not_found(self, client, tmp_path, monkeypatch):
        webui = _try_import_webui()
        monkeypatch.setattr(webui, "UPLOAD_ROOT", tmp_path)
        res = client.get("/api/files/nonexistent.png")
        assert res.status_code == 404


class TestSafeFilename:
    """测试 _safe_filename 工具函数。"""

    def test_strips_path(self):
        webui = _try_import_webui()
        result = webui._safe_filename("../../etc/passwd")
        assert "/" not in result
        assert "\\" not in result
        assert "passwd" in result

    def test_replaces_unsafe_chars(self):
        webui = _try_import_webui()
        result = webui._safe_filename("a b$c@d.txt")
        # 特殊字符应该被替换为 _ 或者保留 . - _
        assert "/" not in result
        assert "txt" in result

    def test_empty_fallback(self):
        webui = _try_import_webui()
        result = webui._safe_filename("")
        assert result == "file"

    def test_truncates_long_names(self):
        webui = _try_import_webui()
        long = "a" * 200 + ".txt"
        result = webui._safe_filename(long)
        assert len(result) <= 120 + 4  # 120 chars + extension
