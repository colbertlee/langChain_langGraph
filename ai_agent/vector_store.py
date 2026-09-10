"""
v2.2.2 — Local-First Chroma Vector Store (Milestone 2.2.2)

设计目标：
  1) 用 chromadb 的 PersistentClient 把数据持久化在本地目录（如 data/chroma_db）
  2) Embedding 策略：
     - 默认 Ollama 远程（mxbai-embed-large / nomic-embed-text）
     - 不可用时回退 sentence-transformers（离线小模型）
     - 不可用时回退 DeterministicEmbedding（基于 token 哈希，零网络）
  3) Session 隔离：
     - 每次写入把 session_id / file_id 写入 Document Metadata
     - 查询必须强制 where={"session_id": active_session_id}
  4) 单例 + 线程安全（RLock 保护 _client/_collection 缓存）

注意：
  - 本模块不依赖 langchain_chroma（避免 LC 1.x 兼容性陷阱）
  - 测试不依赖真实网络（DeterministicEmbedding 提供稳定、可重复的伪向量）
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# 默认可写目录：<repo>/data/chroma_db
_DEFAULT_PERSIST_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "chroma_db"
)
_DEFAULT_COLLECTION = "kb_v2_2_2"


# ============================================================
# 1) Embedding 后端抽象 + 三个实现
# ============================================================


class EmbeddingBackend:
    """所有 embedding 实现的统一接口。"""

    name: str = "abstract"
    dim: int = 0

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> List[float]:
        # 默认实现：单文档走 embed_documents
        return self.embed_documents([text])[0]


class DeterministicEmbedding(EmbeddingBackend):
    """v2.2.2 测试用 embedding：基于 token 哈希生成稳定伪向量。

    优点：
      - 零网络、零额外依赖
      - 同样的输入永远产生同样的输出（哈希函数确定性）
      - 短文本能模拟"相似文本有相近向量"（共享 token 越多，cosine 越近）

    缺点：
      - 没有真实语义能力（同义词召回差）
      - 仅用于测试 + 离线兜底
    """

    name = "deterministic"
    dim = 256

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _hash_token(self, tok: str) -> int:
        h = hashlib.sha1(tok.encode("utf-8", errors="ignore")).digest()
        return int.from_bytes(h[:8], "big")

    def _vectorize_tokens(self, tokens: List[str]) -> List[float]:
        vec = [0.0] * self.dim
        if not tokens:
            return vec
        for t in tokens:
            h = self._hash_token(t)
            for i in range(8):
                idx = (h + i * 31) % self.dim
                sign = 1.0 if ((h >> i) & 1) else -1.0
                vec[idx] += sign
        # L2 normalize
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def _tokenize(self, text: str) -> List[str]:
        import re

        text = (text or "").lower()
        en = re.findall(r"[a-z0-9]+", text)
        zh_chars = re.findall(r"[\u4e00-\u9fff]", text)
        zh_bigrams = [f"{zh_chars[i]}{zh_chars[i+1]}" for i in range(len(zh_chars) - 1)]
        return en + zh_chars + zh_bigrams

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._vectorize_tokens(self._tokenize(t)) for t in texts]


class SentenceTransformersEmbedding(EmbeddingBackend):
    """v2.2.2 sentence-transformers 离线 embedding（需 pip install sentence-transformers）。

    默认模型：all-MiniLM-L6-v2 (384 维，~80MB)。可在构造时覆盖 model_name。
    """

    name = "sentence-transformers"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: str = "cpu") -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except Exception as e:
            raise RuntimeError(
                f"sentence-transformers not available: {e}; "
                "pip install sentence-transformers"
            ) from e
        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device=device)
        try:
            self.dim = int(self.model.get_sentence_embedding_dimension())
        except Exception:
            self.dim = 384

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [list(map(float, v)) for v in self.model.encode(
            list(texts or []), normalize_embeddings=True
        )]

    def embed_query(self, text: str) -> List[float]:
        v = self.model.encode([text or ""], normalize_embeddings=True)
        return list(map(float, v[0]))


class OllamaEmbedding(EmbeddingBackend):
    """v2.2.2 — Ollama 本地 embedding（mxbai-embed-large / nomic-embed-text）。

    通过 HTTP POST {base_url}/api/embeddings 调用：
      {"model": "...", "prompt": "..."}
      → {"embedding": [float, ...]}

    base_url 默认 http://localhost:11434，可通过 OLLAMA_BASE_URL 覆盖。
    """

    name = "ollama"

    def __init__(
        self,
        model: str = "mxbai-embed-large",
        base_url: str = "http://localhost:11434",
        timeout: float = 30.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.dim = 0  # 首次调用时填入

    def _call(self, prompt: str) -> List[float]:
        import json
        try:
            import urllib.request
        except Exception:
            from urllib import request as urllib_request
            urllib = type("u", (), {"request": urllib_request})()
        req = urllib.request.Request(
            f"{self.base_url}/api/embeddings",
            data=json.dumps({"model": self.model, "prompt": prompt or ""}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        emb = data.get("embedding") or []
        if self.dim == 0 and emb:
            self.dim = len(emb)
        return [float(x) for x in emb]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._call(t) for t in texts]


# ============================================================
# 2) Embedding 工厂 + 解析环境变量
# ============================================================


def _make_embedding_backend() -> EmbeddingBackend:
    """v2.2.2 — 解析环境变量决定 backend 优先级：

    RAG_EMBEDDING_BACKEND ∈ {ollama | sentence-transformers | deterministic}
      默认 ollama（缺它就降级 sentence-transformers；再降级 deterministic）

    RAG_OLLAMA_MODEL       默认 "mxbai-embed-large"
    RAG_OLLAMA_BASE_URL    默认 "http://localhost:11434"
    RAG_SBERT_MODEL        默认 "all-MiniLM-L6-v2"
    """
    backend = (
        os.environ.get("RAG_EMBEDDING_BACKEND")
        or "ollama"
    ).strip().lower()
    if backend == "ollama":
        try:
            ollama = OllamaEmbedding(
                model=os.environ.get("RAG_OLLAMA_MODEL", "mxbai-embed-large"),
                base_url=os.environ.get("RAG_OLLAMA_BASE_URL", "http://localhost:11434"),
            )
            # 健康检查：尝试调一次，确认可连通（否则 fallback）
            try:
                ollama.embed_query("hi")
            except Exception as _e:
                raise RuntimeError(f"ollama unhealthy: {_e}")
            return ollama
        except Exception as e:
            logger.warning(f"Ollama embedding unavailable, fallback to sentence-transformers: {e}")
            try:
                return SentenceTransformersEmbedding(
                    model_name=os.environ.get("RAG_SBERT_MODEL", "all-MiniLM-L6-v2")
                )
            except Exception as e2:
                logger.warning(
                    f"sentence-transformers init failed, fallback to deterministic: {e2}"
                )
                return DeterministicEmbedding(
                    dim=int(os.environ.get("RAG_DETERMINISTIC_DIM", "256"))
                )
    if backend in ("sentence-transformers", "sbert"):
        try:
            return SentenceTransformersEmbedding(
                model_name=os.environ.get("RAG_SBERT_MODEL", "all-MiniLM-L6-v2")
            )
        except Exception as e:
            logger.warning(
                f"sentence-transformers init failed, fallback to deterministic: {e}"
            )
            return DeterministicEmbedding(
                dim=int(os.environ.get("RAG_DETERMINISTIC_DIM", "256"))
            )
    return DeterministicEmbedding(dim=int(os.environ.get("RAG_DETERMINISTIC_DIM", "256")))


# ============================================================
# 3) Chroma PersistentClient 单例 + 工具
# ============================================================


class VectorStore:
    """v2.2.2 — ChromaDB 持久化单例 + 工具方法。"""

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        collection_name: Optional[str] = None,
        embedding: Optional[EmbeddingBackend] = None,
    ) -> None:
        self.persist_dir = persist_dir or os.environ.get("RAG_CHROMA_DIR", _DEFAULT_PERSIST_DIR)
        self.collection_name = collection_name or os.environ.get("RAG_COLLECTION_NAME", _DEFAULT_COLLECTION)
        self._embedding = embedding or _make_embedding_backend()
        self._lock = threading.RLock()
        self._client = None
        self._collection = None
        self._init_done = False

    @property
    def embedding(self) -> EmbeddingBackend:
        return self._embedding

    @property
    def client(self):
        self._ensure_init()
        return self._client

    @property
    def collection(self):
        self._ensure_init()
        return self._collection

    def _ensure_init(self) -> None:
        if self._init_done:
            return
        with self._lock:
            if self._init_done:
                return
            os.makedirs(self.persist_dir, exist_ok=True)
            try:
                import chromadb
            except Exception as e:
                raise RuntimeError(
                    f"chromadb not available: {e}; pip install chromadb"
                ) from e
            # chromadb 0.4+ 用 PersistentClient（旧 Settings(persist_directory=) 已弃用）
            try:
                self._client = chromadb.PersistentClient(path=self.persist_dir)
            except Exception:
                # 兜底：Settings API
                from chromadb.config import Settings
                self._client = chromadb.Client(
                    Settings(
                        chroma_db_impl="duckdb+parquet",
                        persist_directory=self.persist_dir,
                    )
                )
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            self._init_done = True

    # ---- 写入 ----

    def upsert_chunks(
        self,
        *,
        chunks: List[Dict[str, Any]],
        session_id: str,
        file_id: str,
        file_name: str = "",
    ) -> List[str]:
        """v2.2.2 — 把一组 chunk 写入 collection。

        Args:
          chunks: 每项 { "text": str, "chunk_id": int, "page": int? }
          session_id: 会话 id（强制 metadata）
          file_id: 文件 id（强制 metadata）
          file_name: 文件名（可选，写入 metadata 便于追溯）
        Returns:
          写入的 chroma ids 列表（顺序对应 chunks）
        """
        if not chunks:
            return []
        self._ensure_init()
        texts = [c.get("text") or "" for c in chunks]
        # 生成 embedding
        embeddings = self._safe_embed(texts)
        # 生成稳定 id："<session_id>::<file_id>::<chunk_id>"
        ids: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        for i, c in enumerate(chunks):
            cid = c.get("chunk_id", i)
            ids.append(f"{session_id}::{file_id}::{cid}")
            meta: Dict[str, Any] = {
                "session_id": session_id,
                "file_id": file_id,
                "chunk_id": int(cid) if cid is not None else i,
            }
            if file_name:
                meta["file_name"] = file_name
            if c.get("page") is not None:
                try:
                    meta["page"] = int(c.get("page"))
                except Exception:
                    pass
            metadatas.append(meta)
        with self._lock:
            # chroma 1.5 的 .add() 在 ids 已存在时会抛 ValueError；
            # 我们走 get-then-add 模式实现 upsert 语义（覆盖式）
            try:
                existing = self._collection.get(ids=ids)
                existing_ids = set(existing.get("ids") or [])
            except Exception:
                existing_ids = set()
            new_ids = [i for i in ids if i not in existing_ids]
            new_idx = [ids.index(i) for i in new_ids]
            update_ids = [i for i in ids if i in existing_ids]
            update_idx = [ids.index(i) for i in update_ids]
            if new_ids:
                self._collection.add(
                    ids=[ids[k] for k in new_idx],
                    documents=[texts[k] for k in new_idx],
                    embeddings=[embeddings[k] for k in new_idx] if embeddings else None,
                    metadatas=[metadatas[k] for k in new_idx],
                )
            if update_ids:
                # chroma 没有原生 update documents → 先删再加
                self._collection.delete(ids=update_ids)
                self._collection.add(
                    ids=[ids[k] for k in update_idx],
                    documents=[texts[k] for k in update_idx],
                    embeddings=[embeddings[k] for k in update_idx] if embeddings else None,
                    metadatas=[metadatas[k] for k in update_idx],
                )
            # 0.4+ 持久化是自动的（无需 .persist()）
            try:
                self._client.persist()  # type: ignore[attr-defined]
            except Exception:
                pass
        return ids

    def _safe_embed(self, texts: List[str]) -> List[List[float]]:
        """调 embedding，断网/异常时降级到 DeterministicEmbedding。"""
        try:
            vecs = self._embedding.embed_documents(texts)
            if vecs and all(v and len(v) > 0 for v in vecs):
                return vecs
        except Exception as e:
            logger.warning(f"primary embedding failed: {e}")
        # 兜底
        fb = DeterministicEmbedding(dim=getattr(self._embedding, "dim", 256) or 256)
        return fb.embed_documents(texts)

    # ---- 查询 ----

    def query(
        self,
        *,
        query_text: str,
        session_id: str,
        top_k: int = 3,
        where: Optional[Dict[str, Any]] = None,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """v2.2.2 — 在指定 session 内做相似度检索。

        Args:
          min_score: 相似度下限（cosine similarity）；低于此值的结果会被过滤。
            默认 0.0 表示不过滤。
        Returns:
          [{ "text": ..., "file_id": ..., "file_name": ..., "chunk_id": ..., "score": ... }, ...]
        """
        self._ensure_init()
        if not query_text or not session_id:
            return []
        # 强制 session 隔离
        where_clause: Dict[str, Any] = {"session_id": session_id}
        if where:
            where_clause.update(where)
        # embedding
        try:
            q_emb = self._safe_embed([query_text])[0]
        except Exception:
            q_emb = []
        if not q_emb:
            return []
        with self._lock:
            res = self._collection.query(
                query_embeddings=[q_emb],
                n_results=max(1, int(top_k)),
                where=where_clause,
                include=["documents", "metadatas", "distances"],
            )
        docs: List[Dict[str, Any]] = []
        ids_list = (res.get("ids") or [[]])[0]
        doc_list = (res.get("documents") or [[]])[0]
        meta_list = (res.get("metadatas") or [[]])[0]
        dist_list = (res.get("distances") or [[]])[0]
        for i, doc_text in enumerate(doc_list):
            meta = (meta_list[i] if i < len(meta_list) else {}) or {}
            dist = (dist_list[i] if i < len(dist_list) else None)
            # cosine distance → similarity
            try:
                score = float(1.0 - dist) if dist is not None else 0.0
            except Exception:
                score = 0.0
            # 低分过滤（cosine similarity < min_score 直接丢弃）
            if score < min_score:
                continue
            docs.append({
                "id": (ids_list[i] if i < len(ids_list) else ""),
                "text": doc_text,
                "file_id": meta.get("file_id", ""),
                "file_name": meta.get("file_name", ""),
                "chunk_id": meta.get("chunk_id", -1),
                "page": meta.get("page"),
                "score": round(score, 6),
            })
        return docs

    # ---- 删除 ----

    def delete_file(self, *, session_id: str, file_id: str) -> int:
        """v2.2.2 — 删除指定 session + file_id 下的所有 chunk。"""
        self._ensure_init()
        with self._lock:
            existing = self._collection.get(
                where={"$and": [{"session_id": session_id}, {"file_id": file_id}]}
            )
            ids = existing.get("ids") or []
            if ids:
                self._collection.delete(ids=ids)
                try:
                    self._client.persist()  # type: ignore[attr-defined]
                except Exception:
                    pass
        return len(ids)

    def list_files(self, *, session_id: str) -> List[Dict[str, Any]]:
        """v2.2.2 — 列出某 session 下所有已索引的文件。"""
        self._ensure_init()
        with self._lock:
            existing = self._collection.get(where={"session_id": session_id})
        ids: List[str] = existing.get("ids") or []
        metas: List[Dict[str, Any]] = existing.get("metadatas") or []
        # 按 file_id 聚合
        agg: Dict[str, Dict[str, Any]] = {}
        for i, _id in enumerate(ids):
            m = (metas[i] if i < len(metas) else {}) or {}
            fid = m.get("file_id", "")
            if not fid:
                continue
            entry = agg.setdefault(fid, {
                "file_id": fid,
                "file_name": m.get("file_name", ""),
                "session_id": session_id,
                "chunk_count": 0,
                "first_chunk_id": None,
            })
            entry["chunk_count"] += 1
            try:
                c = int(m.get("chunk_id", -1))
                if entry["first_chunk_id"] is None or c < entry["first_chunk_id"]:
                    entry["first_chunk_id"] = c
            except Exception:
                pass
        return list(agg.values())

    def count(self) -> int:
        self._ensure_init()
        with self._lock:
            return int(self._collection.count() or 0)


# ============================================================
# 4) 模块级单例
# ============================================================


_INSTANCE: Optional[VectorStore] = None
_INSTANCE_LOCK = threading.Lock()


def get_vector_store() -> VectorStore:
    """v2.2.2 — 单例 VectorStore。"""
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = VectorStore()
        return _INSTANCE


def reset_vector_store_instance() -> None:
    """v2.2.2 — 测试辅助：清空单例，下次 get_vector_store 重新创建。"""
    global _INSTANCE
    with _INSTANCE_LOCK:
        _INSTANCE = None


def set_vector_store_instance(vs: VectorStore) -> None:
    """v2.2.2 — 测试辅助：注入 mock VectorStore。"""
    global _INSTANCE
    with _INSTANCE_LOCK:
        _INSTANCE = vs


__all__ = [
    "EmbeddingBackend",
    "DeterministicEmbedding",
    "SentenceTransformersEmbedding",
    "OllamaEmbedding",
    "VectorStore",
    "get_vector_store",
    "reset_vector_store_instance",
    "set_vector_store_instance",
]
