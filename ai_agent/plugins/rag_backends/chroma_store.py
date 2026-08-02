"""Chroma 向量库后端。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import VectorStoreBackend
from .registry import VectorStoreBackendRegistry


class ChromaVectorStoreBackend(VectorStoreBackend):
    backend_id = "chroma"
    display_name = "Chroma (in-memory / local)"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        try:
            from langchain_chroma import Chroma
        except ImportError as e:
            raise ImportError("pip install langchain-chroma chromadb") from e
        self._chroma_cls = Chroma

    def from_documents(self, documents: Any, embedding: Any, **kwargs: Any) -> Any:
        collection_name = self.config.get("collection_name", "knowledge_base")
        return self._chroma_cls.from_documents(
            documents=documents,
            embedding=embedding,
            collection_name=collection_name,
            **kwargs,
        )

    def as_retriever(self, store: Any, **kwargs: Any) -> Any:
        k = self.config.get("k", 3)
        return store.as_retriever(search_kwargs={"k": k, **kwargs})


VectorStoreBackendRegistry.register("chroma", ChromaVectorStoreBackend)