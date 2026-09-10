"""file_parser — 多模态文件解析（v2.1）。

设计目标：
  - 输入：本地上传的文件路径（可以是临时文件）
  - 输出：ParsedFile 字典 {kind, text, markdown, meta}
      * kind     = 'pdf' | 'docx' | 'csv' | 'xlsx' | 'text' | 'image' | 'unknown'
      * text     = 提取出的纯文本（用作上下文注入）
      * markdown = 适合直接拼到消息里的 Markdown 表示（表格等）
      * meta     = 附加信息（页数 / 行列数 / base64 等）
  - 容错：每个解析器都用 try/except 包装，依赖缺失或解析失败不抛，
    返回 {kind: 'unknown', text: '<读取失败: ...>', markdown: '...', meta: {error: ...}}
  - 性能：CSV/XLSX 大文件只截前 N 行（默认 200 行）

可选用依赖（缺失不影响其他格式）：
  - pypdf           —— PDF
  - pdfplumber      —— PDF 备选
  - python-docx     —— DOCX
  - pandas + openpyxl —— XLSX
  - Pillow          —— 图片元信息
"""
from __future__ import annotations

import base64
import csv
import io
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ============================================================
# 类型
# ============================================================


@dataclass
class ParsedFile:
    kind: str
    text: str
    markdown: str
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "text": self.text, "markdown": self.markdown, "meta": self.meta}


# ============================================================
# 工具：可选依赖检查
# ============================================================


def _try_import(name: str, hint: str = ""):
    """尝试导入模块；失败返回 None（不抛错）。"""
    try:
        return __import__(name)
    except Exception:
        if hint:
            logger.debug(f"optional import {name} unavailable ({hint})")
        return None


# ============================================================
# 各格式解析器
# ============================================================


def _parse_pdf(path: str) -> ParsedFile:
    pypdf = _try_import("pypdf")
    if pypdf is not None:
        try:
            reader = pypdf.PdfReader(path)
            pages_text = []
            for i, page in enumerate(reader.pages):
                try:
                    pages_text.append(page.extract_text() or "")
                except Exception as e:
                    pages_text.append(f"[第 {i + 1} 页提取失败: {e}]")
            text = "\n\n".join(pages_text).strip()
            return ParsedFile(
                kind="pdf",
                text=text,
                markdown=text,
                meta={"pages": len(reader.pages), "engine": "pypdf"},
            )
        except Exception as e:
            return ParsedFile("unknown", f"<PDF 解析失败: {e}>", "", {"error": str(e)})
    pdfplumber = _try_import("pdfplumber")
    if pdfplumber is not None:
        try:
            with pdfplumber.open(path) as pdf:
                pages_text = [p.extract_text() or "" for p in pdf.pages]
            text = "\n\n".join(pages_text).strip()
            return ParsedFile(
                kind="pdf",
                text=text,
                markdown=text,
                meta={"pages": len(pages_text), "engine": "pdfplumber"},
            )
        except Exception as e:
            return ParsedFile("unknown", f"<PDF 解析失败: {e}>", "", {"error": str(e)})
    return ParsedFile(
        "unknown",
        "<PDF 解析依赖未安装：pip install pypdf>",
        "",
        {"missing": ["pypdf", "pdfplumber"]},
    )


def _parse_docx(path: str) -> ParsedFile:
    docx = _try_import("docx")
    if docx is None:
        return ParsedFile(
            "unknown",
            "<DOCX 解析依赖未安装：pip install python-docx>",
            "",
            {"missing": ["python-docx"]},
        )
    try:
        doc = docx.Document(path)
        paras = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
        for t in doc.tables:
            for row in t.rows:
                paras.append(" | ".join(cell.text.strip() for cell in row.cells))
        text = "\n".join(paras).strip()
        return ParsedFile(
            kind="docx",
            text=text,
            markdown=text,
            meta={"paragraphs": len(doc.paragraphs)},
        )
    except Exception as e:
        return ParsedFile("unknown", f"<DOCX 解析失败: {e}>", "", {"error": str(e)})


def _parse_csv(path: str, max_rows: int = 200) -> ParsedFile:
    """CSV 用 csv 模块即可；pandas 只用于 XLSX。"""
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return ParsedFile("csv", "", "", {"rows": 0})
        header, *data = rows
        truncated = len(data) > max_rows
        data = data[:max_rows]
        # Markdown 表格
        md_lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
        for row in data:
            md_lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |")
        md = "\n".join(md_lines)
        if truncated:
            md += f"\n\n_（仅展示前 {max_rows} 行；原始文件共 {len(rows) - 1} 行）_"
        text = "\n".join(",".join(r) for r in [header] + data)
        return ParsedFile(
            kind="csv",
            text=text,
            markdown=md,
            meta={"rows": len(rows) - 1, "truncated": truncated, "max_rows": max_rows},
        )
    except UnicodeDecodeError:
        # 兜底：尝试 gbk
        try:
            with open(path, "r", encoding="gbk", errors="ignore", newline="") as f:
                rows = list(csv.reader(f))
            if not rows:
                return ParsedFile("csv", "", "", {"rows": 0, "encoding": "gbk"})
            header, *data = rows
            md = "| " + " | ".join(header) + " |\n| " + " | ".join(["---"] * len(header)) + " |\n"
            md += "\n".join(
                "| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |" for r in data
            )
            return ParsedFile("csv", "\n".join(",".join(r) for r in [header] + data), md, {"encoding": "gbk"})
        except Exception as e:
            return ParsedFile("unknown", f"<CSV 解析失败: {e}>", "", {"error": str(e)})
    except Exception as e:
        return ParsedFile("unknown", f"<CSV 解析失败: {e}>", "", {"error": str(e)})


def _parse_xlsx(path: str, max_rows: int = 200) -> ParsedFile:
    pd = _try_import("pandas")
    if pd is None:
        return ParsedFile(
            "unknown",
            "<XLSX 解析依赖未安装：pip install pandas openpyxl>",
            "",
            {"missing": ["pandas", "openpyxl"]},
        )
    try:
        xls = pd.ExcelFile(path, engine="openpyxl")
        parts = []
        for sheet in xls.sheet_names:
            df = xls.parse(sheet).head(max_rows)
            md = f"### Sheet: {sheet}\n\n"
            md += df.to_markdown(index=False) if not df.empty else "_(empty sheet)_"
            if len(df) == max_rows:
                md += f"\n\n_（仅展示前 {max_rows} 行）_"
            parts.append(md)
        text = "\n\n".join(parts)
        return ParsedFile(
            kind="xlsx",
            text=text,
            markdown=text,
            meta={"sheets": xls.sheet_names, "engine": "pandas"},
        )
    except Exception as e:
        return ParsedFile("unknown", f"<XLSX 解析失败: {e}>", "", {"error": str(e)})


def _parse_text(path: str) -> ParsedFile:
    for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                content = f.read()
            return ParsedFile(kind="text", text=content, markdown=content, meta={"encoding": enc})
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return ParsedFile("unknown", f"<文本读取失败: {e}>", "", {"error": str(e)})
    return ParsedFile("unknown", "<文本编码无法识别>", "", {"error": "encoding detection failed"})


def _parse_json(path: str) -> ParsedFile:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        # 验证 JSON
        try:
            obj = json.loads(raw)
            pretty = json.dumps(obj, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            # 当文本 fallback
            return ParsedFile("text", raw, f"```json\n{raw}\n```", {"invalid_json": True})
        return ParsedFile("json", pretty, f"```json\n{pretty}\n```", {"valid": True})
    except Exception as e:
        return ParsedFile("unknown", f"<JSON 读取失败: {e}>", "", {"error": str(e)})


def _parse_markdown(path: str) -> ParsedFile:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return ParsedFile(kind="markdown", text=content, markdown=content, meta={})
    except Exception as e:
        return ParsedFile("unknown", f"<Markdown 读取失败: {e}>", "", {"error": str(e)})


def _parse_image(path: str) -> ParsedFile:
    """图片：当前实现只生成 base64 + 元信息，不做 OCR（无 OCR 依赖）。

    如果未来 Agent 启用 vision 模型，base64 可直接喂给多模态接口。
    """
    pil = _try_import("PIL.Image")
    meta: dict = {"vision_supported": False}
    try:
        if pil is not None:
            try:
                with pil.open(path) as im:
                    meta.update(
                        {
                            "width": im.width,
                            "height": im.height,
                            "format": im.format,
                            "mode": im.mode,
                        }
                    )
            except Exception as e:
                meta["pil_error"] = str(e)
        with open(path, "rb") as f:
            raw = f.read()
        b64 = base64.b64encode(raw).decode("ascii")
        meta["size_bytes"] = len(raw)
        meta["base64_length"] = len(b64)
        text = f"[图片附件] {os.path.basename(path)} ({meta.get('width', '?')}×{meta.get('height', '?')}, {len(raw)} bytes)"
        return ParsedFile(kind="image", text=text, markdown=text, meta=meta)
    except Exception as e:
        return ParsedFile("unknown", f"<图片读取失败: {e}>", "", {"error": str(e)})


# ============================================================
# 扩展名 → parser 路由表
# ============================================================

EXT_MAP = {
    ".pdf": _parse_pdf,
    ".docx": _parse_docx,
    ".csv": _parse_csv,
    ".xlsx": _parse_xlsx,
    ".txt": _parse_text,
    ".md": _parse_markdown,
    ".markdown": _parse_markdown,
    ".json": _parse_json,
    ".log": _parse_text,
    ".png": _parse_image,
    ".jpg": _parse_image,
    ".jpeg": _parse_image,
    ".webp": _parse_image,
    ".gif": _parse_image,
    ".bmp": _parse_image,
}


# ============================================================
# OCR Fallback（v2.1）— 当 vision 不可用时，从图片中提取文字注入上下文
# ============================================================


def ocr_extract_text(path: str, languages: str = "eng+chi_sim") -> str:
    """调用 pytesseract 从图片提取文字。

    Args:
        path: 图片文件路径（PNG/JPG/WEBP/BMP/GIF）
        languages: tesseract 语言（默认 eng+chi_sim）

    Returns:
        提取出的纯文本；任何错误（依赖缺失 / OCR 失败 / 文件不存在）
        都返回 ""，由调用方决定是否降级提示。
    """
    if not path or not os.path.exists(path):
        return ""
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return ""
    try:
        with Image.open(path) as im:
            text = pytesseract.image_to_string(im, lang=languages)
        return text.strip()
    except Exception:
        return ""


def build_ocr_context(
    files: list[dict],
    upload_root: Optional["Path"] = None,
    languages: str = "eng+chi_sim",
) -> str:
    """对图片附件批量 OCR，返回形如 <ocr_extracted_text> 的可注入上下文字符串。

    Args:
        files: 附件列表，每项至少含 {file_name, file_type, file_id?}
        upload_root: 当 file 只有 file_id 时用于按 disk 路径读图
        languages: tesseract 语言

    Returns:
        Markdown 块，包含 <ocr_extracted_text filename="...">...</ocr_extracted_text>
        ；若所有图片都没 OCR 文本，返回空字符串。

    Notes:
        - 单个图片 OCR 失败不影响其它图片；
        - 自动跳过非图片附件；
        - OCR 文本超长截断到 4000 字符。
    """
    if not files:
        return ""
    parts: list[str] = []
    for f in files:
        if not isinstance(f, dict):
            continue
        fname = str(f.get("file_name") or "unknown")
        ftype = (str(f.get("file_type") or "")).lower()
        # 也接受 content_type:image/*
        ctype = str(f.get("content_type") or "").lower()
        is_image = ftype in {"png", "jpg", "jpeg", "webp", "gif", "bmp"} or ctype.startswith(
            "image/"
        )
        if not is_image:
            continue
        # 先看是否已有 pre-parsed text（前端 / 上传阶段已跑过 OCR）
        text = (f.get("parsed_text") or "").strip()
        if not text:
            disk_path = None
            file_id = f.get("file_id")
            if file_id and upload_root:
                from pathlib import Path as _P

                for cand in _P(upload_root).glob(f"{file_id}_*"):
                    disk_path = str(cand)
                    break
            if not disk_path:
                # 兜底：直接用 file_name 找
                direct = f.get("file_path")
                if direct and os.path.exists(direct):
                    disk_path = str(direct)
            if disk_path:
                text = ocr_extract_text(disk_path, languages=languages)
        if not text:
            continue
        # 截断
        if len(text) > 4000:
            text = text[:4000] + "\n... (OCR 截断)"
        parts.append(
            f'<ocr_extracted_text filename="{fname}">\n{text}\n</ocr_extracted_text>'
        )
    if not parts:
        return ""
    return "<ocr_extracted_files>\n" + "\n\n".join(parts) + "\n</ocr_extracted_files>"


def parse_file(
    path: str,
    filename: Optional[str] = None,
    max_rows: int = 200,
) -> ParsedFile:
    """根据扩展名自动选用解析器。

    Args:
        path: 文件路径
        filename: 可选文件名（用于扩展名推断；缺省则用 path 的 basename）
        max_rows: CSV/XLSX 最多保留行数（防撑爆上下文）
    """
    if not os.path.exists(path):
        return ParsedFile("unknown", f"<文件不存在: {path}>", "", {"error": "not_found"})
    fname = filename or os.path.basename(path)
    ext = os.path.splitext(fname)[1].lower()
    parser = EXT_MAP.get(ext)
    if parser is None:
        # 未知类型 → 当文本兜底尝试
        try:
            return _parse_text(path)
        except Exception:
            return ParsedFile(
                "unknown",
                f"<不支持的文件类型: {ext}>",
                "",
                {"ext": ext, "filename": fname},
            )
    # CSV/XLSX 支持 max_rows，其他 parser 忽略额外参数
    if ext in (".csv", ".xlsx"):
        return parser(path, max_rows=max_rows)
    return parser(path)


# ============================================================
# 上下文注入 helper
# ============================================================


def build_attached_context(
    files: list[dict], upload_root: Optional["Path"] = None
) -> str:
    """根据已上传文件元信息（含可能已预解析的 text）构造上下文块。

    Args:
        files: 每项至少含 {file_name, file_type, text?}; text 缺省时为 ''。
        upload_root: 当 files 含 file_id 但没 text 时，按 file_id 从磁盘读。
    Returns:
        Markdown 块，包含 <attached_context filename="...">...</attached_context> 标签，
        直接拼接到 user message 末尾。
    """
    if not files:
        return ""
    from pathlib import Path as _Path
    parts = ["<attached_files>"]
    for f in files:
        fname = str(f.get("file_name") or "unknown")
        ftype = str(f.get("file_type") or "unknown")
        # 兼容多种字段名：text / parsed_text / content
        text = (
            f.get("text")
            or f.get("parsed_text")
            or f.get("content")
            or ""
        )
        if isinstance(text, str):
            text = text.strip()
        else:
            text = str(text)
        # file_id + upload_root：从磁盘读（兼容 test_chat_stream_vision_non_image_not_blocked）
        if not text and upload_root is not None and f.get("file_id"):
            try:
                root = _Path(upload_root)
                fid = str(f.get("file_id"))
                cand = None
                for ext in ("", ".txt", ".md", ".json", ".csv"):
                    p = root / f"{fid}{ext}"
                    if p.exists() and p.is_file():
                        cand = p
                        break
                if cand is None:
                    matches = list(root.glob(f"{fid}*"))
                    for m in matches:
                        if m.is_file():
                            cand = m
                            break
                if cand is not None:
                    text = cand.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                pass
        if not text:
            text = "(无法提取文本内容，请参考附件原始格式)"
        # 截断防注入撑爆上下文
        if len(text) > 8000:
            text = text[:8000] + f"\n\n... (截断，原文共 {len(text)} 字符)"
        parts.append(
            f'<attached_context filename="{fname}" type="{ftype}">\n'
            f"{text}\n"
            f"</attached_context>"
        )
    parts.append("</attached_files>")
    return "\n\n".join(parts)


def build_image_multimodal_block(path: str, filename: str | None = None, max_bytes: int = 4_000_000) -> dict | None:
    """构造 LangChain multimodal content block（用于 HumanMessage.content）。

    Returns:
        {"type": "image", "source_type": "base64", "mime_type": "...", "data": "...",
         "filename": "..."} —— 与 LangChain ChatPromptValue 多模态约定兼容。
        若 path 不存在或超过 max_bytes，返回 None（调用方降级）。
    """
    if not path or not os.path.exists(path):
        return None
    try:
        size = os.path.getsize(path)
        if size > max_bytes:
            return None
        with open(path, "rb") as f:
            raw = f.read()
        ext = os.path.splitext(filename or path)[1].lower()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }.get(ext, "image/png")
        return {
            "type": "image",
            "source_type": "base64",
            "mime_type": mime,
            "data": base64.b64encode(raw).decode("ascii"),
            "filename": filename or os.path.basename(path),
        }
    except Exception:
        return None


__all__ = [
    "ParsedFile",
    "parse_file",
    "build_attached_context",
    "build_image_multimodal_block",
    "ocr_extract_text",
    "build_ocr_context",
    "EXT_MAP",
]
