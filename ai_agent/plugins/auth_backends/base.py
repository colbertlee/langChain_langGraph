"""鉴权 / 通知抽象。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class AuthPrincipal:
    def __init__(
        self,
        agent_id: str,
        roles: Optional[List[str]] = None,
        display_name: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ):
        self.agent_id = agent_id
        self.roles = roles or []
        self.display_name = display_name or agent_id
        self.extra = extra or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "roles": list(self.roles),
            "display_name": self.display_name,
            "extra": self.extra,
        }


class AuthProvider(ABC):
    """把外部凭证解析为 AuthPrincipal。

    PermissionGuard 不强制使用；未配置 provider 时沿用"本地 policy 表"模式。
    """

    provider_id: str = "abstract"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @abstractmethod
    def resolve(self, credentials: Any) -> Optional[AuthPrincipal]:
        """返回 AuthPrincipal；解析失败返回 None。"""
        ...


class HITLNotifier(ABC):
    """HITL 审批事件分发器。"""

    channel_id: str = "abstract"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @abstractmethod
    async def send_request(self, request: Any) -> None:
        ...

    async def send_resolution(self, request: Any) -> None:  # 默认 no-op
        return None