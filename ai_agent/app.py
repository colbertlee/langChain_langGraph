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

# Day 8-9：统一 schema 层（见 schemas.py）
import schemas as schemas  # noqa: E402
from schemas import (  # noqa: E402
    ChatRequest as _ChatRequest,
    ApiKeyRequest as _ApiKeyRequest,
    ModelSwitchRequest as _ModelSwitchRequest,
    ChatResponse,
    ClearResponse,
    ApiKeyStatusResponse,
    ModelSwitchResponse,
    ModelsResponse,
    MemoryAddRequest as _MemoryAddRequest,
    HealthResponse,
    DoctorResponse,        # Day 15
    EvalsRunRequest as _EvalsRunRequest,
    EvalsRunResponse,
    EvalsHistoryResponse,
)

logger = logging.getLogger("app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


# ============================================================
# 路径与目录
# ============================================================
_HERE = Path(__file__).resolve().parent
_WEB_DIR = _HERE / "web"
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

    def run_stream(self, user_input: str, session_id: Optional[str] = None):
        """同步收集流式 chunk，返回 dict 列表（与前端 SSE 协议兼容）"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    chunks = pool.submit(asyncio.run, self._collect(user_input, session_id)).result()
            else:
                chunks = loop.run_until_complete(self._collect(user_input, session_id))
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
        try:
            from message_bus import get_message_bus
            bus = get_message_bus()
            bus.enable_permission(self._permission_guard, enforce=enforce)
        except Exception as e:
            logger.warning(f"enable_permission_enforcement bus wire failed: {e}")
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    # Day 8-9：re-export 自 schemas.py（保留旧模型名以兼容现有 import）
    """``POST /api/chat`` 请求体 schema。完整定义见 ``schemas.ChatRequest``。"""
    pass  # 仅作为 re-export 锚点


# 直接 alias 到 schemas，避免破坏现有 endpoint 代码
ChatRequest = _ChatRequest


class ApiKeyRequest(BaseModel):
    """``POST /api/api-key`` 请求体 schema。完整定义见 ``schemas.ApiKeyRequest``。"""
    pass


ApiKeyRequest = _ApiKeyRequest


class ModelSwitchRequest(BaseModel):
    """``POST /api/model/switch`` 请求体 schema。完整定义见 ``schemas.ModelSwitchRequest``。"""
    pass


ModelSwitchRequest = _ModelSwitchRequest


# Day 15：剩余本地 model 全部 re-export 自 schemas.py
# （保留旧类名以兼容现有 endpoint 代码）
HITLDecision = schemas.HITLDecision  # type: ignore[assignment]
PolicyRequest = schemas.PolicyRequest  # type: ignore[assignment]
PermissionEnforceRequest = schemas.PermissionEnforceRequest  # type: ignore[assignment]
PlanRequest = schemas.PlanRequest  # type: ignore[assignment]


# 把 legacy ``RememberRequest`` 映射到 ``MemoryRememberRequest``（兼容老 endpoint）
RememberRequest = schemas.MemoryRememberRequest  # type: ignore[assignment] # noqa: F811


# ============================================================
# 基础端点
# ============================================================
@app.get("/")
async def root():
    idx = _WEB_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return {"message": "AI Agent API", "version": "2.1"}


@app.get("/dashboard")
async def dashboard():
    p = _WEB_DIR / "dashboard.html"
    if p.exists():
        return FileResponse(str(p))
    raise HTTPException(status_code=404, detail="dashboard.html not found")


@app.get("/legacy")
async def legacy():
    p = _WEB_DIR / "index.html"
    if p.exists():
        return FileResponse(str(p))
    raise HTTPException(status_code=404, detail="legacy not found")


@app.get("/web/doctor")
async def web_doctor_page(
    request: Request,
    json: Optional[str] = None,
    fmt: Optional[str] = None,
):
    """前端 Doctor 页面（Day 15）。也支持 ``?json=1`` / ``?fmt=json`` / Accept 头。

    详见 ``/diagnose`` 的同款切换逻辑。
    """
    wants_json = False
    if fmt is not None:
        wants_json = fmt.lower() == "json"
    elif json is not None and str(json).lower() in {"1", "true", "yes"}:
        wants_json = True
    else:
        accept = request.headers.get("accept", "")
        if "application/json" in accept.lower() and "text/html" not in accept.lower():
            wants_json = True

    if wants_json:
        from doctor import run_doctor
        checks = run_doctor()
        items = [c.to_dict() for c in checks]
        summary = {
            "ok": sum(1 for c in checks if c.status == "ok"),
            "warn": sum(1 for c in checks if c.status == "warn"),
            "fail": sum(1 for c in checks if c.status == "fail"),
        }
        return {
            "exit_code": 1 if summary["fail"] else 0,
            "checks": items,
            "summary": summary,
            "source": "web_doctor_endpoint",
        }

    p = _WEB_DIR / "doctor.html"
    if p.exists():
        return FileResponse(str(p))
    raise HTTPException(status_code=404, detail="doctor.html not found")


@app.get("/web/doctor/index")
async def web_doctor_shortcut():
    """Doctor 页面别名，便于记忆。"""
    return await web_doctor_page()


@app.get("/diagnose")
async def web_diagnose(
    request: Request,
    json: Optional[str] = None,
    fmt: Optional[str] = None,
):
    """智能切换：page / JSON，看 query 与 Accept 头。

    优先级（高 → 低）：
    1. 显式 ``fmt=json|page`` 强制
    2. ``json=1``（兼容旧形式，等价 ``fmt=json``）
    3. ``Accept`` 头含 ``application/json`` → JSON
    4. 默认：HTML 页面

    示例::

        GET /diagnose              → HTML
        GET /diagnose?json=1       → JSON
        GET /diagnose?fmt=json     → JSON
        GET /diagnose?fmt=page     → HTML
        Accept: application/json + GET /diagnose → JSON
    """
    wants_json = False

    if fmt is not None:
        wants_json = fmt.lower() == "json"
    elif json is not None and str(json).lower() in {"1", "true", "yes"}:
        wants_json = True
    else:
        # fallback: 看 Accept 头
        accept = request.headers.get("accept", "")
        if "application/json" in accept.lower() and "text/html" not in accept.lower():
            wants_json = True

    if wants_json:
        # 复用 /api/doctor 逻辑
        from doctor import run_doctor
        checks = run_doctor()
        items = [c.to_dict() for c in checks]
        summary = {
            "ok": sum(1 for c in checks if c.status == "ok"),
            "warn": sum(1 for c in checks if c.status == "warn"),
            "fail": sum(1 for c in checks if c.status == "fail"),
        }
        return {
            "exit_code": 1 if summary["fail"] else 0,
            "checks": items,
            "summary": summary,
            "source": "diagnose_endpoint",
        }

    p = _WEB_DIR / "doctor.html"
    if p.exists():
        return FileResponse(str(p))
    raise HTTPException(status_code=404, detail="doctor.html not found")


@app.get("/api/index")
async def api_index():
    """侧栏导航清单（前端用）。"""
    return {
        "app": "AI Agent Console",
        "version": "2.1",
        "routes": {
            "ui": ["/", "/dashboard", "/web/doctor", "/diagnose"],
            "api_common": ["/api/health", "/api/version", "/api/doctor", "/api/evals/run", "/api/evals/history"],
            "api_models": ["/api/models", "/api/agents", "/api/api-key", "/api/api-key/status", "/api/model/switch"],
            "api_memory": ["/api/memory/recall", "/api/memory/list", "/api/memory/stats"],
            "api_tools": ["/api/tools", "/api/upload", "/api/capabilities"],
            "api_prompts": ["/api/prompts", "/api/user-prompts"],
            "api_observability": ["/api/events", "/api/traces", "/api/metrics/prometheus", "/api/load_stats"],
            "api_hitl": ["/api/hitl/pending", "/api/hitl/history", "/api/hitl/stats"],
        },
        "ui_actions": [
            {"label": "🌐 健康检查", "target": "/web/doctor"},
            {"label": "📊 监控", "target": "/dashboard"},
            {"label": "📜 Evals 历史", "target": "/api/evals/history"},
        ],
    }


# ============================================================
# /api/doctor — 健康检查（Day 15：Web UI 接入）
# ============================================================
@app.get("/api/doctor", response_model=DoctorResponse, response_model_by_alias=False)
async def doctor_check():
    """运行 ``doctor.check_doctor()``，返回结构化结果给前端。"""
    from doctor import run_doctor
    checks = run_doctor()
    items = [c.to_dict() for c in checks]
    summary = {
        "ok": sum(1 for c in checks if c.status == "ok"),
        "warn": sum(1 for c in checks if c.status == "warn"),
        "fail": sum(1 for c in checks if c.status == "fail"),
    }
    return {
        "exit_code": 1 if summary["fail"] else 0,
        "checks": items,
        "summary": summary,
    }


# 静态资源（uploads）
app.mount("/uploads", StaticFiles(directory=str(_UPLOAD_ROOT)), name="uploads")


# ============================================================
# /api/evals — 回归测试（Day 15：前端触发）
# ============================================================
@app.post("/api/evals/run", response_model=EvalsRunResponse)
async def evals_run(req: _EvalsRunRequest | None = None):
    """前端触发一次回归。"""
    import argparse
    from evals.runner import cmd_run as _cmd_run

    body = req or _EvalsRunRequest()
    ns = argparse.Namespace(case=body.case, all=bool(body.all))
    try:
        rc = _cmd_run(ns)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"evals runner crashed: {e!s}")

    runs_dir = Path(__file__).parent / "evals" / "runs"
    latest = None
    if runs_dir.exists():
        sub = sorted([d for d in runs_dir.iterdir() if d.is_dir()], reverse=True)
        if sub:
            latest = str(sub[0])
    summary_data = None
    if latest and (Path(latest) / "summary.json").exists():
        try:
            summary_data = json.loads(
                Path(latest).joinpath("summary.json").read_text(encoding="utf-8")
            )
        except Exception:
            summary_data = None
    # 用 by_alias=True 让前端 camelCase；Python snake_case 由
    # response_model_exclude_unset / response_model_by_alias 控制
    # 用 python 字段名返回（snake_case），避免 alias 转换。schema 定义仍允许
    # 前端 input 用 camelCase（populate_by_name=True）。
    return {
        "exit_code": rc,
        "latest_run": latest,
        "summary": summary_data,
    }


# 让 /api/evals/history 也走 Python 字段名（前端用 camelCase 用 field_alias 转换）
@app.get("/api/evals/history", response_model=EvalsHistoryResponse, response_model_by_alias=False)
async def evals_history(limit: int = 10):
    """最近 N 次跑的概要列表（供前端页面）"""
    from evals.runner import RUNS_DIR
    if not RUNS_DIR.exists():
        return {"runs": []}
    sub = sorted([d for d in RUNS_DIR.iterdir() if d.is_dir()], reverse=True)
    runs = []
    for r in sub[:limit]:
        s = r / "summary.json"
        if not s.exists():
            continue
        try:
            data = json.loads(s.read_text(encoding="utf-8"))
            runs.append(
                {
                    "id": r.name,
                    "started_at": data.get("started_at"),
                    "finished_at": data.get("finished_at"),
                    "total": data.get("cases_total", 0),
                    "passed": data.get("cases_passed", 0),
                    "failed": data.get("cases_failed", 0),
                }
            )
        except Exception:
            continue
    return {"runs": runs}

# 阶段 A：把 web/ 目录作为静态资源挂载（用于演示 HTML 等）
try:
    app.mount("/web-static", StaticFiles(directory=str(_WEB_DIR)), name="web-static")
except Exception:
    pass


@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": time.time()}


@app.get("/api/version")
async def get_version():
    return {"version": "2.1", "framework": "FastAPI"}


@app.get("/api/tools")
async def get_tools():
    proxy = get_proxy()
    tools = proxy.get_tools_list()
    tool_info = []
    agent = get_agent()
    if agent is not None:
        for name in tools:
            for t in agent.tools:
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

    async def event_gen():
        try:
            chunks = proxy.run_stream(request.message, session_id=sid)
            if not isinstance(chunks, list):
                if isinstance(chunks, dict):
                    chunks = [chunks]
                else:
                    chunks = [{"type": "text", "data": str(chunks)}]
            for c in chunks:
                if not isinstance(c, dict):
                    c = {"type": "text", "data": str(c)}
                event_type = c.get("type", "chunk")
                yield f"event: {event_type}\ndata: {json.dumps(c, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
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
@app.get("/api/agents")
async def list_agents():
    proxy = get_proxy()
    workers = proxy.list_workers()
    return {"agents": workers, "count": len(workers)}


@app.get("/api/capabilities")
async def list_capabilities():
    proxy = get_proxy()
    return {"capabilities": proxy.list_capabilities(), "task_types": proxy.list_task_types()}


@app.get("/api/load_stats")
async def get_load_stats():
    proxy = get_proxy()
    return proxy.get_load_stats()


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

# Day 15：迁移 _MemoryAddRequest → schemas.MemoryAddRequest（仅保留 ``content``）
_MemoryAddRequest = schemas.MemoryAddRequest  # type: ignore[assignment]
# 兼容老用法 —— 仅暴露 content 字段（fill in default=True 让旧代码可省略）


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
# Token 用量 Dashboard（v0.5 新增）
# 暴露：
#   GET  /api/token/usage                       — 当前快照（totals/by_model/scope/...）
#   GET  /api/token/usage/history?range=24h      — timeline 子集（按 range 过滤）
#   GET  /api/token/budget                      — 当前预算/告警/Prometheus 配置
#   POST /api/token/budget                      — 运行期更新预算/告警/cooldown/aggregation
#   POST /api/token/prometheus                  — 运行期更新 Prometheus/Pushgateway 配置
#   POST /api/token/prometheus/push             — 手动 push 一次到 Pushgateway
#   POST /api/token/alert/ack                   — 确认最近一次告警（清空）
# ============================================================


def _get_token_snapshot() -> dict[str, Any]:
    """统一从 registry 读 snapshot（保证 in-process 状态）。"""
    try:
        from agent_middleware import get_token_usage_snapshot
        return get_token_usage_snapshot()
    except Exception as e:  # noqa: BLE001
        logger.warning("token snapshot failed: %s", e)
        return {
            "ok": False,
            "error": str(e),
            "totals": {"input": 0, "output": 0, "total": 0, "cost_usd": 0.0},
            "by_model": [],
            "scope": {},
            "last_alert": None,
            "history": [],
            "history_max": 0,
            "history_bucket_seconds": 60,
            "prometheus": {
                "enabled": False, "http_port": None,
                "pushgateway_url": None, "pushgateway_job": None,
                "push_to_gateway_every_n": None, "grouping_key": {},
            },
            "config": {
                "alert_thresholds": [],
                "alert_cooldown": {},
                "alert_aggregation_window": 0.0,
                "alert_aggregation_jitter": 0.0,
                "budget_persist_path": None,
            },
        }


_APP_TOKEN_DASHBOARD_BOOTSTRAPPED = {"done": False}


def _bootstrap_token_dashboard_defaults() -> None:
    """首次访问时把 dashboard 默认配置应用到所有实例。

    目的：用户直接 import app.py 但没经过 ``init_agent`` 时
    （或在 _NullProxy 路径下），仍能展示 dashboard UI。
    """
    if _APP_TOKEN_DASHBOARD_BOOTSTRAPPED["done"]:
        return
    try:
        from agent_middleware import _TOKEN_USAGE_REGISTRY, TokenUsageConfig
        # 仅当所有实例都用 history_max=0 默认值时才注入 dashboard defaults
        if not _TOKEN_USAGE_REGISTRY:
            return
        for inst in _TOKEN_USAGE_REGISTRY:
            try:
                cfg = inst.config
                if cfg.history_max <= 0:
                    cfg.history_max = 720
                if cfg.history_bucket_seconds <= 0:
                    cfg.history_bucket_seconds = 60
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    _APP_TOKEN_DASHBOARD_BOOTSTRAPPED["done"] = True


@app.get("/api/token/usage")
async def token_usage():
    _bootstrap_token_dashboard_defaults()
    return _get_token_snapshot()


@app.get("/api/token/usage/history")
async def token_usage_history(range: str = "24h", bucket: str = "auto"):
    """返回 timeline 子集。

    - range: ``24h`` / ``1h`` / ``7d`` / ``all`` / 数字秒
    - bucket: ``auto`` / ``60`` / ``300`` / ``3600``（前后端约定的桶大小）
    """
    snap = _get_token_snapshot()
    history = list(snap.get("history") or [])
    now_ts = int(time.time())
    # 解析 range
    rseconds: int | None
    if range == "all":
        rseconds = None
    elif range.endswith("h"):
        try:
            rseconds = int(range[:-1]) * 3600
        except Exception:
            rseconds = 24 * 3600
    elif range.endswith("d"):
        try:
            rseconds = int(range[:-1]) * 86400
        except Exception:
            rseconds = 24 * 3600
    elif range.endswith("m"):
        try:
            rseconds = int(range[:-1]) * 60
        except Exception:
            rseconds = 24 * 3600
    else:
        try:
            rseconds = int(range)
        except Exception:
            rseconds = 24 * 3600
    if rseconds is not None:
        cutoff = now_ts - rseconds
        history = [h for h in history if int(h.get("bucket_ts", 0)) >= cutoff]
    # bucket 聚合
    if bucket != "auto":
        try:
            bs = int(bucket)
        except Exception:
            bs = 0
        if bs > 0:
            agg: dict[int, dict[str, Any]] = {}
            for h in history:
                t = int(h.get("bucket_ts", 0))
                key = (t // bs) * bs
                cell = agg.get(key)
                if cell is None:
                    cell = {
                        "bucket_ts": key,
                        "input": 0, "output": 0, "total": 0,
                        "cost_usd": 0.0, "by_model": {},
                    }
                    agg[key] = cell
                cell["input"] += int(h.get("input", 0))
                cell["output"] += int(h.get("output", 0))
                cell["total"] += int(h.get("total", 0))
                cell["cost_usd"] += float(h.get("cost_usd", 0.0))
                for mn, md in (h.get("by_model") or {}).items():
                    mb = cell["by_model"].get(mn)
                    if mb is None:
                        mb = {"input": 0, "output": 0, "total": 0, "cost_usd": 0.0}
                        cell["by_model"][mn] = mb
                    mb["input"] += int(md.get("input", 0))
                    mb["output"] += int(md.get("output", 0))
                    mb["total"] += int(md.get("total", 0))
                    mb["cost_usd"] += float(md.get("cost_usd", 0.0))
            history = sorted(agg.values(), key=lambda x: x["bucket_ts"])
            # 圆整
            for h in history:
                h["cost_usd"] = round(float(h["cost_usd"]), 6)
                for mn in (h.get("by_model") or {}).values():
                    mn["cost_usd"] = round(float(mn.get("cost_usd", 0.0)), 6)
    return {
        "ok": True,
        "range": range,
        "bucket": bucket,
        "count": len(history),
        "history": history,
        "history_max": snap.get("history_max", 0),
        "history_bucket_seconds": snap.get("history_bucket_seconds", 60),
    }


@app.get("/api/token/budget")
async def token_budget_get():
    snap = _get_token_snapshot()
    return {
        "ok": True,
        "config": snap.get("config", {}),
        "scope": snap.get("scope", {}),
        "prometheus": snap.get("prometheus", {}),
    }


@app.post("/api/token/budget")
async def token_budget_post(payload: Dict[str, Any] = Body(default_factory=dict)):
    """运行期更新预算 / 告警 / cooldown / aggregation / 历史桶。"""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    # 校验类型
    patch: dict[str, Any] = {}
    float_fields = (
        "per_call_budget_usd", "cumulative_budget_usd",
        "daily_budget_usd", "weekly_budget_usd", "monthly_budget_usd",
        "alert_aggregation_window",
    )
    for k in float_fields:
        if k in payload and payload[k] is not None:
            try:
                patch[k] = float(payload[k])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{k} must be a number")
    int_fields = ("history_max", "history_bucket_seconds")
    for k in int_fields:
        if k in payload and payload[k] is not None:
            try:
                patch[k] = int(payload[k])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{k} must be an integer")
    if "alert_thresholds" in payload and payload["alert_thresholds"] is not None:
        ts = payload["alert_thresholds"]
        if not isinstance(ts, list):
            raise HTTPException(status_code=400, detail="alert_thresholds must be list")
        norm: list[list[Any]] = []
        for t in ts:
            if isinstance(t, (list, tuple)) and len(t) == 2:
                norm.append([float(t[0]), str(t[1])])
            else:
                raise HTTPException(status_code=400, detail="alert_thresholds items must be [ratio, severity]")
        patch["alert_thresholds"] = norm
    if "alert_cooldown" in payload and payload["alert_cooldown"] is not None:
        cd = payload["alert_cooldown"]
        if not isinstance(cd, dict):
            raise HTTPException(status_code=400, detail="alert_cooldown must be object")
        patch["alert_cooldown"] = {str(k): float(v) for k, v in cd.items()}
    if "alert_aggregation_jitter" in payload and payload["alert_aggregation_jitter"] is not None:
        j = payload["alert_aggregation_jitter"]
        if isinstance(j, (list, tuple)) and len(j) == 2:
            patch["alert_aggregation_jitter"] = [float(j[0]), float(j[1])]
        else:
            try:
                patch["alert_aggregation_jitter"] = float(j)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="alert_aggregation_jitter must be float or [neg, pos]")
    if "budget_persist_path" in payload and payload["budget_persist_path"]:
        patch["budget_persist_path"] = str(payload["budget_persist_path"])
    try:
        from agent_middleware import update_token_budget
        result = update_token_budget(patch)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"update_token_budget failed: {e}")
    return {"ok": True, "patched": patch, "config": result.get("config", {})}


@app.post("/api/token/prometheus")
async def token_prometheus_post(payload: Dict[str, Any] = Body(default_factory=dict)):
    """运行期更新 Prometheus / Pushgateway 配置。"""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    patch: dict[str, Any] = {}
    if "pushgateway_url" in payload:
        url = payload["pushgateway_url"]
        patch["pushgateway_url"] = str(url) if url else None
    if "pushgateway_job" in payload:
        job = payload["pushgateway_job"]
        patch["pushgateway_job"] = str(job) if job else None
    if "push_to_gateway_every_n" in payload and payload["push_to_gateway_every_n"] is not None:
        try:
            patch["push_to_gateway_every_n"] = max(1, int(payload["push_to_gateway_every_n"]))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="push_to_gateway_every_n must be int")
    if "grouping_key" in payload and payload["grouping_key"] is not None:
        gk = payload["grouping_key"]
        if not isinstance(gk, dict):
            raise HTTPException(status_code=400, detail="grouping_key must be object")
        patch["grouping_key"] = {str(k): str(v) for k, v in gk.items()}
    try:
        from agent_middleware import update_token_prometheus
        result = update_token_prometheus(patch)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"update_token_prometheus failed: {e}")
    return {"ok": True, "patched": patch, "prometheus": result.get("prometheus", {})}


@app.post("/api/token/prometheus/push")
async def token_prometheus_push():
    """主动 push 一次到 Pushgateway（不等累积到 every_n）。"""
    try:
        from agent_middleware import push_token_prometheus_now
        result = push_token_prometheus_now()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"push_token_prometheus_now failed: {e}")
    return {"ok": True, **result}


@app.post("/api/token/alert/ack")
async def token_alert_ack():
    """确认最近一次告警（清空 _last_alert）。"""
    try:
        from agent_middleware import get_token_usage_registry
        for inst in get_token_usage_registry():
            try:
                inst.reset_last_alert()
            except Exception:  # noqa: BLE001
                continue
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"reset_last_alert failed: {e}")
    return {"ok": True}


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
# Plugin Manager API（不依赖 AIAgentExtension 单例）
# ============================================================

@app.get("/plugins")
async def plugins_page():
    p = _WEB_DIR / "plugins.html"
    if p.exists():
        return FileResponse(str(p))
    return {"message": "plugins.html not found"}


def _pm():
    from plugin_manager import get_plugin_manager
    return get_plugin_manager()


@app.get("/api/plugins")
async def list_plugins():
    """列出所有已安装插件（含 disabled / error）。"""
    mgr = _pm()
    return {
        "plugins": [e.to_dict() for e in mgr.list_installed()],
        "stats": mgr.stats(),
    }


@app.get("/api/plugins/enabled")
async def list_enabled_plugins():
    return {"plugins": [e.to_dict() for e in _pm().list_enabled()]}


@app.get("/api/plugins/stats")
async def get_plugin_stats():
    return _pm().stats()


@app.post("/api/plugins/install")
async def install_plugin(payload: Dict[str, Any]):
    """根据 manifest dict 安装插件（body 形如 {"manifest": {...}, "config": {...}}）。"""
    from plugin_manager import PluginManifest
    mgr = _pm()
    body = payload or {}
    manifest = PluginManifest.from_dict(body.get("manifest") or {})
    config = body.get("config") or {}
    entry = mgr.install(manifest, config=config)
    return entry.to_dict()


@app.post("/api/plugins/{name}/enable")
async def enable_plugin(name: str):
    entry = _pm().enable(name)
    return entry.to_dict()


@app.post("/api/plugins/{name}/disable")
async def disable_plugin(name: str):
    entry = _pm().disable(name)
    return entry.to_dict()


@app.delete("/api/plugins/{name}")
async def uninstall_plugin(name: str):
    ok = _pm().uninstall(name)
    return {"name": name, "uninstalled": ok}


@app.get("/api/plugins/find")
async def find_plugin_by_capability(capability: str):
    entries = _pm().find_by_capability(capability)
    return {"capability": capability, "plugins": [e.to_dict() for e in entries]}


@app.post("/api/plugins/save")
async def save_plugins(payload: Optional[Dict[str, Any]] = None):
    path = (payload or {}).get("path") or "plugins.json"
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    _pm().save_state(path)
    return {"saved_to": path}


@app.post("/api/plugins/load")
async def load_plugins(payload: Optional[Dict[str, Any]] = None):
    path = (payload or {}).get("path") or "plugins.json"
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    n = _pm().load_state(path)
    return {"loaded": n, "path": path}


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

    # ---- Plugin bootstrap（启动时一次性加载 rag_backends / auth_backends） ----
    try:
        from multi_agent_integration import bootstrap_builtin_plugins
        plugins_cfg = os.environ.get("PLUGINS_CONFIG", "plugins.json")
        if not os.path.isabs(plugins_cfg):
            plugins_cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), plugins_cfg)
        result = bootstrap_builtin_plugins(config_path=plugins_cfg)
        logger.info(f"Plugins bootstrap: {result}")
    except Exception as e:
        logger.warning(f"Plugin bootstrap failed (non-fatal): {e}")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    run(port=port)