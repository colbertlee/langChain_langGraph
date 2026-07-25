"""端到端测试：模拟前端对所有 API 的调用。

使用 fastapi TestClient，无需真实启动服务器。
"""
import io
import os
import sys
import time

# Windows 终端默认 GBK，强制 UTF-8 避免 emoji 报错
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 让测试使用真实 Agent（即使 key 是占位符，也能验证降级路径返回的功能性消息）
os.environ["AI_AGENT_DISABLE_PLACEHOLDER_CHECK"] = "0"

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from app import app


def _ok(label, resp, expect_status=200):
    sc = resp.status_code
    body = ""
    try:
        body = resp.text[:200]
    except Exception:
        pass
    flag = "PASS" if sc == expect_status else "FAIL"
    # 避免 emoji/中文在某些终端被 GBK 拒绝
    safe_body = body.encode("ascii", "replace").decode("ascii")
    print(f"  [{flag}] {label}: HTTP {sc} {safe_body}")
    return sc == expect_status


def main():
    client = TestClient(app)

    # 先触发 agent 初始化
    r = client.get("/api/health")
    assert r.status_code == 200, r.text

    results = []

    # ============================================
    # 1. 基础
    # ============================================
    print("\n[1] 基础端点")
    results.append(_ok("GET /", client.get("/")))
    results.append(_ok("GET /dashboard", client.get("/dashboard")))
    results.append(_ok("GET /legacy", client.get("/legacy")))
    results.append(_ok("GET /api/health", client.get("/api/health")))
    results.append(_ok("GET /api/version", client.get("/api/version")))

    # ============================================
    # 2. 聊天 / 流式
    # ============================================
    print("\n[2] 聊天 & 流式")
    results.append(_ok("GET /api/tools", client.get("/api/tools")))
    r = client.post("/api/chat", json={"message": "hi"})
    results.append(_ok("POST /api/chat", r))
    # SSE
    with client.stream("POST", "/api/chat/stream", json={"message": "ping"}) as resp:
        ok = resp.status_code == 200 and resp.headers.get("content-type", "").startswith("text/event-stream")
        print(f"  [{'PASS' if ok else 'FAIL'}] POST /api/chat/stream SSE: HTTP {resp.status_code} ct={resp.headers.get('content-type')}")
        results.append(ok)
    results.append(_ok("POST /api/clear", client.post("/api/clear")))

    # ============================================
    # 3. API Key / 模型
    # ============================================
    print("\n[3] API Key / 模型")
    results.append(_ok("GET /api/api-key/status", client.get("/api/api-key/status")))
    r = client.post("/api/api-key", json={"api_key": "sk-test-fake-key-xxx", "provider": "openai"})
    results.append(_ok("POST /api/api-key", r))
    r = client.post("/api/model/switch", json={"provider": "openai", "model_name": "gpt-4o-mini"})
    results.append(_ok("POST /api/model/switch", r))
    results.append(_ok("GET /api/models", client.get("/api/models")))

    # ============================================
    # 4. Agents / Capabilities / Load
    # ============================================
    print("\n[4] Agents / Load")
    results.append(_ok("GET /api/agents", client.get("/api/agents")))
    results.append(_ok("GET /api/capabilities", client.get("/api/capabilities")))
    results.append(_ok("GET /api/load_stats", client.get("/api/load_stats")))

    # ============================================
    # 5. 权限
    # ============================================
    print("\n[5] 权限")
    results.append(_ok("GET /api/policies", client.get("/api/policies")))
    r = client.post(
        "/api/policy",
        json={
            "agent_id": "test-agent",
            "roles": ["user"],
            "capabilities": ["search"],
            "allowed_tools": ["web_search"],
        },
    )
    results.append(_ok("POST /api/policy", r))
    r = client.post("/api/permission/enforce", json={"enforce": True})
    results.append(_ok("POST /api/permission/enforce", r))
    r = client.post("/api/permission/enforce", json={"enforce": False})
    results.append(_ok("POST /api/permission/enforce (off)", r))

    # ============================================
    # 6. HITL
    # ============================================
    print("\n[6] HITL")
    results.append(_ok("GET /api/hitl/pending", client.get("/api/hitl/pending")))
    results.append(_ok("GET /api/hitl/history", client.get("/api/hitl/history")))
    results.append(_ok("GET /api/hitl/stats", client.get("/api/hitl/stats")))
    r = client.post(
        "/api/hitl/decide",
        json={"request_id": "non-existent-id", "status": "approved", "notes": "test"},
    )
    print(f"  [INFO] POST /api/hitl/decide (non-existent): HTTP {r.status_code} (404 expected)")
    results.append(r.status_code in (200, 404))
    r = client.post("/api/hitl/policy?hook_point=default&policy=auto")
    results.append(_ok("POST /api/hitl/policy", r))
    r = client.post("/api/hitl/policy?hook_point=before_tool_call&policy=ask")
    results.append(_ok("POST /api/hitl/policy hook", r))

    # ============================================
    # 7. 计划
    # ============================================
    print("\n[7] 计划")
    results.append(_ok("POST /api/plan/create", client.post("/api/plan/create", json={"goal": "调研 LangChain 最新进展"})))
    results.append(_ok("POST /api/plan/research", client.post("/api/plan/research", json={"goal": "Transformer 架构"})))
    results.append(_ok("POST /api/plan/code", client.post("/api/plan/code", json={"goal": "实现快速排序"})))
    results.append(_ok("POST /api/plan/run", client.post("/api/plan/run", json={"goal": "分析当前对话", "session_id": "test-sid"})))

    # ============================================
    # 8. 记忆
    # ============================================
    print("\n[8] 记忆")
    results.append(_ok(
        "POST /api/memory/remember",
        client.post("/api/memory/remember", json={"key": "user_name", "value": "小红", "scope": "global"}),
    ))
    results.append(_ok(
        "GET /api/memory/recall",
        client.get("/api/memory/recall?key=user_name"),
    ))
    results.append(_ok(
        "GET /api/memory/search",
        client.get("/api/memory/search?keyword=user"),
    ))
    results.append(_ok(
        "DELETE /api/memory/forget",
        client.delete("/api/memory/forget?key=user_name"),
    ))
    results.append(_ok("POST /api/memory/save", client.post("/api/memory/save", params={"path": "memory.json"})))
    results.append(_ok("POST /api/memory/load", client.post("/api/memory/load", params={"path": "memory.json"})))
    results.append(_ok("GET /api/memory/stats", client.get("/api/memory/stats")))

    # ============================================
    # 9. 观测
    # ============================================
    print("\n[9] 观测")
    results.append(_ok("GET /api/events", client.get("/api/events?limit=10")))
    results.append(_ok("GET /api/traces", client.get("/api/traces?limit=10")))
    r = client.get("/api/metrics/prometheus")
    ok = r.status_code == 200 and "text/plain" in r.headers.get("content-type", "")
    print(f"  [{'PASS' if ok else 'FAIL'}] GET /api/metrics/prometheus: HTTP {r.status_code} ct={r.headers.get('content-type')}")
    results.append(ok)

    # ============================================
    # 10. 上传
    # ============================================
    print("\n[10] 上传")
    files = {"file": ("test.txt", b"hello world test content", "text/plain")}
    r = client.post("/api/upload", files=files)
    results.append(_ok("POST /api/upload", r))
    if r.status_code == 200:
        data = r.json()
        url = data.get("url", "")
        if url.startswith("/"):
            results.append(_ok(f"GET {url}", client.get(url)))

    # ============================================
    # 11. 上下文管理
    # ============================================
    print("\n[11] 上下文管理")
    results.append(_ok("GET /api/context/sessions", client.get("/api/context/sessions?limit=5")))
    results.append(_ok("POST /api/context/sessions", client.post("/api/context/sessions")))
    sid = None
    r = client.post("/api/context/sessions")
    if r.status_code == 200:
        sid = r.json().get("session_id")
    if sid:
        results.append(_ok(f"GET /api/context/sessions/{sid[:8]}...", client.get(f"/api/context/sessions/{sid}")))
        results.append(_ok("GET /.../summary", client.get(f"/api/context/sessions/{sid}/summary")))
        results.append(_ok("GET /.../entities", client.get(f"/api/context/sessions/{sid}/entities")))
        results.append(_ok("GET /.../messages", client.get(f"/api/context/sessions/{sid}/messages?limit=10")))
    results.append(_ok("GET /api/context/analytics", client.get("/api/context/analytics")))
    results.append(_ok("GET /api/context/search", client.get("/api/context/search?query=test")))
    results.append(_ok("GET /api/context/stats", client.get("/api/context/stats")))
    results.append(_ok("GET /api/context/performance", client.get("/api/context/performance")))
    results.append(_ok("POST /api/context/performance/reset", client.post("/api/context/performance/reset")))

    # ============================================
    # 总结
    # ============================================
    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"RESULT: {passed}/{total} passed")
    if passed != total:
        print("FAILED:")
        # 详细
    print(f"{'=' * 60}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())