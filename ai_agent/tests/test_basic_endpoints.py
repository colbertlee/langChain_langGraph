"""测试 app.py 的基础端点（不依赖 LLM）。

覆盖：
- GET /api/health
- GET /api/capabilities
- GET /api/agents

注意：v2.5 重构后，backend 不再提供 SPA HTML；
    静态资源 / SPA fallback 由 nginx 处理。
    原 TestStatic.test_root_returns_html_or_fallback 已删除（架构边界变化）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _try_import_app():
    try:
        ROOT = Path(__file__).resolve().parent.parent
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import app  # noqa: F401
        return app
    except ImportError as e:
        pytest.skip(f"app.py 不能导入: {e}")


@pytest.fixture
def client():
    return TestClient(_try_import_app().app)


class TestHealth:
    def test_health_endpoint(self, client):
        res = client.get("/api/health")
        # agent 未初始化时返回 200 + status="no_agent" 或 503
        assert res.status_code in (200, 503), f"got {res.status_code}"
        data = res.json()
        assert "status" in data
        # status 字段必须在已知枚举内
        assert data["status"] in ("ok", "healthy", "degraded", "no_agent")


class TestCapabilities:
    def test_capabilities_returns_list(self, client):
        res = client.get("/api/capabilities")
        assert res.status_code == 200
        data = res.json()
        assert "capabilities" in data
        assert "task_types" in data
        assert isinstance(data["capabilities"], list)
        assert isinstance(data["task_types"], list)


class TestAgents:
    def test_list_agents(self, client):
        res = client.get("/api/agents")
        assert res.status_code == 200
        data = res.json()
        # /api/agents 返回 dict {agents: [...], count: N} 或 "note" 提示
        assert isinstance(data, dict)
        if "agents" in data:
            assert isinstance(data["agents"], list)
        else:
            # 没初始化 agent 时至少有 note 字段
            assert "note" in data


class TestRoot:
    """架构边界（v2.5+）：backend / 应返回 JSON 元信息，不返回 HTML。"""

    def test_root_returns_json_not_html(self, client):
        """GET / 应返回 JSON 元信息（不是 HTML）。"""
        res = client.get("/")
        assert res.status_code == 200
        ct = res.headers.get("content-type", "")
        assert "application/json" in ct, (
            f"backend / 应返回 JSON（got {ct}）。HTML/SPA fallback 应在 nginx 层处理。"
        )
