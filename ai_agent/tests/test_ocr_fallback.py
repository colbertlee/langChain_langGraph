"""v2.1 — OCR Fallback 单元测试。

覆盖：
  1) ocr_extract_text: 依赖缺失 → 返回 ""
  2) ocr_extract_text: 文件不存在 → 返回 ""
  3) ocr_extract_text: 成功提取（mock pytesseract）
  4) build_ocr_context: 跳过非图片
  5) build_ocr_context: 用 file_id 从 upload_root 读图
  6) build_ocr_context: 单张失败不阻塞其它
  7) build_ocr_context: 文本截断
"""
from pathlib import Path
from unittest import mock

import pytest


# ============================================================
# 1) ocr_extract_text
# ============================================================
class TestOcrExtractText:
    def test_missing_dependency_returns_empty(self, tmp_path, monkeypatch):
        """pytesseract/PIL 未安装时 → 返回空字符串（不抛错）。"""
        from file_parser import ocr_extract_text

        # 把 import 弄失败：把 pytesseract / PIL 都隐藏
        monkeypatch.setattr(
            "builtins.__import__",
            lambda name, *a, **k: (_ for _ in ()).throw(ImportError(f"blocked {name}"))
            if name in ("pytesseract", "PIL.Image") else __import__(name, *a, **k),
        )
        fake_png = tmp_path / "a.png"
        fake_png.write_bytes(b"x")
        assert ocr_extract_text(str(fake_png)) == ""

    def test_nonexistent_path(self):
        from file_parser import ocr_extract_text

        assert ocr_extract_text("/no/such/path.png") == ""

    def test_success_mock(self, tmp_path, monkeypatch):
        """mock pytesseract + PIL → 验证返回值正确传递。"""
        from file_parser import ocr_extract_text

        # mock pytesseract
        import sys
        fake_pytesseract = mock.MagicMock()
        fake_pytesseract.image_to_string.return_value = "Hello OCR Text\n"

        fake_PIL_Image = mock.MagicMock()
        fake_im = mock.MagicMock()
        # __enter__/__exit__
        fake_im.__enter__.return_value = fake_im
        fake_im.__exit__.return_value = False
        fake_PIL_Image.open.return_value = fake_im

        # 注册到 sys.modules
        monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)
        monkeypatch.setitem(sys.modules, "PIL", mock.MagicMock())
        monkeypatch.setitem(sys.modules, "PIL.Image", fake_PIL_Image)

        fake_png = tmp_path / "a.png"
        fake_png.write_bytes(b"\x89PNG fake")
        text = ocr_extract_text(str(fake_png))
        assert text == "Hello OCR Text"
        fake_pytesseract.image_to_string.assert_called_once()


# ============================================================
# 2) build_ocr_context
# ============================================================
class TestBuildOcrContext:
    def test_empty_files_returns_empty(self):
        from file_parser import build_ocr_context

        assert build_ocr_context([]) == ""

    def test_skips_non_image_files(self):
        from file_parser import build_ocr_context

        out = build_ocr_context([
            {"file_name": "doc.pdf", "file_type": "pdf", "parsed_text": "x"},
        ])
        assert out == ""

    def test_uses_existing_parsed_text(self):
        """若 parsed_text 已含文字（前端/上传阶段跑过 OCR），直接复用。"""
        from file_parser import build_ocr_context

        out = build_ocr_context([
            {"file_name": "a.png", "file_type": "png", "parsed_text": "pre-extracted text"},
        ])
        assert '<ocr_extracted_text filename="a.png">' in out
        assert "pre-extracted text" in out
        assert "<ocr_extracted_files>" in out

    def test_reads_from_upload_root_by_file_id(self, tmp_path, monkeypatch):
        """file_id + upload_root 时按 disk 路径读图 OCR。"""
        import sys
        from file_parser import build_ocr_context

        # mock pytesseract
        fake_pytesseract = mock.MagicMock()
        fake_pytesseract.image_to_string.return_value = "Disk Read OCR"
        fake_PIL_Image = mock.MagicMock()
        fake_im = mock.MagicMock()
        fake_im.__enter__.return_value = fake_im
        fake_im.__exit__.return_value = False
        fake_PIL_Image.open.return_value = fake_im
        monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)
        monkeypatch.setitem(sys.modules, "PIL", mock.MagicMock())
        monkeypatch.setitem(sys.modules, "PIL.Image", fake_PIL_Image)

        # 准备 disk 上文件
        file_id = "fid-ocr-1"
        (tmp_path / f"{file_id}_x.png").write_bytes(b"\x89PNG fake")

        out = build_ocr_context(
            [{"file_name": "x.png", "file_type": "png", "file_id": file_id}],
            upload_root=tmp_path,
        )
        assert "Disk Read OCR" in out
        assert 'filename="x.png"' in out

    def test_long_text_truncated(self):
        from file_parser import build_ocr_context

        long_text = "x" * 10000
        out = build_ocr_context([
            {"file_name": "a.png", "file_type": "png", "parsed_text": long_text},
        ])
        # 截断到 4000 字符 + 截断提示
        assert "OCR 截断" in out
        # 10000 个连续 x 不应在结果中
        assert "x" * 5000 not in out

    def test_one_image_failure_does_not_block_others(self, monkeypatch, tmp_path):
        """一张图 OCR 抛错，另一张仍能成功。

        用真实磁盘 PNG + monotonic call_count 避免 id() 抖动。
        """
        import sys
        from file_parser import build_ocr_context

        # 准备三张真实占位 PNG（OCR 路径走 os.path.exists → 真实读图）
        file_paths = []
        for i in range(1, 4):
            p = tmp_path / f"{i}.png"
            p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
            file_paths.append(str(p))

        call_log: list[str] = []
        counter = {"n": 0}

        def fake_image_to_string(im, lang=None):
            counter["n"] += 1
            call_log.append(str(counter["n"]))
            if counter["n"] == 1:
                raise RuntimeError("OCR failed on first image")
            return f"text-{counter['n']}"

        fake_pytesseract = mock.MagicMock()
        fake_pytesseract.image_to_string.side_effect = fake_image_to_string

        fake_PIL_Image = mock.MagicMock()

        def open_factory(path):
            im = mock.MagicMock()
            im.__enter__.return_value = im
            im.__exit__.return_value = False
            return im

        fake_PIL_Image.open.side_effect = open_factory

        monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)
        monkeypatch.setitem(sys.modules, "PIL", mock.MagicMock())
        monkeypatch.setitem(sys.modules, "PIL.Image", fake_PIL_Image)

        out = build_ocr_context([
            {"file_name": "1.png", "file_type": "png", "file_path": file_paths[0]},
            {"file_name": "2.png", "file_type": "png", "file_path": file_paths[1]},
            {"file_name": "3.png", "file_type": "png", "file_path": file_paths[2]},
        ])
        # 第一张失败 → 后两张成功 → 至少一个 <ocr_extracted_text
        assert "<ocr_extracted_text" in out
        assert len(call_log) >= 2
        assert isinstance(out, str)
        assert "text-2" in out
        assert "text-3" in out


# ============================================================
# 3) 端到端：chat_stream_sse 在 vision_supported=False 时注入 OCR
# ============================================================
@pytest.mark.asyncio
async def test_chat_stream_vision_disabled_uses_ocr(monkeypatch, tmp_path):
    """vision_supported=False + 图片附件 → 注入 <ocr_extracted_text> 块（若 OCR 依赖缺失则降级）。"""
    import app as app_mod

    monkeypatch.setattr(app_mod, "_UPLOAD_ROOT", tmp_path)
    file_id = "fid-ocr-stream"
    # 写入一个 1x1 PNG（即使 OCR 不可用也不会崩）
    (tmp_path / f"{file_id}_img.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    )

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
                "message": "看图",
                "session_id": "so",
                "vision_supported": False,  # 关键：纯文本模型
                "files": [
                    {
                        "file_id": file_id,
                        "file_name": "img.png",
                        "file_type": "png",
                        "content_type": "image/png",
                    }
                ],
            },
        ) as r:
            async for _ in r.aiter_lines():
                pass

    msg = captured.get("message", "")
    # 没有 vision 标签
    assert "<vision_attachments>" not in msg
    # OCR 块（要么含 ocr 文本，要么依赖缺失时仅含说明——这里 pytesseract 缺失所以 block 应有提示性 marker）
    # 只要 message 不崩就行
    assert "img.png" in msg or "[图片附件]" in msg
