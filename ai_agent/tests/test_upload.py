"""测试 /api/upload + /api/files/{name} 端点（app.py）。

测试不依赖 LangChain / LLM，只验证 FastAPI 路由 + 文件 I/O。

注意（v2.5 重构）：
  - 旧版通过 `_try_import_webui` 引用 _safe_filename helper 失败（webui 模块已删除）
  - 当前实现：_safe_filename 在 app.py 模块级；/api/upload 返回 url=/uploads/{name}（不再 /api/files/）
  - 所有测试改为通过模块 import 获取 helper + 通过 HTTP 客户端验证端点
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ─────────────── 懒加载 app ───────────────

def _try_import_app():
    """懒导入 app；失败时跳过（环境缺少 langchain 等）。"""
    try:
        import app  # noqa: F401
        return app
    except ImportError as e:
        pytest.skip(f"app.py 不能导入（缺少依赖）: {e}")


@pytest.fixture
def app_ctx():
    """返回 (TestClient, app module) 元组；测试可 monkeypatch _UPLOAD_ROOT 等模块级变量。"""
    appmod = _try_import_app()
    return TestClient(appmod.app), appmod


# ─────────────── 端点测试 ───────────────


class TestUpload:
    """POST /api/upload 端点契约。"""

    def test_upload_png_returns_url(self, app_ctx, tmp_path, monkeypatch):
        client, appmod = app_ctx
        # 重定向 _UPLOAD_ROOT 到临时目录（避免污染真实目录）
        monkeypatch.setattr(appmod, "_UPLOAD_ROOT", tmp_path)
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
        assert res.status_code == 200, f"upload failed: {res.status_code} {res.text}"
        data = res.json()
        assert "url" in data
        # v2.5：upload 返回 /uploads/{name}（不再 /api/files/）
        assert data["url"].startswith("/uploads/"), f"unexpected url prefix: {data['url']}"
        assert data["content_type"] == "image/png"
        assert data["size"] == len(png_bytes)

    def test_upload_empty_file_rejected(self, app_ctx, monkeypatch, tmp_path):
        client, appmod = app_ctx
        monkeypatch.setattr(appmod, "_UPLOAD_ROOT", tmp_path)
        res = client.post(
            "/api/upload",
            files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
        )
        assert res.status_code == 400, f"empty file should 400, got {res.status_code}"
        assert "empty" in res.json().get("detail", "").lower()


class TestServeFile:
    """GET /api/files/{name} 端点契约。"""

    def test_serve_uploaded_file(self, app_ctx, tmp_path, monkeypatch):
        client, appmod = app_ctx
        # 准备文件
        name = "test_file_abcdef123456.png"
        (tmp_path / name).write_bytes(b"hello")
        monkeypatch.setattr(appmod, "_UPLOAD_ROOT", tmp_path)

        res = client.get(f"/api/files/{name}")
        assert res.status_code == 200
        assert res.content == b"hello"

    def test_serve_uploaded_file_path_traversal_blocked(
        self, app_ctx, tmp_path, monkeypatch
    ):
        """验证 ../etc/passwd 这种攻击被阻止（4xx，不能 200 拿到文件内容）。"""
        client, appmod = app_ctx
        monkeypatch.setattr(appmod, "_UPLOAD_ROOT", tmp_path)
        for bad in ["../passwd", "..%2Fpasswd", "%2E%2E%2Fpasswd", ".hidden"]:
            res = client.get(f"/api/files/{bad}")
            # 关键：不能 200 返回文件（防止 path traversal 攻击）
            assert res.status_code in (400, 404), (
                f"path traversal not blocked: {bad} → {res.status_code} "
                f"（应是 400/404，不能是 200）"
            )
            # body 不能是真实文件内容
            if res.status_code == 200:
                pytest.fail(f"path traversal succeeded: {bad} → {res.text!r}")

    def test_serve_uploaded_file_not_found(self, app_ctx, tmp_path, monkeypatch):
        client, appmod = app_ctx
        monkeypatch.setattr(appmod, "_UPLOAD_ROOT", tmp_path)
        res = client.get("/api/files/nonexistent.png")
        assert res.status_code == 404


# ─────────────── _safe_filename 工具函数 ───────────────


class TestSafeFilename:
    """测试 app._safe_filename helper（v2.5+ 暴露在 app 模块级）。"""

    def test_strips_path(self):
        appmod = _try_import_app()
        assert hasattr(appmod, "_safe_filename"), "app.py 必须导出 _safe_filename"
        result = appmod._safe_filename("../../etc/passwd")
        assert "/" not in result
        assert "\\" not in result
        assert "passwd" in result

    def test_replaces_unsafe_chars(self):
        appmod = _try_import_app()
        result = appmod._safe_filename("a b$c@d.txt")
        # 特殊字符应被替换为 _；. 和 _ 保留
        assert "/" not in result
        assert "\\" not in result
        assert "txt" in result

    def test_empty_fallback(self):
        appmod = _try_import_app()
        result = appmod._safe_filename("")
        assert result == "file"

    def test_truncates_long_names(self):
        appmod = _try_import_app()
        long = "a" * 200 + ".txt"
        result = appmod._safe_filename(long)
        # _safe_filename 截断到 120 字符
        assert len(result) <= 120

    def test_unicode_filename_sanitized_safely(self):
        """中文文件名会被 _safe_filename 安全处理（不抛错、保留扩展名）。

        注意：当前 _safe_filename 正则只保留 [A-Za-z0-9._-]，中文会被替换为 _；
        这是安全设计（防止 UTF-8 路径攻击 + 文件名规范化）。
        本测试仅验证：处理后仍是非空字符串、保留 .md 扩展名、不含危险字符。
        """
        appmod = _try_import_app()
        result = appmod._safe_filename("中文文档.md")
        assert isinstance(result, str)
        assert len(result) > 0
        # 扩展名必须保留（_UPLOAD_NAME_RE 不含 .）
        assert result.endswith(".md"), f"扩展名丢失：{result!r}"
        # 不能含路径分隔符
        assert "/" not in result
        assert "\\" not in result
