"""
v2.2.2 — RAG System Tests (Milestone 2.2.2)

覆盖：
  1) Embedding 后端（DeterministicEmbedding / 工厂）
  2) 向量切分（RecursiveCharacterTextSplitter）
  3) VectorStore 基本 CRUD + session 隔离
  4) RAGService.index_file / list_files / search / delete_file
  5) /api/rag/* REST 端点
  6) knowledge_search Tool（StructuredTool + session_id 注入）
  7) agent_tool_router 对 knowledge_search 的解析
  8) 端到端：Agent 通过 LangGraph 循环调 knowledge_search 回答问题
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import List

import pytest


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def tmp_chroma_dir():
    """v2.2.2 — 临时 ChromaDB 目录，测试结束清理。"""
    d = tempfile.mkdtemp(prefix="chroma_test_")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def tmp_upload_dir():
    """v2.2.2 — 临时上传目录。"""
    d = tempfile.mkdtemp(prefix="upload_test_")
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def fresh_vector_store(tmp_chroma_dir):
    """v2.2.2 — 全新 VectorStore（用 DeterministicEmbedding 保证零网络）。"""
    from vector_store import (
        VectorStore,
        DeterministicEmbedding,
        reset_vector_store_instance,
    )

    reset_vector_store_instance()
    vs = VectorStore(
        persist_dir=tmp_chroma_dir,
        collection_name="tst",
        embedding=DeterministicEmbedding(dim=128),
    )
    yield vs
    reset_vector_store_instance()


@pytest.fixture
def reset_rag_modules():
    """v2.2.2 — 重置所有 RAG 单例（防止上一个测试残留）。"""
    from vector_store import reset_vector_store_instance
    from rag_service import reset_rag_service_instance
    from v21_tools.rag_tool import reset_knowledge_search_tool_instance

    reset_vector_store_instance()
    reset_rag_service_instance()
    reset_knowledge_search_tool_instance()
    yield
    reset_vector_store_instance()
    reset_rag_service_instance()
    reset_knowledge_search_tool_instance()


# ============================================================
# 1) Embedding 后端
# ============================================================


class TestEmbeddingBackend:
    """v2.2.2 — embedding 工厂 + DeterministicEmbedding 行为。"""

    def test_deterministic_embedding_is_deterministic(self):
        from vector_store import DeterministicEmbedding

        emb = DeterministicEmbedding(dim=64)
        v1 = emb.embed_query("hello world")
        v2 = emb.embed_query("hello world")
        assert v1 == v2
        assert len(v1) == 64

    def test_deterministic_embedding_similiar_texts_closer(self):
        from vector_store import DeterministicEmbedding
        import math

        emb = DeterministicEmbedding(dim=128)
        a = emb.embed_query("chromadb vector database")
        b = emb.embed_query("chromadb vector database")
        c = emb.embed_query("completely unrelated random text")
        # 完全相同 → cosine ~ 1.0
        assert math.fsum(a[i] * b[i] for i in range(len(a))) > 0.95
        # 不相关 → cosine 应该明显更小
        ab = math.fsum(a[i] * b[i] for i in range(len(a)))
        ac = math.fsum(a[i] * c[i] for i in range(len(a)))
        assert ab > ac

    def test_embedding_factory_falls_back_to_deterministic(
        self, monkeypatch, reset_rag_modules
    ):
        """RAG_EMBEDDING_BACKEND=deterministic 强制使用 DeterministicEmbedding。"""
        monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "deterministic")
        from vector_store import _make_embedding_backend, DeterministicEmbedding

        b = _make_embedding_backend()
        assert isinstance(b, DeterministicEmbedding)

    def test_embedding_factory_handles_ollama_failure(
        self, monkeypatch, reset_rag_modules
    ):
        """ollama 不可用时降级：优先 sentence-transformers，再降级 deterministic。"""
        monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "ollama")
        monkeypatch.setenv("RAG_OLLAMA_BASE_URL", "http://127.0.0.1:1")  # 不可达
        from vector_store import _make_embedding_backend

        b = _make_embedding_backend()
        # 至少不应抛异常 + 必须是可用的 backend
        assert b is not None
        # 验证能调 embed_query
        v = b.embed_query("hello")
        assert v and len(v) > 0


# ============================================================
# 2) 文档切分
# ============================================================


class TestTextSplitting:
    """v2.2.2 — RecursiveCharacterTextSplitter 切分。"""

    def test_split_text_short_returns_single_chunk(self):
        from rag_service import split_text

        chunks = split_text("短文本，无需切分", chunk_size=500, chunk_overlap=50)
        assert len(chunks) == 1
        assert chunks[0]["chunk_id"] == 0
        assert "短文本" in chunks[0]["text"]

    def test_split_text_long_produces_multiple_chunks(self):
        from rag_service import split_text

        long_text = ("LangGraph 是 LangChain 的扩展。" * 50)
        chunks = split_text(long_text, chunk_size=100, chunk_overlap=20)
        assert len(chunks) >= 5
        # chunk_id 单调递增
        ids = [c["chunk_id"] for c in chunks]
        assert ids == list(range(len(chunks)))

    def test_split_text_empty_returns_empty(self):
        from rag_service import split_text

        assert split_text("") == []
        assert split_text("   \n  \t  ") == []

    def test_split_text_chinese_separators(self):
        from rag_service import split_text

        text = "第一段。\n\n第二段！\n\n第三段？"
        chunks = split_text(text, chunk_size=200, chunk_overlap=20)
        # 至少 1 段能切出来
        assert len(chunks) >= 1
        # 内容应包含中文
        assert any("段" in c["text"] for c in chunks)


# ============================================================
# 3) VectorStore CRUD
# ============================================================


class TestVectorStore:
    """v2.2.2 — ChromaDB PersistentClient 行为。"""

    def test_init_creates_persist_dir(self, tmp_chroma_dir, reset_rag_modules):
        from vector_store import VectorStore, DeterministicEmbedding

        vs = VectorStore(
            persist_dir=tmp_chroma_dir,
            collection_name="tst",
            embedding=DeterministicEmbedding(),
        )
        # _ensure_init 被 collection 触发
        _ = vs.collection
        assert os.path.isdir(tmp_chroma_dir)

    def test_upsert_and_query(self, fresh_vector_store):
        vs = fresh_vector_store
        chunks = [
            {"text": "ChromaDB 是一个本地向量数据库", "chunk_id": 0},
            {"text": "LangGraph 用来编排 AI Agent 状态机", "chunk_id": 1},
            {"text": "Python 是最常用的 AI 编程语言", "chunk_id": 2},
        ]
        ids = vs.upsert_chunks(
            chunks=chunks, session_id="s1", file_id="f1", file_name="doc.md"
        )
        assert len(ids) == 3
        # 检索
        res = vs.query(query_text="向量数据库", session_id="s1", top_k=2)
        assert len(res) >= 1
        # 第一条应该是 ChromaDB 相关的
        top = res[0]
        assert "ChromaDB" in top["text"] or "向量" in top["text"]
        assert top["file_id"] == "f1"
        assert top["file_name"] == "doc.md"

    def test_session_isolation(self, fresh_vector_store):
        vs = fresh_vector_store
        vs.upsert_chunks(
            chunks=[{"text": "sessionA 的秘密", "chunk_id": 0}],
            session_id="A",
            file_id="fa",
            file_name="a.md",
        )
        vs.upsert_chunks(
            chunks=[{"text": "sessionB 的内容", "chunk_id": 0}],
            session_id="B",
            file_id="fb",
            file_name="b.md",
        )
        # sessionA 检索不到 sessionB 的内容
        res_a = vs.query(query_text="秘密", session_id="A", top_k=5)
        assert all("sessionB" not in r["text"] for r in res_a)
        res_b = vs.query(query_text="内容", session_id="B", top_k=5)
        assert all("sessionA" not in r["text"] for r in res_b)
        # 强制 session_id 不传时 → 拿不到任何结果（隔离生效）
        res_default = vs.query(query_text="secret", session_id="default", top_k=5)
        assert res_default == []

    def test_delete_file(self, fresh_vector_store):
        vs = fresh_vector_store
        vs.upsert_chunks(
            chunks=[
                {"text": "A", "chunk_id": 0},
                {"text": "B", "chunk_id": 1},
            ],
            session_id="s1",
            file_id="f1",
        )
        n = vs.delete_file(session_id="s1", file_id="f1")
        assert n == 2
        # 删除后应检索不到
        res = vs.query(query_text="A", session_id="s1", top_k=3)
        assert res == []

    def test_list_files_aggregates_by_file_id(self, fresh_vector_store):
        vs = fresh_vector_store
        vs.upsert_chunks(
            chunks=[{"text": f"chunk {i}", "chunk_id": i} for i in range(5)],
            session_id="s1",
            file_id="fileA",
            file_name="a.md",
        )
        vs.upsert_chunks(
            chunks=[{"text": f"hello {i}", "chunk_id": i} for i in range(3)],
            session_id="s1",
            file_id="fileB",
            file_name="b.md",
        )
        files = vs.list_files(session_id="s1")
        # 聚合到 file_id
        assert len(files) == 2
        ids = {f["file_id"] for f in files}
        assert ids == {"fileA", "fileB"}
        file_a = next(f for f in files if f["file_id"] == "fileA")
        assert file_a["chunk_count"] == 5

    def test_upsert_overwrites_same_id(self, fresh_vector_store):
        vs = fresh_vector_store
        vs.upsert_chunks(
            chunks=[{"text": "v1", "chunk_id": 0}],
            session_id="s",
            file_id="f",
        )
        vs.upsert_chunks(
            chunks=[{"text": "v2 (覆盖)", "chunk_id": 0}],
            session_id="s",
            file_id="f",
        )
        res = vs.query(query_text="v2", session_id="s", top_k=3)
        # 同一 chunk_id 重复写 → 应被覆盖（不重复）
        assert any("v2" in r["text"] for r in res)
        # 不会出现两个 chunk
        all_texts = [r["text"] for r in res]
        assert "v1" not in "".join(all_texts) or sum(1 for t in all_texts if "v" in t) == 1

    def test_singleton_get_vector_store(self, tmp_chroma_dir, reset_rag_modules, monkeypatch):
        """v2.2.2 — get_vector_store 返回同一实例。"""
        monkeypatch.setenv("RAG_CHROMA_DIR", tmp_chroma_dir)
        monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "deterministic")
        from vector_store import get_vector_store

        a = get_vector_store()
        b = get_vector_store()
        assert a is b


# ============================================================
# 4) RAGService 业务层
# ============================================================


class TestRAGService:
    """v2.2.2 — RAGService.index_file / list_files / search / delete。"""

    def _write_upload(self, upload_dir: Path, name: str, text: str) -> str:
        """在 upload_dir 写文件，返回 file_id（前缀）。"""
        file_id = f"abc12345{Path(name).suffix}"
        (upload_dir / file_id).write_text(text, encoding="utf-8")
        return file_id

    def test_index_text_file(self, tmp_upload_dir, fresh_vector_store, reset_rag_modules):
        from rag_service import RAGService

        text = "ChromaDB 是一个本地向量数据库。" * 30
        fid = self._write_upload(tmp_upload_dir, "note.txt", text)
        svc = RAGService(
            upload_root=str(tmp_upload_dir), vector_store=fresh_vector_store
        )
        result = svc.index_file(session_id="s1", file_id=fid, file_name="note.txt")
        assert result["success"] is True
        assert result["chunk_count"] >= 2
        assert result["text_length"] == len(text)
        assert result["file_id"] == fid

    def test_index_file_not_found(self, tmp_upload_dir, fresh_vector_store):
        from rag_service import RAGService

        svc = RAGService(
            upload_root=str(tmp_upload_dir), vector_store=fresh_vector_store
        )
        result = svc.index_file(session_id="s1", file_id="non-exist")
        assert result["success"] is False
        assert "not found" in result.get("error", "").lower()

    def test_index_then_search(self, tmp_upload_dir, fresh_vector_store):
        from rag_service import RAGService

        fid = self._write_upload(
            tmp_upload_dir,
            "doc.md",
            "LangGraph 是编排 AI 状态机的框架。ChromaDB 用于本地向量检索。",
        )
        svc = RAGService(
            upload_root=str(tmp_upload_dir), vector_store=fresh_vector_store
        )
        svc.index_file(session_id="s1", file_id=fid, file_name="doc.md")
        results = svc.search(session_id="s1", query="ChromaDB 向量", top_k=2)
        assert len(results) >= 1
        assert any("ChromaDB" in r["text"] for r in results)

    def test_list_and_delete(self, tmp_upload_dir, fresh_vector_store):
        from rag_service import RAGService

        fid = self._write_upload(tmp_upload_dir, "a.md", "内容A" * 20)
        svc = RAGService(
            upload_root=str(tmp_upload_dir), vector_store=fresh_vector_store
        )
        svc.index_file(session_id="s1", file_id=fid, file_name="a.md")
        files = svc.list_files(session_id="s1")
        assert len(files) == 1
        n = svc.delete_file(session_id="s1", file_id=fid)
        assert n >= 1
        files_after = svc.list_files(session_id="s1")
        assert files_after == []


# ============================================================
# 5) /api/rag/* REST 端点
# ============================================================


class TestRAGEndpoints:
    """v2.2.2 — FastAPI RAG 端点。"""

    def test_rag_index_and_list(
        self, tmp_upload_dir, fresh_vector_store, reset_rag_modules
    ):
        """v2.2.2 — POST /api/rag/index_file + GET /api/rag/files。"""
        from fastapi.testclient import TestClient
        from app import app
        from rag_service import RAGService, reset_rag_service_instance

        # 注入 test RAGService（绑到我们的 tmp_upload_dir + fresh_vector_store）
        reset_rag_service_instance()
        RAGService.__init__  # noqa
        import rag_service as rs

        rs._SERVICE = RAGService(
            upload_root=str(tmp_upload_dir), vector_store=fresh_vector_store
        )
        try:
            client = TestClient(app)
            # 1) 写文件
            (tmp_upload_dir / "myid1.md").write_text("ChromaDB 本地向量" * 20, encoding="utf-8")
            # 2) 索引
            r = client.post(
                "/api/rag/index_file",
                json={
                    "file_id": "myid1",
                    "session_id": "s1",
                    "file_name": "myid1.md",
                    "upload_root": str(tmp_upload_dir),
                },
            )
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is True
            assert body["chunk_count"] >= 1

            # 3) 列表
            r = client.get("/api/rag/files?session_id=s1")
            assert r.status_code == 200
            data = r.json()
            assert data["count"] >= 1
            assert any(f["file_id"].startswith("myid1") for f in data["files"])
        finally:
            reset_rag_service_instance()

    def test_rag_search(self, tmp_upload_dir, fresh_vector_store, reset_rag_modules):
        from fastapi.testclient import TestClient
        from app import app
        import rag_service as rs
        from rag_service import RAGService, reset_rag_service_instance

        reset_rag_service_instance()
        rs._SERVICE = RAGService(
            upload_root=str(tmp_upload_dir), vector_store=fresh_vector_store
        )
        try:
            (tmp_upload_dir / "f.md").write_text("ChromaDB 持久化向量数据库" * 5, encoding="utf-8")
            client = TestClient(app)
            r = client.post(
                "/api/rag/index_file",
                json={
                    "file_id": "f",
                    "session_id": "s1",
                    "file_name": "f.md",
                    "upload_root": str(tmp_upload_dir),
                },
            )
            assert r.status_code == 200

            r = client.post(
                "/api/rag/search",
                json={"session_id": "s1", "query": "ChromaDB", "top_k": 2},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["count"] >= 1
        finally:
            reset_rag_service_instance()

    def test_rag_search_validation(self, reset_rag_modules):
        from fastapi.testclient import TestClient
        from app import app

        client = TestClient(app)
        # 缺 session_id → 400
        r = client.post("/api/rag/search", json={"query": "x"})
        assert r.status_code == 400

    def test_rag_delete_file(
        self, tmp_upload_dir, fresh_vector_store, reset_rag_modules
    ):
        from fastapi.testclient import TestClient
        from app import app
        import rag_service as rs
        from rag_service import RAGService, reset_rag_service_instance

        reset_rag_service_instance()
        rs._SERVICE = RAGService(
            upload_root=str(tmp_upload_dir), vector_store=fresh_vector_store
        )
        try:
            (tmp_upload_dir / "del1.md").write_text("delete me" * 5, encoding="utf-8")
            client = TestClient(app)
            client.post(
                "/api/rag/index_file",
                json={
                    "file_id": "del1",
                    "session_id": "s1",
                    "file_name": "del1.md",
                    "upload_root": str(tmp_upload_dir),
                },
            )
            r = client.delete("/api/rag/files/del1?session_id=s1")
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is True
            assert body["deleted_chunks"] >= 1
        finally:
            reset_rag_service_instance()


# ============================================================
# 6) knowledge_search Tool
# ============================================================


class TestKnowledgeSearchTool:
    """v2.2.2 — StructuredTool 形式的 knowledge_search。"""

    def test_build_tool_returns_structured_tool(self, reset_rag_modules):
        from v21_tools.rag_tool import build_knowledge_search_tool

        tool = build_knowledge_search_tool()
        assert tool is not None
        assert getattr(tool, "name", "") == "knowledge_search"

    def test_knowledge_search_session_isolation(
        self, tmp_upload_dir, fresh_vector_store, reset_rag_modules
    ):
        """v2.2.2 — knowledge_search 不会跨 session 检索。"""
        from v21_tools.rag_tool import knowledge_search_impl
        import rag_service as rs
        from rag_service import RAGService, reset_rag_service_instance

        reset_rag_service_instance()
        rs._SERVICE = RAGService(
            upload_root=str(tmp_upload_dir), vector_store=fresh_vector_store
        )
        try:
            # sessionA 写一篇笔记
            (tmp_upload_dir / "fa.md").write_text(
                "ChromaDB 是本地持久化向量数据库。" * 10, encoding="utf-8"
            )
            rs._SERVICE.index_file(
                session_id="A", file_id="fa", file_name="fa.md",
                upload_root=str(tmp_upload_dir),
            )
            # sessionB 写另一篇
            (tmp_upload_dir / "fb.md").write_text(
                "LangGraph 是状态机框架。" * 10, encoding="utf-8"
            )
            rs._SERVICE.index_file(
                session_id="B", file_id="fb", file_name="fb.md",
                upload_root=str(tmp_upload_dir),
            )

            # 关键断言：A 调 knowledge_search 查 ChromaDB → 只看到自己的
            res_a = knowledge_search_impl(
                query="ChromaDB", top_k=3, session_id="A"
            )
            assert len(res_a) >= 1
            assert all("LangGraph" not in r["text"] for r in res_a)
            assert all(r["file_id"] == "fa" for r in res_a)

            # B 查 LangGraph → 只看到自己的
            res_b = knowledge_search_impl(
                query="LangGraph", top_k=3, session_id="B"
            )
            assert len(res_b) >= 1
            assert all("ChromaDB" not in r["text"] for r in res_b)

            # 用完全无关的 session 检索 → 应返回空
            res_c = knowledge_search_impl(
                query="ChromaDB", top_k=3, session_id="C"
            )
            assert res_c == []
        finally:
            reset_rag_service_instance()

    def test_tool_func_returns_markdown(
        self, tmp_upload_dir, fresh_vector_store, reset_rag_modules
    ):
        """v2.2.2 — tool func 返回 Markdown 字符串供 LLM 消费。"""
        from v21_tools.rag_tool import knowledge_search_func
        import rag_service as rs
        from rag_service import RAGService, reset_rag_service_instance

        reset_rag_service_instance()
        rs._SERVICE = RAGService(
            upload_root=str(tmp_upload_dir), vector_store=fresh_vector_store
        )
        try:
            (tmp_upload_dir / "m.md").write_text(
                "ChromaDB 持久化向量数据库。" * 5, encoding="utf-8"
            )
            rs._SERVICE.index_file(
                session_id="sX", file_id="m", file_name="m.md",
                upload_root=str(tmp_upload_dir),
            )
            md = knowledge_search_func(query="ChromaDB", top_k=2, session_id="sX")
            assert "knowledge_search" in md or "检索" in md or "ChromaDB" in md
            # 至少包含 chunk_id / score
            assert "score" in md
        finally:
            reset_rag_service_instance()

    def test_tool_handles_empty_query(self, reset_rag_modules):
        from v21_tools.rag_tool import knowledge_search_impl

        assert knowledge_search_impl(query="", session_id="s") == []
        assert knowledge_search_impl(query=None, session_id="s") == []  # type: ignore

    def test_tool_extracts_session_from_config(
        self, tmp_upload_dir, fresh_vector_store, reset_rag_modules
    ):
        """v2.2.2 — config.configurable.thread_id 也能识别 session。"""
        from v21_tools.rag_tool import knowledge_search_impl
        import rag_service as rs
        from rag_service import RAGService, reset_rag_service_instance

        reset_rag_service_instance()
        rs._SERVICE = RAGService(
            upload_root=str(tmp_upload_dir), vector_store=fresh_vector_store
        )
        try:
            (tmp_upload_dir / "c.md").write_text("LangGraph" * 20, encoding="utf-8")
            rs._SERVICE.index_file(
                session_id="configSess", file_id="c", file_name="c.md",
                upload_root=str(tmp_upload_dir),
            )
            res = knowledge_search_impl(
                query="LangGraph",
                top_k=2,
                config={"configurable": {"thread_id": "configSess"}},
            )
            assert len(res) >= 1
        finally:
            reset_rag_service_instance()


# ============================================================
# 7) agent_tool_router 集成
# ============================================================


class TestAgentToolRouterRAG:
    """v2.2.2 — agent_tool_router 对 knowledge_search 的解析。"""

    def test_router_resolves_knowledge_search(self, reset_rag_modules):
        from agent_tool_router import resolve_tools, clear_cache

        clear_cache()
        tools = resolve_tools(["knowledge_search"])
        assert len(tools) == 1
        assert getattr(tools[0], "name", "") == "knowledge_search"

    def test_router_resolves_mixed_tools(self, reset_rag_modules):
        from agent_tool_router import resolve_tools, clear_cache

        clear_cache()
        tools = resolve_tools(["web_search", "knowledge_search", "python_interpreter"])
        names = [getattr(t, "name", "") for t in tools]
        assert set(names) == {"web_search", "knowledge_search", "python_interpreter"}

    def test_router_skips_unknown_tool(self, reset_rag_modules):
        from agent_tool_router import resolve_tools, clear_cache

        clear_cache()
        tools = resolve_tools(["non_existent_tool_xyz"])
        assert tools == []


# ============================================================
# 8) 端到端：Agent 通过 LangGraph 循环调 knowledge_search
# ============================================================


class TestEndToEndKnowledgeSearch:
    """v2.2.2 — LangGraph ReAct loop 自主调用 knowledge_search。"""

    def test_agent_invoke_calls_knowledge_search_when_needed(
        self, tmp_upload_dir, fresh_vector_store, reset_rag_modules, isolated_env
    ):
        """完整 e2e：mock LLM 决定调 knowledge_search → agent 执行 tool → 拿到结果 → 继续生成。"""
        # 1) 准备 KB
        (tmp_upload_dir / "guide.md").write_text(
            "ChromaDB 是一款持久化向量数据库，支持 cosine 距离与 HNSW 索引。\n"
            "本系统使用 ChromaDB 做 Local-First 的 RAG 检索。",
            encoding="utf-8",
        )
        import rag_service as rs
        from rag_service import RAGService, reset_rag_service_instance
        from agent_tool_router import resolve_tools, clear_cache

        reset_rag_service_instance()
        clear_cache()
        rs._SERVICE = RAGService(
            upload_root=str(tmp_upload_dir), vector_store=fresh_vector_store
        )
        rs._SERVICE.index_file(
            session_id="e2e", file_id="guide", file_name="guide.md",
            upload_root=str(tmp_upload_dir),
        )

        # 2) Mock LLM：第一次返回 tool_call(knowledge_search)，第二次返回最终答案
        from langchain_core.messages import AIMessage

        calls = {"n": 0}

        class MockLLM:
            def bind(self, **kw):
                return self

            def bind_tools(self, tools, **kw):
                # LangChain 1.x create_agent 走 bind_tools；返回 self 即可
                return self

            def invoke(self, messages, **kw):
                calls["n"] += 1
                if calls["n"] == 1:
                    # 第一次：决定调 knowledge_search
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call_1",
                                "name": "knowledge_search",
                                "args": {"query": "ChromaDB 是什么", "top_k": 2},
                            }
                        ],
                    )
                return AIMessage(content="ChromaDB 是 Local-First 持久化向量数据库。")

            async def ainvoke(self, messages, **kw):
                return self.invoke(messages, **kw)

        # 3) 构造 agent（走 agent.py 的 create_agent）
        from langchain.agents import create_agent
        from langchain_core.tools import StructuredTool

        tool_objs = resolve_tools(["knowledge_search"])
        agent = create_agent(
            model=MockLLM(),
            tools=tool_objs,
            system_prompt="你是测试助手。",
        )

        # 4) invoke
        from langchain_core.runnables import RunnableConfig

        config = RunnableConfig(configurable={"thread_id": "e2e"})
        result = agent.invoke(
            {"messages": [("user", "ChromaDB 是什么？")]},
            config=config,
        )
        msgs = result.get("messages") if isinstance(result, dict) else result
        # 至少 3 条：user / ai(tool_call) / tool(result) / ai(answer)
        assert len(msgs) >= 3
        # 找到 tool 消息
        tool_msgs = [
            m for m in msgs if getattr(m, "type", "") == "tool"
        ]
        assert len(tool_msgs) >= 1
        # tool 消息应包含 ChromaDB 检索结果
        tool_content = str(getattr(tool_msgs[0], "content", ""))
        assert "ChromaDB" in tool_content or "knowledge_search" in tool_content

    def test_knowledge_search_in_agent_tools_uses_correct_session(
        self, tmp_upload_dir, fresh_vector_store, reset_rag_modules
    ):
        """v2.2.2 — 同一个 agent 在不同 thread_id 下，knowledge_search 只看本 session 数据。

        验证语义（不是 hash 行为）：
          - session A 的所有结果 file_id 都 == 'sa'
          - session B 的所有结果 file_id 都 == 'sb'
          - 跨 session 永远看不到对方的 file_id
        """
        a_text = (
            "alpha bravo charlie delta echo foxtrot golf hotel india juliet "
            "kilo lima mike november oscar papa quebec romeo sierra "
            "alpha bravo charlie delta echo foxtrot golf hotel india juliet "
            "kilo lima mike november oscar papa quebec romeo sierra "
            * 4
        )
        b_text = (
            "victor whiskey xray yankee zulu alpha bravo charlie delta "
            "echo foxtrot golf hotel india juliet kilo lima "
            "victor whiskey xray yankee zulu alpha bravo charlie delta "
            "echo foxtrot golf hotel india juliet kilo lima "
            * 4
        )
        a_text_unique = "UNIQUE_TOKEN_ALPHA_77777 " + a_text
        b_text_unique = "UNIQUE_TOKEN_BETA_99999 " + b_text
        (tmp_upload_dir / "sa.md").write_text(a_text_unique, encoding="utf-8")
        (tmp_upload_dir / "sb.md").write_text(b_text_unique, encoding="utf-8")
        import rag_service as rs
        from rag_service import RAGService, reset_rag_service_instance

        reset_rag_service_instance()
        rs._SERVICE = RAGService(
            upload_root=str(tmp_upload_dir), vector_store=fresh_vector_store
        )
        rs._SERVICE.index_file(
            session_id="A", file_id="sa", file_name="sa.md",
            upload_root=str(tmp_upload_dir),
        )
        rs._SERVICE.index_file(
            session_id="B", file_id="sb", file_name="sb.md",
            upload_root=str(tmp_upload_dir),
        )

        from v21_tools.rag_tool import knowledge_search_impl

        # 各种查询在 A 下：file_id 永远只能是 'sa'
        for q in [
            "UNIQUE_TOKEN_ALPHA_77777",
            "UNIQUE_TOKEN_BETA_99999",
            "alpha bravo charlie",
            "victor whiskey xray",
        ]:
            res = knowledge_search_impl(query=q, top_k=3, session_id="A")
            for r in res:
                assert r["file_id"] == "sa", (
                    f"Session isolation broken: query={q!r} in A returned "
                    f"file_id={r['file_id']!r}"
                )

        # 各种查询在 B 下：file_id 永远只能是 'sb'
        for q in [
            "UNIQUE_TOKEN_ALPHA_77777",
            "UNIQUE_TOKEN_BETA_99999",
            "alpha bravo charlie",
            "victor whiskey xray",
        ]:
            res = knowledge_search_impl(query=q, top_k=3, session_id="B")
            for r in res:
                assert r["file_id"] == "sb", (
                    f"Session isolation broken: query={q!r} in B returned "
                    f"file_id={r['file_id']!r}"
                )

        # 不存在的 session 永远返回空（或者只看到本 session 自己的）——
        # 关键断言：C session 永远看不到 A / B 的 file_id
        res_c = knowledge_search_impl(
            query="UNIQUE_TOKEN_ALPHA_77777", top_k=3, session_id="C"
        )
        for r in res_c:
            assert r["file_id"] not in ("sa", "sb"), (
                f"Cross-session leak: C session returned {r['file_id']!r}"
            )
