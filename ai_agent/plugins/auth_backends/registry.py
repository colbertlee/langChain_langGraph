"""Auth / HITL 注册表。"""

from __future__ import annotations

from typing import Dict, List, Type

from .base import AuthProvider, HITLNotifier


class AuthProviderRegistry:
    _PROVIDERS: Dict[str, Type[AuthProvider]] = {}

    @classmethod
    def register(cls, provider_id: str, provider_cls: Type[AuthProvider]) -> None:
        cls._PROVIDERS[provider_id] = provider_cls

    @classmethod
    def get(cls, provider_id: str) -> Type[AuthProvider]:
        if provider_id not in cls._PROVIDERS:
            raise KeyError(f"auth provider not registered: {provider_id}")
        return cls._PROVIDERS[provider_id]

    @classmethod
    def create(cls, provider_id: str, config: Dict | None = None) -> AuthProvider:
        return cls.get(provider_id)(config)

    @classmethod
    def list(cls) -> List[str]:
        return sorted(cls._PROVIDERS.keys())


class HITLNotifierRegistry:
    _NOTIFIERS: Dict[str, Type[HITLNotifier]] = {}

    @classmethod
    def register(cls, channel_id: str, notifier_cls: Type[HITLNotifier]) -> None:
        cls._NOTIFIERS[channel_id] = notifier_cls

    @classmethod
    def get(cls, channel_id: str) -> Type[HITLNotifier]:
        if channel_id not in cls._NOTIFIERS:
            raise KeyError(f"hitl notifier not registered: {channel_id}")
        return cls._NOTIFIERS[channel_id]

    @classmethod
    def create(cls, channel_id: str, config: Dict | None = None) -> HITLNotifier:
        return cls.get(channel_id)(config)

    @classmethod
    def list(cls) -> List[str]:
        return sorted(cls._NOTIFIERS.keys())