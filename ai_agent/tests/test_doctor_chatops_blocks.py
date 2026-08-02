"""Day 18：doctor_chatops Slack BLOCK KIT 测试。"""
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.doctor_chatops import build_slack_payload, build_discord_payload


class FakeCheck:
    def __init__(self, name, status, message, fix=None):
        self.name = name
        self.status = status
        self.message = message
        self.fix = fix


@pytest.fixture(autouse=True)
def _clean_env():
    yield
    os.environ.pop("DOCTOR_UI_URL", None)


# ---- Slack BLOCK KIT 按钮存在性 ----

def test_slack_payload_has_view_doctor_button_when_remote(monkeypatch):
    monkeypatch.setenv("DOCTOR_UI_URL", "https://ai.example.com/web/doctor")
    checks = [
        FakeCheck("python", "ok", "ok"),
        FakeCheck("deps", "fail", "missing", fix="pip install"),
    ]
    p = build_slack_payload(checks)
    blocks = p["blocks"]
    # 找 actions block
    action_blocks = [b for b in blocks if b.get("type") == "actions"]
    assert len(action_blocks) == 1
    elements = action_blocks[0]["elements"]
    # 至少一个 button，url 正确
    assert any(
        el.get("url") == "https://ai.example.com/web/doctor"
        for el in elements
    )


def test_slack_button_style_based_on_failures(monkeypatch):
    monkeypatch.setenv("DOCTOR_UI_URL", "https://ai.example.com/web/doctor")
    # 全 OK → primary
    p = build_slack_payload([FakeCheck("a", "ok", "x")])
    action = [b for b in p["blocks"] if b.get("type") == "actions"][0]
    btn = action["elements"][0]
    assert btn["style"] == "primary"

    # 有 fail → danger
    p2 = build_slack_payload([FakeCheck("a", "fail", "x")])
    btn2 = [b for b in p2["blocks"] if b.get("type") == "actions"][0]["elements"][0]
    assert btn2["style"] == "danger"

    # 有 warn → default
    p3 = build_slack_payload([FakeCheck("a", "warn", "x")])
    btn3 = [b for b in p3["blocks"] if b.get("type") == "actions"][0]["elements"][0]
    assert btn3["style"] == "default"


def test_slack_no_button_when_local(monkeypatch):
    """localhost 不放 button（避免 Slack 校验出错）。"""
    monkeypatch.setenv("DOCTOR_UI_URL", "http://localhost:8000/web/doctor")
    p = build_slack_payload([FakeCheck("a", "ok", "x")])
    action_blocks = [b for b in p["blocks"] if b.get("type") == "actions"]
    assert action_blocks == []


def test_slack_api_json_button_appends_json_query(monkeypatch):
    monkeypatch.setenv("DOCTOR_UI_URL", "https://ai.example.com/web/doctor")
    p = build_slack_payload([FakeCheck("a", "ok", "x")])
    actions = [b for b in p["blocks"] if b.get("type") == "actions"][0]
    api_btn = [el for el in actions["elements"] if el.get("text", {}).get("text") == "📊 View API JSON"][0]
    assert "json=1" in api_btn["url"]


def test_slack_api_json_button_appends_json_query_to_existing_query(monkeypatch):
    """当 DOCTOR_UI_URL 已有 ?key=val，不破坏 query 串。"""
    monkeypatch.setenv("DOCTOR_UI_URL", "https://ai.example.com/web/doctor?env=prod")
    p = build_slack_payload([FakeCheck("a", "ok", "x")])
    actions = [b for b in p["blocks"] if b.get("type") == "actions"][0]
    api_btn = [el for el in actions["elements"] if el.get("text", {}).get("text") == "📊 View API JSON"][0]
    assert "&json=1" in api_btn["url"]
    assert "env=prod" in api_btn["url"]


def test_slack_payload_text_fallback_present(monkeypatch):
    """text 必须有（Slack 老客户端 fallback）。"""
    monkeypatch.setenv("DOCTOR_UI_URL", "https://ai.example.com/web/doctor")
    p = build_slack_payload([FakeCheck("a", "ok", "x")])
    assert p["text"]
    assert "AI Agent Daily Health" in p["text"]


def test_slack_payload_blocks_have_header_section_context(monkeypatch):
    monkeypatch.setenv("DOCTOR_UI_URL", "https://ai.example.com/web/doctor")
    p = build_slack_payload([FakeCheck("a", "ok", "x")])
    types = [b["type"] for b in p["blocks"]]
    assert "header" in types
    assert "section" in types
    assert "context" in types
    assert "actions" in types  # remote 时也有


def test_slack_payload_blocks_count_when_local(monkeypatch):
    monkeypatch.setenv("DOCTOR_UI_URL", "http://127.0.0.1:8088/web/doctor")
    p = build_slack_payload([FakeCheck("a", "ok", "x")])
    # local 时无 actions，但有 context 说明
    types = [b["type"] for b in p["blocks"]]
    assert "actions" not in types
    assert "context" in types
    # context 里写明 local
    ctx = [b for b in p["blocks"] if b["type"] == "context"][0]
    text = ctx["elements"][0]["text"]
    assert "local" in text.lower()


# ---- Action ID 不重复 ----

def test_slack_action_ids_are_unique(monkeypatch):
    monkeypatch.setenv("DOCTOR_UI_URL", "https://ai.example.com/web/doctor")
    p = build_slack_payload([FakeCheck("a", "ok", "x")])
    actions = [b for b in p["blocks"] if b.get("type") == "actions"][0]
    ids = [el.get("action_id") for el in actions["elements"]]
    assert len(set(ids)) == len(ids)  # 不重复


# ---- Discord payload 不需要按钮 ----

def test_discord_payload_no_buttons_required():
    """Discord embed 不需要 actions button（虽然支持）。"""
    p = build_discord_payload([FakeCheck("a", "ok", "x")])
    # Discord embed 本体只要求 title/description/color
    e = p["embeds"][0]
    assert "title" in e
    assert "description" in e
    # 不强求 components（按钮）


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))