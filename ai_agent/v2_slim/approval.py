"""
v2.0 slim — approval.py（合并 permission.py + human_in_loop.py）

⚠️ 核心铁律：
- SecurityModule.check_input（security.py）依然是唯一的输入侧安全入口，本模块只
  负责"在 SecurityModule 通过之后"做 HITL 审批。
- 不允许 approval.py 自身去判定"用户输入是否有害"，这是 SecurityModule 的职责。
- permission.py 的 Policy / Role 模型通过 ApprovalGate.policy() 暴露，供后端 API 查询。

合并能力：
1. Role / Policy           来自 permission.py（RBAC）
2. ApprovalGate            来自 human_in_loop.py（HITL 拦截 + 超时）
3. 危险 subcommand 列表     来自 tools_v2.py（code_exec.shell / vcs.commit）
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ============================================================
# 来自 permission.py（保留 RBAC 模型）
# ============================================================

class Role(str, Enum):
    SUPERVISOR = "supervisor"
    WORKER = "worker"
    EXTERNAL = "external"
    ADMIN = "admin"
    OBSERVER = "observer"


@dataclass
class Policy:
    agent_id: str
    roles: List[Role] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    allowed_targets: Optional[List[str]] = None
    allowed_tools: List[str] = field(default_factory=list)
    allowed_workers: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "roles": [r.value for r in self.roles],
            "capabilities": self.capabilities,
            "allowed_targets": self.allowed_targets,
            "allowed_tools": self.allowed_tools,
            "allowed_workers": self.allowed_workers,
        }


@dataclass
class PermissionDecision:
    granted: bool
    reason: str = ""
    policy: Optional[Policy] = None
    matched_rule: str = ""


# ============================================================
# 来自 human_in_loop.py（HITL 拦截点 + 策略 + 决策）
# ============================================================

class HookPoint(str, Enum):
    BEFORE_TOOL_CALL = "before_tool_call"
    BEFORE_DELEGATE = "before_delegate"
    BEFORE_SEND = "before_send"
    FINAL_ANSWER = "final_answer"


class HITLPolicy(str, Enum):
    AUTO = "auto"
    ASK = "ask"
    BLOCK = "block"
    DISABLED = "disabled"


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


@dataclass
class ApprovalRequest:
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    hook_point: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    status: ApprovalDecision = ApprovalDecision.SKIPPED
    decision_payload: Optional[Dict[str, Any]] = None


# ============================================================
# ApprovalGate：合并后的统一入口
# ============================================================

# 来自 tools_v2 的"需要 HITL 审批"白名单
#   - code_exec.shell   任意 shell 命令（破坏性大，必须审批）
#   - vcs.commit        git commit（不可逆，必须审批）
#   - file_ops.delete   文件删除（虽然 validate_safe_path 已拦截敏感路径，
#                       但仍属破坏性操作，HITL 二次把关）
DANGEROUS_SUBCOMMANDS: Set[tuple] = {
    ("code_exec", "shell"),
    ("vcs", "commit"),
    ("file_ops", "delete"),
}


class ApprovalGate:
    """HITL 审批 + RBAC 策略的合并入口。

    流程：
        user_input → SecurityModule.check_input  →  ApprovalGate.evaluate
                                                     ├─ 危险 subcommand? → interrupt
                                                     └─ 普通           → SKIPPED
    """

    _instance: Optional["ApprovalGate"] = None

    def __init__(self, default_policy: HITLPolicy = HITLPolicy.ASK):
        self.default_policy = default_policy
        self._policies: Dict[str, Policy] = {}
        self._pending: Dict[str, ApprovalRequest] = {}
        self._hitl_log: List[ApprovalRequest] = []

    # ---------- 单例 ----------
    @classmethod
    def instance(cls) -> "ApprovalGate":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ---------- Policy（来自 permission.py） ----------
    def register_policy(self, policy: Policy) -> None:
        self._policies[policy.agent_id] = policy
        logger.info("approval: register policy agent_id=%s roles=%s",
                    policy.agent_id, [r.value for r in policy.roles])

    def get_policy(self, agent_id: str) -> Optional[Policy]:
        return self._policies.get(agent_id)

    def evaluate_policy(
        self,
        agent_id: str,
        *,
        capability: Optional[str] = None,
        tool: Optional[str] = None,
        target: Optional[str] = None,
    ) -> PermissionDecision:
        """RBAC 检查：调用方是否有权做这件事。"""
        policy = self._policies.get(agent_id)
        if policy is None:
            # 默认保守：通过但不记录（外部 agent 一律放行）
            return PermissionDecision(granted=True, reason="no policy, default allow")
        if capability and policy.capabilities and capability not in policy.capabilities:
            return PermissionDecision(granted=False, reason=f"capability={capability} not in policy",
                                      policy=policy, matched_rule="capability")
        if tool and policy.allowed_tools and tool not in policy.allowed_tools:
            return PermissionDecision(granted=False, reason=f"tool={tool} not allowed",
                                      policy=policy, matched_rule="allowed_tools")
        if target and policy.allowed_targets and target not in policy.allowed_targets:
            return PermissionDecision(granted=False, reason=f"target={target} not allowed",
                                      policy=policy, matched_rule="allowed_targets")
        return PermissionDecision(granted=True, reason="ok", policy=policy)

    # ---------- HITL（来自 human_in_loop.py） ----------
    def set_default_policy(self, p: HITLPolicy) -> None:
        self.default_policy = p
        logger.info("approval: default_policy=%s", p.value)

    def _is_dangerous(self, tool: str, subcommand: Optional[str]) -> bool:
        if subcommand is None:
            return False
        return (tool, subcommand) in DANGEROUS_SUBCOMMANDS

    async def request_approval(
        self,
        hook_point: HookPoint,
        payload: Dict[str, Any],
        *,
        timeout: float = 30.0,
    ) -> ApprovalDecision:
        """异步请求审批。阻塞直到决策或超时。"""
        if self.default_policy == HITLPolicy.DISABLED:
            return ApprovalDecision.SKIPPED
        if self.default_policy == HITLPolicy.AUTO:
            return ApprovalDecision.APPROVED

        tool = payload.get("tool", "")
        sub = payload.get("subcommand")
        req = ApprovalRequest(
            hook_point=hook_point.value,
            payload=payload,
            description=f"tool={tool} subcommand={sub}",
        )
        self._pending[req.request_id] = req
        logger.info("approval: HITL requested id=%s desc=%s", req.request_id, req.description)

        # 真实接入时此处应 await 一个外部通道（WebSocket / Redis / DB），
        # 此处用 asyncio.wait_for 模拟人类决策；HITLPolicy.ASK 时阻塞至决策或超时。
        try:
            decision = await asyncio.wait_for(
                self._await_decision(req.request_id), timeout=timeout
            )
            req.status = decision
            self._hitl_log.append(req)
            return decision
        except asyncio.TimeoutError:
            req.status = ApprovalDecision.TIMEOUT
            self._hitl_log.append(req)
            return ApprovalDecision.TIMEOUT

    async def _await_decision(self, request_id: str) -> ApprovalDecision:
        """等待外部决策回调。开发态 stub：立刻批准。

        真实部署由 ApprovalBus（外部 WebSocket / Redis pub-sub）通过
        resolve(request_id, decision) 注入。
        """
        await asyncio.sleep(0)
        return ApprovalDecision.APPROVED

    def resolve(self, request_id: str, decision: ApprovalDecision, *, payload: Optional[Dict[str, Any]] = None) -> bool:
        req = self._pending.pop(request_id, None)
        if req is None:
            return False
        req.status = decision
        req.decision_payload = payload
        self._hitl_log.append(req)
        return True

    def evaluate(self, tool: str, subcommand: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
        """同步快速判定：返回 {'requires_approval': bool, 'reason': str}。"""
        if self._is_dangerous(tool, subcommand):
            return {
                "requires_approval": True,
                "reason": f"dangerous subcommand: {tool}.{subcommand}",
            }
        return {"requires_approval": False, "reason": "safe"}

    def history(self) -> List[ApprovalRequest]:
        return list(self._hitl_log)


# ============================================================
# 顶层门面
# ============================================================

def get_approval_gate() -> ApprovalGate:
    return ApprovalGate.instance()