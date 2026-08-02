"""headless_checkpoint_backends.py 单测：URL 解析 + LocalFile 端到端 + 协议一致性。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, List

import pytest

from headless_events import HeadlessEvent, HeadlessEventType


def _ev(type_: str, data: dict) -> HeadlessEvent:
    return HeadlessEvent(type=HeadlessEventType(type_), data=data, timestamp=1.0)


# ============================================================
# URL 解析
# ============================================================

def test_redis_url_parsing() -> None:
    from headless_checkpoint_backends import _parse_redis_url

    cfg = _parse_redis_url("redis://myhost:6380/2/my:key")
    assert cfg.host == "myhost"
    assert cfg.port == 6380
    assert cfg.db == 2
    assert cfg.key == "my:key"

    cfg2 = _parse_redis_url("redis://localhost")
    assert cfg2.host == "localhost"
    assert cfg2.port == 6379
    assert cfg2.db == 0
    assert cfg2.key == "headless:events"


def test_s3_url_parsing() -> None:
    from headless_checkpoint_backends import _parse_s3_url

    cfg = _parse_s3_url("s3://my-bucket/some/prefix")
    assert cfg.bucket == "my-bucket"
    assert cfg.key_prefix == "some/prefix"


def test_invalid_url() -> None:
    from headless_checkpoint_backends import _parse_redis_url, _parse_s3_url

    with pytest.raises(ValueError):
        _parse_redis_url("http://localhost")
    with pytest.raises(ValueError):
        _parse_s3_url("redis://localhost")


def test_backend_factory_dispatch() -> None:
    from headless_checkpoint_backends import (
        LocalFileBackend,
        RedisBackend,
        S3Backend,
        backend_from_url,
    )

    assert isinstance(backend_from_url("local.jsonl"), LocalFileBackend)
    assert isinstance(backend_from_url("redis://localhost:6379/0/k"), RedisBackend)
    assert isinstance(backend_from_url("s3://b/k"), S3Backend)


# ============================================================
# LocalFileBackend 端到端
# ============================================================

@pytest.mark.asyncio
async def test_local_file_backend_append_and_read(tmp_path: Path) -> None:
    from headless_checkpoint_backends import LocalFileBackend

    path = tmp_path / "x.jsonl"
    be = LocalFileBackend(path)
    try:
        await be.append(_ev("token", {"delta": "A"}))
        await be.append(_ev("token", {"delta": "B"}))
        await be.append(_ev("done", {"final_text": "AB"}))
    finally:
        await be.close()

    # 重新读
    be2 = LocalFileBackend(path)
    try:
        events = await be2.read_all()
    finally:
        await be2.close()

    assert len(events) == 3
    assert events[0].type == HeadlessEventType.TOKEN
    assert events[-1].type == HeadlessEventType.DONE


@pytest.mark.asyncio
async def test_local_file_backend_handles_bad_lines(tmp_path: Path) -> None:
    """读时跳过非法 JSON 行。"""
    from headless_checkpoint_backends import LocalFileBackend

    path = tmp_path / "mixed.jsonl"
    path.write_text(
        json.dumps({"type": "token", "data": {"delta": "ok"}, "timestamp": 1.0}) + "\n"
        + "this is not json\n"
        + json.dumps({"type": "done", "data": {"final_text": "ok"}, "timestamp": 2.0}) + "\n",
        encoding="utf-8",
    )
    be = LocalFileBackend(path)
    try:
        events = await be.read_all()
    finally:
        await be.close()
    assert len(events) == 2


# ============================================================
# Redis / S3 懒依赖
# ============================================================

def test_redis_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    """无 redis 包时，ensure_client 应抛 RuntimeError。"""
    import builtins

    real_import = builtins.__import__

    def _failing(name, *a, **kw):
        if name.startswith("redis"):
            raise ImportError("simulated missing redis")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _failing)
    from headless_checkpoint_backends import RedisBackend

    be = RedisBackend("redis://localhost:6379/0/k")
    import asyncio
    with pytest.raises(RuntimeError, match="redis"):
        asyncio.run(be.append(_ev("token", {"delta": "x"})))


def test_s3_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _failing(name, *a, **kw):
        if name == "boto3":
            raise ImportError("simulated missing boto3")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _failing)
    from headless_checkpoint_backends import S3Backend

    be = S3Backend("s3://b/k")
    import asyncio
    with pytest.raises(RuntimeError, match="boto3"):
        asyncio.run(be.append(_ev("token", {"delta": "x"})))