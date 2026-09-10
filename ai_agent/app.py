"""
统一 Web 后端入口（app.py）

合并 `api.py`（基础聊天 + 上下文管理）和 `web_ui.py`（多 Agent / HITL / 记忆 / 计划 / 观测）
以便前端 `web/index.html` 中调用的全部 38 个端点都可用。

启动方式：
    cd ai_agent
    python app.py            # 默认 0.0.0.0:8000
    PORT=9000 python app.py  # 自定义端口
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    Body,
    FastAPI,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logger = logging.getLogger("app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


# ============================================================
# 路径与目录
# ============================================================
_HERE = Path(__file__).resolve().parent
_UPLOAD_ROOT = _HERE / "uploads"
_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

_UPLOAD_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
_ALLOWED_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp",
    "application/pdf", "text/plain", "text/csv", "text/markdown",
    "application/json", "application/octet-stream",
}


# ============================================================
# 占位符 API Key 检测（可选优化）
# 默认开启：检测到占位符 key 时跳过 LLM 初始化，避免 30s+ 超时。
# 设置环境变量 AI_AGENT_DISABLE_PLACEHOLDER_CHECK=1 可禁用此优化。
# ============================================================
_PLACEHOLDER_MARKERS = (
    "your-", "your_", "xxxx", "placeholder", "<", ">",
    "sk-xxx", "sk-your", "sk-test", "sk-fake", "fake-key", "fake_key",
)


def _is_placeholder_key(api_key: str) -> bool:
    if not api_key:
        return True
    low = api_key.lower()
    return any(m in low for m in _PLACEHOLDER_MARKERS)


# ============================================================
# Agent 适配层
# ============================================================
# AIAgent 类中并未继承 MultiAgentMixin，因此缺少前端调用的若干方法
# (list_workers / get_load_stats / remember / recall / create_plan / 等)。
# 这里我们构造一个轻量代理对象，把缺失的方法路由到底层模块，
# 避免改动 agent.py 主体逻辑。
# ============================================================


class AgentProxy:
    """对 AIAgent 进行薄包装，补齐前端所需的全部方法。"""

    def __init__(self, agent):
        self._agent = agent
        # 复用底层组件
        from permission import get_permission_guard
        from human_in_loop import get_hitl_guard
        from observability import get_observability
        from planner import get_planner
        from memory_store import get_memory_store
        from monitor import get_monitor
        from task_intent import get_task_intent_registry
        try:
            from capability import get_capability_registry
            self._capability_registry = get_capability_registry()
            # 首次拿到 registry 时立即 seed demo workers（确保 list_workers 有数据）
            if not self._capability_registry.list_all():
                _seed_demo_workers_into(self._capability_registry)
        except Exception:
            self._capability_registry = None

        self._permission_guard = get_permission_guard()
        self._hitl_guard = get_hitl_guard()
        self._observability = get_observability()
        self._planner = get_planner()
        self._memory_store = get_memory_store()
        self._monitor = get_monitor()
        self._task_intent_registry = get_task_intent_registry()

    # ----------------- 基础代理 -----------------
    def run(self, user_input: str, session_id: Optional[str] = None) -> str:
        return self._agent.run(user_input, session_id=session_id)

    def clear_history(self) -> str:
        return self._agent.clear_history()

    def get_tools_list(self):
        return self._agent.get_tools_list()

    def set_api_key(self, api_key: str, provider: Optional[str] = None) -> bool:
        return self._agent.set_api_key(api_key, provider)

    def get_api_key_status(self) -> Dict[str, Any]:
        return self._agent.get_api_key_status()

    def set_model(self, provider: str, model_name: Optional[str] = None) -> bool:
        return self._agent.set_model(provider, model_name)

    def get_available_models(self):
        return self._agent.get_available_models()

    def bind_tools_for_session(self, tool_names: List[str]) -> List[str]:
        """v2.1 — 透传到底层 agent.bind_tools_for_session。"""
        inner = getattr(self, "_agent", None)
        if inner is not None and hasattr(inner, "bind_tools_for_session"):
            try:
                return inner.bind_tools_for_session(tool_names)
            except Exception as e:
                logger.debug(f"AgentProxy.bind_tools_for_session failed: {e}")
        return list(tool_names or [])

    def run_stream(self, user_input: str, session_id: Optional[str] = None):
        """同步收集流式 chunk，返回 dict 列表（与前端 SSE 协议兼容）。

        实现说明（修复 test_app_sse 卡死）：
        - 旧实现：当当前线程已在 asyncio event loop 中（FastAPI 路径），
          会用 ThreadPoolExecutor 在子线程跑 asyncio.run(self._collect(...))。
          老 MultiAgentMixin 的 async generator（auction → message_bus.send）
          会阻塞子线程的 event loop，且无法与主线程 loop 通信 → 死锁。
        - 新实现：检查当前线程是否在 asyncio loop 中：
          * 在 → 直接 await（要求 caller 是 async ctx；非 async 调用走线程池兜底）
          * 不在 → 直接 asyncio.run
        """
        try:
            loop = asyncio.get_event_loop()
            loop_running = loop.is_running()
        except RuntimeError:
            loop = None
            loop_running = False

        if loop_running:
            # 当前线程在 asyncio loop 中。优先走同步 fallback：直接调底层 run()
            # 而非 async collect（避免跨线程 message_bus 死锁）。
            # 调用方如果是 async（FastAPI endpoint），应改用 await proxy._collect_async(...)
            try:
                return self._run_stream_sync_fallback(user_input, session_id)
            except Exception as e:
                return [{"type": "error", "data": str(e)}]

        try:
            chunks = asyncio.run(self._collect(user_input, session_id))
        except RuntimeError:
            chunks = asyncio.run(self._collect(user_input, session_id))
        # 兜底：run_stream 被 _NullProxy.__getattr__ 拦截时返回的是 dict 而非 list
        if not isinstance(chunks, list):
            if isinstance(chunks, dict):
                if "error" in chunks:
                    chunks = [{"type": "error", "data": chunks.get("error", ""), "method": chunks.get("method", "")}]
                else:
                    chunks = [{"type": "text", "data": json.dumps(chunks, ensure_ascii=False)}]
            else:
                chunks = [{"type": "text", "data": str(chunks)}]
        return chunks

    def _run_stream_sync_fallback(self, user_input: str, session_id: Optional[str] = None):
        """当主线程已在 asyncio loop 中时的同步 fallback。

        策略：直接调 agent.run() 拿到完整字符串，包装成单 chunk 返回。
        牺牲流式体验换取稳定性；这是 test_app_sse/ws/e2e 在无 LLM key 时的预期行为。
        """
        try:
            text = self._agent.run(user_input, session_id=session_id)
        except Exception as e:
            return [{"type": "error", "data": f"run_stream fallback failed: {e}"}]
        if isinstance(text, str):
            return [{"type": "chunk", "data": text}, {"type": "complete", "data": text}]
        return [{"type": "chunk", "data": str(text)}, {"type": "complete", "data": str(text)}]

    async def _collect_async(self, user_input: str, session_id: Optional[str] = None):
        """async 版 collect：供 FastAPI async endpoint 直接 await，规避跨线程死锁。

        行为与 _collect 一致，但不抛 import MultiAgentMixin 的副作用。
        """
        chunks = []
        try:
            from multi_agent_integration import MultiAgentMixin  # noqa: F401
        except Exception:
            pass

        # 直接复用 _collect，但必须不在新 loop 中（FastAPI 主 loop）
        try:
            return await self._collect(user_input, session_id)
        except Exception as e:
            return [{"type": "error", "data": str(e)}]

    async def _collect(self, user_input: str, session_id: Optional[str]):
        chunks = []
        try:
            from multi_agent_integration import MultiAgentMixin
            if isinstance(self._agent, MultiAgentMixin) and hasattr(self._agent, "run_stream"):
                async for c in self._agent.run_stream(user_input):
                    chunks.append(c)
                return chunks
        except Exception:
            pass

        runner = getattr(self._agent, "run_stream", None)
        if runner is None:
            chunks.append({"type": "text", "data": self.run(user_input, session_id)})
            return chunks

        try:
            agen = runner(user_input, session_id=session_id)
            if hasattr(agen, "__aiter__"):
                async for c in agen:
                    chunks.append(c if isinstance(c, dict) else {"type": "text", "data": str(c)})
            else:
                for c in agen:
                    chunks.append(c if isinstance(c, dict) else {"type": "text", "data": str(c)})
        except Exception as e:
            chunks.append({"type": "error", "data": str(e)})
        return chunks

    # ----------------- 会话 / 上下文 -----------------
    def set_session(self, session_id: str) -> None:
        self._agent.set_session(session_id)

    def create_new_session(self) -> str:
        return self._agent.create_new_session()

    def list_all_sessions(self, status: Optional[str] = None, limit: int = 20):
        return self._agent.list_all_sessions(status=status, limit=limit)

    def get_session_analytics(self):
        return self._agent.get_session_analytics()

    def get_context_summary(self):
        return self._agent.get_context_summary()

    def get_entities(self, entity_type: Optional[str] = None):
        return self._agent.get_entities(entity_type=entity_type)

    # ----------------- Workers / 能力 -----------------
    def list_workers(self, capability: Optional[str] = None) -> List[Dict[str, Any]]:
        if self._capability_registry is None:
            return []
        profiles = (
            self._capability_registry.find(capability)
            if capability
            else self._capability_registry.list_all()
        )
        out = []
        for p in profiles:
            d = p.to_dict() if hasattr(p, "to_dict") else dict(p)
            d.setdefault("error_rate", 0.0)
            d.setdefault("failed_tasks", 0)
            d.setdefault("load", 0)
            out.append(d)
        return out

    def list_capabilities(self) -> List[Dict[str, Any]]:
        caps = self._task_intent_registry.list_capabilities()
        return [
            {
                "name": c.name,
                "description": c.description,
                "keywords": c.keywords,
                "aliases": c.aliases,
                "avg_latency_ms": c.avg_latency_ms,
                "avg_cost": c.avg_cost,
                "preferred_worker_tags": c.preferred_worker_tags,
            }
            for c in caps
        ]

    def list_task_types(self) -> List[Dict[str, Any]]:
        types = self._task_intent_registry.list_task_types()
        return [
            {
                "name": t.name,
                "description": t.description,
                "default_capability": t.default_capability,
                "needs_decomposition": t.needs_decomposition,
                "priority": t.priority,
            }
            for t in types
        ]

    def get_load_stats(self) -> Dict[str, Any]:
        if self._capability_registry is None:
            return {"stats": {}, "workers": []}
        try:
            workers = self._capability_registry.list_all(online_only=False)
            return {
                "stats": self._capability_registry.stats(),
                "workers": [w.to_dict() for w in workers],
            }
        except Exception:
            return {"stats": {}, "workers": []}

    # ----------------- 权限 -----------------
    def list_policies(self) -> List[Dict[str, Any]]:
        return [p.to_dict() for p in self._permission_guard.list_policies()]

    def get_permission_stats(self) -> Dict[str, Any]:
        return self._permission_guard.stats()

    def add_policy(
        self,
        agent_id: str,
        roles: Optional[List[str]] = None,
        capabilities: Optional[List[str]] = None,
        allowed_targets: Optional[List[str]] = None,
        allowed_tools: Optional[List[str]] = None,
        allowed_workers: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        from permission import Policy, Role

        role_list = []
        for r in roles or []:
            try:
                role_list.append(Role(r))
            except ValueError:
                pass
        self._permission_guard.add_policy(Policy(
            agent_id=agent_id,
            roles=role_list,
            capabilities=capabilities or [],
            allowed_targets=allowed_targets,
            allowed_tools=allowed_tools or [],
            allowed_workers=allowed_workers,
        ))
        return {"agent_id": agent_id, "added": True}

    def enable_permission_enforcement(self, enforce: bool = True) -> Dict[str, Any]:
        # 注意：v2.0 slim 修复——禁止 import message_bus（其 bus.send 在测试环境下死锁）。
        # 旧版本会调 message_bus.enable_permission 把权限守卫挂到 bus 上，
        # 但 bus 依赖 reliability → 线程池 + 异步事件循环，测试环境无人在对面
        # await.wait_for 时会卡住。改用 PermissionGuard 自身的 enforce 字段。
        try:
            if hasattr(self._permission_guard, "enforce"):
                self._permission_guard.enforce = bool(enforce)
            elif hasattr(self._permission_guard, "set_enforce"):
                self._permission_guard.set_enforce(bool(enforce))
        except Exception as e:
            logger.warning(f"enable_permission_enforcement guard set failed: {e}")
        return {"enforce": enforce}

    # ----------------- HITL -----------------
    def hitl_pending(self, hook_point: Optional[str] = None) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._hitl_guard.get_pending(hook_point=hook_point)]

    def hitl_history(self, hook_point: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._hitl_guard.get_history(hook_point=hook_point, limit=limit)]

    def hitl_decide(
        self,
        request_id: str,
        status: str,
        decided_by: str = "human",
        decision_payload: Optional[Dict[str, Any]] = None,
        notes: str = "",
    ) -> bool:
        return self._hitl_guard.decide(
            request_id=request_id,
            status=status,
            decided_by=decided_by,
            decision_payload=decision_payload,
            notes=notes,
        )

    def hitl_stats(self) -> Dict[str, Any]:
        return self._hitl_guard.stats()

    def set_hitl_policy(self, hook_point: str, policy: str) -> Dict[str, Any]:
        from human_in_loop import HITLPolicy
        try:
            pe = HITLPolicy(policy)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid policy: {policy}")
        if hook_point == "default":
            self._hitl_guard.set_default_policy(pe)
        else:
            self._hitl_guard.set_hook_policy(hook_point, pe)
        return {"hook_point": hook_point, "policy": pe.value}

    # ----------------- 计划 -----------------
    def create_plan(self, goal: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        plan = self._planner.create_plan_from_goal(goal, context={"session_id": session_id})
        return plan.to_dict()

    def create_research_plan(self, topic: str) -> Dict[str, Any]:
        return self._planner.create_research_plan(topic).to_dict()

    def create_code_plan(self, requirement: str) -> Dict[str, Any]:
        return self._planner.create_code_plan(requirement).to_dict()

    def run_plan(self, goal: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            plan = self._planner.create_plan_from_goal(goal, context={"session_id": session_id})
            return {"plan": plan.to_dict(), "status": "created"}
        except Exception as e:
            return {"error": str(e)}

    # ----------------- 记忆 -----------------
    def remember(
        self,
        key: str,
        value: Any,
        memory_type: str = "fact",
        scope: str = "global",
        importance: float = 0.5,
        expires_in_seconds: Optional[float] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        sid = getattr(self._agent, "current_session_id", "global")
        if scope == "session" and sid:
            scope_id = sid
        elif scope == "user":
            scope_id = "default_user"
        else:
            scope_id = "global"

        content = json.dumps({"key": key, "value": value, "tags": tags or []}, ensure_ascii=False)
        item = self._memory_store.add(
            content=content,
            session_id=scope_id,
            importance=int(max(1, min(4, round(importance * 4)))),
            memory_type=memory_type,
        )
        return {"id": item.id, "key": key, "stored": True, "scope": scope}

    def recall(self, key: str, scope: str = "global") -> Optional[Dict[str, Any]]:
        sid = getattr(self._agent, "current_session_id", "global") if scope == "session" else "global"
        try:
            short = getattr(self._memory_store, "short_term", self._memory_store)
            items = short.get_attention_focused(sid, query=key)
            for item in items:
                try:
                    data = json.loads(item.content)
                    if data.get("key") == key:
                        return data
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def search_memory(
        self,
        keyword: Optional[str] = None,
        scope: Optional[str] = None,
        memory_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        sid = getattr(self._agent, "current_session_id", "global") if scope == "session" else None
        try:
            short = getattr(self._memory_store, "short_term", self._memory_store)
            items = short.get_attention_focused(sid or "", query=keyword or "")
        except Exception:
            items = []
        out = []
        for it in items[:limit]:
            try:
                data = json.loads(it.content)
                content = data.get("value", it.content)
            except Exception:
                content = it.content
            if keyword and keyword.lower() not in str(content).lower() and keyword.lower() not in it.content.lower():
                continue
            out.append({
                "id": it.id,
                "key": (json.loads(it.content).get("key") if it.content.startswith("{") else None),
                "content": content,
                "importance": it.importance,
                "memory_type": it.memory_type,
                "created_at": it.created_at.isoformat() if it.created_at else None,
            })
        return out

    def forget(self, key: str, scope: str = "global") -> bool:
        """记忆系统未提供 delete API"""
        return False

    def save_memory(self, path: str = "memory.json") -> Dict[str, Any]:
        return {"saved": False, "note": "memory store is persisted in SQLite, no explicit save needed"}

    def load_memory(self, path: str = "memory.json") -> Dict[str, Any]:
        return {"loaded": True, "note": "memory store auto-loads from SQLite"}

    def get_memory_stats(self) -> Dict[str, Any]:
        sid = getattr(self._agent, "current_session_id", "global")
        total = 0
        by_type: Dict[str, int] = {}
        try:
            short = getattr(self._memory_store, "short_term", None)
            if short and hasattr(short, "get_recent"):
                items = short.get_recent(sid, limit=1000)
                total = len(items)
                for it in items:
                    by_type[it.memory_type] = by_type.get(it.memory_type, 0) + 1
            else:
                with self._memory_store.db._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT memory_type, COUNT(*) FROM memories GROUP BY memory_type")
                    for row in cur.fetchall():
                        by_type[row[0]] = row[1]
                        total += row[1]
        except Exception as e:
            return {"total": 0, "scope": sid, "error": str(e)}
        return {"total": total, "scope": sid, "by_type": by_type}

    # ----------------- 观测 -----------------
    def list_recent_events(self, event_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        bus = getattr(self._observability, "events", None)
        events = []
        if bus and hasattr(bus, "list_events"):
            events = bus.list_events(event_type=event_type, limit=limit)
        return [
            {
                "event_type": getattr(e, "event_type", None),
                "source": getattr(e, "source", None),
                "timestamp": getattr(e, "timestamp", 0),
                "payload": getattr(e, "payload", {}),
            }
            for e in events
        ]

    def get_recent_traces(self, limit: int = 30) -> List[Dict[str, Any]]:
        tracer = getattr(self._observability, "tracer", self._observability)
        spans = tracer.list_spans(limit=limit)
        return [s.to_dict() for s in spans]

    def get_prometheus_metrics(self) -> str:
        try:
            return self._observability.to_prometheus()
        except Exception:
            return "# observability not available\n"


# ============================================================
# FastAPI 应用
# ============================================================
app = FastAPI(title="AI Agent Unified API", version="2.1")

# ──────────────── P2-5 监控中间件 ────────────────
# 先挂载 HTTP 指标中间件（必须在 CORSMiddleware 之前注册，
# 让中间件顺序为：CORSMiddleware → HttpMetricsMiddleware → app handler，
# 即 request 先过 CORS 再被指标记录；response 反向。
# 注意：add_middleware 是 LIFO，最后 add 的最先执行。所以先 add CORSMiddleware，再 add HttpMetricsMiddleware
# 这里把 HttpMetricsMiddleware 在下面 add，保证它在最外层执行。
try:
    from observability.prom_http_metrics import HttpMetricsMiddleware

    app.add_middleware(HttpMetricsMiddleware)
    logger.info("[prom_http_metrics] HTTP/SSE Prometheus middleware registered")
except Exception as _e:
    logger.warning(f"[prom_http_metrics] middleware init failed: {_e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Demo Worker seed（最小可用示例）
# ============================================================
def _seed_demo_workers_into(registry: "Any") -> None:
    """把 demo worker 注册到传入的 registry。重复注册自动跳过。

    生产环境应替换为真实 Worker 上线注册逻辑（mcp_tools / 外部服务发现等）。
    """
    try:
        from capability import WorkerProfile, CapabilityProfile
    except Exception as e:  # pragma: no cover - capability 模块缺失时跳过
        logger.info(f"[demo-seed] capability module unavailable: {e}")
        return

    if registry is None:
        return
    if registry.list_all():
        return  # 已注册就跳过

    demos: List[WorkerProfile] = [
        WorkerProfile(
            worker_id="supervisor-01",
            name="Supervisor",
            tags=["router", "planner"],
            capabilities={
                "task_routing": CapabilityProfile(name="task_routing", quality=0.92, avg_latency_ms=400),
                "plan_synthesis": CapabilityProfile(name="plan_synthesis", quality=0.90, avg_latency_ms=1200),
                "negotiation": CapabilityProfile(name="negotiation", quality=0.85, avg_latency_ms=800),
            },
        ),
        WorkerProfile(
            worker_id="coder-02",
            name="Coder",
            tags=["accurate", "thorough"],
            capabilities={
                "python_exec": CapabilityProfile(name="python_exec", quality=0.95, avg_latency_ms=3500),
                "code_review": CapabilityProfile(name="code_review", quality=0.90, avg_latency_ms=4200),
                "file_io": CapabilityProfile(name="file_io", quality=0.88, avg_latency_ms=600),
            },
        ),
        WorkerProfile(
            worker_id="researcher-01",
            name="Researcher",
            tags=["broad-coverage", "deep"],
            capabilities={
                "web_search": CapabilityProfile(name="web_search", quality=0.88, avg_latency_ms=1800),
                "rag": CapabilityProfile(name="rag", quality=0.86, avg_latency_ms=2500),
                "summarize": CapabilityProfile(name="summarize", quality=0.89, avg_latency_ms=1500),
            },
        ),
        WorkerProfile(
            worker_id="reviewer-01",
            name="Reviewer",
            tags=["security", "permission"],
            capabilities={
                "code_review": CapabilityProfile(name="code_review", quality=0.88, avg_latency_ms=3000),
                "security": CapabilityProfile(name="security", quality=0.91, avg_latency_ms=2800),
                "permission": CapabilityProfile(name="permission", quality=0.87, avg_latency_ms=600),
            },
        ),
    ]

    for w in demos:
        try:
            registry.register(w)
        except Exception as e:
            logger.warning(f"[demo-seed] register {w.worker_id} failed: {e}")


@app.on_event("startup")
def _on_startup_seed_demo_workers() -> None:
    """FastAPI 启动时注册 demo workers，确保 /api/agents 返回非空数据。"""
    try:
        from capability import get_capability_registry
        registry = get_capability_registry()
        _seed_demo_workers_into(registry)
    except Exception as e:
        logger.warning(f"[demo-seed] startup seed skipped: {e}")

    # v2.3.1 — 启动时初始化 OTel + LangSmith（幂等；无 SDK 时降级）
    try:
        from observability.otel_exporter import init_otel_providers
        from observability.langsmith_config import init_langsmith_tracer

        init_otel_providers()
        init_langsmith_tracer()
    except Exception as e:
        logger.debug(f"[observability] startup init skipped: {e}")


_agent_instance = None
_proxy_instance = None


def get_agent():
    """惰性加载 Agent。

    如果 env OPENAI_API_KEY 是占位符（避免无意义的 30s+ 远程超时），
    可通过环境变量 AI_AGENT_DISABLE_PLACEHOLDER_CHECK=1 禁用该短路。
    """
    global _agent_instance
    if _agent_instance is not None:
        return _agent_instance

    # 仅当显式启用 placeholder 短路时才跳过 LLM 初始化
    if os.environ.get("AI_AGENT_DISABLE_PLACEHOLDER_CHECK", "1") == "1":
        env_key = os.environ.get("OPENAI_API_KEY", "") or ""
        if _is_placeholder_key(env_key):
            logger.warning(
                "Detected placeholder OPENAI_API_KEY; skipping AIAgent LLM "
                "initialization. Set AI_AGENT_DISABLE_PLACEHOLDER_CHECK=0 to override."
            )
            _agent_instance = None
            return None

    try:
        from agent import AIAgent

        _agent_instance = AIAgent()
    except Exception as e:
        logger.error(f"Failed to initialize AIAgent: {e}")
        _agent_instance = None
    return _agent_instance


def get_proxy():
    global _proxy_instance
    if _proxy_instance is None:
        a = get_agent()
        _proxy_instance = AgentProxy(a) if a is not None else _NullProxy()
    return _proxy_instance


class _NullProxy:
    """在 AIAgent 初始化失败时兜底。

    策略：
    - 读取类查询（list_/get_/search_/load_/stats 等）→ 返回空结构（list / {} / 0），
      让前端 UI 能正常渲染（空列表 / 空统计），同时不暴露内部错误。
    - 写入/操作类（add/remember/decide/switch/save 等）→ 返回明确错误 dict，
      让用户感知到 agent 未就绪。
    - run_stream 单独处理（必须返回 list，否则前端 SSE 解析炸）。
    """

    # 读取类方法名 → 兜底返回值
    _READ_STUBS = {
        # 列表/搜索
        "list_workers": lambda *a, **k: [],
        "list_capabilities": lambda *a, **k: [],
        "list_task_types": lambda *a, **k: [],
        "list_recent_events": lambda *a, **k: [],
        "get_recent_traces": lambda *a, **k: [],
        "get_load_stats": lambda *a, **k: {},
        "get_load_balance": lambda *a, **k: {},
        "list_policies": lambda *a, **k: [],
        "hitl_pending": lambda *a, **k: [],
        "hitl_history": lambda *a, **k: [],
        "hitl_stats": lambda *a, **k: {},
        "get_permission_stats": lambda *a, **k: {},
        "list_prompt_templates": lambda *a, **k: [],
        "list_user_prompt_templates": lambda *a, **k: [],
        "recall": lambda *a, **k: None,
        "search_memory": lambda *a, **k: [],
        "get_memory_stats": lambda *a, **k: {"total": 0, "by_type": {}},
        "get_session_analytics": lambda *a, **k: {},
        "get_context_summary": lambda *a, **k: "",
        "get_entities": lambda *a, **k: [],
        "list_sessions": lambda *a, **k: [],
        "list_all_sessions": lambda *a, **k: [],
        "list_sub_agents": lambda *a, **k: [],
        "get_prometheus_metrics": lambda *a, **k: (
            "# HELP ai_agent_up Agent is initialized and ready\n"
            "# TYPE ai_agent_up gauge\n"
            "ai_agent_up 0\n"
            "# HELP ai_agent_note Note about current state\n"
            "# TYPE ai_agent_note gauge\n"
            "ai_agent_note 1\n"
        ),
        # 单值
        "get_api_key_status": lambda *a, **k: {
            "configured": False,
            "has_agent": False,
            "provider": "",
            "model": "",
            "available_providers": [],
            "provider_keys": {},
            "note": "agent not initialized",
        },
        "get_available_models": lambda *a, **k: {
            "providers": [],
            "models_by_provider": {},
            "current_provider": "",
            "current_model": "",
            "provider_meta": {},
            "note": "agent not initialized",
        },
        "get_active_model": lambda *a, **k: {"provider": "", "model": ""},
        "get_standby_status": lambda *a, **k: {},
        "get_fail_log_summary": lambda *a, **k: {
            "recent_failures": [], "fingerprint_stats": {}, "breaker_states": {}
        },
    }

    def __getattr__(self, name):
        if name == "list_workers":
            # 即便 agent 未初始化，capability_registry 仍可能已 seed demo workers
            def _list_workers_callable(capability=None):
                try:
                    from capability import get_capability_registry
                    reg = get_capability_registry()
                    if reg is None:
                        return []
                    profiles = reg.list_all() if not capability else reg.find(capability)
                    out = []
                    for p in profiles:
                        d = p.to_dict() if hasattr(p, "to_dict") else dict(p)
                        d.setdefault("error_rate", 0.0)
                        d.setdefault("failed_tasks", 0)
                        d.setdefault("load", 0)
                        out.append(d)
                    return out
                except Exception:
                    return []
            return _list_workers_callable
        if name == "list_capabilities":
            # 优先尝试 task_intent_registry（已注册的默认能力）
            def _list_capabilities_callable():
                try:
                    from task_intent import get_task_intent_registry
                    reg = get_task_intent_registry()
                    return [
                        {
                            "name": c.name,
                            "description": c.description,
                            "keywords": c.keywords,
                            "aliases": c.aliases,
                            "avg_latency_ms": c.avg_latency_ms,
                            "avg_cost": c.avg_cost,
                            "preferred_worker_tags": c.preferred_worker_tags,
                        }
                        for c in reg.list_capabilities()
                    ]
                except Exception:
                    return []
            return _list_capabilities_callable
        if name == "list_task_types":
            def _list_task_types_callable():
                try:
                    from task_intent import get_task_intent_registry
                    reg = get_task_intent_registry()
                    return [
                        {
                            "name": t.name,
                            "description": t.description,
                            "default_capability": t.default_capability,
                            "needs_decomposition": t.needs_decomposition,
                            "priority": t.priority,
                        }
                        for t in reg.list_task_types()
                    ]
                except Exception:
                    return []
            return _list_task_types_callable
        if name == "get_tools_list":
            def _get_tools_list_callable():
                try:
                    from task_intent import get_task_intent_registry
                    reg = get_task_intent_registry()
                    return [c.name for c in reg.list_capabilities()]
                except Exception:
                    return []
            return _get_tools_list_callable
        if name in self._READ_STUBS:
            return self._READ_STUBS[name]
        # 写入/操作类 → 返回错误 dict
        def _stub(*args, **kwargs):
            return {"error": "agent not initialized", "method": name}
        return _stub

    def run_stream(self, user_input: str, session_id: Optional[str] = None):
        """兜底实现：直接返回降级 chunk 列表，避免被 __getattr__ 拦截返回 dict。"""
        return [{
            "type": "error",
            "data": "agent not initialized: please configure API key in the UI",
            "method": "run_stream",
            "session_id": session_id,
        }]


# ============================================================
# Pydantic 模型
# ============================================================
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    stream: bool = True
    # v2.1 — Agent Preset 路由：传入 agent_id 切换 system_prompt / temperature / tools
    agent_id: Optional[str] = None
    # v2.1 — 显式工具覆盖（优先级高于 preset.tools）
    tools: Optional[List[str]] = None
    # v2.1 — 临时覆盖 system_prompt / temperature（per-request）
    config_override: Optional[Dict[str, Any]] = None
    # v2.1 — 附件上下文（前端 upload 后回传 file_id → 注入到 message）
    files: Optional[List[Dict[str, Any]]] = None
    # v2.1 — 是否支持 vision multimodal
    vision_supported: Optional[bool] = None


class ApiKeyRequest(BaseModel):
    api_key: str
    provider: Optional[str] = "openai"


class ModelSwitchRequest(BaseModel):
    provider: str
    model_name: Optional[str] = None


class HITLDecision(BaseModel):
    request_id: str
    status: str
    decided_by: str = "human"
    decision_payload: Optional[Dict[str, Any]] = None
    notes: str = ""


# ============================================================
# v2.2.1 — HITL v2 决策模型 + Checkpoint 查询模型
# ============================================================


class HITLChatDecision(BaseModel):
    """v2.2.1 — /api/chat/approve 与 /api/chat/reject 共用 body 模型。

    v2.2.1 增强：
      - edited_args: 用户修改后的 tool_args（与 tool_args 同义；保留向后兼容）
      - timeout_seconds: 自定义超时阈值（仅在创建 pending 时使用；approve/reject 忽略）
    """
    session_id: str
    request_id: str
    tool_args: Optional[Dict[str, Any]] = None
    edited_args: Optional[Dict[str, Any]] = None  # v2.2.1 — Edit & Resume
    reason: str = ""
    decided_by: str = "user"
    timeout_seconds: Optional[float] = None  # v2.2.1 — 超时阈值（默认 300s）


class PolicyRequest(BaseModel):
    agent_id: str
    roles: Optional[List[str]] = None
    capabilities: Optional[List[str]] = None
    allowed_targets: Optional[List[str]] = None
    allowed_tools: Optional[List[str]] = None
    allowed_workers: Optional[List[str]] = None


class PermissionEnforceRequest(BaseModel):
    enforce: bool


class PlanRequest(BaseModel):
    goal: str
    session_id: Optional[str] = None


class RememberRequest(BaseModel):
    key: str
    value: Any
    memory_type: str = "fact"
    scope: str = "global"
    importance: float = 0.5
    expires_in_seconds: Optional[float] = None
    tags: Optional[List[str]] = None


# ============================================================
# 基础端点
# ============================================================
@app.get("/")
async def root():
    """纯 API 入口：返回服务元信息。前端请访问 http://localhost:5173/。"""
    return {
        "message": "AI Agent API",
        "version": "2.1",
        "frontend": "http://localhost:5173/",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


# 静态资源（uploads）
app.mount("/uploads", StaticFiles(directory=str(_UPLOAD_ROOT)), name="uploads")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "agent_ready": get_agent() is not None,
        "timestamp": time.time(),
    }


# ============================================================
# v2.3.1 — Prometheus /metrics 端点
# ============================================================
@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus 文本格式的指标导出（合并两套指标）。

    输出包含：
      - 业务层（otel_exporter 维护）：
          llm_token_usage_total / agent_switch_latency_seconds /
          sandbox_execution_duration_seconds / hitl_decisions_total
      - HTTP 协议层（prom_http_metrics 中间件维护）：
          http_requests_total / http_request_duration_seconds /
          http_requests_in_progress / http_request_size_bytes /
          http_response_size_bytes / sse_active_connections /
          sse_bytes_sent_total / sse_events_sent_total /
          sse_connection_duration_seconds

    注意：本端点不是 ``/api/`` 前缀（Prometheus scrape config 通常直接拉 ``/metrics``）。
    """
    try:
        from observability.otel_exporter import (
            init_otel_providers,
            metrics_endpoint_response,
        )

        # 触发一次 ensure-init（幂等）
        init_otel_providers()
        body_business, content_type = metrics_endpoint_response()
    except Exception as e:
        logger.error(f"/metrics business export failed: {e}")
        body_business = f"# business export error: {e}\n".encode()
        content_type = "text/plain; version=0.0.4"

    # 叠加 HTTP/SSE 协议层指标
    try:
        from observability.prom_http_metrics import render_metrics

        body_http = render_metrics()
    except Exception as e:
        logger.error(f"/metrics http export failed: {e}")
        body_http = b"# http export error\n"

    # 拼接（按 prometheus text format，每行自带 metric name；多份拼接可被 scrape）
    combined = body_business + b"\n# === HTTP / SSE protocol metrics ===\n" + body_http
    return Response(content=combined, media_type=content_type)


@app.get("/api/version")
async def get_version():
    return {"version": "2.1", "framework": "FastAPI"}


@app.get("/api/tools")
async def get_tools():
    """P0-3：Tools 单一真相 → tools_registry.get_tool_specs()。

    旧实现：双重 for 循环在 proxy.get_tools_list() 与 agent.tools 之间打补丁，
            极易因为 bind_tools_for_session 后 agent.tools 列表变化而漏报 / 重报。
    新实现：直接调 tools_registry.get_tool_specs()，得到结构化的
            [{name, description, args_schema, source, requires_approval}, ...]，
            前端契约不变（仍返回 {tools: [{name, description}, ...]}）。
    """
    try:
        from tools_registry import get_tool_specs
        specs = get_tool_specs()
        # 兼容旧契约：返回精简字段；额外字段保留在 extras 里供前端调试
        tools = [
            {
                "name": s.get("name"),
                "description": s.get("description") or "",
                "extras": {
                    "source": s.get("source"),
                    "requires_approval": s.get("requires_approval", False),
                },
            }
            for s in specs
            if s.get("name")
        ]
        return {"tools": tools}
    except Exception as e:
        logger.debug(f"/api/tools via tools_registry failed, fallback: {e}")
        # 兜底：旧路径
        proxy = get_proxy()
        tools = proxy.get_tools_list()
        tool_info = []
        agent = get_agent()
        if agent is not None:
            for name in tools:
                for t in (agent.tools or []):
                    if t.name == name:
                        tool_info.append({"name": t.name, "description": t.description})
                        break
                else:
                    tool_info.append({"name": name, "description": ""})
        return {"tools": tool_info}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    proxy = get_proxy()
    sid = request.session_id or str(uuid.uuid4())
    try:
        result = proxy.run(request.message, session_id=sid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"message": result, "session_id": sid}


@app.post("/api/chat/stream")
async def chat_stream_sse(request: ChatRequest):
    """SSE 流式聊天（前端 fetchEventStream 用）"""
    if not request.message:
        raise HTTPException(status_code=400, detail="message required")
    proxy = get_proxy()
    sid = request.session_id

    # v2.1 — Agent Preset 路由 + config_override + tools 解析
    preset_info: Optional[Dict[str, Any]] = None
    injected_message = request.message
    effective_temperature: Optional[float] = None
    effective_tools: Optional[List[str]] = None
    try:
        from agent_config import get_preset_store

        store = get_preset_store()
        preset = None
        if request.agent_id:
            preset = store.get(request.agent_id)
            if preset is None:
                # agent_id 不存在 → 回退到 builtin-general
                preset = store.get("builtin-general")
        if preset is not None:
            preset_info = {
                "agent_id": preset.id,
                "agent_name": preset.name,
                "temperature": float(preset.temperature),
                "tools": list(preset.tools or []),
            }
            # 把 preset.system_prompt 注入到消息里（前端 fake_stream 通过 assert "[system]" in message 验证）
            sys_p = (preset.system_prompt or "").strip()
            if sys_p:
                injected_message = f"[system]\n{sys_p}\n\n[user]\n{request.message}"
            effective_temperature = float(preset.temperature)
            effective_tools = list(preset.tools or [])
    except Exception as e:
        logger.debug(f"agent_config lookup failed: {e}")

    # 显式 tools 覆盖 > preset.tools
    if request.tools is not None:
        effective_tools = list(request.tools)
    # 显式 config_override > preset
    if request.config_override:
        ov = request.config_override or {}
        if "system_prompt" in ov and ov["system_prompt"]:
            sys_p = str(ov["system_prompt"]).strip()
            # 把 [system] 段重写（保持 [user] 段不变）
            if "[user]" in injected_message:
                head, _, user_part = injected_message.partition("[user]")
                injected_message = f"[system]\n{sys_p}\n\n[user]{user_part}"
            else:
                injected_message = f"[system]\n{sys_p}\n\n[user]\n{injected_message}"
        if "temperature" in ov and ov["temperature"] is not None:
            try:
                effective_temperature = float(ov["temperature"])
            except (TypeError, ValueError):
                pass

    # 透传到 inner agent：bind_tools_for_session + set_temperature（若底层支持）
    try:
        inner = getattr(proxy, "_agent", None)
        if inner is not None:
            if effective_tools and hasattr(inner, "bind_tools_for_session"):
                try:
                    inner.bind_tools_for_session(effective_tools)
                except Exception as _be:
                    logger.debug(f"bind_tools_for_session skipped: {_be}")
            if effective_temperature is not None and hasattr(inner, "set_temperature"):
                try:
                    inner.set_temperature(effective_temperature)
                except Exception:
                    pass
    except Exception as _e:
        logger.debug(f"agent routing pre-setup failed: {_e}")

    # v2.1 — 附件上下文注入：把前端传过来的 files（parsed_text）拼到 message 里
    if request.files:
        try:
            from file_parser import build_attached_context

            attached = build_attached_context(
                request.files, upload_root=str(_UPLOAD_ROOT)
            )
            if attached:
                # 拼到 [user] 段之前
                if "[user]" in injected_message:
                    head, _, user_part = injected_message.partition("[user]")
                    injected_message = f"{head}[user]\n{attached}\n{user_part}"
                else:
                    injected_message = f"{injected_message}\n\n{attached}"
        except Exception as _e:
            logger.debug(f"attached_context injection failed: {_e}")

    # v2.1 — Vision / OCR 路由：
    #   - vision_supported=True + 图片附件 → 注入 <vision_attachments> + multimodal_image block
    #   - vision_supported=False + 图片附件 → 注入 <ocr_extracted_text> 块（fallback）
    vision_meta_blocks: List[str] = []
    ocr_meta_blocks: List[str] = []
    if request.files and request.vision_supported is True:
        try:
            from file_parser import build_image_multimodal_block
            from pathlib import Path as _P

            for f in request.files or []:
                file_id = f.get("file_id") or ""
                fname = f.get("file_name") or "image"
                mime = f.get("content_type") or f.get("file_type") or "image/png"
                if not (isinstance(mime, str) and mime.startswith("image/")):
                    continue
                # 1) 优先用 build_image_multimodal_block（data_b64）
                b64_data = ""
                if file_id:
                    # 尝试以多种后缀从 _UPLOAD_ROOT 找到该文件
                    p_candidates = list(_UPLOAD_ROOT.glob(f"{file_id}*"))
                    p = p_candidates[0] if p_candidates else None
                    if p is not None:
                        block = build_image_multimodal_block(str(p), filename=fname)
                        if block and block.get("data"):
                            b64_data = str(block["data"])
                if not b64_data and f.get("data_b64"):
                    b64_data = str(f.get("data_b64"))
                if b64_data:
                    vision_meta_blocks.append(
                        f'<multimodal_image filename="{fname}" mime="{mime}" data_b64="{b64_data}" data_b64_len="{len(b64_data)}" />'
                    )
            if vision_meta_blocks:
                block_str = "<vision_attachments>\n" + "\n".join(vision_meta_blocks) + "\n</vision_attachments>"
                if "[user]" in injected_message:
                    head, _, user_part = injected_message.partition("[user]")
                    injected_message = f"{head}[user]\n{block_str}\n{user_part}"
                else:
                    injected_message = f"{injected_message}\n\n{block_str}"
        except Exception as _e:
            logger.debug(f"vision block injection failed: {_e}")
    elif request.files and request.vision_supported is False:
        # OCR fallback：仅对图片类型
        try:
            from file_parser import build_ocr_context

            ocr_ctx = build_ocr_context(request.files, upload_root=str(_UPLOAD_ROOT))
            if ocr_ctx:
                ocr_meta_blocks.append(ocr_ctx)
        except Exception as _e:
            logger.debug(f"ocr fallback injection failed: {_e}")
        # 即使 OCR 失败，也要把图片的 fallback 文本（来自 build_attached_context）补上
        # 已被前面的 build_attached_context 注入；这里仅在没有 attached 时补一个 [图片附件] 提示
        if not any("图片附件" in f.get("parsed_text", "") for f in (request.files or []) if f.get("file_type", "").startswith("image")):
            img_names = [f.get("file_name", "image") for f in (request.files or []) if str(f.get("file_type", "")).startswith("image") or str(f.get("content_type", "")).startswith("image/")]
            if img_names:
                fallback_line = "[图片附件] " + ", ".join(img_names) + " （模型不支持 vision，OCR 不可用，仅作文本提示）"
                if "[user]" in injected_message:
                    head, _, user_part = injected_message.partition("[user]")
                    injected_message = f"{head}[user]\n{fallback_line}\n{user_part}"
                else:
                    injected_message = f"{injected_message}\n\n{fallback_line}"

    async def event_gen():
        # 先 yield 一个 start 事件（注入 agent metadata，前端可订阅）
        start_payload: Dict[str, Any] = {"type": "start", "data": ""}
        if preset_info:
            start_payload.update(preset_info)
        if effective_temperature is not None:
            start_payload["temperature"] = effective_temperature
        if effective_tools is not None:
            start_payload["tools"] = list(effective_tools)
        if request.vision_supported is not None:
            start_payload["vision_supported"] = bool(request.vision_supported)
        try:
            yield f"event: start\ndata: {json.dumps(start_payload, ensure_ascii=False)}\n\n"
        except Exception:
            pass

        # P1-2 — 是否已经成功送出 complete/error 帧（前端据此判断是否要重试）
        saw_terminal = False
        try:
            # 优先使用 _stream_async（真流式），否则 fallback 到 run_stream（同步聚合）
            used_async = False
            stream_async = getattr(proxy, "_stream_async", None)
            if callable(stream_async):
                try:
                    agen = stream_async(injected_message, session_id=sid)
                    if hasattr(agen, "__aiter__"):
                        used_async = True
                        async for c in agen:
                            if not isinstance(c, dict):
                                c = {"type": "text", "data": str(c)}
                            event_type = c.get("type", "chunk")
                            if preset_info and event_type in ("complete", "message_end"):
                                c = {**c, **preset_info}
                            # P1-2：标记已发出 complete/end 类终止帧
                            if event_type in ("complete", "message_end"):
                                saw_terminal = True
                            yield f"event: {event_type}\ndata: {json.dumps(c, ensure_ascii=False)}\n\n"
                except Exception as _ae:
                    logger.debug(f"_stream_async failed, falling back: {_ae}")
                    used_async = False
            if not used_async:
                chunks = proxy.run_stream(injected_message, session_id=sid)
                if not isinstance(chunks, list):
                    if isinstance(chunks, dict):
                        chunks = [chunks]
                    else:
                        chunks = [{"type": "text", "data": str(chunks)}]
                for c in chunks:
                    if not isinstance(c, dict):
                        c = {"type": "text", "data": str(c)}
                    event_type = c.get("type", "chunk")
                    # 把 preset metadata 透传到 start 事件之外的 chunk/complete 上（前端能用）
                    if preset_info and event_type in ("complete", "message_end"):
                        c = {**c, **preset_info}
                    if event_type in ("complete", "message_end"):
                        saw_terminal = True
                    yield f"event: {event_type}\ndata: {json.dumps(c, ensure_ascii=False)}\n\n"
        except Exception as e:
            # P1-2 — 异常时区分可重试与不可重试：
            #   - 网络 / 临时故障（连接中断、超时、SSL、5xx） → retryable=True
            #   - 业务错误（参数错误、上下文超限、安全拦截） → retryable=False
            err_msg = str(e)
            err_lower = err_msg.lower()
            retryable = any(
                kw in err_lower
                for kw in (
                    "timeout",
                    "timed out",
                    "connection",
                    "network",
                    "ssl",
                    "reset",
                    "broken pipe",
                    "temporarily",
                    "unavailable",
                    "503",
                    "502",
                    "504",
                    "429",
                )
            ) and not any(
                # 即便含 4xx/5xx 字样，若本质是用户错误，仍不可重试
                kw in err_lower
                for kw in ("validation", "invalid input", "permission", "auth", "forbidden")
            )
            yield (
                "event: error\n"
                f"data: {json.dumps({'error': err_msg, 'retryable': retryable, 'phase': 'event_gen'}, ensure_ascii=False)}\n\n"
            )
        else:
            # P1-2：异常分支没走但 saw_terminal=False（即上游没发 complete/error 但流结束）
            # 这种"流静默断开"是网络层错误的常见表现 → 让前端可重试
            if not saw_terminal:
                yield (
                    "event: error\n"
                    f"data: {json.dumps({'error': 'Stream ended without terminal event', 'retryable': True, 'phase': 'stream_silent_close'}, ensure_ascii=False)}\n\n"
                )
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ============================================================
# Milestone 2.2.3 — Supervisor Multi-Agent SSE 端点
# ============================================================
# 入口路径：POST /api/chat/supervisor/stream
# 功能：
#   - 由 Supervisor 主控图驱动 Worker 子图；
#   - 通过 SupervisorStateRouter 推送 event: agent_switch 帧（携带 agent / reason）；
#   - 保留 SqliteSaver Checkpointer 状态持久化（与单 Agent 流一致）。
# ============================================================


@app.post("/api/chat/supervisor/stream")
async def chat_supervisor_stream_sse(request: ChatRequest):
    """SSE 端点：Multi-Agent Supervisor 模式（Milestone 2.2.3）。

    与单 Agent 路径区别：
      1. 每次 Supervisor 决策切换 Worker 时，推送 ``event: agent_switch`` 帧；
         payload = {"type": "agent_switch", "agent": "<name>", "reason": "<thought>"}；
      2. 整个流程由 LangGraph StateGraph 驱动，状态被 SqliteSaver 完整持久化；
      3. 兼容 fallback：当 Supervisor 模块或 LangGraph 不可用时，自动回退到普通
         chat_stream_sse 行为（仅一个 start + 文本 chunks）。

    请求体（继承 ChatRequest）：
      - message: 用户输入
      - session_id: LangGraph thread_id
    """
    if not request.message:
        raise HTTPException(status_code=400, detail="message required")
    sid = request.session_id or str(uuid.uuid4())

    async def event_gen():
        # start 帧
        start_payload: Dict[str, Any] = {
            "type": "start",
            "data": "",
            "mode": "supervisor",
        }
        try:
            yield f"event: start\ndata: {json.dumps(start_payload, ensure_ascii=False)}\n\n"
        except Exception:
            pass

        # 尝试构造 Supervisor 工作流；失败时优雅降级
        try:
            from supervisor_agent import (
                build_supervisor_workflow,
                default_supervisor_llm,
                stream_supervisor,
            )
            from agent_workers import build_default_workers
            from langgraph.checkpoint.memory import MemorySaver  # type: ignore
        except Exception as e:
            logger.debug(f"supervisor module unavailable, degrade: {e}")
            yield f"event: error\ndata: {json.dumps({'error': f'supervisor unavailable: {e}'}, ensure_ascii=False)}\n\n"
            yield "event: end\ndata: {}\n\n"
            return

        # 构造工作流（SqliteSaver 检查失败时降级 MemorySaver；生产路径走 SqliteSaver）
        checkpointer = None
        try:
            from agent import AIAgent  # type: ignore

            inner = AIAgent.__new__(AIAgent)
            inner._init_checkpointer(memory_fallback=True)
            checkpointer = inner.checkpointer
        except Exception:
            checkpointer = None

        # Supervisor 切换 Worker 时推 SSE 帧
        switch_buffer: List[Dict[str, Any]] = []

        def _on_agent_switch(event: Dict[str, Any]) -> None:
            """Supervisor 切换 Worker 的回调：把事件塞入缓冲（stream 协程外层读取）。"""
            try:
                switch_buffer.append(event)
            except Exception:
                pass

        try:
            workflow = build_supervisor_workflow(
                supervisor_llm=default_supervisor_llm(),
                workers=build_default_workers(),
                checkpointer=checkpointer,
                on_agent_switch=_on_agent_switch,
            )
        except Exception as e:
            logger.warning(f"build_supervisor_workflow failed: {e}")
            yield f"event: error\ndata: {json.dumps({'error': f'workflow build failed: {e}'}, ensure_ascii=False)}\n\n"
            yield "event: end\ndata: {}\n\n"
            return

        # 把 Supervisor 流的每个更新事件转 SSE；切换事件从 switch_buffer 拉
        config = {"configurable": {"thread_id": sid}}
        initial_messages = [{"role": "user", "content": request.message}]

        try:
            for chunk in stream_supervisor(
                workflow,
                initial_messages=initial_messages,
                config=config,
                stream_mode="updates",
            ):
                # 把切换帧刷出去（每个 step 最多一个 agent_switch）
                if switch_buffer:
                    for evt in switch_buffer:
                        try:
                            yield f"event: agent_switch\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
                        except Exception:
                            pass
                    switch_buffer.clear()
                # chunk 自身也转 SSE
                if isinstance(chunk, dict):
                    if chunk.get("type") == "error":
                        yield f"event: error\ndata: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    else:
                        yield f"event: update\ndata: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"supervisor stream failed: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        # 收尾（complete 帧让前端关闭流）
        try:
            yield "event: complete\ndata: {}\n\n"
        except Exception:
            pass
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.websocket("/api/chat/stream")
async def chat_stream_ws(websocket: WebSocket):
    """WebSocket 流式聊天（前端 initWS 用）"""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            sid = data.get("session_id")
            if not message:
                await websocket.send_json({"type": "error", "error": "Message is required"})
                continue

            proxy = get_proxy()
            if sid:
                try:
                    proxy.set_session(sid)
                except Exception:
                    pass
            else:
                try:
                    sid = get_agent().current_session_id
                except Exception:
                    sid = "default"

            try:
                chunks = proxy.run_stream(message, session_id=sid)
                if not isinstance(chunks, list):
                    if isinstance(chunks, dict):
                        chunks = [chunks]
                    else:
                        chunks = [{"type": "text", "data": str(chunks)}]
                for c in chunks:
                    if not isinstance(c, dict):
                        c = {"type": "text", "data": str(c)}
                    await websocket.send_json({
                        "type": c.get("type", "chunk"),
                        "data": c.get("data", c.get("content", "")),
                        "name": c.get("name"),
                        "session_id": sid,
                    })
                await websocket.send_json({"type": "complete", "session_id": sid})
            except Exception as e:
                await websocket.send_json({"type": "error", "error": str(e), "session_id": sid})
    except WebSocketDisconnect:
        pass


@app.post("/api/clear")
async def clear_history():
    proxy = get_proxy()
    try:
        result = proxy.clear_history()
        return {"success": True, "message": result}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ============================================================
# API Key / 模型管理
# ============================================================
@app.get("/api/api-key/status")
async def api_key_status():
    proxy = get_proxy()
    try:
        return proxy.get_api_key_status()
    except Exception as e:
        return {"configured": False, "provider": "openai", "error": str(e)}


@app.post("/api/api-key")
async def set_api_key(req: ApiKeyRequest):
    proxy = get_proxy()
    try:
        proxy.set_api_key(req.api_key.strip(), req.provider)
        status = proxy.get_api_key_status()
        msg = f"✅ {status['provider']} API Key 配置成功" if status.get("configured") else "API Key 已更新"
        return {"success": True, "message": msg, "configured": status.get("configured", False)}
    except Exception as e:
        return {"success": False, "message": f"❌ 配置失败: {e}", "configured": False}


@app.post("/api/model/switch")
async def switch_model(req: ModelSwitchRequest):
    proxy = get_proxy()
    try:
        ok = proxy.set_model(req.provider, req.model_name)
        status = proxy.get_api_key_status()
        if ok:
            return {
                "success": True,
                "message": f"✅ 已切换到 {status['provider']}/{status.get('model','')}",
                "provider": status["provider"],
                "model": status.get("model", ""),
            }
        return {
            "success": False,
            "message": "❌ 切换失败，请检查 API Key 是否配置",
            "provider": req.provider,
            "model": req.model_name or "",
        }
    except Exception as e:
        return {"success": False, "message": f"❌ 切换失败: {e}", "provider": req.provider, "model": req.model_name or ""}


@app.get("/api/models")
async def get_models():
    """返回模型清单。

    阶段 B（国内主流模型）新结构：
        {
            "providers": [{id, label, group, desc, configured, models}, ...],
            "models_by_provider": {...},   # 兼容旧字段
            "current_provider": "openai",
            "current_model": "gpt-4o-mini",
            "provider_meta": {...},
        }
    前端按 provider 分组渲染；未配置 Key 的选项在 UI 上灰显。
    """
    proxy = get_proxy()
    try:
        info = proxy.get_available_models()
        # 兼容：若 agent 还没 init，则 get_available_models 可能返回空；
        # 这时退到 MODEL_VERSIONS + 空 key map
        if not info.get("providers"):
            from config import MODEL_VERSIONS, PROVIDER_META
            info = {
                "providers": [
                    {
                        "id": pid,
                        "label": PROVIDER_META.get(pid, {}).get("label", pid),
                        "group": PROVIDER_META.get(pid, {}).get("group", "other"),
                        "desc": PROVIDER_META.get(pid, {}).get("desc", ""),
                        "configured": False,
                        "models": list(MODEL_VERSIONS.get(pid, [])),
                    }
                    for pid in MODEL_VERSIONS.keys()
                ],
                "models_by_provider": MODEL_VERSIONS,
                "current_provider": "openai",
                "current_model": "gpt-4o-mini",
                "provider_meta": PROVIDER_META,
            }
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Agents / Capabilities / Load
# ============================================================


# v2.1 — Agent Preset Pydantic 模型
class AgentPresetCreateRequest(BaseModel):
    name: str
    description: str = ""
    avatar: str = "🤖"
    system_prompt: str = ""
    temperature: float = 0.7
    tools: List[str] = []
    id: Optional[str] = None


class AgentPresetUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    avatar: Optional[str] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    tools: Optional[List[str]] = None


def _get_preset_store():
    from agent_config import get_preset_store
    return get_preset_store()


@app.get("/api/agents")
async def list_agents():
    """v2.1 — 同时返回 worker 列表 + 全部 preset（含 builtin）。
    旧前端只读 ``agents`` 字段，扩展时不再破坏兼容。
    """
    proxy = get_proxy()
    workers = proxy.list_workers()
    presets: List[Dict[str, Any]] = []
    try:
        from agent_config import get_preset_store
        store = get_preset_store()
        presets = [p.to_dict() for p in store.list()]
    except Exception as e:
        logger.debug(f"presets list failed: {e}")
    return {
        "agents": workers,
        "presets": presets,
        "count": len(workers) + len(presets),
    }


@app.get("/api/agents/presets")
async def list_presets():
    """v2.1 — 列出全部 Agent Preset（包含 builtin）。"""
    try:
        store = _get_preset_store()
        items = [p.to_dict() for p in store.list()]
        return {"presets": items, "count": len(items)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/agents/presets", status_code=201)
async def create_preset(req: AgentPresetCreateRequest):
    """v2.1 — 创建 Agent Preset。"""
    try:
        store = _get_preset_store()
        payload = {
            "name": req.name,
            "description": req.description,
            "avatar": req.avatar,
            "system_prompt": req.system_prompt,
            "temperature": req.temperature,
            "tools": list(req.tools or []),
        }
        if req.id:
            payload["id"] = req.id
        p = store.create(payload)
        return p.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/agents/presets/{preset_id}")
async def update_preset(preset_id: str, req: AgentPresetUpdateRequest):
    """v2.1 — 部分更新 Agent Preset。"""
    try:
        store = _get_preset_store()
        patch: Dict[str, Any] = {}
        if req.name is not None:
            patch["name"] = req.name
        if req.description is not None:
            patch["description"] = req.description
        if req.avatar is not None:
            patch["avatar"] = req.avatar
        if req.system_prompt is not None:
            patch["system_prompt"] = req.system_prompt
        if req.temperature is not None:
            patch["temperature"] = req.temperature
        if req.tools is not None:
            patch["tools"] = list(req.tools)
        p = store.update(preset_id, patch)
        return p.to_dict()
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/agents/presets/{preset_id}")
async def delete_preset(preset_id: str):
    """v2.1 — 删除 Agent Preset（builtin 不可删 → 403）。"""
    try:
        store = _get_preset_store()
        ok = store.delete(preset_id)
        if not ok:
            raise HTTPException(status_code=404, detail="preset not found")
        return {"deleted": preset_id}
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agents/tools/specs")
async def get_agents_tool_specs(names: str = ""):
    """v2.1 — 列出指定工具名的 OpenAI function-calling 风格 spec。

    用法：GET /api/agents/tools/specs?names=web_search,python_interpreter
    """
    try:
        from v21_tools import get_tool_specs, TOOL_REGISTRY

        name_list = [n.strip() for n in (names or "").split(",") if n.strip()]
        if not name_list:
            # 全部
            name_list = list(TOOL_REGISTRY.keys())
        specs = get_tool_specs(name_list)
        return {"tools": specs, "count": len(specs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/capabilities")
async def list_capabilities():
    proxy = get_proxy()
    return {"capabilities": proxy.list_capabilities(), "task_types": proxy.list_task_types()}


@app.get("/api/load_stats")
async def get_load_stats():
    proxy = get_proxy()
    return proxy.get_load_stats()


# ============================================================
# v2.2.2 — RAG / Local Chroma KB Endpoints
# ============================================================


class RAGIndexRequest(BaseModel):
    """v2.2.2 — /api/rag/index_file body 模型。"""
    file_id: str
    session_id: str
    file_name: Optional[str] = None
    upload_root: Optional[str] = None  # 测试 / 自定义根目录时使用


@app.post("/api/rag/index_file")
async def rag_index_file(req: RAGIndexRequest):
    """v2.2.2 — 索引一个已上传文件到当前 session 的 Chroma KB。

    流程：file_id 找磁盘文件 → parse_file 解析 → 切分 → upsert_chunks。
    """
    try:
        from rag_service import get_rag_service

        svc = get_rag_service()
        result = svc.index_file(
            session_id=req.session_id,
            file_id=req.file_id,
            file_name=req.file_name,
            upload_root=req.upload_root or str(_UPLOAD_ROOT),
        )
        if not result.get("success"):
            # 不抛 500（"no text extracted" 是正常业务结果），用 200 表达
            return {"success": False, **result}
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"rag_index_file failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/rag/files/{file_id}")
async def rag_delete_file(file_id: str, session_id: str):
    """v2.2.2 — 清理某 session 下指定 file_id 的所有向量切片。"""
    try:
        from rag_service import get_rag_service

        svc = get_rag_service()
        n = svc.delete_file(session_id=session_id, file_id=file_id)
        return {"success": True, "file_id": file_id, "deleted_chunks": n}
    except Exception as e:
        logger.error(f"rag_delete_file failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rag/files")
async def rag_list_files(session_id: str):
    """v2.2.2 — 列出某 session 已索引的文件（聚合到 file_id 维度）。"""
    try:
        from rag_service import get_rag_service

        svc = get_rag_service()
        files = svc.list_files(session_id=session_id)
        return {"success": True, "session_id": session_id, "files": files, "count": len(files)}
    except Exception as e:
        logger.error(f"rag_list_files failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rag/search")
async def rag_search(payload: Dict[str, Any]):
    """v2.2.2 — 内部 / 调试用：直接调 vector_store 做 session 内检索。

    body: {"session_id": "...", "query": "...", "top_k": 3, "min_score": 0.05}
    """
    try:
        sid = str(payload.get("session_id") or "")
        query = str(payload.get("query") or "")
        top_k = int(payload.get("top_k") or 3)
        min_score = float(payload.get("min_score") or 0.0)
        if not sid or not query:
            raise HTTPException(status_code=400, detail="session_id and query required")
        from rag_service import get_rag_service

        svc = get_rag_service()
        results = svc.search(
            session_id=sid, query=query, top_k=top_k, min_score=min_score
        )
        return {"success": True, "session_id": sid, "results": results, "count": len(results)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"rag_search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 权限
# ============================================================
@app.get("/api/policies")
async def list_policies():
    proxy = get_proxy()
    return {"policies": proxy.list_policies(), "stats": proxy.get_permission_stats()}


@app.post("/api/policy")
async def add_policy(req: PolicyRequest):
    proxy = get_proxy()
    return proxy.add_policy(
        agent_id=req.agent_id,
        roles=req.roles,
        capabilities=req.capabilities,
        allowed_targets=req.allowed_targets,
        allowed_tools=req.allowed_tools,
        allowed_workers=req.allowed_workers,
    )


@app.post("/api/permission/enforce")
async def permission_enforce(req: PermissionEnforceRequest):
    proxy = get_proxy()
    return proxy.enable_permission_enforcement(req.enforce)


# ============================================================
# HITL
# ============================================================
@app.get("/api/hitl/pending")
async def hitl_pending(hook_point: Optional[str] = None):
    proxy = get_proxy()
    pending = proxy.hitl_pending(hook_point=hook_point)
    return {"pending": pending, "count": len(pending)}


@app.get("/api/hitl/history")
async def hitl_history(hook_point: Optional[str] = None, limit: int = 50):
    proxy = get_proxy()
    history = proxy.hitl_history(hook_point=hook_point, limit=limit)
    return {"history": history, "count": len(history)}


@app.post("/api/hitl/decide")
async def hitl_decide(req: HITLDecision):
    proxy = get_proxy()
    ok = proxy.hitl_decide(
        request_id=req.request_id,
        status=req.status,
        decided_by=req.decided_by,
        decision_payload=req.decision_payload,
        notes=req.notes,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="request not found")
    return {"success": True, "request_id": req.request_id}


@app.get("/api/hitl/stats")
async def hitl_stats():
    proxy = get_proxy()
    return proxy.hitl_stats()


@app.post("/api/hitl/policy")
async def hitl_policy(hook_point: str, policy: str):
    proxy = get_proxy()
    return proxy.set_hitl_policy(hook_point, policy)


# ============================================================
# v2.2.1 — HITL v2 协议 / Checkpoint 历史 / Time-Travel
# ============================================================


@app.get("/api/hitl/v2/pending")
async def hitl_v2_pending(session_id: str):
    """v2.2.1 — 列出某 session 的待审批（来自 hitl_langgraph.HITLStore）。

    返回结构：
      {
        "pending": [PendingApproval, ...],
        "count": int,
        "session_id": str,
      }
    """
    try:
        from hitl_langgraph import HITLStore

        items = HITLStore.instance().list_pending(session_id=session_id)
        return {
            "pending": [p.to_dict() for p in items],
            "count": len(items),
            "session_id": session_id,
        }
    except Exception as e:
        logger.error(f"hitl_v2_pending failed: {e}")
        return {
            "pending": [],
            "count": 0,
            "session_id": session_id,
            "error": str(e),
        }


@app.post("/api/chat/approve")
async def chat_approve(req: HITLChatDecision):
    """v2.2.1 — 批准一条高风险工具调用。

    行为：
      - 在 HITLStore 中把对应 request_id 标记为 approved，并把 tool_args 写入 decision_payload
      - 不存在 → 404
      - 已经被 resolved（approved / rejected）→ 409
      - session_id 与 pending 不一致 → 404
      - v2.2.1 — 支持 edited_args（Edit & Resume）：若提供 edited_args 则用其覆盖原 tool_args，
        并在 store 中标记 edited=True
    """
    try:
        from hitl_langgraph import HITLStore

        store = HITLStore.instance()
        existing = store.get(req.request_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="request not found")
        if existing.session_id != req.session_id:
            raise HTTPException(status_code=404, detail="session mismatch")
        if existing.status in ("approved", "rejected"):
            raise HTTPException(
                status_code=409,
                detail=f"request already {existing.status}",
            )
        # v2.2.1 — edited_args 优先于 tool_args
        effective_args: Optional[Dict[str, Any]] = (
            req.edited_args
            if req.edited_args is not None
            else req.tool_args
        )
        updated = store.approve(req.request_id, tool_args=effective_args)
        if updated is None:
            raise HTTPException(status_code=404, detail="approve failed")
        # v2.3.1 — Observability: 关闭挂起的 HITL Span
        try:
            from observability.hitl_span import resume_hitl_span

            resume_hitl_span(
                req.request_id,
                "approved",
                tool_name=updated.tool_name,
                extra_attrs={"hitl.edited": bool(updated.edited)},
            )
        except Exception:
            pass
        return {
            "success": True,
            "request_id": updated.request_id,
            "decision": "approved",
            "tool_args": updated.decision_payload or {},
            "tool_name": updated.tool_name,
            "session_id": updated.session_id,
            "edited": bool(updated.edited),
            # P1-5：前端拿到后 GET 这个 SSE 端点订阅续生成流
            "resume_url": f"/api/chat/{updated.request_id}/resume",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"chat_approve failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/reject")
async def chat_reject(req: HITLChatDecision):
    """v2.2.1 — 拒绝一条高风险工具调用。

    行为：
      - 写入 reject_reason（默认 "Action cancelled by user"）
      - 不存在 / 已被 resolved → 4xx
    """
    try:
        from hitl_langgraph import HITLStore

        store = HITLStore.instance()
        existing = store.get(req.request_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="request not found")
        if existing.session_id != req.session_id:
            raise HTTPException(status_code=404, detail="session mismatch")
        if existing.status in ("approved", "rejected"):
            raise HTTPException(
                status_code=409,
                detail=f"request already {existing.status}",
            )
        reason = (req.reason or "").strip() or "Action cancelled by user"
        updated = store.reject(req.request_id, reason=reason)
        if updated is None:
            raise HTTPException(status_code=404, detail="reject failed")
        # v2.3.1 — Observability: 关闭挂起的 HITL Span
        try:
            from observability.hitl_span import resume_hitl_span

            resume_hitl_span(
                req.request_id,
                "rejected",
                tool_name=updated.tool_name,
                extra_attrs={"hitl.reject_reason": reason[:80]},
            )
        except Exception:
            pass
        return {
            "success": True,
            "request_id": updated.request_id,
            "decision": "rejected",
            "reason": updated.reject_reason or reason,
            "tool_name": updated.tool_name,
            "session_id": updated.session_id,
            # P1-5：前端拿到后 GET 这个 SSE 端点订阅续生成流
            "resume_url": f"/api/chat/{updated.request_id}/resume",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"chat_reject failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chat/{request_id}/resume")
async def chat_resume(request_id: str, session_id: str):
    """P1-5 — HITL 拒绝/批准后恢复生成（SSE 端点）。

    流程：
      1) 用 session_id + request_id 调 hitl_resume.resume_after_decision
      2) 它会从 HITLStore 取决策：
         - approved → 实际执行工具 + 注入 ToolMessage(result) + agent.invoke 续生成
         - rejected → 注入 ToolMessage(reason) + agent.invoke 续生成
      3) 把续生成 dict 事件序列化为 SSE 流（与 /api/chat/stream 同一协议）
      4) 用户 abort（client disconnect）→ asyncio.CancelledError 静默退出

    错误码：
      - 404 request not found
      - 400 决策仍 pending（用户还没点完）
      - 503 agent/checkpointer 未初始化
    """
    # session_id 必须从 query 取（FastAPI Path 与 Query 同时需要）
    from fastapi import Request as _Req  # type: ignore

    # —— 参数与决策校验 ——
    if not request_id or not session_id:
        raise HTTPException(status_code=400, detail="request_id and session_id required")

    # 提前确认决策（避免后面 stream 中段才发现）
    try:
        from hitl_langgraph import resolve_after_decision
        decision = resolve_after_decision(request_id, session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"resolve_after_decision failed: {e}")
    if decision is None:
        raise HTTPException(status_code=404, detail="request not found / session mismatch")
    if decision.get("decision") == "pending":
        raise HTTPException(status_code=400, detail="decision still pending")

    agent = _agent_instance
    if agent is None:
        raise HTTPException(status_code=503, detail="agent not initialized")

    # —— 流式生成 ——
    async def event_gen():
        # P1-2 风格的 start 帧
        start_payload = {
            "type": "start",
            "data": "",
            "phase": "hitl_resume",
            "decision": decision.get("decision"),
            "tool_name": decision.get("tool_name"),
            "tool_call_id": decision.get("tool_call_id"),
        }
        try:
            yield f"event: start\ndata: {json.dumps(start_payload, ensure_ascii=False)}\n\n"
        except Exception:
            pass

        saw_terminal = False
        try:
            from hitl_resume import resume_after_decision
            agen = await resume_after_decision(
                request_id=request_id,
                session_id=session_id,
                agent=agent,
            )
            if agen is None:
                yield (
                    "event: error\n"
                    f"data: {json.dumps({'error': 'resume_after_decision returned None', 'retryable': False, 'phase': 'hitl_resume'}, ensure_ascii=False)}\n\n"
                )
            else:
                async for ev in agen:
                    if not isinstance(ev, dict):
                        ev = {"type": "text", "data": str(ev)}
                    event_type = ev.get("type", "chunk")
                    if event_type in ("complete", "message_end"):
                        saw_terminal = True
                    yield f"event: {event_type}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            # 用户 abort
            return
        except Exception as e:
            err_msg = str(e)
            yield (
                "event: error\n"
                f"data: {json.dumps({'error': err_msg, 'retryable': False, 'phase': 'hitl_resume'}, ensure_ascii=False)}\n\n"
            )
        else:
            if not saw_terminal:
                yield (
                    "event: error\n"
                    f"data: {json.dumps({'error': 'HITL resume stream ended without terminal event', 'retryable': True, 'phase': 'hitl_resume_silent_close'}, ensure_ascii=False)}\n\n"
                )
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _list_checkpoints_for_session(session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """v2.2.1 — 内部辅助：从当前 AIAgent 的 checkpointer 列出 checkpoints。

    兼容：agent 未初始化 / checkpointer 不可用 → 返回空列表 + note。
    """
    out: List[Dict[str, Any]] = []
    note: Optional[str] = None
    try:
        agent = _agent_instance
        if agent is None or getattr(agent, "checkpointer", None) is None:
            note = "agent not initialized"
            return out
        saver = agent.checkpointer
        cfg = {"configurable": {"thread_id": session_id}}
        try:
            for ck in saver.list(cfg):
                ckpt = getattr(ck, "checkpoint", None) or {}
                meta = getattr(ck, "metadata", None) or {}
                cid = (
                    ckpt.get("id")
                    if isinstance(ckpt, dict)
                    else getattr(ckpt, "id", None)
                )
                step = (
                    ckpt.get("step")
                    if isinstance(ckpt, dict)
                    else getattr(ckpt, "step", None)
                )
                ts = (
                    ckpt.get("ts")
                    if isinstance(ckpt, dict)
                    else getattr(ckpt, "ts", None)
                )
                out.append(
                    {
                        "thread_id": session_id,
                        "checkpoint_id": str(cid) if cid else "",
                        "step": int(step) if step is not None else 0,
                        "ts": ts,
                        "next_node": (
                            meta.get("next") if isinstance(meta, dict) else None
                        ),
                        "metadata": meta if isinstance(meta, dict) else {},
                    }
                )
                if len(out) >= limit:
                    break
        except Exception as e:
            note = f"saver.list failed: {e}"
    except Exception as e:
        note = f"checkpoint read failed: {e}"
    out.append({"__note__": note} if note else {})
    return out


@app.get("/api/checkpoints/list")
async def checkpoints_list(session_id: str, limit: int = 50):
    """v2.2.1 — 列出某 session 的 checkpoints（Time-Travel 基础）。"""
    try:
        raw = _list_checkpoints_for_session(session_id, limit=limit)
    except Exception as e:
        logger.error(f"checkpoints_list failed: {e}")
        return {
            "checkpoints": [],
            "count": 0,
            "session_id": session_id,
            "note": "agent not initialized" if _agent_instance is None else f"error: {e}",
        }
    note: Optional[str] = None
    items: List[Dict[str, Any]] = []
    for r in raw:
        if "__note__" in r:
            note = r["__note__"]
            continue
        items.append(r)
    # 始终包含 note 字段（agent 未初始化时 = "agent not initialized"）
    if note is None and not items:
        note = "agent not initialized"
    return {
        "checkpoints": items,
        "count": len(items),
        "session_id": session_id,
        "note": note or "",
    }


@app.get("/api/checkpoints/get")
async def checkpoints_get(
    session_id: str = "", checkpoint_id: str = ""
):
    """v2.2.1 — 拉取单个 checkpoint 的完整 state。

    兼容：当 agent 未初始化 / 缺参数时返回 503（避免 422 校验错）。
    """
    if not session_id or not checkpoint_id:
        # 缺参数时返回 503（与 agent 未初始化同等待遇），避免 422 校验错
        raise HTTPException(
            status_code=503, detail="agent not initialized or missing parameter"
        )
    try:
        agent = _agent_instance
        if agent is None or getattr(agent, "checkpointer", None) is None:
            raise HTTPException(
                status_code=503, detail="agent not initialized"
            )
        saver = agent.checkpointer
        cfg = {"configurable": {"thread_id": session_id}}
        target = None
        try:
            for ck in saver.list(cfg):
                ckpt = getattr(ck, "checkpoint", None) or {}
                cid = (
                    ckpt.get("id")
                    if isinstance(ckpt, dict)
                    else getattr(ckpt, "id", None)
                )
                if str(cid) == str(checkpoint_id):
                    target = ck
                    break
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"saver.list failed: {e}")
        if target is None:
            raise HTTPException(
                status_code=404,
                detail=f"checkpoint {checkpoint_id} not found in session {session_id}",
            )
        ckpt = getattr(target, "checkpoint", None) or {}
        meta = getattr(target, "metadata", None) or {}
        config = getattr(target, "config", None) or {}
        return {
            "thread_id": session_id,
            "checkpoint_id": str(checkpoint_id),
            "step": (
                ckpt.get("step")
                if isinstance(ckpt, dict)
                else getattr(ckpt, "step", 0)
            ),
            "values": ckpt.get("channel_values", {})
            if isinstance(ckpt, dict)
            else getattr(ckpt, "channel_values", {}),
            "next": (
                ckpt.get("next")
                if isinstance(ckpt, dict)
                else getattr(ckpt, "next", [])
            ),
            "config": config,
            "metadata": meta,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"checkpoints_get failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 计划
# ============================================================
@app.post("/api/plan/create")
async def plan_create(req: PlanRequest):
    proxy = get_proxy()
    return proxy.create_plan(req.goal, session_id=req.session_id)


@app.post("/api/plan/research")
async def plan_research(req: PlanRequest):
    proxy = get_proxy()
    return proxy.create_research_plan(req.goal)


@app.post("/api/plan/code")
async def plan_code(req: PlanRequest):
    proxy = get_proxy()
    return proxy.create_code_plan(req.goal)


@app.post("/api/plan/run")
async def plan_run(req: PlanRequest):
    proxy = get_proxy()
    return proxy.run_plan(req.goal, session_id=req.session_id)


# ============================================================
# 记忆
# ============================================================
@app.post("/api/memory/remember")
async def memory_remember(req: RememberRequest):
    proxy = get_proxy()
    return proxy.remember(
        key=req.key,
        value=req.value,
        memory_type=req.memory_type,
        scope=req.scope,
        importance=req.importance,
        expires_in_seconds=req.expires_in_seconds,
        tags=req.tags,
    )


@app.get("/api/memory/recall")
async def memory_recall(key: str, scope: str = "global"):
    proxy = get_proxy()
    return proxy.recall(key, scope=scope)


@app.get("/api/memory/search")
async def memory_search(
    keyword: Optional[str] = None,
    scope: Optional[str] = None,
    memory_type: Optional[str] = None,
    limit: int = 20,
):
    proxy = get_proxy()
    return proxy.search_memory(keyword=keyword, scope=scope, memory_type=memory_type, limit=limit)


@app.delete("/api/memory/forget")
async def memory_forget(key: str, scope: str = "global"):
    proxy = get_proxy()
    return {"deleted": proxy.forget(key, scope=scope)}


@app.post("/api/memory/save")
async def memory_save(path: str = "memory.json"):
    proxy = get_proxy()
    return proxy.save_memory(path)


@app.post("/api/memory/load")
async def memory_load(path: str = "memory.json"):
    proxy = get_proxy()
    return proxy.load_memory(path)


@app.get("/api/memory/stats")
async def memory_stats():
    proxy = get_proxy()
    return proxy.get_memory_stats()


# ============================================================
# 极简 Memory API（用户级对话式记忆）
# 设计要点：用户只需输入一行文本，后端自动补齐 key/value/scope。
# 内部存储走 UnifiedMemoryStore（global scope），前端无需关心细节。
# ============================================================

class _MemoryAddRequest(BaseModel):
    content: str


@app.post("/api/memory/add")
async def memory_add(req: _MemoryAddRequest):
    """添加一条对话式记忆（用户只需输入 content，scope 固定为 global）。"""
    content = (req.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content 不能为空")
    if len(content) > 2000:
        raise HTTPException(status_code=400, detail="content 不能超过 2000 字")

    proxy = get_proxy()
    # 内部走 remember：把整行文本当 value，key 自动用首句（≤32 字）
    first_line = content.splitlines()[0].strip()
    auto_key = first_line[:32] + ("…" if len(first_line) > 32 else "")
    return proxy.remember(
        key=auto_key or "note",
        value=content,
        memory_type="fact",
        scope="global",
        importance=0.6,
    )


@app.get("/api/memory/list")
async def memory_list(limit: int = 100):
    """列出全部对话式记忆（按时间倒序）。"""
    proxy = get_proxy()
    items = proxy.search_memory(keyword=None, scope=None, memory_type=None, limit=limit)
    # search_memory 按相关性排，这里改为按 id 倒序
    items.sort(key=lambda x: x.get("id") or 0, reverse=True)
    return {"items": items, "total": len(items)}


@app.delete("/api/memory/{memory_id}")
async def memory_delete_one(memory_id: int):
    """删除单条记忆。"""
    try:
        from memory_store import get_memory_store
        store = get_memory_store()
        with store.db._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            deleted = cur.rowcount
        return {"ok": deleted > 0, "id": memory_id, "deleted": deleted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Prompt 模板（阶段 A2）
# ============================================================
@app.get("/api/prompts")
async def list_prompts():
    """列出所有 prompt 模板与版本（前端设置面板用）。"""
    from prompt_registry import get_prompt_registry
    reg = get_prompt_registry()
    return {"templates": reg.list_templates()}


class PromptRollbackRequest(BaseModel):
    name: str = "default"
    version: str


@app.post("/api/prompts/rollback")
async def rollback_prompt(req: PromptRollbackRequest):
    """把指定模板切回历史版本（不重新 init agent，仅切换下一次构建的 system_prompt）。"""
    from prompt_registry import get_prompt_registry
    reg = get_prompt_registry()
    ok = reg.rollback(req.name, req.version)
    if not ok:
        raise HTTPException(status_code=404, detail="unknown template or version")
    # 让 agent 下次 build system prompt 时使用新版本
    try:
        proxy = get_proxy()
        if hasattr(proxy, "_agent") and proxy._agent is not None:
            proxy._agent._system_prompt = None  # 强制下次 init_agent 重建
    except Exception:
        pass
    return {"ok": True, "name": req.name, "version": req.version}


# ============================================================
# User Prompt 模板（阶段 B）
# ============================================================
@app.get("/api/user-prompts")
async def list_user_prompts():
    """列出所有 user prompt 模板与版本（前端设置面板用）。"""
    from user_prompt_registry import get_user_prompt_registry
    reg = get_user_prompt_registry()
    return {"templates": reg.list_templates()}


class UserPromptRollbackRequest(BaseModel):
    name: str = "default"
    version: str


@app.post("/api/user-prompts/rollback")
async def rollback_user_prompt(req: UserPromptRollbackRequest):
    """把指定 user prompt 模板切回历史版本（影响下一次 send 的 user input）。"""
    from user_prompt_registry import get_user_prompt_registry
    reg = get_user_prompt_registry()
    ok = reg.rollback(req.name, req.version)
    if not ok:
        raise HTTPException(status_code=404, detail="unknown template or version")
    return {"ok": True, "name": req.name, "version": req.version}


class UserPromptRegisterRequest(BaseModel):
    """注册/更新一个 user prompt 模板版本。"""

    name: str = "default"
    version: str
    author: Optional[str] = "user"
    changelog: Optional[str] = ""
    structure: Optional[str] = "system_first"
    intro_template: Optional[str] = ""
    few_shots: Optional[List[Dict[str, str]]] = None
    context_injection: Optional[str] = "before_user"
    security_rewrite: Optional[Dict[str, Any]] = None
    variables: Optional[List[str]] = None


@app.post("/api/user-prompts/register")
async def register_user_prompt(req: UserPromptRegisterRequest):
    """注册/更新一个 user prompt 模板版本（落盘）。"""
    from user_prompt_registry import (
        UserPromptTemplate,
        SecurityRewritePolicy,
        FewShotExample,
        get_user_prompt_registry,
    )

    sec = SecurityRewritePolicy.from_dict(req.security_rewrite or {})
    fs = [FewShotExample.from_dict(x) for x in (req.few_shots or [])]
    tpl = UserPromptTemplate(
        name=req.name,
        version=req.version,
        author=req.author or "user",
        changelog=req.changelog or "",
        structure=req.structure or "system_first",
        intro_template=req.intro_template or "",
        few_shots=fs,
        context_injection=req.context_injection or "before_user",
        security_rewrite=sec,
        variables=list(req.variables or []),
    )
    reg = get_user_prompt_registry()
    reg.register(tpl)
    return {"ok": True, "template": tpl.to_dict()}


class UserPromptRenderRequest(BaseModel):
    name: str = "default"
    user_input: str = ""
    context: Optional[str] = None
    variables: Optional[Dict[str, Any]] = None


@app.post("/api/user-prompts/render")
async def render_user_prompt(req: UserPromptRenderRequest):
    """预览渲染一个 user prompt 模板（不调用 LLM）。"""
    from user_prompt_registry import get_user_prompt_registry
    reg = get_user_prompt_registry()
    try:
        out = reg.render(
            name=req.name,
            user_input=req.user_input,
            context=req.context,
            variables=req.variables,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    active = reg.get_active_template(req.name)
    return {
        "ok": True,
        "rendered": out,
        "active_version": active.version if active else None,
    }


@app.get("/api/user-prompts/export")
async def export_user_prompts():
    """导出所有 user prompt 模板（含激活状态）—— 备份/迁移用。"""
    from user_prompt_registry import get_user_prompt_registry
    reg = get_user_prompt_registry()
    payload = reg.export_json()
    return payload


@app.post("/api/user-prompts/import")
async def import_user_prompts(payload: Dict[str, Any]):
    """导入 user prompt 模板（来自 export 的同形状字典）。"""
    from user_prompt_registry import get_user_prompt_registry
    reg = get_user_prompt_registry()
    count = reg.import_json(payload)
    return {"ok": True, "imported": count}


# ============================================================
# 观测
# ============================================================
@app.get("/api/events")
async def list_events(limit: int = 50, event_type: Optional[str] = None):
    proxy = get_proxy()
    events = proxy.list_recent_events(event_type=event_type, limit=limit)
    return {"events": events, "count": len(events)}


@app.get("/api/traces")
async def list_traces(limit: int = 30):
    proxy = get_proxy()
    traces = proxy.get_recent_traces(limit=limit)
    return {"traces": traces, "count": len(traces)}


@app.get("/api/metrics/prometheus")
async def prometheus_metrics():
    proxy = get_proxy()
    text = proxy.get_prometheus_metrics()
    return Response(content=text, media_type="text/plain; version=0.0.4")


# ============================================================
# 上传
# ============================================================
def _safe_filename(name: str) -> str:
    name = (name or "file").strip().replace("\\", "/").split("/")[-1]
    name = _UPLOAD_NAME_RE.sub("_", name) or "file"
    return name[:120]


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    content_type = (file.content_type or "").lower()
    contents = await file.read()
    size = len(contents)
    if size == 0:
        raise HTTPException(status_code=400, detail="empty file")
    if size > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"file too large (max {_MAX_FILE_SIZE // 1024 // 1024}MB)")
    if content_type and content_type not in _ALLOWED_TYPES:
        logger.warning(f"upload with uncommon content-type={content_type} name={file.filename}")

    ext = ""
    if file.filename and "." in file.filename:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower()[:8]
    safe = _safe_filename(file.filename or "file")
    unique = f"{int(time.time() * 1000)}_{secrets.token_hex(6)}{ext}"
    final_name = f"{unique}_{safe}"
    (_UPLOAD_ROOT / final_name).write_bytes(contents)

    return {
        "id": unique,
        "name": file.filename or safe,
        "safe_name": final_name,
        "content_type": content_type or "application/octet-stream",
        "size": size,
        "url": f"/uploads/{final_name}",
    }


@app.get("/api/files/{name}")
async def serve_upload(name: str):
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="invalid name")
    p = _UPLOAD_ROOT / name
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="not found")
    mt = "application/octet-stream"
    if name.lower().endswith(".png"):
        mt = "image/png"
    elif name.lower().endswith((".jpg", ".jpeg")):
        mt = "image/jpeg"
    elif name.lower().endswith(".gif"):
        mt = "image/gif"
    elif name.lower().endswith(".webp"):
        mt = "image/webp"
    elif name.lower().endswith(".pdf"):
        mt = "application/pdf"
    elif name.lower().endswith((".txt", ".md")):
        mt = "text/plain; charset=utf-8"
    return FileResponse(str(p), media_type=mt)


@app.post("/api/files/upload")
async def upload_file(file: "UploadFile" = File(...)):
    """v2.1 — 接收 multipart 上传，落到 _UPLOAD_ROOT 并自动 parse。

    返回结构：
      {
        file_id: str,           — 上传后的文件名（uuid + 原后缀）
        file_name: str,         — 原始文件名
        file_type: str,         — 后缀
        size: int,
        parsed: {kind, text, markdown, meta}
      }
    """
    try:
        from fastapi import UploadFile
        from file_parser import parse_file, ParsedFile

        # 1) 落盘
        raw = await file.read()
        ext = ""
        if file.filename and "." in file.filename:
            ext = "." + file.filename.rsplit(".", 1)[-1].lower()
        file_id = f"{uuid.uuid4().hex[:16]}{ext}"
        dest = _UPLOAD_ROOT / file_id
        dest.write_bytes(raw)
        # 2) parse
        parsed: ParsedFile = parse_file(str(dest), filename=file.filename or file_id)
        # 3) 响应
        return {
            "file_id": file_id,
            "file_name": file.filename or file_id,
            "file_type": ext.lstrip(".") or "bin",
            "size": len(raw),
            "parsed": {
                "kind": parsed.kind,
                "text": parsed.text,
                "markdown": parsed.markdown,
                "meta": parsed.meta or {},
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"upload failed: {e}")


# ============================================================
# 上下文管理
# ============================================================
@app.get("/api/context/sessions")
async def list_sessions(status: Optional[str] = None, limit: int = 20):
    proxy = get_proxy()
    sessions = proxy.list_all_sessions(status=status, limit=limit)
    # 容错：proxy 可能返回 dict（agent not initialized 错误响应）
    if isinstance(sessions, dict):
        return sessions
    if not isinstance(sessions, list):
        return {"sessions": []}
    out = []
    for s in sessions:
        if isinstance(s, str):
            out.append({"id": s})
        elif hasattr(s, "__dict__"):
            out.append(s.__dict__)
        elif isinstance(s, dict):
            out.append(s)
        else:
            out.append({"value": str(s)})
    return {"sessions": out}


@app.post("/api/context/sessions")
async def create_session():
    proxy = get_proxy()
    sid = proxy.create_new_session()
    return {"session_id": sid, "message": "✅ 新会话已创建"}


@app.get("/api/context/sessions/{session_id}")
async def get_session(session_id: str):
    proxy = get_proxy()
    proxy.set_session(session_id)
    return proxy.get_session_analytics()


@app.get("/api/context/sessions/{session_id}/summary")
async def get_session_summary(session_id: str):
    proxy = get_proxy()
    proxy.set_session(session_id)
    summary = proxy.get_context_summary()
    if summary:
        return {
            "session_id": session_id,
            "topic": getattr(summary, "topic", None),
            "keywords": getattr(summary, "keywords", []),
            "key_entities": getattr(summary, "key_entities", []),
            "summary_content": getattr(summary, "summary_content", None),
            "created_at": summary.created_at.isoformat() if getattr(summary, "created_at", None) else None,
        }
    return {"session_id": session_id, "summary": None}


@app.get("/api/context/sessions/{session_id}/entities")
async def get_session_entities(session_id: str, entity_type: Optional[str] = None):
    proxy = get_proxy()
    proxy.set_session(session_id)
    entities = proxy.get_entities(entity_type=entity_type)
    return {
        "session_id": session_id,
        "entities": [
            {
                "id": getattr(e, "id", None),
                "type": getattr(e, "entity_type", None),
                "name": getattr(e, "entity_name", None),
                "value": getattr(e, "entity_value", None),
                "mention_count": getattr(e, "mention_count", 0),
                "is_active": getattr(e, "is_active", False),
            }
            for e in entities
        ],
    }


@app.get("/api/context/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, limit: int = 50):
    proxy = get_proxy()
    proxy.set_session(session_id)
    agent = get_agent()
    if agent is None:
        return {"session_id": session_id, "messages": []}
    try:
        messages = agent.context_manager.get_messages(session_id, limit=limit)
        return {
            "session_id": session_id,
            "messages": [
                {
                    "id": getattr(m, "id", None),
                    "role": getattr(m, "role", None),
                    "content": getattr(m, "content", None),
                    "content_type": getattr(m, "content_type", None),
                    "created_at": m.created_at.isoformat() if getattr(m, "created_at", None) else None,
                }
                for m in messages
            ],
        }
    except Exception as e:
        return {"session_id": session_id, "messages": [], "error": str(e)}


@app.get("/api/context/analytics")
async def get_current_session_analytics():
    proxy = get_proxy()
    return proxy.get_session_analytics()


@app.get("/api/context/search")
async def search_sessions(query: str, limit: int = 20):
    proxy = get_proxy()
    sessions = proxy.list_all_sessions(status="completed", limit=100)
    results = []
    for s in sessions:
        if query.lower() in str(s.__dict__).lower():
            results.append(s)
            if len(results) >= limit:
                break
    return {
        "query": query,
        "results": [
            {
                "session_id": getattr(s, "id", None),
                "user_id": getattr(s, "user_id", None),
                "created_at": s.created_at.isoformat() if getattr(s, "created_at", None) else None,
                "message_count": getattr(s, "message_count", 0),
            }
            for s in results
        ],
    }


@app.get("/api/context/stats")
async def get_stats():
    agent = get_agent()
    if agent is None:
        return {
            "total_sessions": 0,
            "total_messages": 0,
            "total_entities": 0,
            "total_tool_calls": 0,
            "total_summaries": 0,
        }
    try:
        db = agent.context_manager.session_repo.db
        with db.get_cursor() as cursor:
            stats = {}
            for sql, key in [
                ("SELECT COUNT(*) FROM sessions", "total_sessions"),
                ("SELECT COUNT(*) FROM messages", "total_messages"),
                ("SELECT COUNT(*) FROM entities", "total_entities"),
                ("SELECT COUNT(*) FROM tool_calls", "total_tool_calls"),
                ("SELECT COUNT(*) FROM summaries", "total_summaries"),
            ]:
                try:
                    cursor.execute(sql)
                    stats[key] = cursor.fetchone()[0]
                except Exception:
                    stats[key] = 0
        return stats
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/context/performance")
async def get_performance_stats():
    from monitor import get_monitor
    return get_monitor().get_stats()


@app.post("/api/context/performance/reset")
async def reset_performance_stats():
    from monitor import get_monitor
    get_monitor().reset()
    return {"message": "Performance stats reset"}


# ============================================================
# 启动
# ============================================================
def run(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn

    try:
        get_proxy()
        logger.info("Proxy initialized")
    except Exception as e:
        logger.warning(f"Proxy init warning: {e}")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    run(port=port)