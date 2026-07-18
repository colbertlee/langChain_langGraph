from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uuid, os
from agent import AIAgent

app = FastAPI(title="AI Agent API")
agent = None

def get_agent():
    global agent
    if agent is None: agent = AIAgent()
    return agent

@app.get("/")
async def root(): return FileResponse("ai_agent/web/index.html")
@app.get("/api/health")
async def health(): return {"status": "ok"}

@app.websocket("/api/chat/stream")
async def chat_stream(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            for chunk in get_agent().run_stream(data.get("message", "")):
                await websocket.send_json({"type": "chunk", "data": chunk})
            await websocket.send_json({"type": "complete"})
    except: pass

os.makedirs("ai_agent/web", exist_ok=True)
app.mount("/web", StaticFiles(directory="ai_agent/web"), name="web")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)