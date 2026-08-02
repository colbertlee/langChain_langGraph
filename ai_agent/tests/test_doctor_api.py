"""Day 15：doctor / evals 端点单测。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient

from app import app


@pytest.fixture
def client():
    return TestClient(app)


# ---- /api/doctor ----

def test_doctor_endpoint_returns_healthy_shape(client):
    r = client.get("/api/doctor")
    assert r.status_code == 200
    data = r.json()
    # 接受 snake 或 camel
    assert "exit_code" in data or "exitCode" in data
    assert "checks" in data
    assert "summary" in data
    # summary 三个 key
    assert set(data["summary"].keys()) >= {"ok", "warn", "fail"}


def test_doctor_check_items_have_required_fields(client):
    r = client.get("/api/doctor")
    data = r.json()
    if not data["checks"]:
        pytest.skip("doctor returned no checks (env misconfigured)")
    for ck in data["checks"]:
        assert "name" in ck
        assert "status" in ck
        assert ck["status"] in ("ok", "warn", "fail")
        assert "message" in ck


# ---- /api/evals/run 与 /api/evals/history ----

def test_evals_run_all_returns_expected_shape(client, tmp_path, monkeypatch):
    """跑一次全部回归，应返回 summary + latest_run"""
    from evals import runner as runner_mod
    monkeypatch.setattr(runner_mod, "RUNS_DIR", tmp_path)
    r = client.post("/api/evals/run", json={"all": True})
    assert r.status_code == 200
    body = r.json()
    # 接受 snake 或 camel
    assert "exit_code" in body or "exitCode" in body
    assert "latest_run" in body or "latestRun" in body
    assert body["summary"] is None or isinstance(body["summary"], dict)


def test_evals_run_specific_case(client, tmp_path, monkeypatch):
    from evals import runner as runner_mod
    monkeypatch.setattr(runner_mod, "RUNS_DIR", tmp_path)
    r = client.post("/api/evals/run", json={"case": "intent_routing"})
    assert r.status_code == 200


def test_evals_history_lists_runs(client, tmp_path, monkeypatch):
    from evals import runner as runner_mod
    monkeypatch.setattr(runner_mod, "RUNS_DIR", tmp_path)
    # 手工制造一份 run
    (tmp_path / "20260101_000000").mkdir()
    (tmp_path / "20260101_000000" / "summary.json").write_text(
        json.dumps({"started_at": "x", "finished_at": "y",
                    "cases_total": 3, "cases_passed": 3, "cases_failed": 0}),
        encoding="utf-8"
    )
    r = client.get("/api/evals/history?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert "runs" in body
    ids = [it.get("id") for it in body["runs"]]
    assert "20260101_000000" in ids


def test_evals_history_empty(client, tmp_path, monkeypatch):
    from evals import runner as runner_mod
    monkeypatch.setattr(runner_mod, "RUNS_DIR", tmp_path)
    # 空目录
    r = client.get("/api/evals/history?limit=5")
    assert r.status_code == 200
    assert r.json().get("runs") == []


# ---- 静态页面 ----

def test_web_doctor_page_exists(client):
    r = client.get("/web/doctor")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Doctor" in r.text or "doctor" in r.text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))
