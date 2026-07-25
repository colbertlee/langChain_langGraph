"""
models_registry - 数据结构与模型接口统一注册表（13.1.4 章节）

背景：
- 项目早期把 provider 列表、模型清单、API Key 解析、base_url 解析、调用接口等
  散落在 config.py 与 agent.py 中，前端 / 测试 / 上层脚本需要分别从多处拼装；
- 本模块提供：
    1) Pydantic 数据模型（ProviderInfo / ModelInfo / ApiKeyStatus / ModelsBundle /
       ChatRequest / ChatResponse / ToolInfo 等），作为跨层契约的「接口定义」；
    2) 注册表 ModelsRegistry：把 config.MODEL_VERSIONS / PROVIDER_META /
       _build_provider_base_url / _api_key_for_provider 等统一封装为单例；
    3) 与现有代码 100% 向后兼容：原 import path 仍然有效（仅 re-export）。

设计原则：
- 单一真相源：所有 provider/model 元信息仍来自 config.py；本模块只做"声明 + 装配"；
- Pydantic v2：使用 model_config = ConfigDict(from_attributes=True) 兼容 dataclass；
- 不依赖 FastAPI：纯数据层，可在 CLI / 测试 / 后端任意位置使用。
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Dict, List, Optional

# pydantic 是可选依赖；缺失时退化为 dataclass 接口（不阻塞导入）
try:
    from pydantic import BaseModel, Field, ConfigDict
    _HAS_PYDANTIC = True
except Exception:  # pragma: no cover
    _HAS_PYDANTIC = False

    class BaseModel:  # type: ignore[no-redef]
        """最小占位实现：仅当 pydantic 不可用时兜底。"""

        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)

        def model_dump(self) -> Dict[str, Any]:  # noqa: D401
            return self.__dict__

    def Field(default: Any = None, **kwargs: Any) -> Any:  # type: ignore[no-redef]
        return default

    class ConfigDict(dict):  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)


# ============================================================
# 常量定义（Provider 列表与协议族）
# ============================================================

# 与 config.PROVIDER_META 中 group 字段一致
class ProviderGroup(str, Enum):
    GLOBAL = "global"
    CHINA = "china"
    OTHER = "other"


# OpenAI 兼容协议族：走 ChatOpenAI(base_url=...) 的 provider
_OPENAI_COMPATIBLE_PROVIDERS: frozenset = frozenset({
    "openai", "deepseek", "qwen", "zhipu", "moonshot", "minimax",
    "doubao", "hunyuan", "siliconflow",
})


# ============================================================
# Pydantic 数据模型（13.1.4 接口定义）
# ============================================================

if _HAS_PYDANTIC:

    class ProviderMeta(BaseModel):
        """Provider 元信息（label / group / desc）。"""

        model_config = ConfigDict(from_attributes=True)

        label: str = Field(..., description="前端展示名（中文/品牌名）")
        group: ProviderGroup = Field(default=ProviderGroup.OTHER, description="分组：global/china/other")
        desc: str = Field(default="", description="描述说明")

    class ModelInfo(BaseModel):
        """单个模型条目。"""

        model_config = ConfigDict(from_attributes=True)

        id: str = Field(..., description="模型 ID（OpenAI 兼容协议的 model 字段）")
        provider: str = Field(..., description="所属 provider")

        @property
        def qualified_name(self) -> str:  # noqa: D401
            return f"{self.provider}/{self.id}"

    class ProviderInfo(BaseModel):
        """单个 Provider 完整信息（前端卡片 / 下拉项）。"""

        model_config = ConfigDict(from_attributes=True)

        id: str = Field(..., description="provider 标识（env key 后缀 / config 字典 key）")
        label: str = Field(..., description="展示名")
        group: ProviderGroup = Field(default=ProviderGroup.OTHER)
        desc: str = Field(default="")
        configured: bool = Field(default=False, description="是否已配置 API Key")
        base_url: Optional[str] = Field(default=None, description="OpenAI 兼容协议的 base_url；None=走官方")
        models: List[str] = Field(default_factory=list, description="该 provider 支持的模型清单")
        is_openai_compatible: bool = Field(default=False, description="是否走 OpenAI 兼容协议")

    class ApiKeyStatus(BaseModel):
        """API Key 配置状态。"""

        model_config = ConfigDict(from_attributes=True)

        configured: bool
        has_agent: bool
        provider: str
        model: str
        available_providers: List[str]
        provider_keys: Dict[str, bool]

    class ModelsBundle(BaseModel):
        """前端一次性消费的"全部 provider + 模型"快照。"""

        model_config = ConfigDict(from_attributes=True)

        providers: List[ProviderInfo]
        models_by_provider: Dict[str, List[str]]
        current_provider: str
        current_model: str
        provider_meta: Dict[str, ProviderMeta]


# ============================================================
# API Key / base_url 解析（对 config / agent 的薄封装）
# ============================================================

def _env_api_key_for(provider: str) -> str:
    """根据 provider 从 os.environ 读取对应的 API Key（不依赖 config 常量）。

    设计要点：
    - 仅读取"原始 env"，用于热更新场景（用户 set_api_key 后立即生效）；
    - 未配置时返回空串，不抛异常。
    """
    candidates = [
        f"{provider.upper()}_API_KEY",
        # 历史别名兼容：智谱 provider 也可使用 GLM_API_KEY
        "GLM_API_KEY" if provider == "zhipu" else None,
    ]
    for name in candidates:
        if not name:
            continue
        val = os.getenv(name, "")
        if val:
            return val
    return ""


def build_provider_base_url(provider: str) -> Optional[str]:
    """根据 provider 返回对应的 base_url；OpenAI 返回 None 使用官方端点。

    与 agent._build_provider_base_url 完全等价；保留作为公共 API。
    """
    mapping: Dict[str, str] = {
        "deepseek":    "https://api.deepseek.com/v1",
        "qwen":        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "zhipu":       "https://open.bigmodel.cn/api/paas/v4",
        "moonshot":    "https://api.moonshot.cn/v1",
        "minimax":     "https://api.minimax.chat/v1",
        "doubao":      "https://ark.cn-beijing.volces.com/api/v3",
        "hunyuan":     "https://api.hunyuan.tencent.com/v1",
        "siliconflow": "https://api.siliconflow.cn/v1",
    }
    return mapping.get(provider)


def api_key_for_provider(provider: str) -> str:
    """根据 provider 取出对应的 API Key（不依赖 config 模块）。

    与 agent._api_key_for_provider 等价；返回 "" 表示未配置。
    """
    return _env_api_key_for(provider)


# ============================================================
# 注册表（单例）
# ============================================================

class ModelsRegistry:
    """Provider / Model / ApiKey 注册表。

    行为契约：
    - 单例（get_models_registry()），与项目内其他模块保持一致；
    - 不修改 config.MODEL_VERSIONS / PROVIDER_META；仅做读取 + 装配；
    - 暴露 list_providers() / get_provider() / resolve_base_url() / resolve_api_key()
      等公共方法，供 api.py / web_ui.py / 测试脚本使用。
    """

    def __init__(self) -> None:
        # 延迟导入避免循环（config 可能被脚本直接 import）
        from config import MODEL_VERSIONS, PROVIDER_META  # type: ignore

        self._model_versions: Dict[str, List[str]] = dict(MODEL_VERSIONS)
        self._provider_meta: Dict[str, Dict[str, Any]] = {
            k: dict(v) for k, v in PROVIDER_META.items()
        }

    # --------------------- 查询接口 ---------------------

    def list_providers(self) -> List[str]:
        return list(self._model_versions.keys())

    def list_models(self, provider: str) -> List[str]:
        return list(self._model_versions.get(provider, []))

    def get_provider_meta(self, provider: str) -> Dict[str, Any]:
        return dict(self._provider_meta.get(provider, {}))

    def get_provider_group(self, provider: str) -> str:
        return self._provider_meta.get(provider, {}).get("group", "other")

    def is_openai_compatible(self, provider: str) -> bool:
        return provider in _OPENAI_COMPATIBLE_PROVIDERS

    def resolve_base_url(self, provider: str) -> Optional[str]:
        return build_provider_base_url(provider)

    def resolve_api_key(self, provider: str) -> str:
        return _env_api_key_for(provider)

    # --------------------- 装配（带 API Key 状态） ---------------------

    def build_provider_info(
        self, provider: str, configured: Optional[bool] = None
    ) -> "ProviderInfo":
        meta = self._provider_meta.get(provider, {})
        if configured is None:
            configured = bool(self.resolve_api_key(provider))
        base_url = self.resolve_base_url(provider)
        return ProviderInfo(
            id=provider,
            label=meta.get("label", provider),
            group=ProviderGroup(meta.get("group", "other")),
            desc=meta.get("desc", ""),
            configured=configured,
            base_url=base_url,
            models=self.list_models(provider),
            is_openai_compatible=self.is_openai_compatible(provider),
        )

    def build_provider_infos(
        self, key_status: Optional[Dict[str, bool]] = None
    ) -> List["ProviderInfo"]:
        infos: List[ProviderInfo] = []
        for prov in self._model_versions.keys():
            configured = (
                key_status.get(prov)
                if key_status is not None
                else bool(self.resolve_api_key(prov))
            )
            infos.append(self.build_provider_info(prov, configured=configured))
        return infos

    def build_bundle(
        self,
        current_provider: str,
        current_model: str,
        key_status: Optional[Dict[str, bool]] = None,
    ) -> "ModelsBundle":
        providers = self.build_provider_infos(key_status=key_status)
        models_by_provider = {p.id: list(p.models) for p in providers}
        provider_meta_objs: Dict[str, ProviderMeta] = {
            p.id: ProviderMeta(
                label=p.label,
                group=p.group,
                desc=p.desc,
            )
            for p in providers
        }
        return ModelsBundle(
            providers=providers,
            models_by_provider=models_by_provider,
            current_provider=current_provider,
            current_model=current_model,
            provider_meta=provider_meta_objs,
        )


# ============================================================
# 单例与向后兼容 re-export
# ============================================================

_models_registry_instance: Optional[ModelsRegistry] = None


def get_models_registry() -> ModelsRegistry:
    """获取 ModelsRegistry 单例。"""
    global _models_registry_instance
    if _models_registry_instance is None:
        _models_registry_instance = ModelsRegistry()
    return _models_registry_instance


def reset_models_registry() -> None:
    """重置单例（仅测试用）。"""
    global _models_registry_instance
    _models_registry_instance = None


__all__ = [
    # enums
    "ProviderGroup",
    # pydantic models
    "ProviderMeta",
    "ModelInfo",
    "ProviderInfo",
    "ApiKeyStatus",
    "ModelsBundle",
    # helpers
    "build_provider_base_url",
    "api_key_for_provider",
    # registry
    "ModelsRegistry",
    "get_models_registry",
    "reset_models_registry",
]