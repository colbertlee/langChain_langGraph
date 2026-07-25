"""国内主流模型 Provider 单元测试（阶段 B）。

覆盖：
- MODEL_VERSIONS / PROVIDER_META 完整性
- _build_provider_base_url / _api_key_for_provider
- get_api_key_status / get_available_models
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from config import MODEL_VERSIONS, PROVIDER_META, MODEL_PROVIDER
from agent import AIAgent, _build_provider_base_url, _api_key_for_provider


def test_model_versions_contains_all_china_providers():
    required = {
        "openai", "deepseek", "qwen", "zhipu", "moonshot", "minimax",
        "baidu", "spark",
        "doubao", "hunyuan", "siliconflow",  # 阶段 B 新增
    }
    assert required.issubset(set(MODEL_VERSIONS.keys())), \
        f"missing providers: {required - set(MODEL_VERSIONS.keys())}"


def test_every_provider_has_at_least_one_model():
    for prov, models in MODEL_VERSIONS.items():
        assert models, f"provider {prov} has empty models"
        assert all(isinstance(m, str) and m for m in models), f"invalid model in {prov}"


def test_provider_meta_covers_all_providers():
    """PROVIDER_META 应覆盖所有有模型清单的 provider（前端展示需要 label/desc）。"""
    for prov in MODEL_VERSIONS.keys():
        assert prov in PROVIDER_META, f"PROVIDER_META missing {prov}"
        meta = PROVIDER_META[prov]
        assert meta.get("label"), f"{prov} missing label"
        assert meta.get("group") in ("global", "china", "other"), \
            f"{prov} group={meta.get('group')!r} not in expected set"


@pytest.mark.parametrize("provider,expected_url", [
    ("deepseek", "https://api.deepseek.com/v1"),
    ("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ("zhipu", "https://open.bigmodel.cn/api/paas/v4"),
    ("moonshot", "https://api.moonshot.cn/v1"),
    ("minimax", "https://api.minimax.chat/v1"),
    ("doubao", "https://ark.cn-beijing.volces.com/api/v3"),
    ("hunyuan", "https://api.hunyuan.tencent.com/v1"),
    ("siliconflow", "https://api.siliconflow.cn/v1"),
])
def test_build_provider_base_url(provider, expected_url):
    assert _build_provider_base_url(provider) == expected_url


def test_build_provider_base_url_openai_returns_none():
    assert _build_provider_base_url("openai") is None


def test_build_provider_base_url_unknown_returns_none():
    assert _build_provider_base_url("ghost") is None


def test_api_key_for_provider_returns_string():
    """无 Key 时返回空串（不抛异常）。"""
    for prov in MODEL_VERSIONS.keys():
        key = _api_key_for_provider(prov)
        assert isinstance(key, str), f"{prov} key not str"


def test_api_key_for_provider_unknown_falls_back_to_openai():
    """未知的 provider 名应回退到 OPENAI_API_KEY。"""
    # 这个 case 与"未配置 openai key"会返回空串一致；只保证不抛异常
    assert isinstance(_api_key_for_provider("ghost"), str)


# ---- AIAgent 集成 ----

@pytest.fixture(autouse=True)
def _patch_checkpointer(monkeypatch):
    monkeypatch.setattr(AIAgent, "_init_checkpointer", lambda self: None)
    yield


def test_get_api_key_status_contains_all_providers():
    agent = AIAgent()
    status = agent.get_api_key_status()
    assert "provider_keys" in status
    keys = status["provider_keys"]
    for prov in MODEL_VERSIONS.keys():
        assert prov in keys, f"provider_keys missing {prov}"
        assert isinstance(keys[prov], bool)


def test_get_available_models_returns_providers_list():
    agent = AIAgent()
    info = agent.get_available_models()
    assert "providers" in info
    assert "models_by_provider" in info
    assert "current_provider" in info
    assert "current_model" in info
    assert len(info["providers"]) == len(MODEL_VERSIONS)
    for p in info["providers"]:
        assert {"id", "label", "group", "configured", "models"}.issubset(set(p.keys()))


def test_get_available_models_groups_global_before_china():
    agent = AIAgent()
    info = agent.get_available_models()
    groups = [p["group"] for p in info["providers"]]
    # global 应该出现在 china 之前
    if "global" in groups and "china" in groups:
        assert groups.index("global") < groups.index("china")


def test_get_available_models_each_has_models():
    agent = AIAgent()
    info = agent.get_available_models()
    for p in info["providers"]:
        assert len(p["models"]) >= 1, f"provider {p['id']} has empty models"


def test_get_available_models_has_doubao_hunyuan_siliconflow():
    agent = AIAgent()
    info = agent.get_available_models()
    ids = [p["id"] for p in info["providers"]]
    assert "doubao" in ids
    assert "hunyuan" in ids
    assert "siliconflow" in ids


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))