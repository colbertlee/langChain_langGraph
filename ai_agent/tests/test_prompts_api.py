"""Prompt API（阶段 A2）端到端测试。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app


def test_prompts_list_endpoint():
    client = TestClient(app)
    r = client.get("/api/prompts")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "templates" in data
    names = [t["name"] for t in data["templates"]]
    assert "default" in names
    # 应至少有两个版本
    default_t = next(t for t in data["templates"] if t["name"] == "default")
    versions = [v["version"] for v in default_t["versions"]]
    assert "1.0.0" in versions and "2.0.0" in versions
    assert default_t["active_version"] in ("1.0.0", "2.0.0")
    print("[PASS] /api/prompts returns templates + versions")


def test_prompts_rollback_endpoint():
    client = TestClient(app)
    # 切到 v1.0.0
    r = client.post("/api/prompts/rollback", json={"name": "default", "version": "1.0.0"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["version"] == "1.0.0"

    # 再切到 v2.0.0（恢复默认）
    r = client.post("/api/prompts/rollback", json={"name": "default", "version": "2.0.0"})
    assert r.status_code == 200, r.text
    print("[PASS] /api/prompts/rollback toggles active version")


def test_prompts_rollback_unknown_version_404():
    client = TestClient(app)
    r = client.post("/api/prompts/rollback", json={"name": "default", "version": "9.9.9"})
    assert r.status_code == 404
    print("[PASS] /api/prompts/rollback 404 on unknown version")


def test_prompts_rollback_unknown_template_404():
    client = TestClient(app)
    r = client.post("/api/prompts/rollback", json={"name": "ghost_template", "version": "1.0.0"})
    assert r.status_code == 404
    print("[PASS] /api/prompts/rollback 404 on unknown template")


if __name__ == "__main__":
    test_prompts_list_endpoint()
    test_prompts_rollback_endpoint()
    test_prompts_rollback_unknown_version_404()
    test_prompts_rollback_unknown_template_404()
    print("[ALL PASS]")