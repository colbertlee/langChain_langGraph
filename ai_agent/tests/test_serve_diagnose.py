"""Day 16：独立诊断端口 (serve_diagnose.py) 单测。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """每次请求新 build_app，确保 test 互相隔离。"""
    from scripts.serve_diagnose import build_app
    return TestClient(build_app())


# ---- /api/health ----

def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == "2.1"
    assert "uptimeSeconds" in body


# ---- /api/doctor ----

def test_doctor_endpoint_returns_shape(client):
    r = client.get("/api/doctor")
    assert r.status_code == 200
    data = r.json()
    assert "exit_code" in data
    assert "checks" in data
    assert "summary" in data
    # summary 三 key
    s = data["summary"]
    assert set(s.keys()) >= {"ok", "warn", "fail"}


def test_doctor_exit_code_consistent_with_failures(client):
    r = client.get("/api/doctor")
    data = r.json()
    fail = data["summary"]["fail"]
    assert (data["exit_code"] == 0) == (fail == 0)


# ---- /api/evals/history ----

def test_evals_history_empty(client):
    """默认 RUNS_DIR 没跑过也可能为空；不应崩。"""
    r = client.get("/api/evals/history?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert "runs" in body
    assert isinstance(body["runs"], list)


# ---- / ----

def test_index_shortcuts(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["ui_url"] == "/web/doctor"
    assert body["api_url"] == "/api/doctor"


# ---- /web/doctor / /diagnose ----

def test_web_doctor_returns_html(client):
    r = client.get("/web/doctor")
    # 我们项目里存在 doctor.html，应该 200
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Doctor" in r.text


def test_diagnose_alias_works(client):
    r = client.get("/diagnose")
    # 应该与 /web/doctor 等价
    assert r.status_code == 200


# ---- 不应暴露 agent runtime ----

def test_no_agent_runtime_exposed(client):
    """Doctor 端口**不应**暴露 /api/chat 等敏感端点。"""
    for forbidden in ("/api/chat", "/api/chat/stream", "/api/run_code"):
        r = client.get(forbidden)
        assert r.status_code in (404, 405), (
            f"{forbidden} should not be exposed on diagnose port, got {r.status_code}"
        )


def test_no_upload_endpoint(client):
    """上传文件应仅主控制台可见。"""
    r = client.post("/api/upload", files={"file": ("x.txt", b"hello")})
    assert r.status_code in (404, 405)