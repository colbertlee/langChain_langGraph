"""
外部 MCP 服务器管理 —— 可重入 stdio 子进程 + JSON-RPC 客户端

设计要点:
- 每个 external server 一个 asyncio 子进程,通过 stdin/stdout JSON-RPC 通信
- 进程状态 / tools 列表缓存在内存,供 /api/mcp/* 端点直接查询
- 启动失败 / 进程崩溃只更新 last_error,不抛回 UI
- 写 mcp_config.json 用 os.replace + 临时文件,避免半写状态
- 重启即生效,无需重启 FastAPI 主进程

典型用法:
    from mcp_external import external_mcp_manager
    await external_mcp_manager.reload()      # 启动所有 enabled=True 的
    info = external_mcp_manager.list_servers()
    await external_mcp_manager.toggle("minimax", True)
"""
import asyncio
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# MCP 协议版本与初始化握手参数
MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_CLIENT_INFO = {"name": "ai-agent-external-client", "version": "1.0.0"}

# 不同工具的默认超时(秒);长任务如视频生成会更长
TOOL_TIMEOUT_DEFAULTS = {
    "text_to_audio": 30,
    "list_voices": 15,
    "voice_clone": 60,
    "voice_design": 60,
    "play_audio": 15,
    "music_generation": 120,
    "generate_video": 180,
    "image_to_video": 180,
    "query_video_generation": 30,
    "text_to_image": 60,
}


def _project_root() -> str:
    """mcp_external.py 与 mcp_config.json 同级 → 项目根目录"""
    return os.path.dirname(os.path.abspath(__file__))


def _default_config_path() -> str:
    return os.path.join(_project_root(), "mcp_config.json")


def _expand_env(value: str) -> str:
    """把 ${VAR} / $VAR 展开成环境变量值;找不到时返回原串"""
    if not isinstance(value, str):
        return value
    if value.startswith("${") and value.endswith("}"):
        key = value[2:-1]
        return os.environ.get(key, value)
    return os.environ.get(value, value) if value.startswith("$") else value


def _materialize_env(raw_env: Dict[str, str]) -> Dict[str, str]:
    """把 env 字典里的 ${VAR} 解析成真实值,保留未填的原始字面量供诊断"""
    return {k: _expand_env(v) for k, v in (raw_env or {}).items()}


# 哪些 env key 视作"本地输出/数据库路径",启动时自动确保目录存在
_OUTPUT_PATH_KEYS = (
    "MINIMAX_MCP_BASE_PATH",
    "OUTPUT_PATH",
    "BASE_PATH",
    "DATABASE_PATH",
    "DATA_PATH",
)


def _ensure_output_paths(cfg: Dict[str, Any]) -> List[str]:
    """对 env 中已配置且指向本地的路径字段,自动 mkdir -p。

    返回真正创建的目录路径列表(供前端/日志提示)。对 ${X} 未解析的值直接跳过。
    """
    created: List[str] = []
    env_raw = cfg.get("env", {}) or {}
    env_materialized = _materialize_env(env_raw)
    for key, raw_val in env_raw.items():
        if key not in _OUTPUT_PATH_KEYS:
            continue
        val = env_materialized.get(key, "")
        if _env_value_is_missing(val):
            continue
        # 若是 sqlite db 文件,把父目录建出来
        path = val
        if key == "DATABASE_PATH" and not path.endswith(("/", "\\")):
            path = os.path.dirname(path) or "."
        if not path:
            continue
        if not os.path.isabs(path):
            path = os.path.join(_project_root(), path)
        try:
            os.makedirs(path, exist_ok=True)
            created.append(path)
        except Exception as e:  # noqa: BLE001
            logger.warning("[MCP] ensure path %s (%s) failed: %s", key, path, e)
    return created


def _env_value_is_missing(value: str) -> bool:
    """判断一个解析后的 env 值是否缺失(空字符串或仍是 ${X} 字面量)"""
    if not value:
        return True
    return value.startswith("${") and value.endswith("}")


@dataclass
class ExternalProc:
    """单个 external MCP server 的运行时状态"""

    server_id: str
    config: Dict[str, Any]
    proc: Optional[asyncio.subprocess.Process] = None
    initialized: bool = False
    tools: List[Dict[str, Any]] = field(default_factory=list)
    resources: List[Dict[str, Any]] = field(default_factory=list)
    last_error: Optional[str] = None
    started_at: Optional[float] = None
    next_request_id: int = 1
    pending: Dict[int, asyncio.Future] = field(default_factory=dict)
    reader_task: Optional["asyncio.Task[None]"] = None
    stderr_task: Optional["asyncio.Task[None]"] = None


class MCPStdioClient:
    """单个 stdio MCP server 的 JSON-RPC 客户端(轻量实现,不依赖 mcp sdk)"""

    def __init__(self, proc_state: ExternalProc):
        self.p = proc_state

    async def _send(self, obj: Dict[str, Any]) -> None:
        if self.p.proc is None or self.p.proc.stdin is None:
            raise RuntimeError("process not running")
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self.p.proc.stdin.write(data)
            await self.p.proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            raise RuntimeError("stdio broken pipe: {}".format(e)) from e

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None,
                      timeout: float = 30.0) -> Dict[str, Any]:
        """发送请求并等待响应。超时或进程异常 → 抛 RuntimeError"""
        rid = self.p.next_request_id
        self.p.next_request_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self.p.pending[rid] = fut

        payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            payload["params"] = params

        try:
            await self._send(payload)
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as e:
            self.p.pending.pop(rid, None)
            raise RuntimeError("timeout waiting for {}".format(method)) from e
        finally:
            self.p.pending.pop(rid, None)

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        """单向通知(notification),不期望响应"""
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        await self._send(payload)


class ExternalMCPManager:
    """外部 MCP server 全局管理器(单例)"""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or _default_config_path()
        self._procs: Dict[str, ExternalProc] = {}
        self._clients: Dict[str, MCPStdioClient] = {}
        self._lock = asyncio.Lock()

    # ---------------- 公共 API ----------------

    def list_servers(self) -> List[Dict[str, Any]]:
        """列出所有 external server(供前端 UI 使用),env 字段不回 value"""
        config = self._load_config()
        servers_cfg = config.get("external_servers", {}) or {}
        out: List[Dict[str, Any]] = []
        for sid, cfg in servers_cfg.items():
            state = self._procs.get(sid)
            running = bool(state and state.proc and state.proc.returncode is None and state.initialized)
            env_raw = cfg.get("env", {}) or {}
            env_materialized = _materialize_env(env_raw)
            env_keys: List[Dict[str, Any]] = []
            for k in env_raw.keys():
                env_keys.append({
                    "name": k,
                    "configured": not _env_value_is_missing(env_materialized.get(k, "")),
                    "required": k in (cfg.get("required_env", []) or []),
                })
            out.append({
                "id": sid,
                "name": cfg.get("name") or sid,
                "description": cfg.get("description", ""),
                "command": cfg.get("command", "npx"),
                "args": cfg.get("args", []),
                "enabled": bool(cfg.get("enabled", False)),
                "running": running,
                "tools_count": len(state.tools) if (state and running) else 0,
                "env_keys": env_keys,
                "env_defaults": cfg.get("env_defaults", {}) or {},
                "host_region_note": cfg.get("host_region_note", ""),
                "pid": state.proc.pid if (state and state.proc and running) else None,
                "last_error": state.last_error if state else None,
            })
        return out

    def list_tools(self) -> List[Dict[str, Any]]:
        """列出所有 running external server 的 tools,前端 /tools 页用"""
        out: List[Dict[str, Any]] = []
        for sid, state in self._procs.items():
            if not (state.proc and state.proc.returncode is None and state.initialized):
                continue
            for t in state.tools:
                out.append({
                    "server_id": sid,
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "inputSchema": t.get("inputSchema", {}),
                })
        return out

    async def toggle(self, server_id: str, enabled: bool) -> Dict[str, Any]:
        """切换启用状态:写 mcp_config.json + 启停子进程"""
        cfg = self._load_config()
        servers_cfg = cfg.get("external_servers", {}) or {}
        if server_id not in servers_cfg:
            return {"ok": False, "error": "unknown server_id: {}".format(server_id)}

        # 1) 写配置
        servers_cfg[server_id]["enabled"] = bool(enabled)
        cfg["external_servers"] = servers_cfg
        self._save_config(cfg)

        # 2) 启停
        if enabled:
            missing = self._check_required_env(servers_cfg[server_id])
            if missing:
                return {
                    "ok": False,
                    "error": "missing required env",
                    "missing_env": missing,
                }
            try:
                await self._start(server_id)
            except Exception as e:
                logger.exception("toggle start failed: %s", e)
                return {"ok": False, "error": str(e)}
        else:
            await self._stop(server_id)

        return {"ok": True, "enabled": bool(enabled)}

    async def reload(self) -> Dict[str, Any]:
        """重读 mcp_config.json,按 enabled 启停全部 external server"""
        cfg = self._load_config()
        servers_cfg = cfg.get("external_servers", {}) or {}
        # 先确保所有 server 的本地输出目录存在(minimax / sqlite 等)
        ensured: Dict[str, List[str]] = {}
        for sid, scfg in servers_cfg.items():
            try:
                paths = _ensure_output_paths(scfg)
                if paths:
                    ensured[sid] = paths
            except Exception as e:  # noqa: BLE001
                logger.debug("[MCP] ensure paths for %s failed: %s", sid, e)
        results: Dict[str, str] = {}
        # 先停全部
        for sid in list(self._procs.keys()):
            await self._stop(sid)
        # 再按 enabled 启
        for sid, scfg in servers_cfg.items():
            if scfg.get("enabled", False):
                try:
                    await self._start(sid)
                    results[sid] = "started"
                except Exception as e:
                    logger.warning("reload start %s failed: %s", sid, e)
                    results[sid] = "error: {}".format(e)
        return {"ok": True, "results": results, "ensured_paths": ensured}

    async def call_tool(self, server_id: str, tool_name: str,
                        arguments: Dict[str, Any]) -> Dict[str, Any]:
        """供 agent 侧调用某个 external MCP 工具"""
        state = self._procs.get(server_id)
        if not state or not state.proc or state.proc.returncode is not None:
            return {"isError": True, "content": [{"type": "text", "text": "server not running"}]}
        client = self._clients.get(server_id)
        if client is None:
            return {"isError": True, "content": [{"type": "text", "text": "client missing"}]}
        timeout = TOOL_TIMEOUT_DEFAULTS.get(tool_name, 60.0)
        try:
            resp = await client.request(
                "tools/call",
                {"name": tool_name, "arguments": arguments or {}},
                timeout=timeout,
            )
            return resp if isinstance(resp, dict) else {"isError": True, "content": [{"type": "text", "text": "bad response"}]}
        except Exception as e:
            return {"isError": True, "content": [{"type": "text", "text": str(e)}]}

    async def shutdown(self) -> None:
        """FastAPI lifespan 关闭时调用"""
        for sid in list(self._procs.keys()):
            await self._stop(sid)

    # ---------------- 内部实现 ----------------

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            return {"external_servers": {}}
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_config(self, cfg: Dict[str, Any]) -> None:
        """原子写入,避免半写状态"""
        dirpath = os.path.dirname(self.config_path) or "."
        fd, tmp = tempfile.mkstemp(prefix=".mcp_config.", dir=dirpath, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.config_path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def _check_required_env(self, cfg: Dict[str, Any]) -> List[str]:
        env_raw = cfg.get("env", {}) or {}
        required = cfg.get("required_env", []) or []
        env_materialized = _materialize_env(env_raw)
        return [k for k in required if _env_value_is_missing(env_materialized.get(k, ""))]

    async def _start(self, server_id: str) -> None:
        async with self._lock:
            if server_id in self._procs and self._procs[server_id].proc and \
                    self._procs[server_id].proc.returncode is None:
                return  # 已 running

            cfg = self._load_config()
            scfg = (cfg.get("external_servers", {}) or {}).get(server_id)
            if not scfg:
                raise RuntimeError("unknown server_id: {}".format(server_id))

            cmd = scfg.get("command", "npx")
            args = scfg.get("args", []) or []
            env_raw = scfg.get("env", {}) or {}
            env_materialized = _materialize_env(env_raw)

            # 兜底默认值(env_defaults),仅在原值缺失时填
            for k, v in (scfg.get("env_defaults", {}) or {}).items():
                if _env_value_is_missing(env_materialized.get(k, "")):
                    env_materialized[k] = v

            # 启动前确保本地输出/数据库目录存在(MINIMAX_MCP_BASE_PATH 等)
            _ensure_output_paths({"env": env_raw})

            proc_env = os.environ.copy()
            proc_env.update(env_materialized)

            logger.info("[MCP] starting %s: %s %s", server_id, cmd, " ".join(args))
            proc = await asyncio.create_subprocess_exec(
                cmd, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=proc_env,
                cwd=_project_root(),
            )

            state = ExternalProc(server_id=server_id, config=scfg, proc=proc)
            self._procs[server_id] = state
            self._clients[server_id] = MCPStdioClient(state)

            # 起 stdout reader / stderr drain
            state.reader_task = asyncio.create_task(self._reader_loop(server_id))
            state.stderr_task = asyncio.create_task(self._stderr_loop(server_id))

            client = self._clients[server_id]

            # initialize
            try:
                init_resp = await client.request(
                    "initialize",
                    {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": MCP_CLIENT_INFO,
                    },
                    timeout=15.0,
                )
                _ = init_resp  # 不解析 serverInfo,只要不抛异常即视为握手成功
                await client.notify("notifications/initialized", {})
                state.initialized = True
            except Exception as e:
                state.last_error = "initialize failed: {}".format(e)
                await self._kill_proc(state)
                raise RuntimeError(state.last_error)

            # tools/list
            try:
                tools_resp = await client.request("tools/list", {}, timeout=15.0)
                state.tools = list(tools_resp.get("tools", []) or [])
            except Exception as e:
                state.last_error = "tools/list failed: {}".format(e)
                await self._kill_proc(state)
                raise RuntimeError(state.last_error)

            try:
                res_resp = await client.request("resources/list", {}, timeout=10.0)
                state.resources = list(res_resp.get("resources", []) or [])
            except Exception:
                state.resources = []  # resources 是可选

            state.last_error = None
            state.started_at = asyncio.get_running_loop().time()
            logger.info("[MCP] %s started, %d tools", server_id, len(state.tools))

    async def _stop(self, server_id: str) -> None:
        async with self._lock:
            state = self._procs.pop(server_id, None)
            self._clients.pop(server_id, None)
        if state is None:
            return
        if state.reader_task:
            state.reader_task.cancel()
        if state.stderr_task:
            state.stderr_task.cancel()
        await self._kill_proc(state)

    async def _kill_proc(self, state: ExternalProc) -> None:
        proc = state.proc
        if proc is None:
            return
        try:
            if proc.returncode is None:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                except Exception:
                    pass
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        pass
        except Exception as e:
            logger.warning("kill proc %s error: %s", state.server_id, e)

    async def _reader_loop(self, server_id: str) -> None:
        """持续读 stdout,把 JSON-RPC 响应 dispatch 到对应 Future"""
        state = self._procs.get(server_id)
        if state is None or state.proc is None or state.proc.stdout is None:
            return
        try:
            while True:
                line = await state.proc.stdout.readline()
                if not line:
                    break
                try:
                    text = line.decode("utf-8", errors="replace").strip()
                except Exception:
                    continue
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    logger.debug("[MCP:%s] non-json line: %s", server_id, text[:200])
                    continue
                # response
                if isinstance(msg, dict) and "id" in msg:
                    rid = msg.get("id")
                    fut = state.pending.pop(rid, None) if isinstance(rid, int) else None
                    if fut and not fut.done():
                        if "error" in msg:
                            fut.set_exception(RuntimeError(str(msg["error"])))
                        else:
                            fut.set_result(msg.get("result", {}))
                # notification / request from server → 暂忽略
                else:
                    logger.debug("[MCP:%s] unsolicited: %s", server_id, text[:200])
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[MCP:%s] reader error: %s", server_id, e)
        finally:
            # 进程退出 → 把所有 pending future 标异常
            for fut in state.pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("process exited"))
            state.pending.clear()

    async def _stderr_loop(self, server_id: str) -> None:
        state = self._procs.get(server_id)
        if state is None or state.proc is None or state.proc.stderr is None:
            return
        try:
            while True:
                line = await state.proc.stderr.readline()
                if not line:
                    break
                try:
                    text = line.decode("utf-8", errors="replace").rstrip()
                except Exception:
                    continue
                if text:
                    logger.info("[MCP:%s stderr] %s", server_id, text)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("[MCP:%s] stderr loop error: %s", server_id, e)


# 全局单例
external_mcp_manager = ExternalMCPManager()