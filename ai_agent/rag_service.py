"""
v2.2.2 — RAG Service (Milestone 2.2.2)

职责：
  1) 接收 file_id + session_id → 找到磁盘上的上传文件 → parse_file 解析
  2) RecursiveCharacterTextSplitter 切分
  3) 调 VectorStore.upsert_chunks 写入 ChromaDB
  4) 提供 list_files / delete_file / search 三个上层 API（供 app.py / rag_tool 调用）

设计：
  - 上传文件位于 app._UPLOAD_ROOT（可通过 _upload_root 参数覆盖）
  - 强依赖 file_parser.parse_file
  - 强依赖 langchain_text_splitters.RecursiveCharacterTextSplitter（已安装）
  - 弱依赖 vector_store.get_vector_store（DI 友好）

单例：RAGService 用 module-level get_rag_service()，测试可 reset
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# 默认 chunk 切分参数
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 80


def _extract_session_id(
    *,
    explicit: Optional[str] = None,
    kwargs: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """P0-4 — 从多源提取 session_id。

    优先级：
      1) explicit 显式传入（最快路径，测试友好）
      2) kwargs['session_id'] 或 kwargs['thread_id']（StructuredTool 调用形式）
      3) config['configurable']['thread_id' | 'session_id']（LangGraph invoke 上下文）
      4) fallback 'default'
    """
    if explicit:
        return str(explicit)
    if kwargs:
        for key in ("session_id", "thread_id"):
            v = kwargs.get(key)
            if v:
                return str(v)
    if config and isinstance(config, dict):
        cfg = config.get("configurable") or {}
        if isinstance(cfg, dict):
            for key in ("thread_id", "session_id"):
                v = cfg.get(key)
                if v:
                    return str(v)
    return "default"


# ============================================================
# 1) 文本切分（包装 langchain RecursiveCharacterTextSplitter）
# ============================================================


def split_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    separators: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """v2.2.2 — 文本切分。每块返回 {text, chunk_id, page?}。"""
    if not text or not text.strip():
        return []
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except Exception as e:
        raise RuntimeError(
            f"langchain_text_splitters not available: {e}; pip install langchain-text-splitters"
        ) from e
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=list(separators) if separators else [
            "\n\n", "\n", "。", "！", "？", "；", " ", ""
        ],
    )
    parts = splitter.split_text(text)
    return [{"text": p, "chunk_id": i} for i, p in enumerate(parts)]


# ============================================================
# 2) RAG Service
# ============================================================


class RAGService:
    """v2.2.2 — RAG 高层 service。

    依赖：
      - upload_root: 上传文件目录（默认 app._UPLOAD_ROOT，测试可覆盖）
      - vector_store: VectorStore 实例（默认 get_vector_store()）
    """

    def __init__(
        self,
        upload_root: Optional[str] = None,
        vector_store: Any = None,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        self.upload_root = Path(upload_root) if upload_root else None
        self._vector_store = vector_store  # 延迟取
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def _get_vs(self):
        if self._vector_store is not None:
            return self._vector_store
        from vector_store import get_vector_store
        return get_vector_store()

    # ------------------------------------------------------------------
    # 索引：file_id + session_id → 解析 + 切分 + 写 chroma
    # ------------------------------------------------------------------

    def index_file(
        self,
        *,
        session_id: str,
        file_id: str,
        file_name: Optional[str] = None,
        upload_root: Optional[str] = None,
    ) -> Dict[str, Any]:
        """v2.2.2 — 把指定 file_id 索引到当前 session 的 KB。

        Returns:
          { success: bool, file_id, file_name, chunk_count, text_length, source }
        """
        if not session_id or not file_id:
            return {"success": False, "error": "session_id and file_id required"}

        # 1) 找文件
        root_str = upload_root or (str(self.upload_root) if self.upload_root else None)
        if not root_str:
            return {"success": False, "error": "upload_root not configured"}
        root = Path(root_str)
        if not root.exists():
            return {"success": False, "error": f"upload_root not exists: {root}"}

        # 2) 解析
        try:
            from file_parser import parse_file
        except Exception as e:
            return {"success": False, "error": f"file_parser unavailable: {e}"}

        # file_id 可能带后缀或不带：尝试 file_id* glob
        candidates = sorted(root.glob(f"{file_id}*"))
        target: Optional[Path] = None
        for c in candidates:
            if c.is_file():
                target = c
                break
        if target is None:
            return {"success": False, "error": f"file not found for id: {file_id}"}
        fname = file_name or target.name
        parsed = parse_file(str(target), filename=fname)
        text = parsed.text or ""
        if not text.strip():
            # 没有可索引文本：返回 success=False 但保留 file_name 记录
            return {
                "success": False,
                "error": "no text extracted from file",
                "file_id": file_id,
                "file_name": fname,
                "chunk_count": 0,
                "text_length": 0,
            }

        # 3) 切分
        chunks = split_text(
            text, chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap
        )
        if not chunks:
            return {
                "success": False,
                "error": "text splitter produced 0 chunks",
                "file_id": file_id,
                "file_name": fname,
            }

        # 4) 写入 vector store
        vs = self._get_vs()
        try:
            ids = vs.upsert_chunks(
                chunks=chunks, session_id=session_id, file_id=file_id, file_name=fname
            )
        except Exception as e:
            logger.error(f"upsert_chunks failed: {e}")
            return {"success": False, "error": f"vector store upsert failed: {e}"}

        return {
            "success": True,
            "file_id": file_id,
            "file_name": fname,
            "chunk_count": len(ids),
            "text_length": len(text),
            "source": parsed.kind or "unknown",
        }

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def search(
        self,
        *,
        session_id: str,
        query: str,
        top_k: int = 3,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """v2.2.2 — 在指定 session 内做相似度检索。"""
        vs = self._get_vs()
        return vs.query(
            query_text=query, session_id=session_id, top_k=top_k, min_score=min_score
        )

    # ------------------------------------------------------------------
    # 列表 / 删除
    # ------------------------------------------------------------------

    def list_files(self, *, session_id: str) -> List[Dict[str, Any]]:
        vs = self._get_vs()
        return vs.list_files(session_id=session_id)

    def delete_file(self, *, session_id: str, file_id: str) -> int:
        vs = self._get_vs()
        return vs.delete_file(session_id=session_id, file_id=file_id)


# ============================================================
# 3) 单例
# ============================================================


_SERVICE: Optional[RAGService] = None
_SERVICE_LOCK = threading.Lock()


def get_rag_service() -> RAGService:
    """v2.2.2 — 单例 RAGService（upload_root 默认从 app 拉）。"""
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            upload_root = None
            try:
                from app import _UPLOAD_ROOT  # type: ignore
                upload_root = str(_UPLOAD_ROOT)
            except Exception:
                pass
            _SERVICE = RAGService(upload_root=upload_root)
        return _SERVICE


def reset_rag_service_instance() -> None:
    """v2.2.2 — 测试辅助。"""
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = None


def set_rag_service_instance(svc: RAGService) -> None:
    """v2.2.2 — 测试辅助：注入 mock service。"""
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = svc


__all__ = [
    "RAGService",
    "split_text",
    "get_rag_service",
    "reset_rag_service_instance",
    "set_rag_service_instance",
    "_extract_session_id",
]
