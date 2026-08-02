"""OpenAI Embedding 后端（默认）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import EmbeddingBackend
from .registry import EmbeddingBackendRegistry, VectorStoreBackendRegistry


class OpenAIEmbeddingBackend(EmbeddingBackend):
    backend_id = "openai"
    display_name = "OpenAI text-embedding-3-small"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError as e:
            raise ImportError("pip install langchain-openai") from e
        from config import OPENAI_API_KEY, EMBEDDING_API_KEY

        api_key = (config or {}).get("api_key") or EMBEDDING_API_KEY or OPENAI_API_KEY
        self._lc = OpenAIEmbeddings(api_key=api_key)

    def as_langchain_embeddings(self) -> Any:
        return self._lc

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._lc.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._lc.embed_query(text)


class ZhipuEmbeddingBackend(EmbeddingBackend):
    backend_id = "zhipu"
    display_name = "Zhipu embedding-2"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        try:
            from langchain_community.embeddings import ZhipuAIEmbeddings
        except ImportError as e:
            raise ImportError("pip install langchain-community") from e
        from config import EMBEDDING_API_KEY, OPENAI_API_KEY

        api_key = (config or {}).get("api_key") or EMBEDDING_API_KEY or OPENAI_API_KEY
        self._lc = ZhipuAIEmbeddings(
            api_key=api_key,
            model="embedding-2",
            zhipuai_api_base="https://open.bigmodel.cn/api/paas/v4/",
        )

    def as_langchain_embeddings(self) -> Any:
        return self._lc

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._lc.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._lc.embed_query(text)


class OllamaEmbeddingBackend(EmbeddingBackend):
    backend_id = "ollama"
    display_name = "Ollama mxbai-embed-large"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        try:
            from langchain_community.embeddings import OllamaEmbeddings
        except ImportError as e:
            raise ImportError("pip install langchain-community") from e
        model = (config or {}).get("model", "mxbai-embed-large")
        base_url = (config or {}).get("base_url", "http://localhost:11434")
        self._lc = OllamaEmbeddings(model=model, base_url=base_url)

    def as_langchain_embeddings(self) -> Any:
        return self._lc

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._lc.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._lc.embed_query(text)


# ---- 注册 ----
EmbeddingBackendRegistry.register("openai", OpenAIEmbeddingBackend)
EmbeddingBackendRegistry.register("zhipu", ZhipuEmbeddingBackend)
EmbeddingBackendRegistry.register("ollama", OllamaEmbeddingBackend)


# ---- Plugin 入口（被 PluginManager 通过 entry_point="plugins.rag_backends.openai_embedding" 加载）----
from plugin_manager import PluginManifest


class _RAGBackendPlugin:
    """把本模块内的注册视为一个 plugin 单元。"""

    PLUGIN_NAME = "rag_backends_builtin"

    def __init__(self, config: Dict | None = None):
        self.config = config or {}

    def on_load(self) -> None:
        # 触发 vector store 子模块的注册（import 即注册）
        try:
            from . import chroma_store  # noqa: F401
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "[plugin:rag_backends] vector store import failed: %s", e
            )
        import logging
        logging.getLogger(__name__).info(
            "[plugin:rag_backends] ready embedding=%s vector_store=%s",
            EmbeddingBackendRegistry.list(),
            VectorStoreBackendRegistry.list(),
        )

    def on_unload(self) -> None:
        # 不真正注销（避免破坏其他依赖）；仅打日志
        import logging
        logging.getLogger(__name__).info("[plugin:rag_backends] unloading (kept registrations)")


PLUGIN_CLASS = _RAGBackendPlugin


def builtin_manifest() -> PluginManifest:
    return PluginManifest(
        name="rag_backends_builtin",
        version="0.1.0",
        description="OpenAI/Zhipu/Ollama embedding + Chroma vector store 后端",
        entry_point="plugins.rag_backends.openai_embedding",
        capabilities=["embedding", "vector_store"],
        hooks=[],
        tags=["rag"],
    )