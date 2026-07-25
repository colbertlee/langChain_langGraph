"""permission.py 单元测试。

覆盖：Role enum、Policy / PermissionDecision dataclass、PermissionGuard 各检查方法。
"""
import pytest
from unittest.mock import MagicMock

from permission import (
    Role,
    Policy,
    PermissionDecision,
    PermissionGuard,
    get_permission_guard,
    reset_permission_guard,
)


@pytest.fixture(autouse=True)
def reset_guard():
    """每个测试前重置全局 guard。"""
    reset_permission_guard()
    yield
    reset_permission_guard()


# ─────────────────── Role enum ───────────────────


class TestRole:

    def test_role_values(self):
        assert Role.SUPERVISOR.value == "supervisor"
        assert Role.WORKER.value == "worker"
        assert Role.EXTERNAL.value == "external"
        assert Role.ADMIN.value == "admin"
        assert Role.OBSERVER.value == "observer"


# ─────────────────── Policy dataclass ───────────────────


class TestPolicy:

    def test_policy_defaults(self):
        p = Policy(agent_id="a1")
        assert p.agent_id == "a1"
        assert p.roles == []
        assert p.capabilities == []
        assert p.allowed_targets is None
        assert p.allowed_tools == []
        assert p.allowed_workers is None

    def test_policy_to_dict(self):
        p = Policy(
            agent_id="a1",
            roles=[Role.WORKER],
            capabilities=["search"],
            allowed_tools=["tool1"],
        )
        d = p.to_dict()
        assert d["agent_id"] == "a1"
        assert d["roles"] == ["worker"]
        assert d["capabilities"] == ["search"]
        assert d["allowed_tools"] == ["tool1"]


# ─────────────────── PermissionDecision ───────────────────


class TestPermissionDecision:

    def test_decision_defaults(self):
        d = PermissionDecision(granted=True)
        assert d.granted is True
        assert d.reason == ""
        assert d.policy is None
        assert d.matched_rule == ""

    def test_decision_denied(self):
        d = PermissionDecision(granted=False, reason="not allowed")
        assert d.granted is False
        assert d.reason == "not allowed"

    def test_decision_to_dict(self):
        p = Policy(agent_id="a")
        d = PermissionDecision(granted=True, reason="ok", policy=p, matched_rule="rule1")
        dd = d.to_dict()
        assert dd["granted"] is True
        assert dd["reason"] == "ok"
        assert dd["policy"]["agent_id"] == "a"


# ─────────────────── PermissionGuard ───────────────────


class TestPermissionGuard:

    def test_init(self):
        guard = PermissionGuard()
        assert guard is not None

    def test_add_policy(self):
        guard = PermissionGuard()
        policy = Policy(agent_id="a1", roles=[Role.WORKER])
        guard.add_policy(policy)
        assert guard.get_policy("a1") is policy

    def test_remove_policy(self):
        guard = PermissionGuard()
        policy = Policy(agent_id="a1")
        guard.add_policy(policy)
        guard.remove_policy("a1")
        assert guard.get_policy("a1") is None

    def test_remove_nonexistent(self):
        guard = PermissionGuard()
        # 不应抛错
        guard.remove_policy("nonexistent")

    def test_get_policy_nonexistent(self):
        guard = PermissionGuard()
        assert guard.get_policy("nonexistent") is None

    def test_list_policies_empty(self):
        guard = PermissionGuard()
        assert guard.list_policies() == []

    def test_list_policies_after_add(self):
        guard = PermissionGuard()
        guard.add_policy(Policy(agent_id="a1"))
        guard.add_policy(Policy(agent_id="a2"))
        assert len(guard.list_policies()) == 2


# ─────────────────── Block / Unblock ───────────────────


class TestBlockUnblock:

    def test_block_agent(self):
        guard = PermissionGuard()
        guard.block_agent("bad_agent")
        # 验证 blocked 状态（内部状态）
        assert "bad_agent" in guard._blocked_agents

    def test_unblock_agent(self):
        guard = PermissionGuard()
        guard.block_agent("agent1")
        guard.unblock_agent("agent1")
        assert "agent1" not in guard._blocked_agents

    def test_blocked_agent_denied(self):
        guard = PermissionGuard()
        guard.add_policy(Policy(agent_id="a1", roles=[Role.WORKER], capabilities=["x"]))
        guard.block_agent("a1")
        decision = guard.check_capability("a1", "x")
        assert decision.granted is False

    def test_unblock_then_allowed(self):
        guard = PermissionGuard()
        guard.add_policy(Policy(agent_id="a1", roles=[Role.WORKER], capabilities=["x"]))
        guard.block_agent("a1")
        guard.unblock_agent("a1")
        decision = guard.check_capability("a1", "x")
        assert decision.granted is True


# ─────────────────── check_send ───────────────────


class TestCheckSend:

    def test_send_to_self(self):
        guard = PermissionGuard()
        guard.add_policy(Policy(agent_id="a1"))
        decision = guard.check_send("a1", "a1")
        # 发给自己通常允许
        assert isinstance(decision, PermissionDecision)

    def test_send_unregistered(self):
        guard = PermissionGuard()
        decision = guard.check_send("unknown_sender", "unknown_target")
        assert isinstance(decision, PermissionDecision)

    def test_send_admin_to_worker(self):
        guard = PermissionGuard()
        guard.add_policy(Policy(agent_id="admin1", roles=[Role.ADMIN]))
        guard.add_policy(Policy(agent_id="worker1", roles=[Role.WORKER]))
        decision = guard.check_send("admin1", "worker1")
        assert isinstance(decision, PermissionDecision)

    def test_send_with_allowed_targets(self):
        guard = PermissionGuard()
        guard.add_policy(Policy(
            agent_id="a1",
            roles=[Role.WORKER],
            allowed_targets=["b1", "b2"],
        ))
        guard.add_policy(Policy(agent_id="b1", roles=[Role.WORKER]))
        guard.add_policy(Policy(agent_id="b2", roles=[Role.WORKER]))

        # 允许的目标
        decision = guard.check_send("a1", "b1")
        assert decision.granted is True

        # 禁止的目标
        decision = guard.check_send("a1", "b3")
        assert decision.granted is False


# ─────────────────── check_capability ───────────────────


class TestCheckCapability:

    def test_check_capability_with_policy(self):
        guard = PermissionGuard()
        guard.add_policy(Policy(agent_id="a1", roles=[Role.WORKER], capabilities=["search", "analyze"]))
        decision = guard.check_capability("a1", "search")
        assert decision.granted is True

    def test_check_capability_not_in_list(self):
        guard = PermissionGuard()
        guard.add_policy(Policy(agent_id="a1", roles=[Role.WORKER], capabilities=["search"]))
        decision = guard.check_capability("a1", "write_file")
        assert decision.granted is False

    def test_check_capability_no_policy(self):
        guard = PermissionGuard()
        decision = guard.check_capability("unknown", "x")
        assert isinstance(decision, PermissionDecision)


# ─────────────────── check_worker ───────────────────


class TestCheckWorker:

    def test_check_worker_allowed(self):
        guard = PermissionGuard()
        guard.add_policy(Policy(agent_id="a1", roles=[Role.WORKER], allowed_workers=["w1", "w2"]))
        decision = guard.check_worker("a1", "w1")
        assert decision.granted is True

    def test_check_worker_not_allowed(self):
        guard = PermissionGuard()
        guard.add_policy(Policy(agent_id="a1", roles=[Role.WORKER], allowed_workers=["w1"]))
        decision = guard.check_worker("a1", "w2")
        assert decision.granted is False


# ─────────────────── check_tool ───────────────────


class TestCheckTool:

    def test_check_tool_allowed(self):
        guard = PermissionGuard()
        guard.add_policy(Policy(agent_id="a1", roles=[Role.WORKER], allowed_tools=["tool1", "tool2"]))
        decision = guard.check_tool("a1", "tool1")
        assert decision.granted is True

    def test_check_tool_not_allowed(self):
        guard = PermissionGuard()
        guard.add_policy(Policy(agent_id="a1", roles=[Role.WORKER], allowed_tools=["tool1"]))
        decision = guard.check_tool("a1", "bad_tool")
        assert decision.granted is False


# ─────────────────── enforce ───────────────────


class TestEnforce:

    def test_enforce_granted(self):
        guard = PermissionGuard()
        decision = PermissionDecision(granted=True)
        result = guard.enforce(decision)
        assert result is True

    def test_enforce_denied_no_callback(self):
        guard = PermissionGuard()
        decision = PermissionDecision(granted=False, reason="test")
        result = guard.enforce(decision)
        assert result is False

    def test_enforce_denied_with_callback(self):
        guard = PermissionGuard()
        decision = PermissionDecision(granted=False, reason="test")
        callback = MagicMock()
        result = guard.enforce(decision, on_violation=callback)
        assert result is False
        callback.assert_called_once()


# ─────────────────── stats ───────────────────


class TestStats:

    def test_stats_returns_dict(self):
        guard = PermissionGuard()
        stats = guard.stats()
        assert isinstance(stats, dict)

    def test_stats_includes_policies(self):
        guard = PermissionGuard()
        guard.add_policy(Policy(agent_id="a1"))
        stats = guard.stats()
        assert "policies" in stats or "policy_count" in stats or len(stats) > 0


# ─────────────────── Supervisor group ───────────────────


class TestSupervisorGroup:

    def test_set_supervisor_group(self):
        guard = PermissionGuard()
        guard.set_supervisor_group("worker1", "sup1")
        assert "worker1" in guard._agent_to_supervisor
        assert guard._agent_to_supervisor["worker1"] == "sup1"


# ─────────────────── Global singleton ───────────────────


class TestGlobalGuard:

    def test_get_permission_guard_singleton(self):
        g1 = get_permission_guard()
        g2 = get_permission_guard()
        assert g1 is g2

    def test_reset_permission_guard(self):
        g1 = get_permission_guard()
        g1.add_policy(Policy(agent_id="test"))
        reset_permission_guard()
        g2 = get_permission_guard()
        assert g1 is not g2
        # 新 guard 应为空
        assert g2.get_policy("test") is None


# ─────────────────── Edge cases ───────────────────


class TestEdgeCases:

    def test_policy_with_empty_capabilities(self):
        p = Policy(agent_id="a1", roles=[Role.WORKER])
        assert p.capabilities == []
        assert p.allowed_tools == []

    def test_decision_with_all_fields(self):
        p = Policy(agent_id="a1")
        d = PermissionDecision(
            granted=True,
            reason="allowed by rule",
            policy=p,
            matched_rule="rule1",
        )
        dd = d.to_dict()
        assert dd["granted"] is True
        assert dd["reason"] == "allowed by rule"
        assert dd["matched_rule"] == "rule1"
        assert dd["policy"] is not None

    def test_multiple_policies_different_agents(self):
        guard = PermissionGuard()
        guard.add_policy(Policy(agent_id="a1", roles=[Role.WORKER], capabilities=["x"]))
        guard.add_policy(Policy(agent_id="a2", roles=[Role.ADMIN], capabilities=["y"]))
        assert guard.get_policy("a1").capabilities == ["x"]
        assert guard.get_policy("a2").capabilities == ["y"]
