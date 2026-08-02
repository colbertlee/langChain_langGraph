"""schemas.py 单元测试（Day 8-9 回归用）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from pydantic import ValidationError

from schemas import (
    ChatRequest,
    ApiKeyRequest,
    ModelSwitchRequest,
    ApiKeyStatusResponse,
    MemoryAddRequest,
    HealthResponse,
    PromptRollbackRequest,
)


# ---- ChatRequest ----

def test_chat_request_required_message():
    r = ChatRequest(message="hello")
    assert r.message == "hello"
    assert r.session_id is None


def test_chat_request_accepts_session_id_alias():
    """前端发送 sessionId 也能映射到 session_id。"""
    r = ChatRequest(message="hi", sessionId="s-1")
    assert r.session_id == "s-1"


def test_chat_request_strips_message():
    r = ChatRequest(message="  hello  ")
    assert r.message == "hello"


def test_chat_request_blank_message_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(message="")


def test_chat_request_extra_fields_ignored():
    """前端加字段不会 422。"""
    r = ChatRequest(message="hi", unknown_field="x", future_feature=True)
    assert r.message == "hi"


def test_chat_request_too_long_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(message="x" * 200_000)


# ---- ApiKeyRequest ----

def test_api_key_request_default_provider():
    r = ApiKeyRequest(apiKey="sk-test")
    assert r.provider == "openai"


def test_api_key_request_invalid_provider_rejected():
    """ProviderId 字面量校验能挡住非法 provider。"""
    with pytest.raises(ValidationError):
        ApiKeyRequest(apiKey="sk-test", provider="ghost")


def test_api_key_accepts_all_known_providers():
    for prov in ("openai", "deepseek", "qwen", "zhipu", "moonshot", "minimax",
                 "baidu", "spark", "doubao", "hunyuan", "siliconflow"):
        r = ApiKeyRequest(apiKey="sk-x", provider=prov)
        assert r.provider == prov


def test_api_key_accepts_legacy_provider_field():
    """前端老代码 ``provider='openai'`` 也兼容（populate_by_name 生效）。"""
    r = ApiKeyRequest(apiKey="sk-test", provider="zhipu")
    assert r.provider == "zhipu"


# ---- ModelSwitchRequest ----

def test_model_switch_accepts_model_name():
    r = ModelSwitchRequest(provider="openai", modelName="gpt-4o")
    # alias 会写入 model_name（同时通过 validator 把 model 同步）
    assert r.model_name == "gpt-4o"


def test_model_switch_accepts_model_alias():
    """前端用 ``model`` 也能映射到 ``model_name``（向后兼容）。"""
    r = ModelSwitchRequest(provider="openai", model="gpt-4o")
    # model_validator 会把 model 写到 model_name
    assert r.model == "gpt-4o"


def test_model_switch_unknown_provider_rejected():
    with pytest.raises(ValidationError):
        ModelSwitchRequest(provider="ghost-provider", modelName="x")


# ---- ApiKeyStatusResponse ----

def test_api_key_status_response_basic():
    r = ApiKeyStatusResponse(
        configured=True,
        hasAgent=True,
        provider="openai",
        model="gpt-4o",
    )
    assert r.configured is True
    assert r.available_providers == []


def test_api_key_status_response_with_providers():
    r = ApiKeyStatusResponse(
        configured=True,
        hasAgent=True,
        provider="openai",
        model="gpt-4o",
        availableProviders=["openai", "deepseek"],
        providerKeys={"openai": True, "deepseek": False},
    )
    assert "deepseek" in r.available_providers
    assert r.provider_keys["openai"] is True


# ---- MemoryAddRequest ----

def test_memory_add_request_minimal():
    r = MemoryAddRequest(content="x")
    assert r.importance == 3
    assert r.session_id is None


def test_memory_add_importance_bounds():
    with pytest.raises(ValidationError):
        MemoryAddRequest(content="x", importance=11)
    with pytest.raises(ValidationError):
        MemoryAddRequest(content="x", importance=-1)


# ---- HealthResponse ----

def test_health_response_status_literal():
    r = HealthResponse(
        status="ok",
        version="0.1.0",
        uptimeSeconds=12.3,
        components={"rag": "ok", "llm": "degraded"},
    )
    assert r.uptime_seconds == 12.3
    assert r.components["llm"] == "degraded"


def test_health_response_invalid_status():
    with pytest.raises(ValidationError):
        HealthResponse(status="unknown", version="0.1.0", uptimeSeconds=1.0)


# ---- 其它 ----

def test_prompt_rollback_request():
    r = PromptRollbackRequest(name="default", version="2.0.0")
    assert r.version == "2.0.0"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))
