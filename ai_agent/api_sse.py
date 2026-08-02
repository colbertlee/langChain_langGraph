"""
api_sse.py — 把 HeadlessAgent.stream() 通过 SSE 暴露给 Web 客户端。

设计
----
- **不替换** 现有 ``/api/chat/stream`` WebSocket（前端仍在用），而是**并存**；
- 调用方在启动时调一次 ``mount_sse_routes(app, agent_factory=...)`` 即可挂载；
- SSE 路由与 WebSocket 完全独立，前端可按场景任选其一；
- 路由前缀 ``/api/sse/*``，与现有 REST/WebSocket 不冲突。

挂载示例
--------

::

    # main.py / app.py / 等启动入口：
    from api_sse import mount_sse_routes
    mount_sse_routes(app, agent_factory=lambda: get_agent())

或者最简形式::

    mount_sse_routes(app)  # 默认从 ai_agent.AIAgent 懒加载

端点
----
- ``GET /api/sse/chat``  query: ?message=...&session_id=...
   单次 SSE 流；连接断开时立刻停止。

- ``GET /api/sse/health``  无依赖的存活探针（返回 ``ok\\n\\n`` 一行 SSE）。

事件映射
--------
``HeadlessEventType`` → SSE event 字段：
- ``token`` / ``tool_call`` / ``tool_result`` / ``permission_request`` /
  ``permission_response`` / ``error`` / ``done`` 一一对应

依赖
----
- fastapi（与 api.py 一致）；
- headless_sse / headless_agent / headless_events（本项目内）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Callable, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from headless_agent import HeadlessAgent
from headless_sse import SSEConfig, to_sse_lines

logger = logging.getLogger(__name__)


# ============================================================
# 默认 agent 工厂
# ============================================================

_AgentFactory = Callable[[], Any]


def _default_agent_factory() -> Any:
    """懒加载 AIAgent（避免启动时强依赖）。"""
    from agent import AIAgent  # 懒导入
    return AIAgent()


# ============================================================
# 路由注册
# ============================================================

def mount_sse_routes(
    app: FastAPI,
    *,
    agent_factory: Optional[_AgentFactory] = None,
    heartbeat_interval_s: float = 15.0,
    prefix: str = "/api/sse",
) -> None:
    """挂载 SSE 路由到 FastAPI app。

    Args:
        app: FastAPI 实例。
        agent_factory: 返回一个 AIAgent 实例的可调用对象（每次请求独立）。
        heartbeat_interval_s: SSE 心跳间隔（秒）；<= 0 禁用。
        prefix: 路由前缀，默认 ``/api/sse``。
    """
    factory = agent_factory or _default_agent_factory
    sse_cfg = SSEConfig(heartbeat_interval_s=heartbeat_interval_s)

    # ---------- /api/sse/chat ----------
    @app.get(f"{prefix}/chat")
    async def sse_chat(request: Request, message: str, session_id: Optional[str] = None):
        if not message or not message.strip():
            raise HTTPException(status_code=400, detail="message is required")

        agent = factory()
        if session_id:
            try:
                agent.set_session(session_id)
            except Exception as e:  # pragma: no cover
                logger.warning(f"[sse_chat] set_session failed: {e}")

        # 用 HeadlessAgent 包装现有 AIAgent 实例
        headless = HeadlessAgent(agent=agent)

        async def event_source() -> AsyncIterator[bytes]:
            try:
                async for chunk in to_sse_lines(headless.stream(message), sse_cfg):
                    # 客户端断开 → 抛 GeneratorExit，让 stream 停止
                    if await request.is_disconnected():
                        logger.info("[sse_chat] client disconnected, aborting stream")
                        break
                    yield chunk.encode("utf-8") if isinstance(chunk, str) else chunk
            except asyncio.CancelledError:
                # 客户端断连触发的取消
                logger.info("[sse_chat] stream cancelled")
                raise
            except Exception as e:  # pragma: no cover - 防御性
                logger.exception(f"[sse_chat] unexpected error: {e}")
                # 尝试把错误以 SSE 帧发出
                yield f"event: error\ndata: {{\"message\":\"{e}\"}}\n\n".encode("utf-8")

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
                "Connection": "keep-alive",
            },
        )

    # ---------- /api/sse/health ----------
    @app.get(f"{prefix}/health")
    async def sse_health():
        async def _ok():
            yield b"event: ping\ndata: {\"status\":\"ok\"}\n\n"

        return StreamingResponse(
            _ok(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    logger.info(f"[api_sse] SSE routes mounted at {prefix}/*")


# ============================================================
# 独立的 minimal app（便于直接 ``python api_sse.py`` 调试）
# ============================================================

def create_minimal_app() -> FastAPI:
    """构造一个最小 FastAPI app 并挂载 SSE 路由（仅用于本地调试）。"""
    from fastapi import FastAPI
    app = FastAPI(title="Headless SSE", version="0.1.0")

    @app.get("/")
    async def root():
        return {
            "endpoints": ["/api/sse/chat?message=...", "/api/sse/health"],
            "docs": "see api_sse.py docstring",
        }

    mount_sse_routes(app)
    return app


app = create_minimal_app()  # 让 ``uvicorn api_sse:app`` 直接可跑


if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)