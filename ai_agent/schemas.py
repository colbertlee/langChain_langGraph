"""API Schema 层（Day 8-9 + Day 15）。

把所有 ``/api/*`` 端点进出的 JSON 结构集中到 Pydantic v2 模型。

设计目标
~~~~~~~~
1. **类型即文档**：前端只读这个文件就能拿到全部类型。
2. **运行时校验**：模型校验失败时由 FastAPI 自动返回 422，前端可解析错误定位。
3. **OpenAPI 自动暴露**：所有 Pydantic 模型挂到 ``/openapi.json``，第三方工具可直接消费。
4. **全局 ``_Base`` 容纳多字段容错**：前端加字段不会 422。

覆盖策略（Day 15 全面铺开）
~~~~~~~~~~~~~~~~~~~~~~~~~~~
本文件已覆盖几乎所有 ``/api/*`` 端点的入参 / 出参模型：

- 第一批（Day 8-9）：高频变动的 ``/api/chat``、``/api/clear``、``/api/api-key``、``/api/model/switch``、``/api/memory/*``、``/api/prompts/*``
- 第二批（Day 15）：WebSocket / SSE / Upload / HITL / Plan / Policy / Doctor / Evals

新接入原则：所有 *新* 端点必须先在本文档定义 schema，再写 endpoint。
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ============================================================
# 公共枚举 / 字面量
# ============================================================

ProviderId = Literal[
    "openai", "deepseek", "qwen", "zhipu", "moonshot", "minimax",
    "baidu", "spark", "doubao", "hunyuan", "siliconflow",
]


# ============================================================
# 基础模型
# ============================================================

class _Base(BaseModel):
    """所有 API schema 的基类。

    - ``extra="allow"``：接收多余字段（向前兼容）
    - ``populate_by_name=True``：允许 input ``sessionId`` 映射到 ``session_id``
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_aliases(cls, data: Any) -> Any:
        """同步老 API 用法：如 ``model_name`` ↔ ``model``。"""
        if isinstance(data, dict):
            if "model_name" not in data and "model" in data:
                data["model_name"] = data["model"]
            elif "model" not in data and "model_name" in data:
                data["model"] = data["model_name"]
        return data


# ============================================================
# /api/chat · /api/chat/stream
# ============================================================

class ChatRequest(_Base):
    """``POST /api/chat`` 与 ``POST /api/chat/stream`` 的请求体。"""
    message: str = Field(..., description="用户原始输入（必填）", min_length=1, max_length=100_000)
    session_id: Optional[str] = Field(default=None, alias="sessionId", description="会话 id")

    @field_validator("message")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("message 不能为空或纯空白")
        return v


class ChatResponse(_Base):
    response: str
    session_id: Optional[str] = Field(default=None, alias="sessionId")
    provider: Optional[str] = None
    model: Optional[str] = None
    trace_id: Optional[str] = Field(default=None, alias="traceId")
    degraded: bool = False
    tools_called: List[str] = Field(default_factory=list, alias="toolsCalled")


# ============================================================
# SSE / WebSocket
# ============================================================

class SseChatRequest(_Base):
    """``POST /api/chat/stream``（SSE）的请求体。"""
    message: str = Field(..., min_length=1, max_length=100_000)
    session_id: Optional[str] = Field(default=None, alias="sessionId")


class WsChatMessage(_Base):
    """``WS /api/chat/stream`` 的入站消息。"""
    message: str = Field(..., min_length=1, max_length=100_000)
    session_id: Optional[str] = Field(default=None, alias="sessionId")
    model: Optional[str] = None
    stream: bool = True


class WsChatOutEvent(_Base):
    type: Literal[
        "start", "chunk", "complete", "error",
        "reset", "safety", "thinking", "tool_call", "degraded",
    ]
    data: str = ""
    name: Optional[str] = None
    session_id: Optional[str] = Field(default=None, alias="sessionId")
    trace_id: Optional[str] = Field(default=None, alias="traceId")
    status: Optional[str] = None


class WsErrorEvent(_Base):
    type: Literal["error"]
    error: str
    session_id: Optional[str] = Field(default=None, alias="sessionId")


# ============================================================
# /api/clear
# ============================================================

class ClearResponse(_Base):
    message: str
    cleared: List[str] = Field(default_factory=list)


# ============================================================
# /api/api-key · /api/model/switch
# ============================================================

class ApiKeyRequest(_Base):
    api_key: str = Field(..., alias="apiKey", min_length=1, max_length=4096)
    provider: Optional[ProviderId] = Field(default="openai")


class ApiKeyStatusResponse(_Base):
    configured: bool
    has_agent: bool = Field(alias="hasAgent")
    provider: str
    model: str
    available_providers: List[str] = Field(default_factory=list, alias="availableProviders")
    provider_keys: Dict[str, bool] = Field(default_factory=dict, alias="providerKeys")


class ModelSwitchRequest(_Base):
    provider: ProviderId
    model_name: Optional[str] = Field(default=None, alias="modelName")
    model: Optional[str] = None


class ModelSwitchResponse(_Base):
    success: bool
    provider: str
    model: str
    message: Optional[str] = None


class ProviderInfo(_Base):
    id: str
    label: str
    group: str
    desc: str = ""
    configured: bool
    models: List[str]


class ModelsResponse(_Base):
    providers: List[ProviderInfo]
    current_provider: str = Field(alias="currentProvider")
    current_model: str = Field(alias="currentModel")
    models_by_provider: Dict[str, List[str]] = Field(default_factory=dict, alias="modelsByProvider")
    provider_meta: Dict[str, Any] = Field(default_factory=dict, alias="providerMeta")


# ============================================================
# /api/memory/*
# ============================================================

class MemoryAddRequest(_Base):
    content: str = Field(..., min_length=1, max_length=100_000)
    importance: Optional[int] = Field(default=3, ge=0, le=10)
    intent: Optional[str] = None
    session_id: Optional[str] = Field(default=None, alias="sessionId")


class MemoryRememberRequest(_Base):
    """``/api/memory/remember`` 的 key/value 风格请求体。"""
    key: str = Field(..., min_length=1, max_length=200)
    value: Any
    memory_type: str = Field(default="fact", alias="memoryType")
    scope: str = Field(default="global")
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    expires_in_seconds: Optional[float] = Field(default=None, alias="expiresInSeconds", ge=0)
    tags: Optional[List[str]] = None


class MemorySaveRequest(_Base):
    session_id: Optional[str] = Field(default=None, alias="sessionId")
    content: Dict[str, Any]


class MemoryLoadResponse(_Base):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    count: int = 0


class MemoryListItem(_Base):
    id: str
    content: str
    importance: int
    intent: Optional[str] = None
    session_id: Optional[str] = Field(default=None, alias="sessionId")
    created_at: Optional[str] = Field(default=None, alias="createdAt")


class MemoryListResponse(_Base):
    items: List[MemoryListItem] = Field(default_factory=list)
    total: int = 0


class MemoryForgetResponse(_Base):
    removed: bool
    memory_id: str = Field(alias="memoryId")


class MemoryRecallItem(_Base):
    id: str
    content: str
    importance: int
    intent: Optional[str] = None
    session_id: Optional[str] = Field(default=None, alias="sessionId")
    created_at: Optional[str] = Field(default=None, alias="createdAt")


class MemoryRecallResponse(_Base):
    query: str
    context: str = ""
    items: List[MemoryRecallItem] = Field(default_factory=list)


class MemorySearchRequest(_Base):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=100, alias="topK")


class MemorySearchResponse(_Base):
    items: List[MemoryRecallItem] = Field(default_factory=list)


class MemoryStatsResponse(_Base):
    total: int = 0
    by_intent: Dict[str, int] = Field(default_factory=dict, alias="byIntent")
    by_importance: Dict[str, int] = Field(default_factory=dict, alias="byImportance")


# ============================================================
# /api/upload
# ============================================================

class UploadResponse(_Base):
    """``POST /api/upload`` 的响应。"""
    name: str
    url: str
    size: int = Field(ge=0)


class FileInfo(_Base):
    """``GET /api/files/{name}`` 的响应。"""
    name: str
    size: int = Field(ge=0)
    content_type: str = Field(default="application/octet-stream", alias="contentType")
    url: str


# ============================================================
# /api/prompts · /api/user-prompts
# ============================================================

class PromptInfo(_Base):
    name: str
    version: str
    is_active: bool = Field(alias="isActive")


class PromptsListResponse(_Base):
    prompts: List[PromptInfo] = Field(default_factory=list)
    active: Optional[str] = None


class PromptRollbackRequest(_Base):
    name: str
    version: str


class UserPromptRollbackRequest(_Base):
    name: str
    version: Optional[str] = None
    target_version: Optional[str] = Field(default=None, alias="targetVersion")


class UserPromptRegisterRequest(_Base):
    name: str
    content: Dict[str, Any]


class UserPromptRenderRequest(_Base):
    name: str = "default"
    user_input: str = Field(..., alias="userInput", min_length=1)
    context: Optional[str] = None
    variables: Optional[Dict[str, Any]] = None


class UserPromptRenderResponse(_Base):
    rendered: str


# ============================================================
# /api/plan · /api/policy · /api/permission · /api/hitl
# ============================================================

class PlanRequest(_Base):
    goal: str = Field(..., min_length=1, max_length=10_000)
    session_id: Optional[str] = Field(default=None, alias="sessionId")


class PolicyRequest(_Base):
    agent_id: str = Field(..., alias="agentId")
    roles: Optional[List[str]] = None
    capabilities: Optional[List[str]] = None
    allowed_targets: Optional[List[str]] = Field(default=None, alias="allowedTargets")
    allowed_tools: Optional[List[str]] = Field(default=None, alias="allowedTools")
    allowed_workers: Optional[List[str]] = Field(default=None, alias="allowedWorkers")


class PermissionEnforceRequest(_Base):
    enforce: bool


class HITLDecision(_Base):
    request_id: str = Field(..., alias="requestId")
    status: Literal["approved", "denied", "pending"]
    decided_by: str = Field(default="human", alias="decidedBy")
    decision_payload: Optional[Dict[str, Any]] = Field(default=None, alias="decisionPayload")
    notes: str = ""


class HITLHistoryItem(_Base):
    id: str
    status: str
    decided_at: Optional[str] = Field(default=None, alias="decidedAt")
    decided_by: Optional[str] = Field(default=None, alias="decidedBy")


class HITLStatsResponse(_Base):
    total_pending: int = Field(alias="totalPending")
    total_approved: int = Field(alias="totalApproved")
    total_denied: int = Field(alias="totalDenied")
    by_kind: Dict[str, int] = Field(default_factory=dict, alias="byKind")


# ============================================================
# /api/health · /api/doctor · /api/evals
# ============================================================

class HealthResponse(_Base):
    status: Literal["ok", "degraded", "down"] = "ok"
    version: str
    uptime_seconds: float = Field(alias="uptimeSeconds")
    components: Dict[str, Literal["ok", "degraded", "down"]] = Field(default_factory=dict)


class DoctorCheckItem(_Base):
    name: str
    status: Literal["ok", "warn", "fail"]
    message: str
    fix: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class DoctorSummary(_Base):
    ok: int = 0
    warn: int = 0
    fail: int = 0


class DoctorResponse(_Base):
    """``GET /api/doctor`` 的响应。"""
    exit_code: int = Field(alias="exitCode")
    checks: List[DoctorCheckItem] = Field(default_factory=list)
    summary: DoctorSummary


class EvalsRunRequest(_Base):
    """``POST /api/evals/run`` 的请求体。"""
    case: Optional[str] = None
    all: bool = False


class EvalsCaseSummary(_Base):
    started_at: str = Field(alias="startedAt")
    finished_at: str = Field(alias="finishedAt")
    cases_total: int = Field(alias="casesTotal")
    cases_passed: int = Field(alias="casesPassed")
    cases_failed: int = Field(alias="casesFailed")
    cases_errored: int = Field(alias="casesErrored", default=0)


class EvalsRunResponse(_Base):
    exit_code: int = Field(alias="exitCode")
    latest_run: Optional[str] = Field(default=None, alias="latestRun")
    summary: Optional[EvalsCaseSummary] = None


class EvalsHistoryItem(_Base):
    id: str
    started_at: Optional[str] = Field(default=None, alias="startedAt")
    finished_at: Optional[str] = Field(default=None, alias="finishedAt")
    total: int = 0
    passed: int = 0
    failed: int = 0


class EvalsHistoryResponse(_Base):
    runs: List[EvalsHistoryItem] = Field(default_factory=list)


# ============================================================
# 错误响应统一形态
# ============================================================

class ErrorBody(_Base):
    """所有错误响应的标准体（HTTPException / RequestValidationError）。"""
    detail: Any


__all__ = [
    "_Base",
    "ProviderId",
    # chat
    "ChatRequest", "ChatResponse", "ClearResponse",
    # WS / SSE
    "SseChatRequest", "WsChatMessage", "WsChatOutEvent", "WsErrorEvent",
    # api-key
    "ApiKeyRequest", "ApiKeyStatusResponse",
    "ModelSwitchRequest", "ModelSwitchResponse",
    "ProviderInfo", "ModelsResponse",
    # memory
    "MemoryAddRequest", "MemoryRememberRequest",
    "MemorySaveRequest", "MemoryLoadResponse",
    "MemoryListItem", "MemoryListResponse",
    "MemoryForgetResponse",
    "MemoryRecallItem", "MemoryRecallResponse",
    "MemorySearchRequest", "MemorySearchResponse",
    "MemoryStatsResponse",
    # upload
    "UploadResponse", "FileInfo",
    # prompts
    "PromptInfo", "PromptsListResponse",
    "PromptRollbackRequest", "UserPromptRollbackRequest",
    "UserPromptRegisterRequest", "UserPromptRenderRequest",
    "UserPromptRenderResponse",
    # plan / policy
    "PlanRequest", "PolicyRequest", "PermissionEnforceRequest",
    # HITL
    "HITLDecision", "HITLHistoryItem", "HITLStatsResponse",
    # health / doctor / evals / error
    "HealthResponse",
    "DoctorCheckItem", "DoctorSummary", "DoctorResponse",
    "EvalsRunRequest", "EvalsCaseSummary", "EvalsRunResponse",
    "EvalsHistoryItem", "EvalsHistoryResponse",
    "ErrorBody",
]
