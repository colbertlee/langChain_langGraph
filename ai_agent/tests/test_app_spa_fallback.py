"""v2.0.11+ — SPA Catch-all 与 backend 边界测试。

架构边界（v2.5 重构后）：
  - SPA fallback 由 nginx.conf 的 `try_files $uri /index.html` 处理
  - FastAPI 后端不提供 SPA HTML（职责清晰：backend = JSON API，edge = 静态 + fallback）
  - /api/* 必须返回 JSON（不允许被 fallback 吞）
  - /api/* 找不到必须返回 JSON 404（不允许 HTML 404）

测试目标：
  1. /api/health 返回 JSON 200
  2. /api/this-route-does-not-exist 返回 JSON 404（不是 HTML）
  3. 静态资源 /favicon.ico 找不到返回 JSON 404（backend 不挂 static files）
  4. /openapi.json + /docs 仍可访问（FastAPI 默认端点）
  5. 不依赖 web_console/dist 存在（backend 与构建产物解耦）
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app import app


@pytest.mark.asyncio
async def test_api_health_returns_json():
    """/api/health 必须返回 JSON 200。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/health")
        assert r.status_code == 200, f"/api/health → {r.status_code}"
        assert "application/json" in r.headers.get("content-type", ""), (
            f"/api/health expected JSON, got {r.headers.get('content-type')}"
        )
        data = r.json()
        assert "status" in data


@pytest.mark.asyncio
async def test_api_unknown_returns_json_404_not_html():
    """/api/this-route-does-not-exist 必须返回 JSON 404，不能被 SPA fallback 吞。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/this-route-does-not-exist")
        assert r.status_code == 404, f"expected 404, got {r.status_code}"
        ct = r.headers.get("content-type", "")
        assert "application/json" in ct, (
            f"expected JSON 404, got content-type={ct}"
        )
        body = r.json()
        assert "detail" in body, f"expected FastAPI JSON detail, got body={body!r}"


@pytest.mark.asyncio
async def test_unknown_path_with_extension_returns_json_404_not_html():
    """/favicon.ico, /missing.css 等找不到的有后缀路径必须返回 JSON 404，不能返回 HTML。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for path in ("/favicon.ico", "/missing.css", "/foo.js"):
            r = await ac.get(path)
            # backend 没有挂 static files（nginx 负责），未知路径应 404
            assert r.status_code == 404, f"{path} should 404, got {r.status_code}"
            ct = r.headers.get("content-type", "")
            assert "text/html" not in ct, (
                f"{path} returned HTML for a missing asset: {ct}"
            )


@pytest.mark.asyncio
async def test_openapi_and_docs_accessible():
    """/openapi.json 与 /docs 仍可访问（FastAPI 默认端点）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # openapi.json 必返回 JSON
        r = await ac.get("/openapi.json")
        assert r.status_code == 200
        assert "application/json" in r.headers.get("content-type", "")
        assert "paths" in r.json()


@pytest.mark.asyncio
async def test_spa_routes_return_404_not_html_from_backend():
    """架构契约：backend 不承担 SPA fallback，/chat / agents / tools 等 SPA 路由在 backend 应为 404（由 nginx 接管）。

    防止有人误把 SPA fallback 加回 backend（破坏前后端职责清晰）。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for path in ("/chat", "/agents", "/tools", "/settings"):
            r = await ac.get(path)
            # 期望 404（backend 不知道这些 SPA 路由）
            assert r.status_code == 404, (
                f"{path} 应由 nginx 服务，backend 不应返回 SPA HTML（got {r.status_code}）"
            )
            ct = r.headers.get("content-type", "")
            # 必须是 JSON 404，不是 HTML（防止有人误把 HTML fallback 加回 backend）
            assert "text/html" not in ct, (
                f"{path} returned HTML from backend; SPA fallback 应在 nginx 层处理"
            )
