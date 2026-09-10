"""
test_hitl_approval.py — v2.2.1 Human-in-the-loop (HITL) 拦截与人工批准 / 拒绝测试

覆盖：
  - HITLStore: request / approve / reject / list / consume 状态机
  - python_interpreter 必须被标记 requires_approval=True（v21_tools registry）
  - 工具拦截流：
      * 首次调用 → 创建 pending，写 sentinel
      * approve 后再次调用 → 真正执行 inner tool
      * reject 后再次调用 → 返回 "Action cancelled by user" 消息
  - /api/chat/approve 与 /api/chat/reject FastAPI 端点
  - /api/hitl/v2/pending 端点
  - 幂等：重复 approve 抛 409
  - 跨 session 隔离：approve session A 不会影响 session B
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ============================================================
# 通用 fixture
# ============================================================

@pytest.fixture
def isolated_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-for-tests-only")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake-key")
    monkeypatch.setenv("AI_AGENT_DISABLE_PLACEHOLDER_CHECK", "1")
    monkeypatch.setenv("AI_AGENT_INMEM_CHECKPOINT", "1")  # checkpointer 走内存即可
    yield


@pytest.fixture
def fresh_hitl_store():
    """每个测试独立 HITLStore 实例（不污染全局单例）。"""
    from hitl_langgraph import HITLStore
    HITLStore.reset_instance()
    yield HITLStore
    HITLStore.reset_instance()


# ============================================================
# 1) HITLStore 状态机
# ============================================================

def test_hitl_store_request_then_list(fresh_hitl_store, tmp_path):
    """请求审批后必须能在 list_pending 中看到。"""
    store = fresh_hitl_store.instance()
    req = store.request_approval(
        session_id="sess-A",
        tool_name="python_interpreter",
        tool_args={"code": "print(1)"},
        reason="test reason",
    )
    assert req.status == "pending"
    assert req.tool_name == "python_interpreter"
    assert req.session_id == "sess-A"
    pending = store.list_pending("sess-A")
    assert len(pending) == 1
    assert pending[0].request_id == req.request_id
    print("[OK] request + list_pending")


def test_hitl_store_approve_modifies_args(fresh_hitl_store):
    """approve 时 tool_args 可以被覆盖（用户修改）。"""
    store = fresh_hitl_store.instance()
    req = store.request_approval(
        session_id="s", tool_name="python_interpreter",
        tool_args={"code": "x = 1"},
    )
    updated = store.approve(req.request_id, tool_args={"code": "y = 2"})
    assert updated.status == "approved"
    assert updated.decision_payload == {"code": "y = 2"}
    print("[OK] approve with modified args")


def test_hitl_store_reject(fresh_hitl_store):
    """reject 后必须能查到 reject_reason。"""
    store = fresh_hitl_store.instance()
    req = store.request_approval(
        session_id="s", tool_name="python_interpreter", tool_args={"code": "dangerous"},
    )
    updated = store.reject(req.request_id, reason="用户拒绝：太危险")
    assert updated.status == "rejected"
    assert updated.reject_reason == "用户拒绝：太危险"
    print("[OK] reject with reason")


def test_hitl_store_session_isolation(fresh_hitl_store):
    """不同 session_id 的 pending 必须互不影响。"""
    store = fresh_hitl_store.instance()
    r1 = store.request_approval(session_id="A", tool_name="t", tool_args={"x": 1})
    r2 = store.request_approval(session_id="B", tool_name="t", tool_args={"x": 1})
    assert store.list_pending("A")[0].request_id == r1.request_id
    assert store.list_pending("B")[0].request_id == r2.request_id
    # 批准 A 不会影响 B
    store.approve(r1.request_id)
    assert store.list_pending("A") == []  # approved 后不再 pending
    assert len(store.list_pending("B")) == 1
    print("[OK] session isolation")


def test_hitl_store_consume_pending_marks_consumed(fresh_hitl_store):
    """consume_pending 必须在 list_pending 中移除已消费项。"""
    store = fresh_hitl_store.instance()
    store.request_approval(session_id="s", tool_name="t", tool_args={"x": 1})
    consumed = store.consume_pending("s")
    assert len(consumed) == 1
    assert store.list_pending("s") == []
    # 即使再 consume 也是空
    assert store.consume_pending("s") == []
    print("[OK] consume_pending semantics")


def test_hitl_store_persistence_roundtrip(tmp_path):
    """pending 必须能跨进程持久化（重启后能从 DB 加载）。"""
    from hitl_langgraph import HITLStore
    HITLStore.reset_instance()
    db = str(tmp_path / "hitl.db")
    s1 = HITLStore(db_path=db)
    req = s1.request_approval(session_id="s", tool_name="python_interpreter", tool_args={"code": "a"})
    rid = req.request_id
    s1.approve(rid)
    # 模拟重启：丢弃内存，新建 store
    HITLStore.reset_instance()
    s2 = HITLStore(db_path=db)
    loaded = s2.get(rid)
    assert loaded is not None
    assert loaded.status == "approved"
    print("[OK] persistence roundtrip")
    HITLStore.reset_instance()


# ============================================================
# 2) tool_requires_approval —— python_interpreter 必须被拦截
# ============================================================

def test_python_interpreter_requires_approval():
    """v21_tools.TOOL_REGISTRY 中 python_interpreter 必须 requires_approval=True。"""
    from v21_tools import TOOL_REGISTRY

    assert "python_interpreter" in TOOL_REGISTRY
    entry = TOOL_REGISTRY["python_interpreter"]
    assert entry.get("requires_approval") is True, (
        "python_interpreter must require human approval by default"
    )
    print("[OK] python_interpreter marked requires_approval=True")


def test_tool_requires_approval_via_registry():
    """tool_requires_approval 必须能从 v21_tools registry 推断出来。"""
    from hitl_langgraph import tool_requires_approval
    from v21_tools import get_langchain_tools

    tools = get_langchain_tools(["python_interpreter", "web_search"])
    by_name = {t.name: t for t in tools}
    assert tool_requires_approval(by_name["python_interpreter"]) is True
    assert tool_requires_approval(by_name["web_search"]) is False
    print("[OK] tool_requires_approval registry-based dispatch")


# ============================================================
# 3) _HITLWrappedTool 拦截流
# ============================================================

def test_hitl_wrapped_tool_pending_then_approve(isolated_env, fresh_hitl_store):
    """首次调用 → pending；approve 后 → 真正执行 inner tool。"""
    from hitl_langgraph import HITLStore
    from agent import _HITLWrappedTool

    # 内层 mock tool：记录是否被调用 + 返回固定结果
    inner = MagicMock()
    inner.name = "python_interpreter"
    inner.description = "mock python"
    inner.args_schema = {"type": "object"}
    inner.invoke.return_value = "OK result"

    wrapped = _HITLWrappedTool(inner)
    thread_id = f"sess-{uuid.uuid4().hex[:8]}"

    # 第一次调用：没有 approval → sentinel
    out1 = wrapped.invoke(
        {"code": "print(1)"},
        config={"configurable": {"thread_id": thread_id}},
    )
    assert "__HITL_PENDING__" in out1
    assert inner.invoke.call_count == 0, "inner must NOT be called on pending"
    print(f"[OK] first call returns sentinel: {out1[:60]}...")

    # 找到对应的 pending 并 approve
    pending = HITLStore.instance().list_pending(thread_id)
    assert len(pending) == 1
    HITLStore.instance().approve(pending[0].request_id)

    # 第二次调用：approved → 真正执行
    out2 = wrapped.invoke(
        {"code": "print(1)"},
        config={"configurable": {"thread_id": thread_id}},
    )
    assert inner.invoke.call_count == 1, "inner MUST be called after approve"
    assert out2 == "OK result"
    print("[OK] approve → real execution")


def test_hitl_wrapped_tool_reject(isolated_env, fresh_hitl_store):
    """reject 后调用必须返回取消消息，不调用 inner。"""
    from hitl_langgraph import HITLStore
    from agent import _HITLWrappedTool

    inner = MagicMock()
    inner.name = "python_interpreter"
    inner.description = "mock"
    inner.args_schema = {"type": "object"}
    inner.invoke.return_value = "should not be called"

    wrapped = _HITLWrappedTool(inner)
    thread_id = f"sess-{uuid.uuid4().hex[:8]}"

    # 第一次：pending
    wrapped.invoke({"code": "rm -rf /"}, config={"configurable": {"thread_id": thread_id}})

    pending = HITLStore.instance().list_pending(thread_id)
    HITLStore.instance().reject(pending[0].request_id, reason="禁止危险操作")

    out = wrapped.invoke(
        {"code": "rm -rf /"}, config={"configurable": {"thread_id": thread_id}}
    )
    assert "cancelled by user" in out
    assert "禁止危险操作" in out
    assert inner.invoke.call_count == 0
    print(f"[OK] rejected → cancel message: {out}")


def test_hitl_wrapped_tool_no_thread_id_direct_execute(isolated_env, fresh_hitl_store):
    """无 thread_id 时直接执行 inner（兜底）。"""
    from agent import _HITLWrappedTool

    inner = MagicMock()
    inner.name = "python_interpreter"
    inner.description = "mock"
    inner.args_schema = {"type": "object"}
    inner.invoke.return_value = "direct-result"

    wrapped = _HITLWrappedTool(inner)
    out = wrapped.invoke({"code": "1+1"}, config=None)
    assert out == "direct-result"
    assert inner.invoke.call_count == 1
    print("[OK] no-thread-id path executes directly")


def test_hitl_wrapped_tool_idempotent_wrap():
    """同一个 tool 多次 wrap 不会嵌套（_wrap_tools_with_hitl 幂等性）。"""
    from agent import AIAgent

    fake_tool = MagicMock()
    fake_tool.name = "python_interpreter"
    fake_tool.description = "fake"
    fake_tool.args_schema = {"type": "object"}
    fake_tool._hitl_wrapped = False

    with patch("agent.ChatOpenAI"):
        # 不实际 init agent；只调用工具包装方法
        a = AIAgent.__new__(AIAgent)  # 不走 __init__
    out = a._wrap_tools_with_hitl([fake_tool])
    assert len(out) == 1
    wrapped = out[0]
    assert getattr(wrapped, "_hitl_wrapped", False) is True
    # 再次 wrap 应该不会嵌套（wrapped._inner 还是 fake_tool）
    out2 = a._wrap_tools_with_hitl(out)
    assert len(out2) == 1
    assert out2[0] is wrapped, "second wrap must be a no-op"
    print("[OK] wrap idempotent")


# ============================================================
# 4) FastAPI 端点
# ============================================================

def test_chat_approve_endpoint_success(isolated_env, fresh_hitl_store):
    """POST /api/chat/approve 必须成功批准并返回 updated state。"""
    from fastapi.testclient import TestClient
    from app import app
    from hitl_langgraph import HITLStore

    store = HITLStore.instance()
    req = store.request_approval(
        session_id="sess-1", tool_name="python_interpreter",
        tool_args={"code": "1+1"},
    )
    client = TestClient(app)
    r = client.post(
        "/api/chat/approve",
        json={
            "session_id": "sess-1",
            "request_id": req.request_id,
            "tool_args": {"code": "2+2"},
            "decided_by": "tester",
        },
    )
    assert r.status_code == 200, f"status={r.status_code} body={r.text}"
    body = r.json()
    assert body["success"] is True
    assert body["decision"] == "approved"
    assert body["tool_args"] == {"code": "2+2"}
    print("[OK] /api/chat/approve success")


def test_chat_approve_endpoint_wrong_session(isolated_env, fresh_hitl_store):
    """session_id 不匹配必须 404。"""
    from fastapi.testclient import TestClient
    from app import app
    from hitl_langgraph import HITLStore

    req = HITLStore.instance().request_approval(
        session_id="sess-A", tool_name="python_interpreter", tool_args={"code": "x"},
    )
    client = TestClient(app)
    r = client.post(
        "/api/chat/approve",
        json={"session_id": "sess-B", "request_id": req.request_id},
    )
    assert r.status_code == 404, f"expected 404, got {r.status_code}"
    print("[OK] /api/chat/approve rejects wrong session")


def test_chat_approve_endpoint_double_approve(isolated_env, fresh_hitl_store):
    """重复 approve 必须 409（幂等性 + 防误操作）。"""
    from fastapi.testclient import TestClient
    from app import app
    from hitl_langgraph import HITLStore

    req = HITLStore.instance().request_approval(
        session_id="s", tool_name="python_interpreter", tool_args={"code": "x"},
    )
    client = TestClient(app)
    r1 = client.post("/api/chat/approve", json={"session_id": "s", "request_id": req.request_id})
    assert r1.status_code == 200
    r2 = client.post("/api/chat/approve", json={"session_id": "s", "request_id": req.request_id})
    assert r2.status_code == 409, f"expected 409, got {r2.status_code}"
    print("[OK] /api/chat/approve double-approve → 409")


def test_chat_reject_endpoint_success(isolated_env, fresh_hitl_store):
    """POST /api/chat/reject 必须成功拒绝并返回 reason。"""
    from fastapi.testclient import TestClient
    from app import app
    from hitl_langgraph import HITLStore

    req = HITLStore.instance().request_approval(
        session_id="s", tool_name="python_interpreter", tool_args={"code": "x"},
    )
    client = TestClient(app)
    r = client.post(
        "/api/chat/reject",
        json={
            "session_id": "s",
            "request_id": req.request_id,
            "reason": "用户主动取消",
        },
    )
    assert r.status_code == 200, f"status={r.status_code}"
    body = r.json()
    assert body["decision"] == "rejected"
    assert body["reason"] == "用户主动取消"
    print("[OK] /api/chat/reject success")


def test_chat_reject_endpoint_default_reason(isolated_env, fresh_hitl_store):
    """不传 reason 时必须 fallback 到默认文案。"""
    from fastapi.testclient import TestClient
    from app import app
    from hitl_langgraph import HITLStore

    req = HITLStore.instance().request_approval(
        session_id="s", tool_name="python_interpreter", tool_args={"code": "x"},
    )
    client = TestClient(app)
    r = client.post(
        "/api/chat/reject",
        json={"session_id": "s", "request_id": req.request_id},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "rejected"
    assert "cancelled" in body["reason"].lower() or "取消" in body["reason"]
    print("[OK] /api/chat/reject default reason")


def test_hitl_v2_pending_endpoint(isolated_env, fresh_hitl_store):
    """GET /api/hitl/v2/pending 必须返回当前 session 的 pending approvals。"""
    from fastapi.testclient import TestClient
    from app import app
    from hitl_langgraph import HITLStore

    HITLStore.instance().request_approval(
        session_id="s-A", tool_name="python_interpreter", tool_args={"code": "1"},
    )
    HITLStore.instance().request_approval(
        session_id="s-B", tool_name="python_interpreter", tool_args={"code": "2"},
    )
    client = TestClient(app)
    r = client.get("/api/hitl/v2/pending", params={"session_id": "s-A"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["pending"][0]["session_id"] == "s-A"
    print("[OK] /api/hitl/v2/pending filters by session")


# ============================================================
# 5) 端到端：完整 approve 流（wrap → pending → API approve → re-invoke）
# ============================================================

def test_e2e_hitl_approve_flow(isolated_env, fresh_hitl_store):
    """完整 HITL approve 流程。"""
    from fastapi.testclient import TestClient
    from app import app
    from agent import _HITLWrappedTool
    from hitl_langgraph import HITLStore

    inner = MagicMock()
    inner.name = "python_interpreter"
    inner.description = "mock"
    inner.args_schema = {"type": "object"}
    inner.invoke.return_value = "executed: y=2"

    wrapped = _HITLWrappedTool(inner)
    thread_id = "sess-e2e"

    # Step 1: 首次调用 → pending
    out1 = wrapped.invoke({"code": "x=1"}, config={"configurable": {"thread_id": thread_id}})
    assert "__HITL_PENDING__" in out1
    assert inner.invoke.call_count == 0

    # Step 2: 用户修改 args 后调用 /api/chat/approve
    pending_list = HITLStore.instance().list_pending(thread_id)
    assert len(pending_list) == 1
    request_id = pending_list[0].request_id

    client = TestClient(app)
    r = client.post(
        "/api/chat/approve",
        json={
            "session_id": thread_id,
            "request_id": request_id,
            "tool_args": {"code": "y=2"},  # 用户修改后的 args
        },
    )
    assert r.status_code == 200

    # Step 3: 再次调用 → 真正执行 inner（用修改后的 args）
    out2 = wrapped.invoke({"code": "x=1"}, config={"configurable": {"thread_id": thread_id}})
    assert inner.invoke.call_count == 1
    # inner 收到的应该是用户修改后的 args
    args_used = inner.invoke.call_args[0][0]
    assert args_used == {"code": "y=2"}
    assert out2 == "executed: y=2"
    print("[OK] end-to-end HITL approve flow with args modification")


def test_e2e_hitl_reject_flow(isolated_env, fresh_hitl_store):
    """完整 HITL reject 流程。"""
    from fastapi.testclient import TestClient
    from app import app
    from agent import _HITLWrappedTool
    from hitl_langgraph import HITLStore

    inner = MagicMock()
    inner.name = "python_interpreter"
    inner.description = "mock"
    inner.args_schema = {"type": "object"}
    inner.invoke.return_value = "DANGEROUS: should not run"

    wrapped = _HITLWrappedTool(inner)
    thread_id = "sess-reject"

    # Step 1: pending
    out1 = wrapped.invoke({"code": "rm -rf /"}, config={"configurable": {"thread_id": thread_id}})
    assert "__HITL_PENDING__" in out1

    # Step 2: /api/chat/reject
    pending_list = HITLStore.instance().list_pending(thread_id)
    request_id = pending_list[0].request_id
    client = TestClient(app)
    r = client.post(
        "/api/chat/reject",
        json={
            "session_id": thread_id,
            "request_id": request_id,
            "reason": "禁止执行破坏性命令",
        },
    )
    assert r.status_code == 200

    # Step 3: 再次调用 → inner 不被调用，返回取消消息
    out2 = wrapped.invoke({"code": "rm -rf /"}, config={"configurable": {"thread_id": thread_id}})
    assert inner.invoke.call_count == 0
    assert "cancelled by user" in out2
    assert "禁止执行破坏性命令" in out2
    print(f"[OK] end-to-end HITL reject flow: {out2}")


# ============================================================
# v2.2.1 — Edit & Resume（参数修改重投）
# ============================================================
class TestEditAndResume:
    """v2.2.1 — 用户修改 tool_args 后批准，agent 使用修改后的 args 执行。"""

    def test_approve_with_edited_args_marks_edited(self):
        from hitl_langgraph import HITLStore
        store = HITLStore.instance()
        sid = "sess-edit"
        p = store.request_approval(
            session_id=sid,
            tool_name="python_interpreter",
            tool_args={"code": "print('unsafe')"},
            reason="test",
        )
        # 用户修改了 args
        updated = store.approve(
            p.request_id, tool_args={"code": "print('safe')"}
        )
        assert updated is not None
        assert updated.status == "approved"
        assert updated.edited is True
        assert updated.decision_payload == {"code": "print('safe')"}

    def test_approve_with_same_args_not_marked_edited(self):
        from hitl_langgraph import HITLStore
        store = HITLStore.instance()
        sid = "sess-edit-same"
        p = store.request_approval(
            session_id=sid,
            tool_name="python_interpreter",
            tool_args={"code": "print('hi')"},
        )
        # 用相同的 args 批准
        updated = store.approve(
            p.request_id, tool_args={"code": "print('hi')"}
        )
        assert updated.edited is False

    def test_chat_approve_endpoint_uses_edited_args(self):
        """POST /api/chat/approve 接受 edited_args，覆盖 tool_args。"""
        from fastapi.testclient import TestClient
        from hitl_langgraph import HITLStore
        from app import app

        store = HITLStore.instance()
        sid = "sess-edit-ep"
        p = store.request_approval(
            session_id=sid,
            tool_name="python_interpreter",
            tool_args={"code": "rm -rf /"},
        )

        client = TestClient(app)
        r = client.post(
            "/api/chat/approve",
            json={
                "session_id": sid,
                "request_id": p.request_id,
                "edited_args": {"code": "print('safe')"},
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["edited"] is True
        assert body["tool_args"] == {"code": "print('safe')"}

    def test_e2e_edit_and_resume_invokes_with_edited_args(self):
        """end-to-end: 拦截 → 批准 with edited args → inner tool 用 edited args 执行。"""
        from agent import _HITLWrappedTool
        from hitl_langgraph import HITLStore
        from fastapi.testclient import TestClient
        from app import app

        # 清空 store
        store = HITLStore.instance()
        sid = "sess-edit-e2e"
        # 构造 mock inner tool
        inner = MagicMock()
        inner.name = "python_interpreter"
        inner.description = "test"
        inner.args_schema = {"type": "object"}
        inner.invoke.return_value = "ran with edited"

        wrapped = _HITLWrappedTool(inner)

        # Step 1: 拦截
        out1 = wrapped.invoke(
            {"code": "dangerous"},
            config={"configurable": {"thread_id": sid}},
        )
        assert "__HITL_PENDING__" in out1

        # Step 2: 批准 with edited args
        pending = store.list_pending(sid)
        rid = pending[0].request_id
        client = TestClient(app)
        r = client.post(
            "/api/chat/approve",
            json={
                "session_id": sid,
                "request_id": rid,
                "edited_args": {"code": "safe_code"},
            },
        )
        assert r.status_code == 200

        # Step 3: 再次调用 → inner 应该用 edited args 执行
        out2 = wrapped.invoke(
            {"code": "dangerous"},
            config={"configurable": {"thread_id": sid}},
        )
        # inner.invoke 应被调用一次，参数是 edited_args
        assert inner.invoke.call_count == 1
        call_args = inner.invoke.call_args
        # 实际调用形如 inner.invoke({"code": "safe_code"}, config={...})
        first_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("input")
        assert first_arg == {"code": "safe_code"}
        assert "ran with edited" in str(out2)


# ============================================================
# v2.2.1 — 超时自动拒绝 (Timeout Auto-Reject)
# ============================================================
class TestTimeoutAutoReject:
    """v2.2.1 — Pending 超过 timeout_seconds 自动 rejected + 注入 cancelled 消息。"""

    def test_default_timeout_is_300_seconds(self):
        from hitl_langgraph import HITLStore
        store = HITLStore.instance()
        p = store.request_approval(
            session_id="t1",
            tool_name="python_interpreter",
            tool_args={"code": "x"},
        )
        assert p.timeout_seconds == 300.0

    def test_custom_timeout(self):
        from hitl_langgraph import HITLStore
        store = HITLStore.instance()
        p = store.request_approval(
            session_id="t2",
            tool_name="python_interpreter",
            tool_args={"code": "x"},
            timeout_seconds=5.0,
        )
        assert p.timeout_seconds == 5.0

    def test_check_timeouts_marks_as_rejected(self):
        from hitl_langgraph import HITLStore
        store = HITLStore.instance()
        sid = "sess-timeout-1"
        p = store.request_approval(
            session_id=sid,
            tool_name="python_interpreter",
            tool_args={"code": "x"},
            timeout_seconds=0.001,
        )
        # 模拟过了很久
        import time as _t
        _t.sleep(0.05)
        timed_out = store.check_approval_timeouts()
        assert len(timed_out) == 1
        assert timed_out[0].request_id == p.request_id
        assert timed_out[0].status == "rejected"
        assert timed_out[0].timed_out is True
        assert "timed out" in (timed_out[0].reject_reason or "").lower()

    def test_check_timeouts_skips_non_pending(self):
        """已 resolved 的不应被超时再处理。"""
        from hitl_langgraph import HITLStore
        store = HITLStore.instance()
        sid = "sess-timeout-skip"
        p = store.request_approval(
            session_id=sid,
            tool_name="python_interpreter",
            tool_args={"code": "x"},
            timeout_seconds=0.001,
        )
        # 立即 approve
        store.approve(p.request_id)
        import time as _t
        _t.sleep(0.05)
        timed_out = store.check_approval_timeouts()
        assert all(t.request_id != p.request_id for t in timed_out)

    def test_emit_timeout_events_returns_sse_payload(self):
        from hitl_langgraph import HITLStore, emit_timeout_events
        store = HITLStore.instance()
        sid = "sess-timeout-emit"
        p = store.request_approval(
            session_id=sid,
            tool_name="python_interpreter",
            tool_args={"code": "x"},
            timeout_seconds=0.001,
        )
        import time as _t
        _t.sleep(0.05)
        events = emit_timeout_events()
        assert any(
            e.get("type") == "approval_timeout" and e.get("request_id") == p.request_id
            for e in events
        )
        evt = next(e for e in events if e.get("request_id") == p.request_id)
        assert "timed out" in evt["reason"].lower()

    def test_e2e_timeout_rejects_invocation(self):
        """end-to-end: 拦截 → 等待超时 → 自动 reject → 再次调用返回 cancelled。"""
        from agent import _HITLWrappedTool
        from hitl_langgraph import HITLStore, emit_timeout_events
        inner = MagicMock()
        inner.name = "python_interpreter"
        inner.description = "test"
        inner.args_schema = {"type": "object"}
        inner.invoke.return_value = "ran"

        wrapped = _HITLWrappedTool(inner)
        sid = "sess-timeout-e2e"

        # Step 1: 拦截
        out1 = wrapped.invoke(
            {"code": "x"},
            config={"configurable": {"thread_id": sid}},
        )
        assert "__HITL_PENDING__" in out1

        # Step 2: 触发超时（修改 pending 的 timeout_seconds=0.001 后 sleep）
        store = HITLStore.instance()
        p = store.list_all_for_session(sid)[0]
        p.timeout_seconds = 0.001
        import time as _t
        _t.sleep(0.05)
        events = emit_timeout_events()
        assert any(e.get("request_id") == p.request_id for e in events)

        # Step 3: 再次调用 → 应返回 cancelled 消息，inner 不被调用
        out2 = wrapped.invoke(
            {"code": "x"},
            config={"configurable": {"thread_id": sid}},
        )
        assert inner.invoke.call_count == 0
        assert "cancelled" in out2.lower() or "timed out" in out2.lower()
