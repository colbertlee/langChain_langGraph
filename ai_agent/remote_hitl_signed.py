"""
remote_hitl_signed.py — 飞书 / 钉钉 / SMTP 真实签名实现

替换 ``remote_hitl.py`` 里的 LarkChannel / DingTalkChannel / SMTPChannel 骨架，
加上官方签名 + 最小请求体。

签名规范
--------
- 飞书（Lark）：自定义机器人 Webhook 用 HMAC-SHA256，timestamp + secret 在 URL 上；
  本实现对应"自定义机器人接入"，是企业自建应用通知的简化版。
- 钉钉：自定义机器人用 ``secret`` 加签，timestamp + sign 拼到 URL。
- SMTP：明文 / STARTTLS / SSL-TLS 三档，靠 ``aiosmtplib`` 异步发送。

依赖
----
- 三个 channel 都依赖 aiohttp（飞书/钉钉）和 aiosmtplib（邮件）；
  缺失时 import 阶段就会失败——上层调用方应 ``pip install aiohttp aiosmtplib``，
  否则使用 ``remote_hitl.WebhookChannel`` 通用 webhook 兜底。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from headless_agent import PermissionRequest
from remote_hitl import RemoteHITLChannel  # 协议（接口）从原模块继承

logger = logging.getLogger(__name__)


# ============================================================
# 飞书 (Lark) 自定义机器人
# ============================================================

class LarkChannel:
    """飞书自定义机器人（Incoming Webhook）。

    签名算法（HmacSHA256，timestamp 在 URL 上）::

        string_to_sign = f"{timestamp}\\n{secret}"
        digest = hmac.new(secret.encode(), string_to_sign.encode(),
                          hashlib.sha256).digest()
        sign = base64.b64encode(digest).decode()
        url_with_sign = f"{webhook_url}?timestamp={ts}&sign={quote(sign)}"

    参考：飞书"自定义机器人使用指南" → 安全设置 → 签名校验。
    """

    def __init__(self, webhook_url: str, *, secret: str = "") -> None:
        if not webhook_url:
            raise ValueError("webhook_url is required for LarkChannel")
        self.webhook_url = webhook_url
        self.secret = secret

    def _sign_url(self) -> str:
        ts = str(int(time.time()))
        string_to_sign = f"{ts}\n{self.secret}".encode("utf-8")
        digest = hmac.new(
            self.secret.encode("utf-8"), string_to_sign, hashlib.sha256
        ).digest()
        sign = base64.b64encode(digest).decode("utf-8")
        return f"{self.webhook_url}?timestamp={ts}&sign={quote_plus(sign)}"

    def _build_payload(
        self, request_id: str, request: PermissionRequest
    ) -> Dict[str, Any]:
        """最小请求体：interactive card + 两个 callback 链接。

        业务侧可替换 msg_type 为 ``interactive`` 并补 card.header / card.elements。
        """
        approve_url = f"https://your-host/hitl/resolve?request_id={request_id}&approved=true"
        deny_url = f"https://your-host/hitl/resolve?request_id={request_id}&approved=false"

        return {
            "timestamp": int(time.time()),
            "sign": "",  # 已移到 URL 上；body 这里可省
            "msg_type": "post",
            "content": {
                "post": {
                    "en-US": {
                        "title": f"[HITL] 工具调用审批: {request.tool}",
                        "content": [
                            [
                                {"tag": "text", "text": f"工具: {request.tool}"},
                                {"tag": "text", "text": f"参数: {json.dumps(request.args, ensure_ascii=False)}"},
                            ],
                            [
                                {"tag": "a", "text": "放行", "href": approve_url},
                                {"tag": "text", "text": "  "},
                                {"tag": "a", "text": "拒绝", "href": deny_url},
                            ],
                        ],
                    }
                }
            },
        }

    async def submit(self, request_id: str, request: PermissionRequest) -> None:
        try:
            import aiohttp  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "LarkChannel requires aiohttp; "
                "install with `pip install aiohttp`"
            ) from e

        url = self._sign_url() if self.secret else self.webhook_url
        payload = self._build_payload(request_id, request)

        try:
            timeout = aiohttp.ClientTimeout(total=10.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    body = await resp.text()
                    if resp.status >= 400:
                        logger.warning(
                            f"[LarkChannel] HTTP {resp.status}: {body[:200]}"
                        )
                    else:
                        logger.debug(f"[LarkChannel] OK: {body[:80]}")
        except Exception as e:  # pragma: no cover - 网络异常
            logger.warning(f"[LarkChannel] submit failed: {e}")

    async def wait_for_response(
        self, request_id: str, timeout_s: float
    ):  # pragma: no cover
        raise NotImplementedError


# ============================================================
# 钉钉 (DingTalk) 自定义机器人
# ============================================================

class DingTalkChannel:
    """钉钉自定义机器人（加签模式）。

    签名算法::

        string_to_sign = f"{timestamp}\\n{secret}"
        digest = hmac.new(secret.encode(), string_to_sign.encode(),
                          hashlib.sha256).digest()
        sign = base64.b64encode(digest).decode()
        url_with_sign = f"{webhook_url}&timestamp={ts}&sign={quote(sign)}"
    """

    def __init__(self, webhook_url: str, *, secret: str = "") -> None:
        if not webhook_url:
            raise ValueError("webhook_url is required for DingTalkChannel")
        self.webhook_url = webhook_url
        self.secret = secret

    def _sign_url(self) -> str:
        ts = str(round(time.time() * 1000))
        string_to_sign = f"{ts}\n{self.secret}".encode("utf-8")
        digest = hmac.new(
            self.secret.encode("utf-8"), string_to_sign, hashlib.sha256
        ).digest()
        sign = quote_plus(base64.b64encode(digest).decode("utf-8"))
        sep = "&" if "?" in self.webhook_url else "?"
        return f"{self.webhook_url}{sep}timestamp={ts}&sign={sign}"

    def _build_payload(
        self, request_id: str, request: PermissionRequest
    ) -> Dict[str, Any]:
        approve_url = f"https://your-host/hitl/resolve?request_id={request_id}&approved=true"
        deny_url = f"https://your-host/hitl/resolve?request_id={request_id}&approved=false"
        return {
            "msgtype": "actionCard",
            "actionCard": {
                "title": f"[HITL] 工具调用审批: {request.tool}",
                "text": (
                    f"### 工具调用审批请求\\n\\n"
                    f"**工具**: {request.tool}\\n\\n"
                    f"**参数**: `{json.dumps(request.args, ensure_ascii=False)}`\\n\\n"
                    f"---\\n请在 5 分钟内回复\\n"
                ),
                "singleTitle": "放行",
                "singleURL": approve_url,
                "btns": [
                    {"title": "放行", "actionURL": approve_url},
                    {"title": "拒绝", "actionURL": deny_url},
                ],
            },
        }

    async def submit(self, request_id: str, request: PermissionRequest) -> None:
        try:
            import aiohttp  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "DingTalkChannel requires aiohttp; "
                "install with `pip install aiohttp`"
            ) from e

        url = self._sign_url() if self.secret else self.webhook_url
        payload = self._build_payload(request_id, request)

        try:
            timeout = aiohttp.ClientTimeout(total=10.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    body = await resp.text()
                    if resp.status >= 400:
                        logger.warning(
                            f"[DingTalkChannel] HTTP {resp.status}: {body[:200]}"
                        )
                    else:
                        logger.debug(f"[DingTalkChannel] OK: {body[:80]}")
        except Exception as e:  # pragma: no cover
            logger.warning(f"[DingTalkChannel] submit failed: {e}")

    async def wait_for_response(
        self, request_id: str, timeout_s: float
    ):  # pragma: no cover
        raise NotImplementedError


# ============================================================
# SMTP 邮件
# ============================================================

class SMTPChannel:
    """异步 SMTP 邮件审批。

    支持：
    - 明文（端口 25，通常内网）
    - STARTTLS（端口 587，推荐）
    - SSL/TLS（端口 465）

    邮件内容为纯文本 + 审批链接（reply-to 不强制；用链接回调更可靠）。
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        from_addr: str = "",
        to_addrs: Optional[List[str]] = None,
        use_ssl: bool = False,
        use_starttls: bool = True,
    ) -> None:
        if not host or not username or not to_addrs:
            raise ValueError(
                "SMTPChannel requires host, username, and to_addrs"
            )
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.from_addr = from_addr or username
        self.to_addrs = list(to_addrs)
        self.use_ssl = bool(use_ssl)
        self.use_starttls = bool(use_starttls) and not self.use_ssl

    def _build_message(
        self, request_id: str, request: PermissionRequest
    ) -> str:
        approve_url = f"https://your-host/hitl/resolve?request_id={request_id}&approved=true"
        deny_url = f"https://your-host/hitl/resolve?request_id={request_id}&approved=false"

        body_lines = [
            "请审批以下工具调用：",
            "",
            f"工具: {request.tool}",
            f"参数: {json.dumps(request.args, ensure_ascii=False)}",
            "",
            f"放行: {approve_url}",
            f"拒绝: {deny_url}",
        ]
        body = "\n".join(body_lines)

        headers = [
            f"From: {self.from_addr}",
            f"To: {', '.join(self.to_addrs)}",
            f"Subject: [HITL] 工具调用审批: {request.tool}",
            "MIME-Version: 1.0",
            "Content-Type: text/plain; charset=utf-8",
            "",
            body,
        ]
        return "\r\n".join(headers)

    async def submit(self, request_id: str, request: PermissionRequest) -> None:
        try:
            import aiosmtplib  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "SMTPChannel requires aiosmtplib; "
                "install with `pip install aiosmtplib`"
            ) from e

        message = self._build_message(request_id, request)

        try:
            if self.use_ssl:
                await aiosmtplib.send(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    sender=self.from_addr,
                    recipients=self.to_addrs,
                    message=message.encode("utf-8"),
                    use_tls=True,
                )
            else:
                await aiosmtplib.send(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    sender=self.from_addr,
                    recipients=self.to_addrs,
                    message=message.encode("utf-8"),
                    use_tls=False,
                    start_tls=self.use_starttls,
                )
            logger.info(f"[SMTPChannel] sent to {len(self.to_addrs)} recipient(s)")
        except Exception as e:  # pragma: no cover - 网络异常
            logger.warning(f"[SMTPChannel] send failed: {e}")

    async def wait_for_response(
        self, request_id: str, timeout_s: float
    ):  # pragma: no cover
        raise NotImplementedError


# 显式导出，便于旧 import 路径兼容
__all__ = ["LarkChannel", "DingTalkChannel", "SMTPChannel"]