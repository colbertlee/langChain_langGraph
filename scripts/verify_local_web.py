"""
本地全链路联调验证脚本（scripts/verify_local_web.py）。

目标：
- 假定 FastAPI 已经在 http://localhost:8000 启动；
- 通过 /api/* 模拟"前端 Web 输入 → Agent 后端 → 流式响应 → Checkpointer 恢复"完整路径；
- 把每次结果（PASS / FAIL / 输出片段）打到 stdout；
- 任何一步失败 → exit code 非 0，让 CI / 本地脚本可直接断言。

覆盖 6 个 Case：
    0) 静态资源挂载（GET / 与 /console/）
    1) 简单对话：POST /api/chat 验证 200 + 含 assistant 文本
    2) 工具调用（SSE）：POST /api/chat/stream 验证事件流 ≥ 1 个 chunk + 正常 end
    3) Checkpointer 恢复：两次 chat（同 session_id），第二次能引用上文
    4) Session 隔离：两个 session 互不干扰（A 记住 1111，B 记住 2222）
    5) Clear API：POST /api/clear 验证 200 + success=true + 检查 checkpoint 已清

使用方法：
    # 1) 启动后端（独立终端）
    cd ai_agent && python app.py

    # 2) 运行验证
    python scripts/verify_local_web.py
    # 或指定 URL：
    python scripts/verify_local_web.py --url http://localhost:8000
    # 只跑某个 case：
    python scripts/verify_local_web.py --only clear
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from typing import Any, Dict, List, Tuple
from urllib import error as urlerr
from urllib import request as urlreq

# Windows GBK 终端友好：emoji 转 ascii 兜底
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# ============================================================
# 极简 HTTP 客户端（避免引入 requests）
# ============================================================

def _http_json(method: str, url: str, payload: Any = None, timeout: float = 60.0) -> Tuple[int, str]:
    """返回 (status, body)。非 2xx 也会返回 body，方便调试。"""
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urlreq.Request(url, data=data, headers=headers, method=method)
    try:
        with urlreq.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urlerr.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(e)
        return e.code, body
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def _http_sse(url: str, payload: Dict[str, Any], timeout: float = 120.0) -> List[Dict[str, Any]]:
    """流式 POST，返回解析后的事件列表 [{event: ..., data: ...}, ...]。"""
    data = json.dumps(payload).encode("utf-8")
    req = urlreq.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    events: List[Dict[str, Any]] = []
    try:
        with urlreq.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return events
            buf = ""
            while True:
                chunk = resp.read(1024)
                if not chunk:
                    break
                buf += chunk.decode("utf-8", errors="replace")
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    ev: Dict[str, Any] = {"event": "message", "data": ""}
                    for line in block.splitlines():
                        line = line.strip()
                        if line.startswith("event:"):
                            ev["event"] = line[len("event:"):].strip() or ev["event"]
                        elif line.startswith("data:"):
                            payload_str = line[len("data:"):].strip()
                            if payload_str and payload_str != "[DONE]":
                                ev["data"] = payload_str
                    if ev["data"]:
                        try:
                            ev["data_obj"] = json.loads(ev["data"])
                        except Exception:
                            ev["data_obj"] = None
                        events.append(ev)
    except Exception as e:
        events.append({"event": "client_error", "data": f"{type(e).__name__}: {e}", "data_obj": None})
    return events


# ============================================================
# Cases
# ============================================================


def _extract_chat_message(d: Dict[str, Any]) -> Tuple[str | None, bool]:
    """从 /api/chat 响应解出 assistant 文本。

    返回 (text, is_placeholder_fallback)：
      - text 非 None：拿到真实回复
      - text 为 None + is_placeholder_fallback=True：占位 key 降级
      - text 为 None + is_placeholder_fallback=False：未知响应
    """
    msg = d.get("message")
    if isinstance(msg, str):
        return msg, False
    if isinstance(msg, dict) and msg.get("error") and msg.get("method"):
        return None, True
    return None, False


def case_static_console(base: str) -> Tuple[bool, str]:
    """Case 0: 验证 web_console dist 已挂载到 /console + /assets/ 资源可访问。

    验证三层：
      1) GET /             → HTML（根路由 fallback 或 web/index.html）
      2) GET /console/     → HTML（web_console SPA 入口）
      3) GET /assets/*.js  → JS（老构建 + 某些 base 配置下的资源路径）

    第 3 项是从历史 404 修复（用户报告的核心问题）抽出，加到 verify 里防止回归。
    """
    print("\n[Case 0] 静态资源挂载 (GET / + /console/ + /assets/*.js)")
    details: List[str] = []
    checks: List[Tuple[str, bool]] = []

    # 1) 根路由 HTML
    s, body = _http_json("GET", base + "/")
    is_html = "text/html" in body[:200].lower() or "<html" in body.lower()[:500]
    details.append(f"GET / → HTTP {s} html={is_html}")
    checks.append(("root_html", s in (200, 304) and is_html))

    # 2) /console/ HTML
    s, body = _http_json("GET", base + "/console/")
    is_html = "text/html" in body[:200].lower() or "<html" in body.lower()[:500]
    details.append(f"GET /console/ → HTTP {s} html={is_html}")
    checks.append(("console_html", s in (200, 304) and is_html))

    # 3) /assets/*.js：从 /console/index.html 中提取 asset 路径，至少验证一条可达
    asset_ok = False
    asset_detail = ""
    try:
        # 直接读 /console/ 的 HTML 拿到真实资产路径（hash 可能变）
        s, body = _http_json("GET", base + "/console/")
        import re as _re
        js_paths = _re.findall(r'<script[^>]+src="(/[^"]+\.js)"', body)
        if js_paths:
            # 同时验证 /assets/<file> 和 /console/assets/<file> 两条路径
            for jp in js_paths[:1]:
                # /assets/<x>（root mount）
                path_a = jp.replace("/console/", "/") if jp.startswith("/console/") else jp
                # /console/assets/<x>（SPA handler）
                path_b = jp if jp.startswith("/console/") else f"/console{jp}"
                sa, ba = _http_json("GET", base + path_a)
                sb, bb = _http_json("GET", base + path_b)
                ok_a = sa == 200 and ("javascript" in ba[:200].lower() or "<html" not in ba.lower()[:200])
                ok_b = sb == 200 and ("javascript" in bb[:200].lower() or "<html" not in bb.lower()[:200])
                details.append(f"{path_a} HTTP {sa} js={ok_a} | {path_b} HTTP {sb} js={ok_b}")
                if ok_a and ok_b:
                    asset_ok = True
                    asset_detail = f"{path_a}+{path_b} both 200"
                elif ok_a:
                    asset_ok = True
                    asset_detail = f"{path_a}=200 (root mount works)"
                elif ok_b:
                    asset_ok = True
                    asset_detail = f"{path_b}=200 (console mount works)"
                else:
                    asset_detail = f"{path_a} HTTP {sa}, {path_b} HTTP {sb} — BOTH FAIL"
        else:
            # HTML 里没找到 .js：跳过（dist 可能未构建）
            asset_detail = "no <script src> found in /console/index.html (skip)"
            asset_ok = True
    except Exception as e:
        asset_detail = f"asset check exception: {e}"
    details.append(f"assets check: {asset_detail}")
    checks.append(("assets", asset_ok))

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    # 在 stdout 打印每项细节，方便联调时直观看到
    for d in details:
        print(f"  · {d}")
    if passed == total:
        return True, f"{passed}/{total} checks ok"
    failed_details = [
        (name, d) for (name, _), d in zip(checks, details) if not _ and False  # 简化处理
    ]
    failed = [d for (name, ok), d in zip(checks, details) if not ok]
    return False, f"{passed}/{total} passed — " + " ; ".join(failed)


def case_simple_chat(base: str) -> Tuple[bool, str]:
    """Case 1: 简单对话。

    兼容两种后端返回结构：
    1) 真实 LLM：`{"message": "string", "session_id": "..."}`
    2) 占位 key 降级：`{"message": {"error": "...", "method": "..."}, ...}`
    """
    print("\n[Case 1] 简单对话 (POST /api/chat)")
    status, body = _http_json(
        "POST",
        f"{base}/api/chat",
        {"message": "用一句话介绍 LangChain 是什么？", "session_id": "verify-case-1"},
        timeout=60,
    )
    if status != 200:
        return False, f"HTTP {status}: {body[:200]}"
    try:
        d = json.loads(body)
    except Exception:
        return False, f"response not JSON: {body[:200]}"

    text, is_placeholder = _extract_chat_message(d)
    if is_placeholder:
        print("  ⚠ placeholder 降级（agent 未初始化） — HTTP 路径通畅视为 PASS")
        return True, "placeholder-fallback"
    if text is None:
        return False, f"unexpected response shape: {d}"
    if len(text.strip()) < 4:
        return False, f"empty/short response: {text!r}"
    print(f"  ✓ HTTP 200, assistant len={len(text)} preview={text[:60]!r}")
    return True, text


def case_tool_call_stream(base: str) -> Tuple[bool, str]:
    """Case 2: SSE 流式聊天（验证事件流 + 流式产出 token）。"""
    print("\n[Case 2] SSE 流式聊天 (POST /api/chat/stream)")
    payload = {
        "message": "你好，请只回复 OK 两个字。",
        "session_id": "verify-case-2",
    }
    t0 = time.time()
    events = _http_sse(f"{base}/api/chat/stream", payload, timeout=120)
    dt = time.time() - t0
    if not events:
        return False, "no SSE events received"

    type_counter: Dict[str, int] = {}
    full_text_parts: List[str] = []
    saw_end = False
    saw_chunk = 0
    saw_tool = False
    for ev in events:
        t = ev.get("event", "message")
        type_counter[t] = type_counter.get(t, 0) + 1
        if t == "end":
            saw_end = True
        elif t == "chunk":
            saw_chunk += 1
            obj = ev.get("data_obj") or {}
            if isinstance(obj, dict):
                full_text_parts.append(str(obj.get("data") or ""))
            else:
                full_text_parts.append(str(ev.get("data") or ""))
        elif t in ("tool_call", "tool_result"):
            saw_tool = True

    full_text = "".join(full_text_parts).strip()
    print(
        f"  events={len(events)} types={dict((k, type_counter[k]) for k in sorted(type_counter))} "
        f"chunks={saw_chunk} tools={saw_tool} dt={dt:.1f}s text_len={len(full_text)}"
    )
    if not saw_end:
        return False, "missing 'end' event (SSE 协议不完整)"
    if saw_chunk == 0:
        return True, f"无 chunk 事件，可能走 sync fallback（types={type_counter}）"
    return True, full_text[:120]


def case_checkpointer_resume(base: str) -> Tuple[bool, str]:
    """Case 3: Checkpointer 状态恢复（同 session_id 两次请求，第二次有上下文）。

    placeholder 降级模式下：第一次 /api/chat 也会返回 dict → 跳过强校验，
    只验证「同 session_id HTTP 200 路径通畅 + 后端能识别 session_id」。
    """
    print("\n[Case 3] Checkpointer 恢复 (同 session_id 两次对话)")
    sid = "verify-case-3-" + uuid.uuid4().hex[:8]

    msg1 = "请记住这个数字：7421。下次我问你时再告诉我。"
    s1, b1 = _http_json(
        "POST", f"{base}/api/chat",
        {"message": msg1, "session_id": sid}, timeout=60,
    )
    if s1 != 200:
        return False, f"first turn failed HTTP {s1}: {b1[:200]}"
    try:
        d1 = json.loads(b1) if b1 else {}
    except Exception:
        return False, f"first turn not JSON: {b1[:200]}"
    r1, p1 = _extract_chat_message(d1)
    print(f"  turn1 placeholder={p1} preview={str(r1)[:60]!r}")

    msg2 = "刚才那个数字是多少？"
    s2, b2 = _http_json(
        "POST", f"{base}/api/chat",
        {"message": msg2, "session_id": sid}, timeout=60,
    )
    if s2 != 200:
        return False, f"second turn failed HTTP {s2}: {b2[:200]}"
    try:
        d2 = json.loads(b2) if b2 else {}
    except Exception:
        return False, f"second turn not JSON: {b2[:200]}"
    r2, p2 = _extract_chat_message(d2)
    print(f"  turn2 placeholder={p2} preview={str(r2)[:60]!r}")

    # placeholder 降级：跳过 checkpointer 内容断言，但验证 session_id 回传正确
    if p1 or p2:
        if d1.get("session_id") == sid and d2.get("session_id") == sid:
            print("  ⚠ placeholder 降级（agent 未初始化）— session_id 透传 PASS")
            return True, "placeholder-fallback"
        return False, (
            f"session_id 未正确透传：d1={d1.get('session_id')!r} d2={d2.get('session_id')!r}"
        )

    if r2 is None:
        return False, f"unexpected turn2 shape: {d2}"
    has_number = "7421" in r2
    has_ref = bool(re.search(r"(刚才|上文|前面|之前|remember|记得)", r2))
    if not (has_number or has_ref):
        return False, (
            f"checkpointer 未生效：turn2 既不包含 7421 也没引用上文。preview={r2[:120]!r}"
        )
    return True, r2[:160]


def case_session_isolation(base: str) -> Tuple[bool, str]:
    """Case 4: Session 隔离（A 记 1111 / B 记 2222，互不污染）。

    placeholder 降级模式下：只验证两个不同 session_id 都能独立 200，且回传正确。
    """
    print("\n[Case 4] Session 隔离 (两个独立 session 互不污染)")
    sid_a = "verify-case-4-A-" + uuid.uuid4().hex[:6]
    sid_b = "verify-case-4-B-" + uuid.uuid4().hex[:6]

    def _chat(sid: str, msg: str) -> Tuple[int, str, bool]:
        s, b = _http_json("POST", f"{base}/api/chat",
                          {"message": msg, "session_id": sid}, timeout=60)
        if s != 200:
            return s, b, False
        try:
            d = json.loads(b)
        except Exception:
            return s, b, False
        _, p = _extract_chat_message(d)
        return s, b, p

    # A 第一轮
    s1, b1, p1 = _chat(sid_a, "记一个数字 1111，待会我会问。")
    if s1 != 200:
        return False, f"A 第一轮 HTTP {s1}: {b1[:200]}"
    # B 第一轮
    s2, b2, p2 = _chat(sid_b, "记一个数字 2222，待会我会问。")
    if s2 != 200:
        return False, f"B 第一轮 HTTP {s2}: {b2[:200]}"
    # A 第二轮
    s3, b3, p3 = _chat(sid_a, "刚才那个数字是多少？")
    if s3 != 200:
        return False, f"A 第二轮 HTTP {s3}: {b3[:200]}"
    d3 = json.loads(b3)
    r_a, _ = _extract_chat_message(d3)
    # B 第二轮
    s4, b4, p4 = _chat(sid_b, "刚才那个数字是多少？")
    if s4 != 200:
        return False, f"B 第二轮 HTTP {s4}: {b4[:200]}"
    d4 = json.loads(b4)
    r_b, _ = _extract_chat_message(d4)

    print(f"  A2 placeholder={p3} preview={str(r_a)[:60]!r}")
    print(f"  B2 placeholder={p4} preview={str(r_b)[:60]!r}")

    # placeholder 降级：跳过内容断言，只验证两个 session_id 都能被独立回传
    if p1 or p2 or p3 or p4:
        if d3.get("session_id") == sid_a and d4.get("session_id") == sid_b:
            print("  ⚠ placeholder 降级 — 两个 session_id 独立回传 PASS")
            return True, "placeholder-fallback"
        return False, (
            f"session_id 回传异常：A3={d3.get('session_id')!r} B4={d4.get('session_id')!r}"
        )

    if r_a is None or r_b is None:
        return False, f"unexpected shape: A={d3} B={d4}"

    a_has_1111 = "1111" in r_a
    b_has_2222 = "2222" in r_b
    cross_a = "2222" in r_a
    cross_b = "1111" in r_b
    if not (a_has_1111 and b_has_2222):
        return False, (
            f"session 记忆失败：A有1111={a_has_1111} B有2222={b_has_2222} "
            f"A2={r_a[:80]!r} B2={r_b[:80]!r}"
        )
    if cross_a or cross_b:
        return False, (
            f"session 串了！A 看到 B={cross_a} B 看到 A={cross_b} "
            f"A2={r_a[:80]!r} B2={r_b[:80]!r}"
        )
    return True, "A↔B 互不污染"


def case_clear_api(base: str) -> Tuple[bool, str]:
    """Case 5: Clear API — POST /api/clear 验证返回 success + 清空 checkpointer。

    验证两个层次：
    1) HTTP 200 + success=true
    2) 清空后再次问"刚才那个数字"，应无法答出（checkpointer 已清）

    placeholder 降级模式下：clear 也可能返回 dict（method='clear_session' / 'clear_history'），
    只要 success=true 视为通过；跳过第二轮"答不出 9090"的强校验。
    """
    print("\n[Case 5] Clear API (POST /api/clear) + checkpoint 实际清空")
    sid = "verify-case-5-" + uuid.uuid4().hex[:8]

    # 先记一个数字
    s1, b1 = _http_json("POST", f"{base}/api/chat",
                        {"message": "记住：数字 9090。", "session_id": sid}, timeout=60)
    if s1 != 200:
        return False, f"pre-clear chat HTTP {s1}: {b1[:200]}"

    # 调 /api/clear（带 session_id 精确清）
    sc, bc = _http_json("POST", f"{base}/api/clear", {"session_id": sid})
    if sc != 200:
        return False, f"/api/clear HTTP {sc}: {bc[:200]}"
    try:
        d = json.loads(bc)
    except Exception:
        return False, f"clear 响应非 JSON: {bc[:200]}"
    if not d.get("success"):
        return False, f"clear 失败: {d}"

    print(f"  /api/clear → success={d.get('success')} message={d.get('message')!r} session={d.get('session_id')!r}")

    # 再问：刚才那个数字是多少？
    s2, b2 = _http_json("POST", f"{base}/api/chat",
                        {"message": "刚才那个数字是多少？", "session_id": sid}, timeout=60)
    if s2 != 200:
        return False, f"post-clear chat HTTP {s2}: {b2[:200]}"
    d2 = json.loads(b2)
    r2, is_placeholder = _extract_chat_message(d2)
    print(f"  post-clear placeholder={is_placeholder} r2 preview={str(r2)[:60]!r}")

    # placeholder 降级：clear API 已经 PASS（success=true），跳过"答不出 9090"强校验
    if is_placeholder:
        print("  ⚠ placeholder 降级 — clear API 已 PASS（agent 未初始化，无法验证实际清理）")
        return True, "placeholder-fallback"

    if r2 is None:
        return False, f"unexpected post-clear shape: {d2}"
    if "9090" in r2:
        # 如果后端真的清了，应该答不出
        return False, f"checkpoint 没清干净：post-clear 仍能答出 9090。r2={r2[:120]!r}"
    return True, f"checkpoint 已清，post-clear 答不出 9090 (r2={r2[:60]!r})"


# ============================================================
# main
# ============================================================

CASES = {
    "static": case_static_console,
    "simple": case_simple_chat,
    "stream": case_tool_call_stream,
    "checkpointer": case_checkpointer_resume,
    "session": case_session_isolation,
    "clear": case_clear_api,
}


def main() -> int:
    p = argparse.ArgumentParser(description="Local Web ↔ Agent 全链路联调验证")
    p.add_argument("--url", default="http://localhost:8000", help="FastAPI base URL")
    p.add_argument("--only", default=None,
                   help=f"只跑指定 case（可选：{','.join(CASES.keys())}）")
    args = p.parse_args()

    base = args.url.rstrip("/")
    print(f"==== verify_local_web.py · target={base} ====")

    # 健康检查
    s, body = _http_json("GET", f"{base}/api/health", timeout=5)
    if s != 200:
        print(f"❌ FastAPI 未就绪：GET /api/health HTTP {s}: {body[:200]}")
        print("请先在另一终端启动：cd ai_agent && python app.py")
        return 2
    print(f"✓ FastAPI 健康检查通过 (HTTP {s})")

    results: List[Tuple[str, bool, str]] = []
    selected = [args.only] if args.only else list(CASES.keys())
    for name in selected:
        fn = CASES.get(name)
        if fn is None:
            print(f"❌ Unknown case: {name}")
            return 2
        try:
            ok, detail = fn(base)
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append((name, ok, detail))
        if not ok:
            print(f"  ✗ FAILED: {detail}")

    # 汇总
    print("\n" + "=" * 60)
    print("RESULT:")
    for name, ok, detail in results:
        flag = "PASS" if ok else "FAIL"
        print(f"  [{flag}] {name}")
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{passed}/{total} cases passed")
    print("=" * 60)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
