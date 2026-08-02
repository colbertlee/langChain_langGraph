"""
权限与隔离（Permission / Isolation）

提供：
- Role         角色（如 Supervisor / Worker / External / Admin）
- Policy       策略：定义"agent_id → roles / capabilities / 允许的 targets"
- PermissionGuard  权限拦截器：在 message_bus / worker / tool 等接入点检查

模型（简化的 RBAC + ACL）：
    Agent ----- 拥有 -> Roles
    Role   ----- 包含 -> Capabilities（search/code/...）
    Role   ----- 允许 -> Targets（可发消息到的 agent_ids / 可调用工具 / 可使用 capability）

默认策略：
- supervisor 角色可发消息到任何 worker
- worker 角色只能发到 supervisor / 同组 worker
- external 角色默认无任何 capability

拦截点：
1. MessageBus.send：检查 sender 是否在 receiver 的允许列表
2. Worker.execute_task：检查调用方 agent_id 是否有权用此 capability
3. ToolEngine.invoke：检查调用方 agent_id 是否有权用此 tool
"""

import logging
import uuid
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger(__name__)


# ============================================================
# Role / Permission 模型
# ============================================================

class Role(str, Enum):
    """预定义角色"""
    SUPERVISOR = "supervisor"        # 主编排 Agent
    WORKER = "worker"                # 工人 Agent
    EXTERNAL = "external"            # 外部 Agent（如其他系统的接口）
    ADMIN = "admin"                  # 管理 Agent
    OBSERVER = "observer"            # 观察者（只读）


@dataclass
class Policy:
    """策略"""
    agent_id: str
    roles: List[Role] = field(default_factory=list)
    # 该 agent 能调用的 capability 列表
    capabilities: List[str] = field(default_factory=list)
    # 该 agent 能 send 给哪些 agent_id（None = 默认按角色推断）
    allowed_targets: Optional[List[str]] = None
    # 该 agent 能用哪些 tools
    allowed_tools: List[str] = field(default_factory=list)
    # 该 agent 能用哪些 worker 类型（甚至具体 worker_id）
    allowed_workers: Optional[List[str]] = None

    def to_dict(self) -> Dict:
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
    """权限判定结果"""
    granted: bool
    reason: str = ""
    policy: Optional[Policy] = None
    matched_rule: str = ""

    def to_dict(self) -> Dict:
        return {
            "granted": self.granted,
            "reason": self.reason,
            "matched_rule": self.matched_rule,
            "policy": self.policy.to_dict() if self.policy else None,
        }


# ============================================================
# PermissionGuard（总控）
# ============================================================

class PermissionGuard:
    """
    权限守卫

    持有所有 agent 的 policy + 角色规则。
    提供 check_* 系列方法给各拦截点调用。
    """

    def __init__(self):
        self._policies: Dict[str, Policy] = {}
        self._lock = Lock()
        # 全局拒绝列表：blocklist
        self._blocked_agents: Set[str] = set()
        # 角色默认能力（角色 → 默认 capability 集合）
        self._role_defaults: Dict[Role, List[str]] = {
            Role.SUPERVISOR: ["search", "code", "analysis", "write", "calculate", "translate", "negotiation", "auction"],
            Role.WORKER: [],  # 工作 Agent 默认无额外能力，capabilities 来自业务
            Role.EXTERNAL: [],
            Role.ADMIN: ["*"],
            Role.OBSERVER: [],  # 只读，无 capability
        }
        # 角色默认允许的目标（role → 默认 allowed_targets 表达式）
        # '*' = 任何；'same_supervisor' = 同 supervisor 下；其它 = explicit list
        self._role_target_rules: Dict[Role, str] = {
            Role.SUPERVISOR: "*",
            Role.WORKER: "supervisor_or_same_group",
            Role.EXTERNAL: "explicit_only",
            Role.ADMIN: "*",
            Role.OBSERVER: "explicit_only",
        }
        # 同 group（按 supervisor_id 划）映射
        self._agent_to_supervisor: Dict[str, str] = {}

        # 回调：denied 时调用
        self.on_denied: Optional[Callable[[str, str, Any], None]] = None

        # 外部 AuthProvider（plugin 注入，可选；不强制使用）
        #   - 缓存：(credentials_hash) -> AuthPrincipal
        #   - 缓存命中后仍走本地 policy 做 send/capability 检查
        self._auth_provider = None
        self._auth_principal_cache: Dict[str, Any] = {}

    # ----------------- Auth Provider (plugin) -----------------

    def set_auth_provider(self, provider) -> None:
        """注入外部 AuthProvider（来自 plugin）。"""
        self._auth_provider = provider
        self._auth_principal_cache.clear()

    def authenticate(self, credentials) -> Any:
        """把外部凭证解析为 AuthPrincipal；无 provider / 失败返回 None。"""
        if self._auth_provider is None:
            return None
        try:
            key = repr(credentials)
        except Exception:
            key = id(credentials)
        if key in self._auth_principal_cache:
            return self._auth_principal_cache[key]
        principal = self._auth_provider.resolve(credentials)
        if principal is not None:
            self._auth_principal_cache[key] = principal
            # 同步给本地 policy（覆盖默认空 policy）
            self._policies.setdefault(
                principal.agent_id,
                Policy(agent_id=principal.agent_id, roles=[
                    # string -> Role 兼容；plugin 给出字符串时仅做"原样保留"
                    r for r in principal.roles if hasattr(Role, "_value_") or True
                ]),
            )
        return principal

    # ----------------- 策略管理 -----------------

    def add_policy(self, policy: Policy) -> None:
        with self._lock:
            self._policies[policy.agent_id] = policy
            logger.info(
                f"[Permission] Policy set for {policy.agent_id}: "
                f"roles={[r.value for r in policy.roles]}, caps={policy.capabilities[:3]}..."
            )

    def remove_policy(self, agent_id: str) -> None:
        with self._lock:
            self._policies.pop(agent_id, None)

    def get_policy(self, agent_id: str) -> Optional[Policy]:
        return self._policies.get(agent_id)

    def block_agent(self, agent_id: str) -> None:
        self._blocked_agents.add(agent_id)

    def unblock_agent(self, agent_id: str) -> None:
        self._blocked_agents.discard(agent_id)

    def set_supervisor_group(self, agent_id: str, supervisor_id: str) -> None:
        """把 agent 标记为某 supervisor 的子节点（用于决定同组）"""
        self._agent_to_supervisor[agent_id] = supervisor_id

    # ----------------- 检查 API -----------------

    def check_send(
        self,
        sender_id: str,
        receiver_id: str,
    ) -> PermissionDecision:
        """检查 sender 能否向 receiver 发消息"""
        # 全局 blocklist
        if sender_id in self._blocked_agents:
            return PermissionDecision(False, f"sender {sender_id} is blocked")

        sender_policy = self._policies.get(sender_id)
        if not sender_policy:
            # 默认放行（无策略 = 友好模式）
            return PermissionDecision(True, "no_policy_specified, default_allow", matched_rule="default_allow")

        # 显式 allowed_targets
        if sender_policy.allowed_targets is not None:
            if receiver_id in sender_policy.allowed_targets or "*" in sender_policy.allowed_targets:
                return PermissionDecision(True, "explicit_target_allowed", sender_policy, matched_rule="allowed_targets")
            return PermissionDecision(
                False,
                f"sender {sender_id} not allowed to send to {receiver_id}",
                sender_policy,
                matched_rule="denied",
            )

        # 按角色规则推断
        for role in sender_policy.roles:
            rule = self._role_target_rules.get(role, "explicit_only")
            if rule == "*":
                return PermissionDecision(True, f"role {role.value} allows any", sender_policy, matched_rule=f"role:{role.value}")
            if rule == "supervisor_or_same_group":
                # receiver 是 supervisor 或同组
                send_sup = self._agent_to_supervisor.get(sender_id)
                recv_sup = self._agent_to_supervisor.get(receiver_id)
                # worker 给自己组的 supervisor
                if send_sup and receiver_id == send_sup:
                    return PermissionDecision(True, "to_own_supervisor", sender_policy, matched_rule=f"role:{role.value}")
                # 同组 worker
                if send_sup and recv_sup and send_sup == recv_sup:
                    return PermissionDecision(True, "same_group", sender_policy, matched_rule=f"role:{role.value}")
                # receiver 是 supervisor role（纯角色判断）
                if Role.SUPERVISOR in (self._policies.get(receiver_id, Policy(agent_id="")).roles or []):
                    # 这里其实更准确的判断是看 receiver 的角色，需要到 _policies 查
                    rec_pol = self._policies.get(receiver_id)
                    if rec_pol and Role.SUPERVISOR in rec_pol.roles:
                        return PermissionDecision(True, "to_supervisor", sender_policy, matched_rule=f"role:{role.value}")

        return PermissionDecision(
            False,
            f"role rules deny send to {receiver_id}",
            sender_policy,
            matched_rule="role_rules",
        )

    def check_capability(
        self,
        sender_id: str,
        capability: str,
    ) -> PermissionDecision:
        """检查 sender 是否有权调用 capability"""
        if sender_id in self._blocked_agents:
            return PermissionDecision(False, f"sender {sender_id} is blocked")

        policy = self._policies.get(sender_id)
        if not policy:
            return PermissionDecision(True, "no_policy_default_allow", matched_rule="default_allow")

        # Admin 通配
        if Role.ADMIN in policy.roles and "*" in policy.capabilities:
            return PermissionDecision(True, "admin_role", policy, matched_rule="role:admin")

        # 显式 capability
        if capability in policy.capabilities or "*" in policy.capabilities:
            return PermissionDecision(True, "explicit_capability_allowed", policy, matched_rule="allowed_caps")

        # 角色默认能力
        for role in policy.roles:
            defaults = self._role_defaults.get(role, [])
            if capability in defaults or "*" in defaults:
                return PermissionDecision(True, f"role {role.value} default allows", policy, matched_rule=f"role:{role.value}")

        return PermissionDecision(
            False,
            f"sender {sender_id} not allowed to use capability '{capability}'",
            policy,
            matched_rule="no_cap_match",
        )

    def check_worker(
        self,
        caller_id: str,
        worker_id: str,
        worker_capability: str = "",
    ) -> PermissionDecision:
        """检查 caller 能否使用 worker"""
        if caller_id in self._blocked_agents:
            return PermissionDecision(False, f"caller {caller_id} is blocked")

        policy = self._policies.get(caller_id)
        if not policy:
            return PermissionDecision(True, "no_policy_default_allow", matched_rule="default_allow")

        # Admin 可用任何 worker
        if Role.ADMIN in policy.roles:
            return PermissionDecision(True, "admin_role", policy, matched_rule="role:admin")

        # 检查 allowed_workers（None 或不设置 = 默认按角色）
        if policy.allowed_workers is not None:
            if worker_id in policy.allowed_workers or "*" in policy.allowed_workers:
                return PermissionDecision(True, "explicit_worker_allowed", policy, matched_rule="allowed_workers")
            else:
                return PermissionDecision(
                    False,
                    f"caller {caller_id} not allowed to use worker {worker_id}",
                    policy,
                    matched_rule="denied",
                )

        # 检查 capability 权限
        if worker_capability:
            cap_decision = self.check_capability(caller_id, worker_capability)
            return cap_decision

        return PermissionDecision(True, "no_restriction", policy, matched_rule="default_allow")

    def check_tool(
        self,
        caller_id: str,
        tool_name: str,
    ) -> PermissionDecision:
        """检查 caller 能否使用 tool"""
        if caller_id in self._blocked_agents:
            return PermissionDecision(False, f"caller {caller_id} is blocked")

        policy = self._policies.get(caller_id)
        if not policy:
            return PermissionDecision(True, "no_policy_default_allow", matched_rule="default_allow")

        # Admin 通配
        if Role.ADMIN in policy.roles:
            return PermissionDecision(True, "admin_role", policy, matched_rule="role:admin")

        if tool_name in policy.allowed_tools or "*" in policy.allowed_tools:
            return PermissionDecision(True, "tool_allowed", policy, matched_rule="allowed_tools")

        return PermissionDecision(
            False,
            f"caller {caller_id} not allowed to use tool '{tool_name}'",
            policy,
            matched_rule="no_tool_match",
        )

    # ----------------- 装饰器 / 拦截 -----------------

    def enforce(self, decision: PermissionDecision, on_violation: Optional[Callable] = None) -> bool:
        """统一的违规处理入口"""
        if decision.granted:
            return True
        logger.warning(
            f"[Permission DENIED] {decision.reason} (rule={decision.matched_rule})"
        )
        if self.on_denied:
            try:
                self.on_denied(decision.matched_rule, decision.reason, decision.policy)
            except Exception:
                pass
        if on_violation:
            try:
                on_violation(decision)
            except Exception:
                pass
        return False

    # ----------------- 状态查询 -----------------

    def list_policies(self) -> List[Policy]:
        return list(self._policies.values())

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            n = len(self._policies)
        return {
            "policies_count": n,
            "blocked_agents": list(self._blocked_agents),
            "supervisor_groups": dict(self._agent_to_supervisor),
            "role_defaults": {r.value: caps for r, caps in self._role_defaults.items()},
        }


# ============================================================
# 全局单例 + 预设
# ============================================================

_permission_guard: Optional[PermissionGuard] = None

# 需要 HITL 审批的工具集合(跨 agent 全局生效)。
# dispatcher(如 minimax MCP)在调用前自查,若在集合中则先返回"已入队审批"占位,
# 让上层走 human_in_loop 流程。
_REQUIRE_APPROVAL_TOOLS: Set[str] = set()

# 默认需要审批的 minimax MCP 工具:会产生外部副作用或付费
DEFAULT_REQUIRE_APPROVAL_TOOLS: Set[str] = {
    "minimax_voice_clone",
    "minimax_voice_design",
    "minimax_play_audio",
    "minimax_music_generation",
    "minimax_generate_video",
    "minimax_image_to_video",
    "minimax_text_to_image",
}


def get_permission_guard() -> PermissionGuard:
    """获取全局 PermissionGuard 单例"""
    global _permission_guard
    if _permission_guard is None:
        _permission_guard = PermissionGuard()
        _apply_default_policies(_permission_guard)
    return _permission_guard


def reset_permission_guard() -> None:
    """重置(测试用)"""
    global _permission_guard
    _permission_guard = None
    global _REQUIRE_APPROVAL_TOOLS
    _REQUIRE_APPROVAL_TOOLS = set()


def require_approval_tools() -> Set[str]:
    """获取当前所有需要 HITL 审批的工具名"""
    return set(_REQUIRE_APPROVAL_TOOLS)


def add_require_approval_tool(tool_name: str) -> None:
    """把工具加入审批清单"""
    _REQUIRE_APPROVAL_TOOLS.add(tool_name)


def remove_require_approval_tool(tool_name: str) -> None:
    """从审批清单移除"""
    _REQUIRE_APPROVAL_TOOLS.discard(tool_name)


def is_require_approval(tool_name: str) -> bool:
    """工具是否需要审批"""
    return tool_name in _REQUIRE_APPROVAL_TOOLS


def _apply_default_policies(guard: PermissionGuard) -> None:
    """应用默认策略(开发环境常用)"""
    # 默认情况下:
    # - main agent 有 supervisor 角色(任意 capability)
    # - workers 是 worker 角色(受组约束)
    # 默认不强制,注册 policy 时启用
    # 同时把 minimax 高危工具加入审批集合
    _REQUIRE_APPROVAL_TOOLS.update(DEFAULT_REQUIRE_APPROVAL_TOOLS)
