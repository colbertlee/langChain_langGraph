"""EmbeddingBackendRegistry / VectorStoreBackendRegistry。"""

from __future__ import annotations

from typing import Dict, Iterable, List, Type

from .base import EmbeddingBackend, VectorStoreBackend


class EmbeddingBackendRegistry:
    _BACKENDS: Dict[str, Type[EmbeddingBackend]] = {}

    @classmethod
    def register(cls, backend_id: str, backend_cls: Type[EmbeddingBackend]) -> None:
        cls._BACKENDS[backend_id] = backend_cls

    @classmethod
    def get(cls, backend_id: str) -> Type[EmbeddingBackend]:
        if backend_id not in cls._BACKENDS:
            raise KeyError(f"embedding backend not registered: {backend_id}")
        return cls._BACKENDS[backend_id]

    @classmethod
    def create(cls, backend_id: str, config: Dict | None = None) -> EmbeddingBackend:
        return cls.get(backend_id)(config)

    @classmethod
    def list(cls) -> List[str]:
        return sorted(cls._BACKENDS.keys())


class VectorStoreBackendRegistry:
    _BACKENDS: Dict[str, Type[VectorStoreBackend]] = {}

    @classmethod
    def register(cls, backend_id: str, backend_cls: Type[VectorStoreBackend]) -> None:
        cls._BACKENDS[backend_id] = backend_cls

    @classmethod
    def get(cls, backend_id: str) -> Type[VectorStoreBackend]:
        if backend_id not in cls._BACKENDS:
            raise KeyError(f"vector store backend not registered: {backend_id}")
        return cls._BACKENDS[backend_id]

    @classmethod
    def create(cls, backend_id: str, config: Dict | None = None) -> VectorStoreBackend:
        return cls.get(backend_id)(config)

    @classmethod
    def list(cls) -> List[str]:
        return sorted(cls._BACKENDS.keys())


def iter_all_backends() -> Iterable[str]:
    return list(EmbeddingBackendRegistry.list()) + [
        f"vector:{b}" for b in VectorStoreBackendRegistry.list()
    ]