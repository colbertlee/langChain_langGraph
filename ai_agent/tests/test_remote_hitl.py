"""Remote HITL 单测。"""
from __future__ import annotations

import asyncio

import pytest

from headless_agent import PermissionRequest
from remote_hitl import (
    RemoteHITLAdapter,
    WebhookChannel,
)


class _FakeChannel:
    """模拟远程通道：缓存 submit 出去的请求，不实际发。"""

    def __init__(self) -> None:
        self.submitted: list[tuple[str, PermissionRequest]] = []
        self.wait_calls = 0

    async def submit(self, request_id: str, request: PermissionRequest) -> None:
        self.submitted.append((request_id, request))

    async def wait_for_response(self, request_id: str, timeout_s: float):
        self.wait_calls += 1
        raise NotImplementedError  # 真实流程走 resolve()


@pytest.mark.asyncio
async def test_remote_adapter_approve_path() -> None:
    """用户在远程点"放行" → decide 返回 approved。"""
    ch = _FakeChannel()
    adapter = RemoteHITLAdapter(ch, timeout_s=2.0)

    async def _consumer():
        return await adapter.decide(PermissionRequest(tool="minimax_text_to_image", args={}))

    task = asyncio.create_task(_consumer())
    # 等 submit 完成
    for _ in range(50):
        if ch.submitted:
            break
        await asyncio.sleep(0.02)
    assert len(ch.submitted) == 1
    req_id = ch.submitted[0][0]

    # 模拟远程用户回复
    await adapter.resolve(req_id, approved=True, reason="OK by admin")
    resp = await task
    assert resp.approved is True
    assert resp.rule == "user_approved"
    assert resp.reason == "OK by admin"
    assert adapter.pending_count() == 0


@pytest.mark.asyncio
async def test_remote_adapter_deny_path() -> None:
    ch = _FakeChannel()
    adapter = RemoteHITLAdapter(ch, timeout_s=2.0)

    async def _consumer():
        return await adapter.decide(PermissionRequest(tool="web_search", args={"q": "x"}))

    task = asyncio.create_task(_consumer())
    for _ in range(50):
        if ch.submitted:
            break
        await asyncio.sleep(0.02)
    req_id = ch.submitted[0][0]
    await adapter.resolve(req_id, approved=False, reason="nope")
    resp = await task
    assert resp.approved is False
    assert resp.rule == "user_denied"


@pytest.mark.asyncio
async def test_remote_adapter_timeout() -> None:
    """没人回复 → 超时 → deny + rule=timeout。"""
    ch = _FakeChannel()
    adapter = RemoteHITLAdapter(ch, timeout_s=0.2)

    t0 = asyncio.get_event_loop().time()
    resp = await adapter.decide(PermissionRequest(tool="shell", args={}))
    elapsed = asyncio.get_event_loop().time() - t0
    assert resp.approved is False
    assert resp.rule == "timeout"
    assert elapsed >= 0.18


def test_resolve_unknown_request_id_warns(caplog) -> None:
    ch = _FakeChannel()
    adapter = RemoteHITLAdapter(ch, timeout_s=1.0)
    # 同步测试：resolve 未知 id 返回 False
    import asyncio
    ok = asyncio.run(adapter.resolve("unknown-id", approved=True))
    assert ok is False


def test_pending_count_and_listing() -> None:
    ch = _FakeChannel()
    adapter = RemoteHITLAdapter(ch, timeout_s=1.0)
    assert adapter.pending_count() == 0
    assert adapter.list_pending() == []


def test_webhook_channel_dry_run_without_aiohttp() -> None:
    """未装 aiohttp 时，submit 走 dry-run，不抛错。"""
    ch = WebhookChannel(url="https://example.com/hitl")
    import asyncio
    # 即便没有 aiohttp，也不应抛
    asyncio.run(ch.submit("rid", PermissionRequest(tool="t", args={})))