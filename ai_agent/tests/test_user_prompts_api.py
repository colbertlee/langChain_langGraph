"""User Prompts API（阶段 B）端到端测试。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app


def test_user_prompts_list():
    client = TestClient(app)
    r = client.get("/api/user-prompts")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "templates" in data
    names = [t["name"] for t in data["templates"]]
    assert "default" in names
    default_t = next(t for t in data["templates"] if t["name"] == "default")
    versions = [v["version"] for v in default_t["versions"]]
    # 至少存在 1.0.0；其它版本(2.0.0 / 2.6.0 等)由其它测试按需注册，
    # 本测试不依赖具体 active_version，避免与测试运行顺序耦合。
    assert "1.0.0" in versions
    assert isinstance(default_t["active_version"], str)
    print("[PASS] /api/user-prompts returns templates + versions")


def test_user_prompts_rollback_known_and_unknown():
    client = TestClient(app)
    # 先切到 1.0.0
    r = client.post(
        "/api/user-prompts/rollback",
        json={"name": "default", "version": "1.0.0"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "1.0.0"

    # 未知版本 -> 404
    r = client.post(
        "/api/user-prompts/rollback",
        json={"name": "default", "version": "9.9.9"},
    )
    assert r.status_code == 404
    print("[PASS] /api/user-prompts/rollback: known-ok + unknown-404")


def test_user_prompts_register_then_active():
    client = TestClient(app)
    payload = {
        "name": "default",
        "version": "2.6.0",
        "structure": "system_first",
        "intro_template": "",
        "few_shots": [
            {"role": "user", "content": "alpha"},
            {"role": "assistant", "content": "beta"},
        ],
        "context_injection": "after_user",
        "security_rewrite": {
            "enabled": True,
            "redact_patterns": [],
            "strip_injection_markers": True,
            "max_length": 2000,
        },
        "variables": [],
    }
    r = client.post("/api/user-prompts/register", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["template"]["version"] == "2.6.0"

    # 切到新版本
    rr = client.post(
        "/api/user-prompts/rollback",
        json={"name": "default", "version": "2.6.0"},
    )
    assert rr.status_code == 200
    assert rr.json()["version"] == "2.6.0"
    print("[PASS] /api/user-prompts/register + rollback")


def test_user_prompts_render_preview():
    client = TestClient(app)
    r = client.post(
        "/api/user-prompts/render",
        json={
            "name": "default",
            "user_input": "帮我总结一下这篇文章",
            "context": "[会话上下文] 用户问的是 NVMe 技术",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert "帮我总结一下这篇文章" in body["rendered"]
    print("[PASS] /api/user-prompts/render preview works")


def test_user_prompts_export_import():
    client = TestClient(app)
    r = client.get("/api/user-prompts/export")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert "templates" in payload

    # 再导入一次(同形状)
    r2 = client.post("/api/user-prompts/import", json=payload)
    assert r2.status_code == 200
    assert r2.json()["imported"] >= 1
    print("[PASS] /api/user-prompts/export + import roundtrip")


if __name__ == "__main__":
    test_user_prompts_list()
    test_user_prompts_rollback_known_and_unknown()
    test_user_prompts_register_then_active()
    test_user_prompts_render_preview()
    test_user_prompts_export_import()
    print("[OK] all user_prompts_api tests passed")
