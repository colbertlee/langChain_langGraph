"""RAG 后端抽象接口。

插件只需要实现 ``embed_documents`` / ``embed_query``，无需关心具体 SDK。
rag.RAGModule 通过 ``EmbeddingBackendRegistry`` 按 ``backend_id`` 路由。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class EmbeddingBackend(ABC):
    """Embedding 后端抽象。"""

    backend_id: str = "abstract"
    display_name: str = "abstract"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        ...

    @abstractmethod
    def embed_query(self, text: str) -> List[float]:
        ...

    # 可选：把 LangChain Embeddings 实例暴露出来，便于 RAGModule 直接复用
    def as_langchain_embeddings(self) -> Any:
        """返回 LangChain ``Embeddings`` 实例（默认 None，子类按需实现）。"""
        return None


class VectorStoreBackend(ABC):
    """向量库后端抽象。"""

    backend_id: str = "abstract"
    display_name: str = "abstract"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @abstractmethod
    def from_documents(self, documents: Any, embedding: Any, **kwargs: Any) -> Any:
        ...

    @abstractmethod
    def as_retriever(self, store: Any, **kwargs: Any) -> Any:
        ...