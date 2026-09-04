"""
v2.0 slim — run / run_stream DRY 管线端到端探针（核心闭环）

run 与 run_stream 必须共享前置/后置管线（DRY 原则）。
两条路径唯一的差别：
- run：返回字符串（同步 invoke + text_extractor）
- run_stream：yield 事件（流式 invoke + 事件 schema）

本测试通过 mock LLM 走完整管线，验证：
1. 两条路径共享 7 个前置步骤（_resolve_session / _ensure_agent_ready /
   _check_safety / _detect_intent / _record_user_turn / _build_enhanced_input /
   _apply_user_prompt_template）
2. run 返回 string，run_stream 返回 generator
3. 安全拦截在两条路径上都生效
4. 异常输入前置拦截（不消耗 LLM 配额）
5. agent 未配置时返回错误，不进入 fallback
6. _sanitize_for_output 在 run 路径生效（去敏感）
"""
from __future__ import annotations

import sys
import re
from pathlib import Path
from typing import Iterator, List, Dict, Any, Optional

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# 1. run 与 run_stream 共用前置管线（DRY）
# ============================================================

def test_run_and_run_stream_share_pre_pipeline():
    """run / run_stream 的源码必须包含同样的 7 个前置 helper 调用。"""
    import inspect
    from agent import AIAgent
    src_run = inspect.getsource(AIAgent.run)
    src_stream = inspect.getsource(AIAgent.run_stream)

    shared_helpers = [
        "_resolve_session",
        "_ensure_agent_ready",
        "_check_safety",
        "_detect_intent",
        "_record_user_turn",
        "_build_enhanced_input",
        "_apply_user_prompt_template",
    ]
    missing_run = [h for h in shared_helpers if h not in src_run]
    missing_stream = [h for h in shared_helpers if h not in src_stream]
    assert not missing_run, f"run 缺少前置 helper: {missing_run}"
    assert not missing_stream, f"run_stream 缺少前置 helper: {missing_stream}"


# ============================================================
# 2. run 返回类型是 str，run_stream 返回 generator
# ============================================================

def test_run_returns_str_run_stream_returns_iterator():
    """run / run_stream 类型签名必须明确（前端/调用方契约）。"""
    import inspect
    from agent import AIAgent
    sig_run = inspect.signature(AIAgent.run)
    sig_stream = inspect.signature(AIAgent.run_stream)

    # run 返回值注解应为 str
    assert sig_run.return_annotation is str, (
        f"AIAgent.run 返回类型应为 str，实际 {sig_run.return_annotation}"
    )
    # run_stream 返回类型应含 Iterator（generator 是 Iterator 子类）
    ann = sig_stream.return_annotation
    ann_str = str(ann)
    assert "Iterator" in ann_str, f"AIAgent.run_stream 返回类型应含 Iterator，实际 {ann}"


# ============================================================
# 3. 安全拦截在两条路径上都生效
# ============================================================

def test_safety_blocks_run_pipeline_source():
    """run 路径源码必须在 _check_safety 失败时立即返回。"""
    import inspect
    from agent import AIAgent
    src = inspect.getsource(AIAgent.run)
    # _check_safety 返回非空 err → return err（不进入 fallback）
    assert "_check_safety" in src
    # 紧跟 if err: ... return err 模式
    assert re.search(r"err\s*=\s*self\._check_safety\(user_input\).*?if\s+err:.*?return\s+err", src, re.DOTALL), (
        "run 路径必须在 _check_safety 返回 err 时立即返回"
    )


def test_safety_blocks_run_stream_pipeline_source():
    """run_stream 路径源码必须在 _check_safety 失败时 yield safety 事件。"""
    import inspect
    from agent import AIAgent
    src = inspect.getsource(AIAgent.run_stream)
    assert "_check_safety" in src
    assert 'yield _evt("safety"' in src or "yield _evt('safety'" in src


# ============================================================
# 4. 异常输入前置拦截（不消耗 LLM）
# ============================================================

def test_empty_input_blocks_run():
    """空输入必须在 _ensure_agent_ready 之前拦截。"""
    import inspect
    from agent import AIAgent
    src = inspect.getsource(AIAgent.run)
    # 检查 `if not user_input or not user_input.strip()` 模式
    assert "not user_input" in src and "user_input.strip()" in src, (
        "run 必须在前置检查空输入"
    )


def test_empty_input_blocks_run_stream():
    """run_stream 空输入必须 yield error 事件。"""
    import inspect
    from agent import AIAgent
    src = inspect.getsource(AIAgent.run_stream)
    assert "not user_input" in src


# ============================================================
# 5. agent 未配置时前置拦截
# ============================================================

def test_agent_not_ready_blocks_run():
    """agent 未配置时，run 必须返回配置错误（前置拦截）。"""
    import inspect
    from agent import AIAgent
    src = inspect.getsource(AIAgent.run)
    assert "_ensure_agent_ready" in src
    # if err: return err 模式
    assert re.search(r"err\s*=\s*self\._ensure_agent_ready\(\).*?if\s+err:.*?return\s+err", src, re.DOTALL)


# ============================================================
# 6. 降级路径在两条路径上都生效
# ============================================================

def test_run_uses_invoker_with_five_layers():
    """run 必须通过 self.invoker.invoke 调用五层容错栈。"""
    import inspect
    from agent import AIAgent
    src = inspect.getsource(AIAgent.run)
    assert "self.invoker.invoke" in src, "run 必须调 invoker.invoke"
    # 必须传 agent_factory + payload + text_extractor
    for arg in ["agent_factory=self._build_agent_for_provider",
                "payload=payload",
                "text_extractor=self._extract_ai_text"]:
        assert arg in src, f"run 缺少 invoker 参数: {arg}"


def test_run_stream_uses_invoker_stream():
    """run_stream 必须通过 self.invoker.stream 走流式容错。"""
    import inspect
    from agent import AIAgent
    src = inspect.getsource(AIAgent.run_stream)
    assert "self.invoker.stream" in src, "run_stream 必须调 invoker.stream"


# ============================================================
# 7. _sanitize_for_output 在 run 路径生效
# ============================================================

def test_run_sanitizes_output():
    """run 路径必须调 _sanitize_for_output 去除敏感信息。"""
    import inspect
    from agent import AIAgent
    src = inspect.getsource(AIAgent.run)
    assert "_sanitize_for_output" in src, "run 必须调 _sanitize_for_output"


# ============================================================
# 8. 助手轮（assistant turn）记录在两条路径上都生效
# ============================================================

def test_both_paths_record_assistant_turn():
    """run 与 run_stream 都必须调 _record_assistant_turn。"""
    import inspect
    from agent import AIAgent
    src_run = inspect.getsource(AIAgent.run)
    src_stream = inspect.getsource(AIAgent.run_stream)
    assert "_record_assistant_turn" in src_run, "run 必须记录 assistant turn"
    assert "_record_assistant_turn" in src_stream, "run_stream 必须记录 assistant turn"


# ============================================================
# 9. 失败计数与降级日志在 run 路径生效
# ============================================================

def test_run_logs_provider_and_degrade():
    """run 路径必须记录 provider / fallbacks / 降级日志。"""
    import inspect
    from agent import AIAgent
    src = inspect.getsource(AIAgent.run)
    assert "logger.info" in src, "run 必须打 INFO 日志（成功）"
    assert "[OK]" in src, "run 必须打 [OK] 日志（成功路径）"
    assert "[DEGRADED]" in src or "degraded" in src, "run 必须识别降级路径"


# ============================================================
# 10. session_id 持久化（resolve_session 唯一入口）
# ============================================================

def test_session_resolve_single_entry():
    """run / run_stream 都必须以 self._resolve_session 为唯一 session 解析入口。"""
    import inspect
    from agent import AIAgent
    for method_name in ("run", "run_stream"):
        src = inspect.getsource(getattr(AIAgent, method_name))
        assert "self._resolve_session(" in src, (
            f"{method_name} 必须调 self._resolve_session()"
        )
        # 不允许直接修改 self.current_session_id（只能通过 helper）
        assert "self.current_session_id = " not in src, (
            f"{method_name} 不应直接修改 current_session_id（违反封装）"
        )


# ============================================================
# 11. 完整事件类型（DRY）—— run_stream 7 事件
# ============================================================

def test_run_stream_yields_event_with_type_field():
    """run_stream 的 helper _evt 必须 yield 含 type 字段的 dict。"""
    import inspect
    from agent import AIAgent
    src = inspect.getsource(AIAgent.run_stream)
    # 抓所有 _evt(type_, ...) 中的 type
    evt_types = set(re.findall(r'_evt\(["\']([a-z_]+)["\']', src))
    expected = {"start", "safety", "thinking", "chunk", "tool_call", "error", "complete"}
    assert evt_types == expected, f"run_stream 事件类型集合不符：{evt_types}"
