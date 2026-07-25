"""测试 web_ui.py 的基础端点（不依赖 LLM）。

覆盖：
- GET /api/health
- GET /api/capabilities
- GET / 静态资源
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _try_import_webui():
    try:
        ROOT = Path(__file__).resolve().parent.parent
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import web_ui  # noqa: F401
        return web_ui
    except ImportError as e:
        pytest.skip(f"web_ui.py 不能导入: {e}")


@pytest.fixture
def client():
    return TestClient(_try_import_webui().app)


class TestHealth:
    def test_health_endpoint(self, client):
        res = client.get("/api/health")
        # agent 未初始化时返回 200 + status="no_agent"
        assert res.status_code in (200, 503)
        data = res.json()
        assert "status" in data


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


class TestStatic:
    def test_root_returns_html_or_fallback(self, client):
        """GET / 应返回 HTML（新版 dist/ 或 fallback 老版 web/index.html）。"""
        res = client.get("/")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
