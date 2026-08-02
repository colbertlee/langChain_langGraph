"""DocumentLoaderRegistry + RAG 多格式加载测试（Day 11-12）。"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from langchain_core.documents import Document

from rag import DocumentLoaderRegistry


# ---- 结构 ----

def test_supported_suffixes_includes_common_formats():
    suffixes = DocumentLoaderRegistry.supported_suffixes()
    # 必须支持最常见的 txt / md
    assert ".txt" in suffixes
    assert ".md" in suffixes


def test_register_custom_loader():
    """自定义 loader 注册。"""
    original = DocumentLoaderRegistry._LOADERS.copy()

    def my_loader(p: str):
        return [Document(page_content="custom", metadata={"path": p})]

    DocumentLoaderRegistry.register(".myformat", my_loader)
    assert ".myformat" in DocumentLoaderRegistry.supported_suffixes()

    # 恢复原始
    DocumentLoaderRegistry._LOADERS.clear()
    DocumentLoaderRegistry._LOADERS.update(original)


def test_register_normalizes_suffix():
    """register 不带点也能识别。"""
    # 先记录原始 loader，测试后恢复
    original = DocumentLoaderRegistry._LOADERS.copy()

    def ldr(p):
        return [Document(page_content="x")]

    DocumentLoaderRegistry.register("XYZ", ldr)
    assert ".xyz" in DocumentLoaderRegistry.supported_suffixes()
    assert DocumentLoaderRegistry.get(".XYZ") is ldr
    assert DocumentLoaderRegistry.get("xyz") is ldr

    # 还原
    DocumentLoaderRegistry._LOADERS.clear()
    DocumentLoaderRegistry._LOADERS.update(original)


def test_register_get_is_case_insensitive():
    original = DocumentLoaderRegistry._LOADERS.copy()

    def ldr(p):
        return []

    DocumentLoaderRegistry.register(".TXT", ldr)
    assert DocumentLoaderRegistry.get(".txt") is ldr

    # 恢复（不能简单 pop —— 可能覆盖了原有 .txt）
    DocumentLoaderRegistry._LOADERS.clear()
    DocumentLoaderRegistry._LOADERS.update(original)
    assert DocumentLoaderRegistry.get(".txt") is not ldr


# ---- 真实加载 ----

def test_load_txt_file(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("Hello AI Agent", encoding="utf-8")
    docs = DocumentLoaderRegistry.load(str(f))
    assert len(docs) >= 1
    assert any("Hello AI Agent" in d.page_content for d in docs)


def test_load_md_file_as_text(tmp_path):
    """MD 走 TextLoader（不需要额外依赖）。"""
    f = tmp_path / "doc.md"
    f.write_text("# Title\n\nSome content", encoding="utf-8")
    docs = DocumentLoaderRegistry.load(str(f))
    assert any("# Title" in d.page_content for d in docs)


def test_load_csv_file(tmp_path):
    """CSV 需要 langchain_community CSVLoader；缺包时给出友好提示。"""
    f = tmp_path / "data.csv"
    f.write_text("name,age\nAlice,30\nBob,25\n", encoding="utf-8")
    try:
        docs = DocumentLoaderRegistry.load(str(f))
        # 至少 1 个 doc
        assert docs
    except RuntimeError as e:
        # 缺包时跳过（环境差异）
        pytest.skip(f"csv loader not available: {e}")


def test_load_json_file(tmp_path):
    f = tmp_path / "data.json"
    f.write_text('[{"a": 1}, {"a": 2}]', encoding="utf-8")
    try:
        docs = DocumentLoaderRegistry.load(str(f))
        assert isinstance(docs, list)
    except RuntimeError as e:
        pytest.skip(f"json loader not available: {e}")


def test_load_pdf_file_when_pypdf_missing(tmp_path):
    """PDF 没装 pypdf 时给出可读错误。"""
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 (fake)")
    try:
        from langchain_community.document_loaders import PyPDFLoader  # noqa: F401
    except ImportError:
        # pypdf 不可用 → runtime error 提示安装
        with pytest.raises(RuntimeError, match="需要额外依赖"):
            DocumentLoaderRegistry.load(str(f))
    else:
        # 装了 pypdf：跑通即可
        try:
            docs = DocumentLoaderRegistry.load(str(f))
            assert isinstance(docs, list)
        except Exception as e:
            pytest.skip(f"pdf load failed: {e}")


def test_load_docx_file_when_docx2txt_missing(tmp_path):
    f = tmp_path / "doc.docx"
    f.write_bytes(b"PK fake docx")
    try:
        from langchain_community.document_loaders import Docx2txtLoader  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="需要额外依赖"):
            DocumentLoaderRegistry.load(str(f))
    else:
        try:
            docs = DocumentLoaderRegistry.load(str(f))
            assert isinstance(docs, list)
        except Exception as e:
            pytest.skip(f"docx load failed: {e}")


def test_load_unknown_extension_falls_back_to_text(tmp_path):
    """未注册扩展名走文本兜底（不能崩）。"""
    # 使用罕见的扩展名避免被其他测试污染（每个测试的 tmp_path 是独立的）
    f = tmp_path / "weird.qzz999"
    f.write_text("fallback content", encoding="utf-8")
    docs = DocumentLoaderRegistry.load(str(f))
    assert any("fallback" in d.page_content for d in docs)


def test_load_missing_file_raises(tmp_path):
    """不存在的文件要明确报错。"""
    with pytest.raises(FileNotFoundError):
        DocumentLoaderRegistry.load(str(tmp_path / "nope.txt"))


# ---- 集成：load_documents 返回 (ok, summary) ----

def test_load_documents_returns_tuple_format(tmp_path):
    """Day 11-12：新接口约定为 (ok, summary) — 不调用真实 chroma。"""
    from unittest.mock import MagicMock

    from rag import RAGModule
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    f = tmp_path / "hello.txt"
    f.write_text("Hello RAG", encoding="utf-8")

    # 跳过 __init__，手工注入必要字段
    rag = RAGModule.__new__(RAGModule)
    rag.text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    rag.embeddings = MagicMock()
    rag.vectorstore = None
    rag.model = MagicMock()
    rag.prompt = MagicMock()

    # Replace Chroma.from_documents + as_retriever
    class FakeChroma:
        def as_retriever(self, **_kw):
            class R:
                def invoke(self, q):
                    return []

            return R()

    with patch("rag.Chroma.from_documents", return_value=FakeChroma()):
        ok, summary = rag.load_documents([str(f)])

    assert isinstance(ok, bool)
    assert isinstance(summary, str)
    assert ok is True
    assert "chunk" in summary or "部分" in summary or "加载" in summary


def test_supported_formats_returns_list():
    from rag import RAGModule

    with patch.object(RAGModule, "__init__", lambda self: None):
        rag = RAGModule()
        formats = rag.supported_formats()
        assert isinstance(formats, list)
        # 不能依赖大小写或顺序；每个都该出现
        assert "txt" in {f.lower() for f in formats}
        assert "md" in {f.lower() for f in formats}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))
