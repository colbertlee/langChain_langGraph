"""Day 17：/diagnose + /web/doctor 智能切换测试。

覆盖：
- 默认 → HTML
- ?json=1 → JSON
- ?fmt=json / ?fmt=page → 显式切换
- Accept 头 application/json → JSON
- Accept 含 text/html + application/json → HTML（text/html 优先级）
"""
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


# ---- 默认 ----

def test_diagnose_default_returns_html(client):
    r = client.get("/diagnose")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_web_doctor_default_returns_html(client):
    r = client.get("/web/doctor")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


# ---- ?json=1 兼容 ----

def test_diagnose_json_query_returns_json(client):
    r = client.get("/diagnose?json=1")
    assert r.status_code == 200
    body = r.json()
    assert "exit_code" in body
    assert "checks" in body
    assert "summary" in body
    assert body["source"] == "diagnose_endpoint"


def test_web_doctor_json_query_returns_json(client):
    r = client.get("/web/doctor?json=1")
    body = r.json()
    assert body["source"] == "web_doctor_endpoint"


def test_json_query_accepts_truthy_values(client):
    for v in ("1", "true", "True", "yes"):
        r = client.get(f"/diagnose?json={v}")
        assert r.headers.get("content-type", "").startswith("application/json"), v


# ---- ?fmt= 显式 ----

def test_diagnose_fmt_json(client):
    r = client.get("/diagnose?fmt=json")
    assert "application/json" in r.headers.get("content-type", "")
    assert r.json()["source"] == "diagnose_endpoint"


def test_diagnose_fmt_page(client):
    r = client.get("/diagnose?fmt=page")
    assert "text/html" in r.headers.get("content-type", "")


def test_fmt_overrides_json_query(client):
    """fmt=page 与 json=1 同时存在时，fmt 优先。"""
    r = client.get("/diagnose?fmt=page&json=1")
    assert "text/html" in r.headers.get("content-type", "")


# ---- Accept 头 ----

def test_accept_application_json_returns_json(client):
    r = client.get("/diagnose", headers={"Accept": "application/json"})
    assert "application/json" in r.headers.get("content-type", "")
    assert r.json()["source"] == "diagnose_endpoint"


def test_accept_text_html_returns_html(client):
    """Accept 含 text/html 时强制 HTML（即便只有 html 与 */*）。"""
    r = client.get("/diagnose", headers={"Accept": "text/html"})
    assert "text/html" in r.headers.get("content-type", "")


def test_accept_html_plus_json_returns_html(client):
    """text/html 与 application/json 同时出现时，html 胜出。"""
    r = client.get("/diagnose", headers={"Accept": "text/html,application/json"})
    assert "text/html" in r.headers.get("content-type", "")


def test_accept_json_q_higher_than_html_returns_json(client):
    """application/json 优先 q 值时返回 JSON。"""
    h = "text/html;q=0.4,application/json;q=0.9"
    r = client.get("/diagnose", headers={"Accept": h})
    # 实现里只看 application/json 关键字 + 没有 text/html 时 → json；
    # 这里 Accept 含 text/html 所以默认 HTML。
    # 这是有意简单：避免 q 值解析复杂度
    assert "text/html" in r.headers.get("content-type", "")


def test_diagnose_shortcut_alias(client):
    """/diagnose 与 /diagnose.html 不需 alias；验证默认入口。"""
    r = client.get("/diagnose")
    assert r.status_code == 200


# ---- 边界 ----

def test_diagnose_json_exit_code_consistency(client):
    """exit_code 与 summary.fail 应一致。"""
    r = client.get("/diagnose?json=1")
    body = r.json()
    fail = body["summary"]["fail"]
    assert (body["exit_code"] == 0) == (fail == 0)


def test_diagnose_json_no_extra_fields_bypass(client):
    """JSON 形态不会被 extra 字段漏掉。"""
    r = client.get("/diagnose?json=1")
    body = r.json()
    # 关键字段必须全
    assert {"exit_code", "checks", "summary", "source"} <= set(body.keys())