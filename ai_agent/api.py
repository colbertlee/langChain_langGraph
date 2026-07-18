from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import uuid
import os

from agent import AIAgent

app = FastAPI(title="AI Agent API", version="1.0.0")

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

class ApiKeyResponse(BaseModel):
    success: bool
    message: str
    configured: bool

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
            session_id = data.get("session_id", str(uuid.uuid4()))
            
            if not message:
                await websocket.send_json({"error": "Message is required"})
                continue
            
            try:
                agent = get_agent()
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
        agent.set_api_key(request.api_key.strip())
        status = agent.get_api_key_status()
        return ApiKeyResponse(
            success=True,
            message="✅ API Key 配置成功" if status["configured"] else "API Key 已清除",
            configured=status["configured"]
        )
    except Exception as e:
        return ApiKeyResponse(
            success=False,
            message=f"❌ 配置失败: {str(e)}",
            configured=False
        )

os.makedirs("web", exist_ok=True)
app.mount("/web", StaticFiles(directory="web"), name="web")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)