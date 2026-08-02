from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import List, Optional
import uuid
import os

from agent import AIAgent
from mcp_external import external_mcp_manager

app = FastAPI(title="AI Agent API", version="2.0.0")


@asynccontextmanager
async def _lifespan(app):
    """FastAPI 启动/关闭钩子:启动时加载 enabled 的 external MCP,关闭时清理"""
    try:
        await external_mcp_manager.reload()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("mcp_external reload failed at startup: %s", e)
    try:
        yield
    finally:
        try:
            await external_mcp_manager.shutdown()
        except Exception:
            pass


app.router.lifespan_context = _lifespan

agent = None

def get_agent():
    global agent
    if agent is None:
        agent = AIAgent()
    return agent

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    message: str
    session_id: str

class ToolInfo(BaseModel):
    name: str
    description: str

class ClearResponse(BaseModel):
    success: bool
    message: str

class ApiKeyRequest(BaseModel):
    api_key: str
    provider: Optional[str] = "openai"

class ApiKeyResponse(BaseModel):
    success: bool
    message: str
    configured: bool

class ModelSwitchRequest(BaseModel):
    provider: str
    model_name: Optional[str] = None

class ModelSwitchResponse(BaseModel):
    success: bool
    message: str
    provider: str
    model: str

@app.get("/")
async def root():
    return FileResponse("web/index.html")

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "AI Agent API is running"}

@app.get("/api/tools")
async def get_tools():
    agent = get_agent()
    tools = agent.get_tools_list()
    tool_info = []
    for tool_name in tools:
        tool_list = [t for t in agent.tools if t.name == tool_name]
        if tool_list:
            tool = tool_list[0]
            tool_info.append({
                "name": tool.name,
                "description": tool.description
            })
    return {"tools": tool_info}

@app.post("/api/chat")
async def chat(request: ChatRequest):
    try:
        agent = get_agent()
        session_id = request.session_id or str(uuid.uuid4())
        result = agent.run(request.message)
        return ChatResponse(message=result, session_id=session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/api/chat/stream")
async def chat_stream(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            session_id = data.get("session_id")  # 可选，不传则使用默认
            
            if not message:
                await websocket.send_json({"error": "Message is required"})
                continue
            
            try:
                agent = get_agent()
                # 如果提供了 session_id，设置到 agent
                if session_id:
                    agent.set_session(session_id)
                else:
                    session_id = agent.current_session_id
                
                for chunk in agent.run_stream(message):
                    await websocket.send_json({
                        "type": "chunk",
                        "data": chunk,
                        "session_id": session_id
                    })
                
                await websocket.send_json({
                    "type": "complete",
                    "session_id": session_id
                })
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "error": str(e),
                    "session_id": session_id
                })
    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")

@app.post("/api/clear")
async def clear_history():
    try:
        agent = get_agent()
        result = agent.clear_history()
        return ClearResponse(success=True, message=result)
    except Exception as e:
        return ClearResponse(success=False, message=str(e))


# ============================================================
# 语音流式识别 + 置信度兜底确认
# ============================================================

from audio_streaming import StreamingASRSession, wav_to_pcm
from multimodal import Modality, Attachment, get_attachment_store
from audio_pipeline import get_audio_pipeline


class AudioConfirmRequest(BaseModel):
    """前端 low_confidence 事件后回写的确认结果"""
    session_id: str
    audio_attachment_id: Optional[str] = None
    original_text: str
    corrected_text: str
    confidence: float = 0.0
    provider: Optional[str] = None


class AudioConfirmResponse(BaseModel):
    success: bool
    message: str
    final_text: str


@app.post("/api/audio/confirm", response_model=AudioConfirmResponse)
async def audio_confirm(req: AudioConfirmRequest):
    """低置信度结果由用户确认后回写"""
    try:
        final_text = (req.corrected_text or "").strip() or (req.original_text or "").strip()

        # 1. 训练数据入库（如果 audio_feedback 表存在）
        try:
            from audio_feedback import get_audio_feedback_store
            fb_store = get_audio_feedback_store()
            fb_store.record(
                session_id=req.session_id,
                attachment_id=req.audio_attachment_id or "",
                original_text=req.original_text,
                corrected_text=req.corrected_text,
                confidence=req.confidence,
                provider=req.provider or "",
            )
        except Exception as e:  # noqa: BLE001
            logger_warning(f"feedback record failed: {e}")

        # 2. 更新 attachment 的 text_content（如有）
        if req.audio_attachment_id:
            store = get_attachment_store()
            att = store.get(req.audio_attachment_id)
            if att is not None:
                att.text_content = final_text
                att.metadata = dict(att.metadata or {})
                att.metadata["user_confirmed"] = True
                att.metadata["asr_confidence"] = req.confidence

        return AudioConfirmResponse(
            success=True,
            message="confirmed",
            final_text=final_text,
        )
    except Exception as e:
        return AudioConfirmResponse(success=False, message=str(e), final_text=req.original_text or "")


def logger_warning(msg: str):
    import logging
    logging.getLogger(__name__).warning(msg)


@app.post("/api/audio/transcribe")
async def audio_transcribe_endpoint(
    attachment_id: str,
    lang: Optional[str] = None,
    provider: Optional[str] = None,
):
    """对一已上传音频附件做离线转录（返回 text + meta）"""
    try:
        store = get_attachment_store()
        att = store.get(attachment_id)
        if att is None or att.modality != Modality.AUDIO:
            raise HTTPException(status_code=404, detail="audio attachment not found")
        pipeline = get_audio_pipeline()
        if lang:
            pipeline.config.default_lang = lang
        result = pipeline.transcribe(att)
        if provider:
            # 指定 provider 重跑
            result = pipeline.transcribe_bytes(att.data, mime=att.mime, provider=provider)
        return {
            "text": result.text,
            "provider": result.provider,
            "confidence": result.confidence,
            "lang": result.lang,
            "fallback_used": result.fallback_used,
            "hotwords_hit": result.hotwords_hit,
            "duration_sec": result.duration_sec,
            "error": result.error,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/api/audio/stream")
async def audio_stream(websocket: WebSocket):
    """流式 ASR WebSocket 端点。

    客户端协议：
      → {"type":"start", "lang":"zh", "provider":"whisper_local", "session_id":"..."}
      → {"type":"audio", "data":"<base64 PCM>", "sample_rate":16000}
      → {"type":"stop"}
    服务端推送：
      ← {"type":"ready", ...}
      ← {"type":"final", "text":..., "confidence":..., "fallback_used":..., ...}
      ← {"type":"low_confidence", "text":..., "confidence":..., "session_id":...}
      ← {"type":"error", "error":...}
      ← {"type":"closed", "session_id":...}
    """
    await websocket.accept()
    session: Optional[StreamingASRSession] = None
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                await websocket.send_json({"type": "error", "error": "invalid json"})
                continue

            mtype = msg.get("type")
            if mtype == "start":
                sid = msg.get("session_id") or str(uuid.uuid4())
                session = StreamingASRSession(session_id=sid)
                ready = await session.handle_start(msg)
                await websocket.send_json(ready)
            elif mtype == "audio":
                if session is None:
                    await websocket.send_json({"type": "error", "error": "send start first"})
                    continue
                events = await session.handle_audio(msg)
                for ev in events:
                    await websocket.send_json(ev)
            elif mtype == "stop":
                if session is None:
                    await websocket.send_json({"type": "error", "error": "session not started"})
                    continue
                events = await session.handle_stop()
                for ev in events:
                    await websocket.send_json(ev)
            elif mtype == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "error", "error": f"unknown type: {mtype}"})
    except WebSocketDisconnect:
        logger.info(f"[audio_stream] disconnected sid={getattr(session, 'session_id', '?')}")
    except Exception as e:
        logger.exception(f"[audio_stream] error: {e}")
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass

@app.get("/api/version")
async def get_version():
    return {"version": "1.0.0", "framework": "FastAPI"}

@app.get("/api/api-key/status")
async def get_api_key_status():
    agent = get_agent()
    return agent.get_api_key_status()

@app.post("/api/api-key")
async def set_api_key(request: ApiKeyRequest):
    try:
        agent = get_agent()
        agent.set_api_key(request.api_key.strip(), request.provider)
        status = agent.get_api_key_status()
        return ApiKeyResponse(
            success=True,
            message=f"✅ {status['provider']} API Key 配置成功" if status["configured"] else "API Key 已清除",
            configured=status["configured"]
        )
    except Exception as e:
        return ApiKeyResponse(
            success=False,
            message=f"❌ 配置失败: {str(e)}",
            configured=False
        )

@app.post("/api/model/switch")
async def switch_model(request: ModelSwitchRequest):
    """切换模型提供商和模型"""
    try:
        agent = get_agent()
        success = agent.set_model(request.provider, request.model_name)
        status = agent.get_api_key_status()
        
        if success:
            return ModelSwitchResponse(
                success=True,
                message=f"✅ 已切换到 {status['provider']}/{status['model']}",
                provider=status['provider'],
                model=status['model']
            )
        else:
            return ModelSwitchResponse(
                success=False,
                message=f"❌ 切换失败，请检查 API Key 是否配置",
                provider=request.provider,
                model=request.model_name or ""
            )
    except Exception as e:
        return ModelSwitchResponse(
            success=False,
            message=f"❌ 切换失败: {str(e)}",
            provider=request.provider,
            model=request.model_name or ""
        )

@app.get("/api/models")
async def get_models():
    """获取所有可用的模型列表"""
    try:
        agent = get_agent()
        models = agent.get_available_models()
        status = agent.get_api_key_status()

        return {
            "current_provider": status["provider"],
            "current_model": status["model"],
            "models": models
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# 外部 MCP Servers 管理 API
# =====================================================

class MCPToggleRequest(BaseModel):
    enabled: bool


class MCPSetHostRequest(BaseModel):
    host: str  # 例如 "https://api.minimax.chat" / "https://api.minimaxi.chat"


@app.get("/api/mcp/servers")
async def list_mcp_servers():
    """列出所有 external MCP server + 运行时状态(env 字段不回 value)"""
    try:
        return {"servers": external_mcp_manager.list_servers()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mcp/tools")
async def list_mcp_tools():
    """列出所有 running external MCP server 的 tools"""
    try:
        return {"tools": external_mcp_manager.list_tools()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mcp/servers/{server_id}/toggle")
async def toggle_mcp_server(server_id: str, request: MCPToggleRequest):
    """切换 external MCP server 启用状态;enabled=true 时要求 required_env 齐全"""
    try:
        result = await external_mcp_manager.toggle(server_id, request.enabled)
        if not result.get("ok"):
            # 区分 missing_env(400)与其它错误(500)
            if "missing_env" in result:
                raise HTTPException(status_code=400, detail=result)
            raise HTTPException(status_code=500, detail=result)
        # 返回最新状态
        return {
            "ok": True,
            "server_id": server_id,
            "enabled": request.enabled,
            "server": next(
                (s for s in external_mcp_manager.list_servers() if s["id"] == server_id),
                None,
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mcp/servers/{server_id}/host")
async def set_mcp_server_host(server_id: str, request: MCPSetHostRequest):
    """仅供前端切换 minimax MCP 的 API_HOST(国内/国际);其它字段不通过此端点修改"""
    try:
        import json as _json
        cfg_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "mcp_config.json"
        )
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = _json.load(f)
        servers = cfg.get("external_servers", {})
        if server_id not in servers:
            raise HTTPException(status_code=404, detail="unknown server_id")
        env = servers[server_id].setdefault("env", {})
        env["MINIMAX_API_HOST"] = request.host
        cfg["external_servers"] = servers
        # 用 manager 自带的原子写
        external_mcp_manager._save_config(cfg)
        return {"ok": True, "server_id": server_id, "host": request.host}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mcp/reload")
async def reload_mcp_servers():
    """重读 mcp_config.json,按 enabled 启停全部 external server"""
    try:
        result = await external_mcp_manager.reload()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# 结构化上下文 API
# =====================================================

@app.get("/api/context/sessions")
async def list_sessions(status: Optional[str] = None, limit: int = 20):
    """列出会话列表"""
    try:
        agent = get_agent()
        sessions = agent.list_all_sessions(status=status, limit=limit)
        return {"sessions": [s.__dict__ for s in sessions]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/context/sessions")
async def create_session():
    """创建新会话"""
    try:
        agent = get_agent()
        session_id = agent.create_new_session()
        return {"session_id": session_id, "message": "✅ 新会话已创建"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/context/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话详情"""
    try:
        agent = get_agent()
        agent.set_session(session_id)
        analytics = agent.get_session_analytics()
        return analytics
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/context/sessions/{session_id}/summary")
async def get_session_summary(session_id: str):
    """获取会话摘要"""
    try:
        agent = get_agent()
        agent.set_session(session_id)
        summary = agent.get_context_summary()
        if summary:
            return {
                "session_id": session_id,
                "topic": summary.topic,
                "keywords": summary.keywords,
                "key_entities": summary.key_entities,
                "summary_content": summary.summary_content,
                "created_at": summary.created_at.isoformat() if summary.created_at else None
            }
        return {"session_id": session_id, "summary": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/context/sessions/{session_id}/entities")
async def get_session_entities(session_id: str, entity_type: Optional[str] = None):
    """获取会话中的实体"""
    try:
        agent = get_agent()
        agent.set_session(session_id)
        entities = agent.get_entities(entity_type=entity_type)
        return {
            "session_id": session_id,
            "entities": [
                {
                    "id": e.id,
                    "type": e.entity_type,
                    "name": e.entity_name,
                    "value": e.entity_value,
                    "mention_count": e.mention_count,
                    "is_active": e.is_active
                }
                for e in entities
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/context/sessions/{session_id}/relations")
async def get_session_relations(session_id: str, relation_type: Optional[str] = None):
    """获取会话中的实体关系"""
    try:
        agent = get_agent()
        agent.set_session(session_id)
        relations = agent.context_manager.get_entity_relations(session_id, relation_type)
        return {
            "session_id": session_id,
            "relations": [
                {
                    "id": r.id,
                    "from_entity_id": r.from_entity_id,
                    "to_entity_id": r.to_entity_id,
                    "relation_type": r.relation_type,
                    "strength": r.strength,
                    "context": r.context
                }
                for r in relations
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/context/entities/{entity_id}/related")
async def get_related_entities(entity_id: int):
    """获取与某实体相关的所有实体"""
    try:
        agent = get_agent()
        related = agent.context_manager.get_related_entities(entity_id)
        return {
            "entity_id": entity_id,
            "similar_to": [
                {"id": e.id, "type": e.entity_type, "name": e.entity_name}
                for e in related.get('similar_to', [])
            ],
            "related_to": [
                {"id": e.id, "type": e.entity_type, "name": e.entity_name}
                for e in related.get('related_to', [])
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/context/users/{user_id}/profile")
async def get_user_profile(user_id: str):
    """获取用户画像"""
    try:
        agent = get_agent()
        profile = agent.context_manager.profile_repo.get_by_user_id(user_id)
        if profile:
            return {
                "user_id": profile.user_id,
                "display_name": profile.display_name,
                "total_sessions": profile.total_sessions,
                "total_messages": profile.total_messages,
                "favorite_tools": profile.favorite_tools,
                "interests": profile.interests,
                "learned_preferences": profile.learned_preferences,
                "common_intents": profile.common_intents
            }
        return {"user_id": user_id, "profile": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/context/users/{user_id}/profile")
async def update_user_profile(user_id: str, display_name: Optional[str] = None, interests: Optional[List[str]] = None):
    """更新用户画像"""
    try:
        agent = get_agent()
        profile = agent.context_manager.profile_repo.get_or_create(user_id)
        
        update_data = {}
        if display_name is not None:
            update_data['display_name'] = display_name
        if interests is not None:
            update_data['interests'] = interests
        
        if update_data:
            profile = agent.context_manager.profile_repo.update(user_id, **update_data)
        
        return {"message": "Profile updated", "profile": {"user_id": profile.user_id, "display_name": profile.display_name}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/context/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, limit: int = 50):
    """获取会话消息历史"""
    try:
        agent = get_agent()
        agent.set_session(session_id)
        messages = agent.context_manager.get_messages(session_id, limit=limit)
        return {
            "session_id": session_id,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "content_type": m.content_type,
                    "created_at": m.created_at.isoformat() if m.created_at else None
                }
                for m in messages
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/context/analytics")
async def get_current_session_analytics():
    """获取当前会话统计"""
    try:
        agent = get_agent()
        return agent.get_session_analytics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/context/search")
async def search_sessions(
    query: str,
    entity_type: Optional[str] = None,
    limit: int = 20
):
    """搜索历史会话"""
    try:
        agent = get_agent()
        
        # 搜索会话
        sessions = agent.list_all_sessions(status="completed", limit=100)
        
        # 简单过滤（实际生产中应该用全文索引）
        results = []
        for session in sessions:
            if query.lower() in str(session.metadata).lower():
                results.append(session)
                if len(results) >= limit:
                    break
        
        return {
            "query": query,
            "results": [
                {
                    "session_id": s.id,
                    "user_id": s.user_id,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "message_count": s.message_count
                }
                for s in results
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/context/stats")
async def get_stats():
    """获取系统统计"""
    try:
        agent = get_agent()
        db = agent.context_manager.session_repo.db
        
        stats = {}
        
        with db.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM sessions")
            stats["total_sessions"] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM messages")
            stats["total_messages"] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM entities")
            stats["total_entities"] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tool_calls")
            stats["total_tool_calls"] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM summaries")
            stats["total_summaries"] = cursor.fetchone()[0]
        
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/context/performance")
async def get_performance_stats():
    """获取性能统计"""
    try:
        from monitor import get_monitor
        monitor = get_monitor()
        return monitor.get_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/context/performance/reset")
async def reset_performance_stats():
    """重置性能统计"""
    try:
        from monitor import get_monitor
        monitor = get_monitor()
        monitor.reset()
        return {"message": "Performance stats reset"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


os.makedirs("web", exist_ok=True)
app.mount("/web", StaticFiles(directory="web", html=True), name="web")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)