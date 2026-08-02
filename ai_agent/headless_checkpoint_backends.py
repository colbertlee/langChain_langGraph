"""
headless_checkpoint_backends.py — 分布式 Checkpoint 后端

目标
----
把 ``headless_persistence.EventCheckpoint`` 的写入能力扩展到分布式存储，
支持：

- LocalFileBackend — 本地 JSONL（已有，搬过来保持接口一致）
- RedisBackend     — Redis List（每条事件 LPUSH + LRANGE 读取）
- S3Backend        — S3 对象（每行作 put_object；读取按行 list+get）

依赖
----
- Redis / S3 后端**懒依赖**：缺失时仅 RuntimeError，调用方可降级到 LocalFile。
- 同步 boto3 通过 ``asyncio.to_thread`` 异步化。

设计
----
``CheckpointBackend`` 是统一协议：``append()`` + ``read_all()``。
``EventCheckpoint`` 维持原 API（``__init__(path)`` + ``append(ev)`` + ``close()``），
构造时根据 path 形式或显式 backend 参数选择 backend：

::

    EventCheckpoint("local.jsonl")            # 自动选 LocalFile
    EventCheckpoint("redis://host:6379/key")  # 自动选 Redis
    EventCheckpoint("s3://bucket/key")        # 自动选 S3
    EventCheckpoint(backend=MyBackend())      # 显式注入
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, List, Optional, Protocol, Union

from headless_events import HeadlessEvent, HeadlessEventType

logger = logging.getLogger(__name__)


# ============================================================
# 序列化辅助（与 headless_persistence 保持一致）
# ============================================================

def _event_to_dict(ev: HeadlessEvent) -> dict:
    return {"type": ev.type.value, "data": ev.data, "timestamp": ev.timestamp}


def _dict_to_event(d: dict) -> HeadlessEvent:
    return HeadlessEvent(
        type=HeadlessEventType(d["type"]),
        data=d.get("data", {}) or {},
        timestamp=float(d.get("timestamp", time.time())),
    )


# ============================================================
# Backend 协议
# ============================================================

class CheckpointBackend(Protocol):
    """统一的 Checkpoint 后端协议。"""

    async def append(self, ev: HeadlessEvent) -> None:
        ...

    async def read_all(self) -> List[HeadlessEvent]:
        ...

    async def close(self) -> None:
        ...


# ============================================================
# LocalFileBackend
# ============================================================

class LocalFileBackend:
    """本地 JSONL 文件 backend。"""

    def __init__(self, path: Union[str, Path]) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._path, "a", encoding="utf-8")
        self._buf = 0
        self._flush_every = 1
        self._closed = False

    async def append(self, ev: HeadlessEvent) -> None:
        if self._closed:
            raise RuntimeError("LocalFileBackend 已关闭")
        line = json.dumps(_event_to_dict(ev), ensure_ascii=False, default=str)
        await asyncio.to_thread(self._write_line, line + "\n")

    def _write_line(self, line: str) -> None:
        self._fh.write(line)
        self._buf += 1
        if self._buf >= self._flush_every:
            self._fh.flush()
            self._buf = 0

    async def read_all(self) -> List[HeadlessEvent]:
        if not self._path.exists():
            return []
        out: list[HeadlessEvent] = []

        def _read() -> list[HeadlessEvent]:
            lines = self._path.read_text(encoding="utf-8").splitlines()
            events: list[HeadlessEvent] = []
            for ln in lines:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    events.append(_dict_to_event(json.loads(ln)))
                except json.JSONDecodeError:
                    logger.warning(f"[LocalFileBackend] skip bad JSON: {ln[:80]}")
            return events

        return await asyncio.to_thread(_read)

    async def close(self) -> None:
        if self._closed:
            return
        await asyncio.to_thread(self._sync_close)
        self._closed = True

    def _sync_close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception as e:  # pragma: no cover
            logger.warning(f"[LocalFileBackend] close error: {e}")


# ============================================================
# RedisBackend
# ============================================================

_REDIS_URL_RE = re.compile(r"^redis://([^/]+)(?:/(\d+))?(?:/(.+))?$")


@dataclass
class _RedisConfig:
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    key: str = "headless:events"


def _parse_redis_url(url: str) -> _RedisConfig:
    """支持 ``redis://host:port[/db[/key]]`` 形式（key 可含 ``:`` 与 ``/``）。

    URL 结构：``redis://host[:port][/db][/key]``
    - host 形如 ``host`` 或 ``host:port``；
    - db 必须为整数（不传 = 0）；
    - key 允许任意字符（``+``、``:``、``/`` 等都会被原样保留）。
    """
    m = _REDIS_URL_RE.match(url)
    if not m:
        raise ValueError(f"invalid redis url: {url!r}")
    host_port = m.group(1)
    db_s = m.group(2)
    key = m.group(3)
    host, _, port_s = host_port.partition(":")
    port = int(port_s) if port_s else 6379
    db = int(db_s) if db_s else 0
    if key is None:
        key = "headless:events"
    return _RedisConfig(host=host, port=port, db=db, key=key)


class RedisBackend:
    """Redis List backend（每事件 LPUSH；读取用 LRANGE 0 -1）。

    选 List 而非 Stream：API 更简单、懒依赖更轻；如需消费组/ack 后续可换 Stream。
    """

    def __init__(
        self,
        url_or_cfg: Union[str, _RedisConfig],
        *,
        max_len: int = 100000,
    ) -> None:
        if isinstance(url_or_cfg, str):
            self._cfg = _parse_redis_url(url_or_cfg)
        else:
            self._cfg = url_or_cfg
        self._max_len = int(max_len)
        self._client: Any = None

    async def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import redis.asyncio as aioredis  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "RedisBackend requires redis>=4.2 with asyncio support; "
                "install with `pip install redis`"
            ) from e
        self._client = aioredis.Redis(
            host=self._cfg.host,
            port=self._cfg.port,
            db=self._cfg.db,
            decode_responses=True,
        )
        return self._client

    async def append(self, ev: HeadlessEvent) -> None:
        client = await self._ensure_client()
        line = json.dumps(_event_to_dict(ev), ensure_ascii=False, default=str)
        # LPUSH + LTRIM 控制最大长度
        await client.lpush(self._cfg.key, line)
        if self._max_len > 0:
            await client.ltrim(self._cfg.key, 0, self._max_len - 1)

    async def read_all(self) -> List[HeadlessEvent]:
        client = await self._ensure_client()
        # LRANGE 0 -1 → 全部；LRANGE 是从老到新，但 LPUSH 是从新到老的逆序
        raw_list = await client.lrange(self._cfg.key, 0, -1)
        # 反转：从老到新
        raw_list.reverse()
        out: list[HeadlessEvent] = []
        for ln in raw_list:
            try:
                out.append(_dict_to_event(json.loads(ln)))
            except (json.JSONDecodeError, KeyError, ValueError):
                logger.warning(f"[RedisBackend] skip bad entry: {ln[:80]}")
        return out

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # pragma: no cover
                pass
            self._client = None


# ============================================================
# S3Backend
# ============================================================

_S3_URL_RE = re.compile(r"^s3://([^/]+)/(.+)$")


@dataclass
class _S3Config:
    bucket: str = ""
    key_prefix: str = "headless/events"


def _parse_s3_url(url: str) -> _S3Config:
    m = _S3_URL_RE.match(url)
    if not m:
        raise ValueError(f"invalid s3 url: {url!r}")
    return _S3Config(bucket=m.group(1), key_prefix=m.group(2).rstrip("/"))


class S3Backend:
    """S3 对象 backend：每个事件 put_object；读取 list_objects_v2。

    设计：
    - 事件 ID 用 UUID + ts；key 形如 ``<prefix>/<ts>_<uuid>.json``；
    - 读取按 key 字典序还原顺序（ts 升序）；
    - 大量小对象成本高，但简单可靠；生产可换 compacted batch object。
    """

    def __init__(
        self,
        url_or_cfg: Union[str, _S3Config],
        *,
        region: str = "",
        endpoint_url: str = "",
    ) -> None:
        if isinstance(url_or_cfg, str):
            self._cfg = _parse_s3_url(url_or_cfg)
        else:
            self._cfg = url_or_cfg
        self._region = region or None
        self._endpoint_url = endpoint_url or None
        self._client: Any = None

    def _ensure_client_sync(self) -> Any:
        """boto3 client 是同步的；包到 to_thread 里。"""
        if self._client is not None:
            return self._client
        try:
            import boto3  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "S3Backend requires boto3; "
                "install with `pip install boto3`"
            ) from e
        self._client = boto3.client(
            "s3",
            region_name=self._region,
            endpoint_url=self._endpoint_url,
        )
        return self._client

    async def _ensure_client(self) -> Any:
        # boto3 client 创建是同步的，放到线程池
        return await asyncio.to_thread(self._ensure_client_sync)

    @staticmethod
    def _make_key(prefix: str) -> str:
        ts_ms = int(time.time() * 1000)
        import uuid as _uuid
        return f"{prefix}/{ts_ms}_{_uuid.uuid4().hex}.json"

    async def append(self, ev: HeadlessEvent) -> None:
        client = await self._ensure_client()
        body = json.dumps(_event_to_dict(ev), ensure_ascii=False, default=str)
        key = self._make_key(self._cfg.key_prefix)

        def _put() -> None:
            client.put_object(
                Bucket=self._cfg.bucket,
                Key=key,
                Body=body.encode("utf-8"),
                ContentType="application/json",
            )

        await asyncio.to_thread(_put)

    async def read_all(self) -> List[HeadlessEvent]:
        client = await self._ensure_client()

        def _list_and_fetch() -> List[HeadlessEvent]:
            paginator = client.get_paginator("list_objects_v2")
            keys: list[str] = []
            for page in paginator.paginate(
                Bucket=self._cfg.bucket, Prefix=self._cfg.key_prefix + "/"
            ):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])
            keys.sort()  # ts 升序

            events: list[HeadlessEvent] = []
            for k in keys:
                try:
                    obj = client.get_object(Bucket=self._cfg.bucket, Key=k)
                    data = obj["Body"].read().decode("utf-8")
                    events.append(_dict_to_event(json.loads(data)))
                except Exception as e:  # pragma: no cover
                    logger.warning(f"[S3Backend] failed to read {k}: {e}")
            return events

        return await asyncio.to_thread(_list_and_fetch)

    async def close(self) -> None:
        # boto3 client 不需要显式关闭；GC 即可
        self._client = None


# ============================================================
# 工厂：根据 URL 自动选 backend
# ============================================================

def backend_from_url(
    url: str,
    *,
    region: str = "",
    endpoint_url: str = "",
) -> CheckpointBackend:
    """根据 URL 形式选择 backend。"""
    if url.startswith("redis://"):
        return RedisBackend(url)
    if url.startswith("s3://"):
        return S3Backend(url, region=region, endpoint_url=endpoint_url)
    # 默认本地文件
    return LocalFileBackend(url)


__all__ = [
    "CheckpointBackend",
    "LocalFileBackend",
    "RedisBackend",
    "S3Backend",
    "backend_from_url",
]