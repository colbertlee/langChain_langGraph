"""remote_hitl_signed.py 单测：飞书/钉钉签名 + 邮件模板（不真正发网络请求）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlparse

import pytest

from headless_agent import PermissionRequest


# ============================================================
# LarkChannel 签名
# ============================================================

def test_lark_sign_url_contains_timestamp_and_sign() -> None:
    from remote_hitl_signed import LarkChannel

    ch = LarkChannel(
        webhook_url="https://open.feishu.cn/hook/abc",
        secret="test_secret",
    )
    signed = ch._sign_url()
    parsed = urlparse(signed)
    qs = parse_qs(parsed.query)
    assert "timestamp" in qs
    assert "sign" in qs
    # 签名合法性自检
    ts = qs["timestamp"][0]
    expected = base64.b64encode(
        hmac.new(
            b"test_secret",
            f"{ts}\ntest_secret".encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")
    assert qs["sign"][0] == expected


def test_lark_payload_contains_tool_and_callback_urls() -> None:
    from remote_hitl_signed import LarkChannel

    ch = LarkChannel(webhook_url="https://x", secret="")
    payload = ch._build_payload("req-1", PermissionRequest(tool="web_search", args={"q": "x"}))
    assert payload["msg_type"] == "post"
    body = json.dumps(payload["content"], ensure_ascii=False)
    assert "web_search" in body
    assert "req-1" in body or "approved=true" in body


def test_lark_requires_url() -> None:
    from remote_hitl_signed import LarkChannel

    with pytest.raises(ValueError):
        LarkChannel(webhook_url="")


# ============================================================
# DingTalkChannel 签名
# ============================================================

def test_dingtalk_sign_url_contains_timestamp_and_sign() -> None:
    from remote_hitl_signed import DingTalkChannel

    ch = DingTalkChannel(
        webhook_url="https://oapi.dingtalk.com/robot/send?access_token=t",
        secret="dt_secret",
    )
    signed = ch._sign_url()
    assert "timestamp=" in signed
    assert "sign=" in signed
    # 校验 timestamp 在 ms（13 位）
    qs = parse_qs(urlparse(signed).query)
    ts = qs["timestamp"][0]
    assert len(ts) >= 13


def test_dingtalk_payload_uses_actioncard() -> None:
    from remote_hitl_signed import DingTalkChannel

    ch = DingTalkChannel(webhook_url="https://x", secret="")
    payload = ch._build_payload("req-2", PermissionRequest(tool="shell", args={}))
    assert payload["msgtype"] == "actionCard"
    assert "btns" in payload["actionCard"]
    assert len(payload["actionCard"]["btns"]) == 2


# ============================================================
# SMTPChannel（不真发邮件，仅校验模板 + 构造）
# ============================================================

def test_smtp_build_message_includes_approve_and_deny_links() -> None:
    from remote_hitl_signed import SMTPChannel

    ch = SMTPChannel(
        host="smtp.example.com",
        port=587,
        username="bot@example.com",
        password="x",
        to_addrs=["admin@example.com"],
    )
    msg = ch._build_message("req-3", PermissionRequest(tool="shell", args={"cmd": "ls"}))
    assert "Subject: [HITL]" in msg
    assert "tool: shell" in msg or "工具: shell" in msg or "shell" in msg
    assert "approved=true" in msg
    assert "approved=false" in msg
    assert "req-3" in msg


def test_smtp_requires_host_and_recipients() -> None:
    from remote_hitl_signed import SMTPChannel

    with pytest.raises(ValueError):
        SMTPChannel(host="", port=25, username="x", password="x", to_addrs=["a@b"])
    with pytest.raises(ValueError):
        SMTPChannel(host="h", port=25, username="x", password="x", to_addrs=[])


# ============================================================
# 懒依赖：缺 aiohttp / aiosmtplib 时应抛 RuntimeError
# ============================================================

def test_lark_submit_without_aiohttp(monkeypatch: pytest.MonkeyPatch) -> None:
    """假装 aiohttp 没装 → submit 应抛 RuntimeError。"""
    import builtins

    real_import = builtins.__import__

    def _failing_import(name, *a, **kw):
        if name == "aiohttp":
            raise ImportError("simulated missing aiohttp")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _failing_import)
    from remote_hitl_signed import LarkChannel

    ch = LarkChannel(webhook_url="https://x", secret="s")
    import asyncio
    with pytest.raises(RuntimeError, match="aiohttp"):
        asyncio.run(ch.submit("rid", PermissionRequest(tool="t", args={})))