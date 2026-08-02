"""Day 23：svg_to_png fallback 单测。"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.svg_to_png import svg_to_png, svg_to_pdf, PLACEHOLDER_PNG, main


SAMPLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">
  <rect width="100" height="50" fill="#34c759"/>
</svg>"""


# ---- svg_to_png fallback ----

def test_svg_to_png_fallback_when_no_cairosvg(tmp_path):
    """cairosvg 不可用 → 写占位 PNG"""
    svg = tmp_path / "in.svg"
    svg.write_text(SAMPLE_SVG, encoding="utf-8")
    png = tmp_path / "out.png"

    with patch.dict("sys.modules", {"cairosvg": None}):
        ok = svg_to_png(svg, png)

    assert ok is False
    assert png.exists()
    assert png.read_bytes() == PLACEHOLDER_PNG


def test_svg_to_png_with_cairosvg_mock(tmp_path):
    """cairosvg 可用时调用 svg2png"""
    svg = tmp_path / "in.svg"
    svg.write_text(SAMPLE_SVG, encoding="utf-8")
    png = tmp_path / "out.png"

    fake_cairo = type("C", (), {})()

    def fake_svg2png(*, url, write_to, output_width):
        Path(write_to).write_bytes(b"FAKE_PNG")

    fake_cairo.svg2png = fake_svg2png

    with patch.dict("sys.modules", {"cairosvg": fake_cairo}):
        ok = svg_to_png(svg, png)

    assert ok is True
    assert png.read_bytes() == b"FAKE_PNG"


def test_svg_to_png_creates_parent_dirs(tmp_path):
    svg = tmp_path / "in.svg"
    svg.write_text(SAMPLE_SVG, encoding="utf-8")
    png = tmp_path / "subdir" / "deep" / "out.png"

    with patch.dict("sys.modules", {"cairosvg": None}):
        svg_to_png(svg, png)

    assert png.exists()


def test_svg_to_png_handles_cairosvg_exception(tmp_path):
    """cairosvg 抛异常 → 走 fallback"""
    svg = tmp_path / "in.svg"
    svg.write_text(SAMPLE_SVG, encoding="utf-8")
    png = tmp_path / "out.png"

    class FakeCairoError:
        def svg2png(self, **kwargs):
            raise RuntimeError("native cairo lib not found")

    with patch.dict("sys.modules", {"cairosvg": FakeCairoError()}):
        ok = svg_to_png(svg, png)

    assert ok is False
    assert png.read_bytes() == PLACEHOLDER_PNG


def test_placeholder_png_is_valid_png_signature():
    """placeholder 应是真 PNG（前 8 字节 magic）"""
    assert PLACEHOLDER_PNG[:8] == b"\x89PNG\r\n\x1a\n"


def test_placeholder_png_is_16x16():
    """Day 24：placeholder 必须是 16×16 而非 1×1"""
    import struct
    # IHDR 在 offset 8：width(4 bytes) + height(4 bytes)
    w, h = struct.unpack(">II", PLACEHOLDER_PNG[16:24])
    assert w == 16
    assert h == 16


def test_placeholder_png_is_grayscale():
    """Day 24：placeholder 颜色类型应为 grayscale (0) 或 RGB (2)"""
    import struct
    # color_type 在 IHDR offset 8+4+4=16 后第 9 个字节
    color_type = PLACEHOLDER_PNG[25]
    assert color_type in (0, 2)  # grayscale or RGB


def test_placeholder_png_below_threshold():
    """Day 24：placeholder 仍 < 100 字节，触发 release notes fallback"""
    assert len(PLACEHOLDER_PNG) < 100


# ---- svg_to_pdf ----

def test_svg_to_pdf_returns_false_when_no_cairosvg(tmp_path):
    """cairosvg 不可用 → 返回 False"""
    svg = tmp_path / "in.svg"
    svg.write_text(SAMPLE_SVG, encoding="utf-8")
    pdf = tmp_path / "out.pdf"
    with patch.dict("sys.modules", {"cairosvg": None}):
        ok = svg_to_pdf(svg, pdf)
    assert ok is False
    # PDF 不会写（cairosvg 不可用）
    assert not pdf.exists()


def test_svg_to_pdf_with_cairosvg_mock(tmp_path):
    """cairosvg 可用时调用 svg2pdf"""
    svg = tmp_path / "in.svg"
    svg.write_text(SAMPLE_SVG, encoding="utf-8")
    pdf = tmp_path / "out.pdf"

    class FakeCairo:
        def svg2pdf(self, **kwargs):
            Path(kwargs["write_to"]).write_bytes(b"%PDF-1.4\nfake")

    with patch.dict("sys.modules", {"cairosvg": FakeCairo()}):
        ok = svg_to_pdf(svg, pdf)

    assert ok is True
    assert pdf.read_bytes() == b"%PDF-1.4\nfake"


# ---- CLI main --also-pdf ----

def test_main_also_pdf_with_fallback(tmp_path):
    svg = tmp_path / "in.svg"
    svg.write_text(SAMPLE_SVG, encoding="utf-8")
    png = tmp_path / "out.png"

    with patch.dict("sys.modules", {"cairosvg": None}):
        rc = main([str(svg), str(png), "--also-pdf"])

    assert rc == 0
    assert png.exists()


def test_main_also_pdf_creates_pdf_with_cairosvg(tmp_path):
    svg = tmp_path / "in.svg"
    svg.write_text(SAMPLE_SVG, encoding="utf-8")
    png = tmp_path / "out.png"

    class FakeCairo:
        def svg2png(self, **kwargs):
            Path(kwargs["write_to"]).write_bytes(b"PNG")
        def svg2pdf(self, **kwargs):
            Path(kwargs["write_to"]).write_bytes(b"%PDF-1.4\n")

    with patch.dict("sys.modules", {"cairosvg": FakeCairo()}):
        rc = main([str(svg), str(png), "--also-pdf"])

    assert rc == 0
    assert png.read_bytes() == b"PNG"
    pdf = png.with_suffix(".pdf")
    assert pdf.exists()
    assert pdf.read_bytes() == b"%PDF-1.4\n"


# ---- CLI main ----

def test_main_returns_0_with_fallback(tmp_path, capsys):
    svg = tmp_path / "in.svg"
    svg.write_text(SAMPLE_SVG, encoding="utf-8")
    png = tmp_path / "out.png"

    with patch.dict("sys.modules", {"cairosvg": None}):
        rc = main([str(svg), str(png)])

    assert rc == 0
    err = capsys.readouterr().err
    assert "placeholder" in err or "fallback" in err


def test_main_returns_0_with_cairosvg_mock(tmp_path):
    svg = tmp_path / "in.svg"
    svg.write_text(SAMPLE_SVG, encoding="utf-8")
    png = tmp_path / "out.png"

    class FakeCairo:
        def svg2png(self, **kwargs):
            Path(kwargs["write_to"]).write_bytes(b"OK")

    with patch.dict("sys.modules", {"cairosvg": FakeCairo()}):
        rc = main([str(svg), str(png)])

    assert rc == 0
    assert png.read_bytes() == b"OK"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))