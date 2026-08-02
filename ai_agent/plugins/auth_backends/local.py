"""默认（noop / 本地）实现：兜底用，不引入任何外部依赖。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .base import AuthPrincipal, AuthProvider, HITLNotifier
from .registry import AuthProviderRegistry, HITLNotifierRegistry

logger = logging.getLogger(__name__)


class StaticAuthProvider(AuthProvider):
    """最简 AuthProvider：直接接受 ``{"agent_id": ..., "roles": [...]}`` 形式凭证。"""

    provider_id = "static"

    def resolve(self, credentials: Any) -> Optional[AuthPrincipal]:
        if not isinstance(credentials, dict):
            return None
        agent_id = credentials.get("agent_id")
        if not agent_id:
            return None
        return AuthPrincipal(
            agent_id=agent_id,
            roles=credentials.get("roles", []) or [],
            display_name=credentials.get("display_name", agent_id),
            extra=credentials.get("extra") or {},
        )


class LoggingHITLNotifier(HITLNotifier):
    """默认 HITLNotifier：仅记录日志，便于本地开发与单测。"""

    channel_id = "log"

    async def send_request(self, request: Any) -> None:
        req_id = getattr(request, "request_id", "?")
        hook = getattr(request, "hook_point", "?")
        logger.info("[hitl/log] request req_id=%s hook=%s", req_id, hook)

    async def send_resolution(self, request: Any) -> None:
        status = getattr(request, "status", "?")
        req_id = getattr(request, "request_id", "?")
        logger.info("[hitl/log] resolved req_id=%s status=%s", req_id, status)


AuthProviderRegistry.register("static", StaticAuthProvider)
HITLNotifierRegistry.register("log", LoggingHITLNotifier)


# ---- Plugin 入口 ----

class _AuthBackendsPlugin:
    PLUGIN_NAME = "auth_backends_builtin"

    def __init__(self, config: Dict | None = None):
        self.config = config or {}

    def on_load(self) -> None:
        logger.info(
            "[plugin:auth_backends] providers=%s notifiers=%s",
            AuthProviderRegistry.list(),
            HITLNotifierRegistry.list(),
        )


PLUGIN_CLASS = _AuthBackendsPlugin


def builtin_manifest():
    from plugin_manager import PluginManifest
    return PluginManifest(
        name="auth_backends_builtin",
        version="0.1.0",
        description="Static AuthProvider + Log HITLNotifier（兜底实现）",
        entry_point="plugins.auth_backends.local",
        capabilities=["auth", "hitl_notify"],
        hooks=[],
        tags=["auth", "hitl", "builtin"],
    )