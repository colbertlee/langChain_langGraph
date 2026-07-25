"""
Distributed Message Bus（分布式 Agent 通信）

设计目标：抽象 bus 接口 + 多种协议适配器
- InProcessTransport   进程内（等同 MessageBus）
- FileTransport        文件（基于 watch directory）
- SocketTransport      TCP socket（JSON 行）
- 抽象 BusTransport 基类（方便扩展 Redis/ZMQ 等）

注意：不强制依赖第三方库；socket 是 stdlib；file 是轮询。
真实生产用 Redis Streams / ZeroMQ / NATS 等。

P3-18
"""

import asyncio
import json
import os
import socket
import time
import uuid
import logging
import threading
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


# ============================================================
# Envelope + Transport
# ============================================================

@dataclass
class Envelope:
    """分布式消息信封（基于 message_protocol.Message）"""
    envelope_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    payload: Dict[str, Any] = field(default_factory=dict)  # 序列化的 Message
    sender_node: str = ""         # 节点 ID
    target_node: Optional[str] = None   # None = 广播
    target_agent: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    ttl: int = 300

    def to_dict(self) -> Dict:
        return {
            "envelope_id": self.envelope_id,
            "payload": self.payload,
            "sender_node": self.sender_node,
            "target_node": self.target_node,
            "target_agent": self.target_agent,
            "timestamp": self.timestamp,
            "ttl": self.ttl,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Envelope":
        return cls(**d)


class TransportType(str, Enum):
    IN_PROCESS = "in_process"
    FILE = "file"
    SOCKET = "socket"


# ============================================================
# BusTransport 抽象基类
# ============================================================

class BusTransport(ABC):
    """
    抽象传输层接口

    实现需提供：
    - send(envelope): 同步发送
    - start_listening(callback): 启动后台接收，callback(envelope) 每次一个信封
    - stop_listening(): 停止后台
    """

    @abstractmethod
    def send(self, envelope: Envelope) -> bool: ...

    @abstractmethod
    def start_listening(self, callback: Callable[[Envelope], None]) -> None: ...

    @abstractmethod
    def stop_listening(self) -> None: ...

    @abstractmethod
    def is_running(self) -> bool: ...

    @property
    @abstractmethod
    def node_id(self) -> str: ...

    @abstractmethod
    def stats(self) -> Dict[str, Any]: ...


# ============================================================
# InProcessTransport
# ============================================================

class InProcessTransport(BusTransport):
    """进程内传输（直接回调，最快）"""

    def __init__(self, node_id: Optional[str] = None):
        self._node_id = node_id or f"node_{uuid.uuid4().hex[:6]}"
        self._callback: Optional[Callable] = None
        self._running = False
        self._sent = 0
        self._received = 0
        self._history: List[Envelope] = []

    @property
    def node_id(self) -> str:
        return self._node_id

    def send(self, envelope: Envelope) -> bool:
        self._sent += 1
        self._history.append(envelope)
        if self._callback:
            self._callback(envelope)
            self._received += 1
        return True

    def start_listening(self, callback: Callable[[Envelope], None]) -> None:
        self._callback = callback
        self._running = True

    def stop_listening(self) -> None:
        self._running = False
        self._callback = None

    def is_running(self) -> bool:
        return self._running

    def stats(self) -> Dict[str, Any]:
        return {
            "type": "in_process",
            "node_id": self._node_id,
            "sent": self._sent,
            "received": self._received,
            "history": len(self._history),
            "running": self._running,
        }


# ============================================================
# FileTransport
# ============================================================

class FileTransport(BusTransport):
    """
    文件传输：把 envelope 写到 watch_dir/*.json
    启动后线程轮询该目录，解析 + 回调。

    适合：跨进程（同一机器不同进程）
    """

    def __init__(
        self,
        watch_dir: str,
        node_id: Optional[str] = None,
        poll_interval: float = 0.1,
    ):
        self._node_id = node_id or f"file_{uuid.uuid4().hex[:6]}"
        self._dir = watch_dir
        self._poll = poll_interval
        self._callback: Optional[Callable] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sent = 0
        self._received = 0
        self._processed: Set[str] = set()  # 已读 envelope_id

        os.makedirs(self._dir, exist_ok=True)

    @property
    def node_id(self) -> str:
        return self._node_id

    def send(self, envelope: Envelope) -> bool:
        # envelope: target_node 设为另一个节点 ID
        # 把 envelope 写到 watch_dir/<envelope_id>.json
        path = os.path.join(self._dir, f"{envelope.envelope_id}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(envelope.to_dict(), f, ensure_ascii=False)
            self._sent += 1
            return True
        except Exception as e:
            logger.error(f"FileTransport send failed: {e}")
            return False

    def _loop(self):
        while self._running:
            try:
                for fname in os.listdir(self._dir):
                    if not fname.endswith(".json"):
                        continue
                    path = os.path.join(self._dir, fname)
                    env_id = fname[:-5]
                    if env_id in self._processed:
                        continue
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        env = Envelope.from_dict(data)
                        if env.sender_node == self._node_id:
                            # 自己发的，跳过
                            self._processed.add(env_id)
                            continue
                        if self._callback:
                            self._callback(env)
                            self._received += 1
                        self._processed.add(env_id)
                    except Exception as e:
                        logger.warning(f"FileTransport read {fname} failed: {e}")
                time.sleep(self._poll)
            except Exception as e:
                logger.warning(f"FileTransport loop error: {e}")
                time.sleep(self._poll)

    def start_listening(self, callback: Callable[[Envelope], None]) -> None:
        self._callback = callback
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop_listening(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=self._poll * 2)
        self._thread = None
        self._callback = None

    def is_running(self) -> bool:
        return self._running

    def stats(self) -> Dict[str, Any]:
        return {
            "type": "file",
            "node_id": self._node_id,
            "dir": self._dir,
            "sent": self._sent,
            "received": self._received,
            "running": self._running,
        }


# ============================================================
# SocketTransport
# ============================================================

class SocketTransport(BusTransport):
    """
    TCP socket 传输：JSON 行。

    角色：server / client
    - server 模式：监听端口，接入的每个连接是一对端
    - client 模式：连接 server（host:port）

    注意：仅为基础实现；生产用 gRPC / ZeroMQ
    """

    def __init__(
        self,
        mode: str = "server",   # "server" or "client"
        host: str = "127.0.0.1",
        port: int = 0,          # 0 = 自动选
        node_id: Optional[str] = None,
    ):
        self._mode = mode
        self._host = host
        self._port = port
        self._node_id = node_id or f"socket_{uuid.uuid4().hex[:6]}"
        self._callback: Optional[Callable] = None
        self._running = False
        self._server_sock: Optional[socket.socket] = None
        self._client_sock: Optional[socket.socket] = None
        self._clients: List[socket.socket] = []
        self._reader_thread: Optional[threading.Thread] = None
        self._sent = 0
        self._received = 0
        self._lock = threading.Lock()

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def actual_port(self) -> int:
        if self._server_sock:
            return self._server_sock.getsockname()[1]
        if self._client_sock:
            return self._client_sock.getsockname()[1]
        return self._port

    def send(self, envelope: Envelope) -> bool:
        data = (json.dumps(envelope.to_dict()) + "\n").encode("utf-8")
        with self._lock:
            try:
                if self._mode == "server":
                    for c in list(self._clients):
                        try:
                            c.sendall(data)
                        except Exception:
                            self._clients.remove(c)
                else:
                    if self._client_sock:
                        self._client_sock.sendall(data)
                self._sent += 1
                return True
            except Exception as e:
                logger.error(f"SocketTransport send failed: {e}")
                return False

    def _loop_server(self):
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self._host, self._port))
        self._server_sock.listen(5)
        self._server_sock.settimeout(0.5)
        logger.info(f"SocketTransport server listening on {self._host}:{self.actual_port}")

        while self._running:
            try:
                conn, addr = self._server_sock.accept()
                self._clients.append(conn)
                # 启动一个 reader 线程
                threading.Thread(
                    target=self._read_loop,
                    args=(conn,),
                    daemon=True,
                ).start()
            except socket.timeout:
                continue
            except Exception as e:
                if not self._running:
                    break
                logger.warning(f"SocketTransport accept error: {e}")

    def _read_loop(self, conn: socket.socket):
        buf = b""
        conn.settimeout(0.5)
        while self._running:
            try:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line.decode("utf-8"))
                        env = Envelope.from_dict(data)
                        if env.sender_node == self._node_id:
                            continue
                        if self._callback:
                            self._callback(env)
                            self._received += 1
                    except Exception as e:
                        logger.warning(f"SocketTransport parse error: {e}")
            except socket.timeout:
                continue
            except Exception as e:
                logger.warning(f"SocketTransport read error: {e}")
                break

    def _loop_client(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        try:
            sock.connect((self._host, self._port))
            self._client_sock = sock
            logger.info(f"SocketTransport client connected to {self._host}:{self._port}")
            threading.Thread(
                target=self._read_loop,
                args=(sock,),
                daemon=True,
            ).start()
        except Exception as e:
            logger.error(f"SocketTransport connect failed: {e}")

    def start_listening(self, callback: Callable[[Envelope], None]) -> None:
        self._callback = callback
        self._running = True
        if self._mode == "server":
            self._reader_thread = threading.Thread(target=self._loop_server, daemon=True)
        else:
            self._reader_thread = threading.Thread(target=self._loop_client, daemon=True)
        self._reader_thread.start()

    def stop_listening(self) -> None:
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
        if self._client_sock:
            try:
                self._client_sock.close()
            except Exception:
                pass
        with self._lock:
            for c in list(self._clients):
                try:
                    c.close()
                except Exception:
                    pass
            self._clients.clear()
        self._callback = None

    def is_running(self) -> bool:
        return self._running

    def stats(self) -> Dict[str, Any]:
        return {
            "type": "socket",
            "mode": self._mode,
            "node_id": self._node_id,
            "host": self._host,
            "port": self.actual_port,
            "sent": self._sent,
            "received": self._received,
            "running": self._running,
            "connected_clients": len(self._clients),
        }


# ============================================================
# DistributedMessageBus（顶层门面）
# ============================================================

class DistributedMessageBus:
    """
    分布式消息总线（门面）。

    包装一个 transport，提供：
    - send_message(message_dict, target_node=None)  高层接口
    - on_message(callback)
    - start() / stop()

    将来可以与现有 MessageBus.send 协同：outgoing 路由到 transport；
    incoming 路由回 MessageBus.send（target_agent 路由）。
    """

    def __init__(self, transport: BusTransport, node_id: Optional[str] = None):
        self._transport = transport
        self._callbacks: List[Callable[[Envelope], None]] = []
        self._running = False

    @property
    def node_id(self) -> str:
        return self._transport.node_id

    @property
    def transport(self) -> BusTransport:
        return self._transport

    def send(
        self,
        payload: Dict[str, Any],
        target_node: Optional[str] = None,
        target_agent: Optional[str] = None,
    ) -> bool:
        """发送一个信封"""
        env = Envelope(
            payload=payload,
            sender_node=self.node_id,
            target_node=target_node,
            target_agent=target_agent,
        )
        return self._transport.send(env)

    def on_message(self, callback: Callable[[Envelope], None]) -> None:
        self._callbacks.append(callback)

    def start(self) -> None:
        if self._running:
            return
        def _dispatch(env: Envelope):
            for cb in self._callbacks:
                try:
                    cb(env)
                except Exception as e:
                    logger.warning(f"on_message callback error: {e}")
        self._transport.start_listening(_dispatch)
        self._running = True

    def stop(self) -> None:
        if not self._running:
            return
        self._transport.stop_listening()
        self._running = False

    def stats(self) -> Dict[str, Any]:
        t = self._transport.stats()
        t["dispatcher_running"] = self._running
        t["callback_count"] = len(self._callbacks)
        return t


# ============================================================
# 全局工厂
# ============================================================

_distributed_buses: Dict[str, DistributedMessageBus] = {}


def create_distributed_bus(
    name: str,
    transport_type: TransportType = TransportType.IN_PROCESS,
    **kwargs,
) -> DistributedMessageBus:
    """创建并命名一个分布式 bus"""
    if transport_type == TransportType.IN_PROCESS:
        t = InProcessTransport(node_id=kwargs.get("node_id", f"{name}_node"))
    elif transport_type == TransportType.FILE:
        t = FileTransport(
            watch_dir=kwargs.get("watch_dir", f"./dist_bus_{name}"),
            node_id=kwargs.get("node_id", f"{name}_node"),
            poll_interval=kwargs.get("poll_interval", 0.1),
        )
    elif transport_type == TransportType.SOCKET:
        t = SocketTransport(
            mode=kwargs.get("mode", "server"),
            host=kwargs.get("host", "127.0.0.1"),
            port=kwargs.get("port", 0),
            node_id=kwargs.get("node_id", f"{name}_node"),
        )
    else:
        raise ValueError(f"unknown transport: {transport_type}")
    bus = DistributedMessageBus(t, node_id=t.node_id)
    _distributed_buses[name] = bus
    return bus


def get_distributed_bus(name: str) -> Optional[DistributedMessageBus]:
    return _distributed_buses.get(name)


def remove_distributed_bus(name: str) -> None:
    bus = _distributed_buses.pop(name, None)
    if bus:
        bus.stop()