"""
Web UI 后端（FastAPI）

提供以下端点：
- GET  /api/health                     健康检查
- GET  /api/agents                     列出所有 Agent（含 worker profile）
- GET  /api/capabilities               列出 capability / task_type
- GET  /api/load_stats                 实时负载
- GET  /api/policies                   权限策略
- GET  /api/events?limit=N             最近事件
- GET  /api/traces?limit=N             最近 trace spans
- GET  /api/metrics/prometheus         Prometheus 文本
- POST /api/chat/stream                SSE 流式聊天（基于 run_stream）
- GET  /api/hitl/pending               待审批请求
- POST /api/hitl/decide                提交审批
- GET  /api/hitl/stats                 HITL 状态
- POST /api/policy                     添加策略
- POST /api/permission/enforce         开启/关闭权限强制

启动方式：
    python web_ui.py
"""

import asyncio
import json
import time
import logging
from typing import Any, Dict, List, Optional

try:
    from fastapi import FastAPI, HTTPException, Request, Body, UploadFile, File
    from fastapi.responses import StreamingResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:
    raise ImportError("FastAPI not installed. Run: pip install fastapi uvicorn")

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ============================================================
# 全局 Agent 持有
# ============================================================

_agent_holder: Dict[str, Any] = {"agent": None}


def set_agent(agent) -> None:
    """设置全局 Agent 引用（启动时调用）"""
    _agent_holder["agent"] = agent


def get_agent_holder() -> Dict[str, Any]:
    return _agent_holder


# ============================================================
# Pydantic models
# ============================================================

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    stream: bool = True


class HITLDecision(BaseModel):
    request_id: str
    status: str  # "approved" | "rejected" | "modified"
    decided_by: str = "human"
    decision_payload: Optional[Dict[str, Any]] = None
    notes: str = ""


class PolicyRequest(BaseModel):
    agent_id: str
    roles: Optional[List[str]] = None
    capabilities: Optional[List[str]] = None
    allowed_targets: Optional[List[str]] = None
    allowed_tools: Optional[List[str]] = None
    allowed_workers: Optional[List[str]] = None


class PermissionEnforceRequest(BaseModel):
    enforce: bool


# ============================================================
# FastAPI app
# ============================================================

try:
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
except ImportError:
    pass

app: FastAPI = FastAPI(title="AI Agent Web UI", version="2.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _safe_call(fn, default=None, *args, **kwargs):
    """安全调用扩展 API（agent 可能未初始化或不支持某方法）"""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.debug(f"safe_call error: {e}")
        return default


# ============================================================
# 基础端点 + 静态前端（同源部署）
# ============================================================

import os
from pathlib import Path

# 1) 新版控制台：web_console/dist （Vite 产物）
_HERE = Path(__file__).resolve().parent
_CONSOLE_DIST = _HERE.parent / "web_console" / "dist"
_LEGACY_WEB = _HERE / "web"


def _console_index() -> str | None:
    p = _CONSOLE_DIST / "index.html"
    return str(p) if p.exists() else None


def _legacy_dashboard() -> str | None:
    p = _LEGACY_WEB / "dashboard.html"
    return str(p) if p.exists() else None


def _legacy_index() -> str | None:
    p = _LEGACY_WEB / "index.html"
    return str(p) if p.exists() else None


@app.get("/")
async def root():
    """SPA 入口：优先新版控制台，回退旧版 dashboard"""
    idx = _console_index()
    if idx:
        return FileResponse(idx)
    legacy = _legacy_dashboard() or _legacy_index()
    if legacy:
        return FileResponse(legacy)
    return {"message": "AI Agent API - see /docs", "version": "2.0"}


@app.get("/dashboard")
async def dashboard():
    """多 Agent 可视化 dashboard（旧版）"""
    legacy = _legacy_dashboard() or _legacy_index()
    if legacy:
        return FileResponse(legacy)
    raise HTTPException(status_code=404, detail="dashboard.html not found")


# 旧版入口（保留兼容）
@app.get("/legacy")
async def legacy_index():
    legacy = _legacy_index() or _legacy_dashboard()
    if legacy:
        return FileResponse(legacy)
    raise HTTPException(status_code=404, detail="legacy web not found")


# 2) 静态资源：仅在 dist 存在时挂载
if _CONSOLE_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(_CONSOLE_DIST / "assets")),
        name="console-assets",
    )

    # SPA fallback handler 已移至本文件末尾（必须在所有 /api/* 注册之后）


@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": time.time()}


@app.get("/api/agents")
async def list_agents():
    """列出系统中所有 Agent 及其状态"""
    agent = _agent_holder["agent"]
    if agent is None:
        return {"agents": [], "note": "agent not initialized"}

    # 尝试拿多 Agent 上下文
    workers = _safe_call(agent.list_workers, default=[])
    return {
        "agents": workers,
        "count": len(workers),
    }


@app.get("/api/capabilities")
async def list_capabilities():
    agent = _agent_holder["agent"]
    if agent is None:
        return {"capabilities": [], "task_types": []}
    return {
        "capabilities": _safe_call(agent.list_capabilities, default=[]),
        "task_types": _safe_call(agent.list_task_types, default=[]),
    }


# ============================================================
# 文件上传（multipart）
# ============================================================
import re
import secrets

# 上传根目录：避免重复 IO
UPLOAD_ROOT = Path(_HERE) / "uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

_UPLOAD_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
_ALLOWED_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp",
    "application/pdf", "text/plain", "text/csv", "text/markdown",
    "application/json", "application/octet-stream",
}


def _safe_filename(name: str) -> str:
    name = (name or "file").strip().replace("\\", "/").split("/")[-1]
    name = _UPLOAD_NAME_RE.sub("_", name) or "file"
    return name[:120]


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """接收 multipart 上传，返回 url/path/id 供前端 message content 引用。"""
    content_type = (file.content_type or "").lower()
    # 读 size，超限直接拒绝
    contents = await file.read()
    size = len(contents)
    if size == 0:
        raise HTTPException(status_code=400, detail="empty file")
    if size > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"file too large (max {_MAX_FILE_SIZE // 1024 // 1024}MB)")
    # 类型兜底
    if content_type and content_type not in _ALLOWED_TYPES:
        # 不严格拒绝，仅警告记录
        logger.warning("upload with uncommon content-type=%s name=%s", content_type, file.filename)

    # 生成唯一文件名：时间戳 + 随机 + 原名
    ext = ""
    if file.filename and "." in file.filename:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower()[:8]
    safe = _safe_filename(file.filename or "file")
    unique = f"{int(time.time() * 1000)}_{secrets.token_hex(6)}{ext}"
    final_name = f"{unique}_{safe}"
    target = UPLOAD_ROOT / final_name
    target.write_bytes(contents)

    # 构造可被前端访问的 URL
    url = f"/api/files/{final_name}"
    return {
        "id": unique,
        "name": file.filename or safe,
        "safe_name": final_name,
        "content_type": content_type or "application/octet-stream",
        "size": size,
        "url": url,
    }


@app.get("/api/files/{name}")
async def serve_upload(name: str):
    """提供上传文件的访问（受严格文件名限制）"""
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="invalid name")
    p = UPLOAD_ROOT / name
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="not found")
    # 推断 mime
    mt = "application/octet-stream"
    if name.lower().endswith((".png", ".jpg", ".jpeg")):
        mt = "image/png" if name.lower().endswith(".png") else "image/jpeg"
    elif name.lower().endswith(".gif"):
        mt = "image/gif"
    elif name.lower().endswith(".webp"):
        mt = "image/webp"
    elif name.lower().endswith(".pdf"):
        mt = "application/pdf"
    elif name.lower().endswith(".txt") or name.lower().endswith(".md"):
        mt = "text/plain; charset=utf-8"
    return FileResponse(str(p), media_type=mt)


@app.get("/api/load_stats")
async def get_load_stats():
    agent = _agent_holder["agent"]
    if agent is None:
        return {"stats": {}, "workers": []}
    return _safe_call(agent.get_load_stats, default={"stats": {}, "workers": []})


@app.get("/api/policies")
async def list_policies():
    agent = _agent_holder["agent"]
    if agent is None:
        return {"policies": [], "stats": {}}
    return {
        "policies": _safe_call(agent.list_policies, default=[]),
        "stats": _safe_call(agent.get_permission_stats, default={}),
    }


@app.post("/api/policy")
async def add_policy(req: PolicyRequest):
    agent = _agent_holder["agent"]
    if agent is None:
        raise HTTPException(status_code=400, detail="agent not initialized")
    return _safe_call(
        agent.add_policy,
        {"error": "method not available"},
        req.agent_id,
        roles=req.roles,
        capabilities=req.capabilities,
        allowed_targets=req.allowed_targets,
        allowed_tools=req.allowed_tools,
        allowed_workers=req.allowed_workers,
    )


@app.post("/api/permission/enforce")
async def permission_enforce(req: PermissionEnforceRequest):
    agent = _agent_holder["agent"]
    if agent is None:
        raise HTTPException(status_code=400, detail="agent not initialized")
    return _safe_call(
        agent.enable_permission_enforcement,
        {"error": "method not available"},
        req.enforce,
    )


# ============================================================
# Observability
# ============================================================

@app.get("/api/events")
async def list_events(limit: int = 50, event_type: Optional[str] = None):
    agent = _agent_holder["agent"]
    if agent is None:
        return {"events": []}
    events = _safe_call(agent.list_recent_events, default=[], event_type=event_type, limit=limit)
    return {"events": events, "count": len(events)}


@app.get("/api/traces")
async def list_traces(limit: int = 50):
    agent = _agent_holder["agent"]
    if agent is None:
        return {"traces": []}
    traces = _safe_call(agent.get_recent_traces, default=[], limit=limit)
    return {"traces": traces, "count": len(traces)}


@app.get("/api/metrics/prometheus")
async def prometheus_metrics():
    agent = _agent_holder["agent"]
    if agent is None:
        return JSONResponse(content="# agent not initialized\n", media_type="text/plain")
    text = _safe_call(agent.get_prometheus_metrics, default="")
    return JSONResponse(content=text, media_type="text/plain")


# ============================================================
# HITL
# ============================================================

@app.get("/api/hitl/pending")
async def hitl_pending(hook_point: Optional[str] = None):
    from human_in_loop import get_hitl_guard
    guard = get_hitl_guard()
    pending = guard.get_pending(hook_point=hook_point)
    return {"pending": [r.to_dict() for r in pending], "count": len(pending)}


@app.get("/api/hitl/history")
async def hitl_history(hook_point: Optional[str] = None, limit: int = 50):
    from human_in_loop import get_hitl_guard
    guard = get_hitl_guard()
    history = guard.get_history(hook_point=hook_point, limit=limit)
    return {"history": [r.to_dict() for r in history], "count": len(history)}


@app.post("/api/hitl/decide")
async def hitl_decide(req: HITLDecision):
    from human_in_loop import get_hitl_guard
    guard = get_hitl_guard()
    ok = guard.decide(
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
    from human_in_loop import get_hitl_guard
    return get_hitl_guard().stats()


# ============================================================
# Planner + Memory
# ============================================================

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


@app.post("/api/plan/create")
async def plan_create(req: PlanRequest):
    agent = _agent_holder["agent"]
    if agent is None:
        raise HTTPException(status_code=400, detail="agent not initialized")
    return _safe_call(agent.create_plan, {"error": "method not available"}, req.goal, session_id=req.session_id)


@app.post("/api/plan/research")
async def plan_research(req: PlanRequest):
    agent = _agent_holder["agent"]
    if agent is None:
        raise HTTPException(status_code=400, detail="agent not initialized")
    return _safe_call(agent.create_research_plan, {"error": "method not available"}, req.goal)


@app.post("/api/plan/code")
async def plan_code(req: PlanRequest):
    agent = _agent_holder["agent"]
    if agent is None:
        raise HTTPException(status_code=400, detail="agent not initialized")
    return _safe_call(agent.create_code_plan, {"error": "method not available"}, req.goal)


@app.post("/api/plan/run")
async def plan_run(req: PlanRequest):
    agent = _agent_holder["agent"]
    if agent is None:
        raise HTTPException(status_code=400, detail="agent not initialized")
    try:
        return await agent.run_plan(req.goal, session_id=req.session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/memory/remember")
async def memory_remember(req: RememberRequest):
    agent = _agent_holder["agent"]
    if agent is None:
        raise HTTPException(status_code=400, detail="agent not initialized")
    return _safe_call(
        agent.remember, {"error": "method not available"},
        req.key, req.value, memory_type=req.memory_type, scope=req.scope,
        importance=req.importance, expires_in_seconds=req.expires_in_seconds, tags=req.tags,
    )


@app.get("/api/memory/recall")
async def memory_recall(key: str, scope: str = "global"):
    agent = _agent_holder["agent"]
    if agent is None:
        raise HTTPException(status_code=400, detail="agent not initialized")
    return _safe_call(agent.recall, None, key, scope=scope)


@app.get("/api/memory/search")
async def memory_search(keyword: Optional[str] = None, scope: Optional[str] = None,
                       memory_type: Optional[str] = None, limit: int = 20):
    agent = _agent_holder["agent"]
    if agent is None:
        raise HTTPException(status_code=400, detail="agent not initialized")
    return _safe_call(
        agent.search_memory, [],
        keyword=keyword, scope=scope, memory_type=memory_type, limit=limit,
    )


@app.delete("/api/memory/forget")
async def memory_forget(key: str, scope: str = "global"):
    agent = _agent_holder["agent"]
    if agent is None:
        raise HTTPException(status_code=400, detail="agent not initialized")
    return {"deleted": _safe_call(agent.forget, False, key, scope=scope)}


@app.post("/api/memory/save")
async def memory_save(path: str = "memory.json"):
    agent = _agent_holder["agent"]
    if agent is None:
        raise HTTPException(status_code=400, detail="agent not initialized")
    return _safe_call(agent.save_memory, {"error": "method not available"}, path)


@app.post("/api/memory/load")
async def memory_load(path: str = "memory.json"):
    agent = _agent_holder["agent"]
    if agent is None:
        raise HTTPException(status_code=400, detail="agent not initialized")
    return _safe_call(agent.load_memory, {"error": "method not available"}, path)


@app.get("/api/memory/stats")
async def memory_stats():
    agent = _agent_holder["agent"]
    if agent is None:
        raise HTTPException(status_code=400, detail="agent not initialized")
    return _safe_call(agent.get_memory_stats, {})


@app.post("/api/hitl/policy")
async def hitl_policy(hook_point: str, policy: str):
    from human_in_loop import get_hitl_guard, HITLPolicy
    guard = get_hitl_guard()
    try:
        policy_enum = HITLPolicy(policy)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid policy: {policy}")
    if hook_point == "default":
        guard.set_default_policy(policy_enum)
    else:
        guard.set_hook_policy(hook_point, policy_enum)
    return {"hook_point": hook_point, "policy": policy_enum.value}


# ============================================================
# Streaming chat (SSE)
# ============================================================

async def _sse_event_stream(prompt: str, session_id: Optional[str] = None):
    """SSE 事件流：把 run_stream 的 chunks 转 SSE 事件"""
    agent = _agent_holder["agent"]
    if agent is None:
        yield f"event: error\ndata: {json.dumps({'error': 'agent not initialized'})}\n\n"
        return

    if not hasattr(agent, "run_stream"):
        yield f"event: error\ndata: {json.dumps({'error': 'run_stream not available'})}\n\n"
        return

    try:
        async for chunk in agent.run_stream(prompt):
            event_type = chunk.get("type", "chunk")
            yield f"event: {event_type}\ndata: {json.dumps(chunk)}\n\n"
    except Exception as e:
        logger.error(f"stream error: {e}")
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    yield "event: end\ndata: {}\n\n"


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 流式聊天"""
    if not req.message:
        raise HTTPException(status_code=400, detail="message required")
    return StreamingResponse(
        _sse_event_stream(req.message, req.session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# 启动入口
# ============================================================

def run(host: str = "0.0.0.0", port: int = 8000):
    """启动 Web 服务（同步）"""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()