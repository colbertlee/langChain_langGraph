"""
Remote HITL（Human-in-the-Loop）适配器

目标
----
headless 场景下没有 Web 弹窗，需要把"工具调用审批"路由到远程通道，
等用户在飞书/钉钉/邮件/自定义 webhook 上回复后再决定放行/拒绝。

设计
----
- ``RemoteHITLChannel`` 是抽象协议：发审批请求 + 等用户回复；
- ``WebhookChannel`` 通用 HTTP 实现，任意能回调 webhook 的前端都能用；
- ``LarkChannel`` / ``DingTalkChannel`` / ``SMTPChannel`` 是三个具体实现；
- ``RemoteHITLAdapter`` 满足 ``HITLAdapter`` 协议，串联 ``Channel`` + 决策缓存。

行为契约
--------
1. ``await adapter.decide(req)`` 立刻返回"已提交审批"的占位响应（默认 deny 并标记 ``pending=true``），
   让主流程不会无限阻塞；
2. 远程用户的最终决定通过 ``adapter.resolve(request_id, approved, reason)`` 写入；
3. 调用方可在后续的 PERMISSION_RESPONSE 事件中观测到结果（channel 自管审计）。

注意
----
- 本模块不直接做 HTTP 请求；``WebhookChannel`` 通过 ``aiohttp.ClientSession``，
  缺失 aiohttp 时降级为"仅记录 URL，不实际发送"。
- 真实环境里 Lark/DingTalk/SMTP 都需要签名 + token，本模块只提供骨架（带 TODO），
  业务侧按各自平台文档补齐签名逻辑即可。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol

from headless_agent import HITLAdapter, PermissionRequest, PermissionResponse

logger = logging.getLogger(__name__)


# ============================================================
# 抽象通道
# ============================================================

class RemoteHITLChannel(Protocol):
    """远程 HITL 通道协议。"""

    async def submit(self, request_id: str, request: PermissionRequest) -> None:
        """把审批请求发到远程通道（飞书卡片 / 钉钉消息 / 邮件 / webhook）。"""

    async def wait_for_response(
        self, request_id: str, timeout_s: float
    ) -> Optional[PermissionResponse]:
        """阻塞等远程用户回复。超时返回 None（视为未审批，默认 deny）。"""


# ============================================================
# 决策缓存 + Adapter
# ============================================================

@dataclass
class _PendingDecision:
    """单条审批请求的内部记录。"""

    request: PermissionRequest
    created_at: float
    response: Optional[PermissionResponse] = None
    event: asyncio.Event = field(default_factory=asyncio.Event)


class RemoteHITLAdapter:
    """把 ``Channel`` 包装成 ``HITLAdapter``，并管理决策缓存。

    使用::

        adapter = RemoteHITLAdapter(WebhookChannel(url="https://.../hitl"))
        headless = HeadlessAgent(hitl=adapter)

        # 在另一线程 / 回调里：
        await adapter.resolve(request_id, approved=True, reason="OK")
    """

    def __init__(
        self,
        channel: RemoteHITLChannel,
        *,
        timeout_s: float = 300.0,
        on_pending: Optional[Callable[[str, PermissionRequest], Awaitable[None]]] = None,
    ) -> None:
        self._channel = channel
        self._timeout_s = float(timeout_s)
        self._pending: Dict[str, _PendingDecision] = {}
        self._on_pending = on_pending

    # -------- HITLAdapter 接口 --------

    async def decide(self, request: PermissionRequest) -> PermissionResponse:
        """提交审批 → 等用户回复（带超时）→ 返回决策。

        - 超时：返回 deny + rule="timeout"，调用方应放弃该工具调用；
        - 用户拒绝：deny + rule="user_denied"；
        - 用户放行：approve + rule="user_approved"。
        """
        req_id = str(uuid.uuid4())
        pending = _PendingDecision(request=request, created_at=time.time())
        self._pending[req_id] = pending

        # 1. 提交到远程
        try:
            await self._channel.submit(req_id, request)
        except Exception as e:  # pragma: no cover - 防御性
            logger.warning(f"[RemoteHITL] submit failed: {e}")
            self._pending.pop(req_id, None)
            return PermissionResponse(
                approved=False,
                reason=f"channel_submit_failed: {e}",
                rule="channel_error",
            )

        if self._on_pending is not None:
            try:
                await self._on_pending(req_id, request)
            except Exception:  # pragma: no cover
                logger.exception("[RemoteHITL] on_pending callback raised; ignored")

        # 2. 等回复（带超时）
        try:
            await asyncio.wait_for(pending.event.wait(), timeout=self._timeout_s)
        except asyncio.TimeoutError:
            pending.response = PermissionResponse(
                approved=False,
                reason="remote approval timeout",
                rule="timeout",
            )

        # 3. 返回 + 清理
        resp = pending.response or PermissionResponse(
            approved=False,
            reason="no response",
            rule="no_response",
        )
        self._pending.pop(req_id, None)
        return resp

    # -------- 远程回调入口 --------

    async def resolve(
        self,
        request_id: str,
        approved: bool,
        reason: str = "",
    ) -> bool:
        """由 webhook 回调调用：把远程用户的决定写入缓存并唤醒等待者。"""
        pending = self._pending.get(request_id)
        if pending is None:
            logger.warning(f"[RemoteHITL] resolve unknown request_id={request_id}")
            return False
        pending.response = PermissionResponse(
            approved=approved,
            reason=reason,
            rule="user_approved" if approved else "user_denied",
        )
        pending.event.set()
        return True

    # -------- 状态查询（用于观测/调试） --------

    def pending_count(self) -> int:
        return len(self._pending)

    def list_pending(self) -> list[Dict[str, Any]]:
        out = []
        for rid, p in self._pending.items():
            out.append(
                {
                    "request_id": rid,
                    "tool": p.request.tool,
                    "args": p.request.args,
                    "created_at": p.created_at,
                    "resolved": p.response is not None,
                }
            )
        return out


# ============================================================
# Webhook 通道（通用 HTTP 实现）
# ============================================================

class WebhookChannel:
    """通过 HTTP POST 把审批请求发到一个 webhook URL。

    接收端需要：

    1. 解析 ``X-Request-Id`` + JSON body；
    2. 在用户回复后调用 ``RemoteHITLAdapter.resolve(request_id, ...)``；
    3. 通常通过反向调用 headless 暴露的另一个 HTTP endpoint 完成（不在本模块实现）。

    若环境中无 aiohttp，本通道会降级为"仅打日志"，不抛错。
    """

    def __init__(
        self,
        url: str,
        *,
        extra_headers: Optional[Dict[str, str]] = None,
        timeout_s: float = 10.0,
    ) -> None:
        self.url = url
        self._headers = {"Content-Type": "application/json"}
        if extra_headers:
            self._headers.update(extra_headers)
        self._timeout_s = timeout_s

    async def submit(self, request_id: str, request: PermissionRequest) -> None:
        payload = {
            "request_id": request_id,
            "tool": request.tool,
            "args": request.args,
            "context": request.context or {},
            "submitted_at": time.time(),
        }
        body = json.dumps(payload, ensure_ascii=False)

        try:
            import aiohttp  # type: ignore
        except ImportError:
            logger.info(
                f"[WebhookChannel] (dry-run, no aiohttp) -> {self.url}: "
                f"{body[:200]}..."
            )
            return

        try:
            timeout = aiohttp.ClientTimeout(total=self._timeout_s)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.url, data=body, headers=self._headers
                ) as resp:
                    if resp.status >= 400:
                        logger.warning(
                            f"[WebhookChannel] POST {self.url} -> HTTP {resp.status}"
                        )
        except Exception as e:  # pragma: no cover - 网络异常
            logger.warning(f"[WebhookChannel] POST failed: {e}")

    async def wait_for_response(
        self, request_id: str, timeout_s: float
    ) -> Optional[PermissionResponse]:
        # WebhookChannel 不在此处阻塞；由 RemoteHITLAdapter.resolve() 触发
        # 这里只保留协议完整性，实际不调用。
        raise NotImplementedError(
            "WebhookChannel uses RemoteHITLAdapter.resolve(); "
            "wait_for_response is not used."
        )


# ============================================================
# 占位：LarkChannel / DingTalkChannel / SMTPChannel
# （骨架，业务侧按各自平台文档补签名/模板）
# ============================================================

class LarkChannel:
    """飞书卡片消息通道（骨架）。"""

    def __init__(self, webhook_url: str, *, sign_secret: str = "") -> None:
        self.webhook_url = webhook_url
        self.sign_secret = sign_secret  # TODO: 实际接入按飞书签名规范

    async def submit(self, request_id: str, request: PermissionRequest) -> None:
        # TODO: 构造飞书 interactive card，包含 [放行] / [拒绝] 按钮；
        # 用户点击后回调到 RemoteHITLAdapter.resolve()。
        logger.info(
            f"[LarkChannel] (TODO) submit request_id={request_id} "
            f"tool={request.tool}"
        )

    async def wait_for_response(
        self, request_id: str, timeout_s: float
    ) -> Optional[PermissionResponse]:
        raise NotImplementedError


class DingTalkChannel:
    """钉钉消息通道（骨架）。"""

    def __init__(self, webhook_url: str, *, secret: str = "") -> None:
        self.webhook_url = webhook_url
        self.secret = secret  # TODO: 钉钉加签

    async def submit(self, request_id: str, request: PermissionRequest) -> None:
        # TODO: 钉钉 ActionCard / Markdown 消息模板
        logger.info(
            f"[DingTalkChannel] (TODO) submit request_id={request_id} "
            f"tool={request.tool}"
        )

    async def wait_for_response(
        self, request_id: str, timeout_s: float
    ) -> Optional[PermissionResponse]:
        raise NotImplementedError


class SMTPChannel:
    """邮件审批通道（骨架）。"""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        from_addr: str = "",
        to_addrs: Optional[list[str]] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_addr = from_addr or username
        self.to_addrs = list(to_addrs or [])

    async def submit(self, request_id: str, request: PermissionRequest) -> None:
        # TODO: 用 aiosmtplib 发邮件，body 含审批链接 + 回复指令
        logger.info(
            f"[SMTPChannel] (TODO) submit request_id={request_id} "
            f"tool={request.tool}"
        )

    async def wait_for_response(
        self, request_id: str, timeout_s: float
    ) -> Optional[PermissionResponse]:
        raise NotImplementedError


__all__ = [
    "RemoteHITLChannel",
    "RemoteHITLAdapter",
    "WebhookChannel",
    "LarkChannel",
    "DingTalkChannel",
    "SMTPChannel",
]