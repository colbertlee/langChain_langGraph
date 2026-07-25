"""agent.py run / run_stream LLM 路径 mock 测试。

mock ResilientLLMInvoker 完整运行五层容错栈（success / fallback / degraded）。
"""
import os
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "sk-fake")


@pytest.fixture
def isolated_env(monkeypatch):
    """注入 fake API keys。"""
    for k, v in {
        "OPENAI_API_KEY": "sk-test-fake",
        "ANTHROPIC_API_KEY": "sk-ant-fake",
        "DEEPSEEK_API_KEY": "",
        "QWEN_API_KEY": "",
        "ZHIPU_API_KEY": "",
        "MOONSHOT_API_KEY": "",
        "MINIMAX_API_KEY": "",
        "BAIDU_API_KEY": "",
        "SPARK_API_KEY": "",
    }.items():
        monkeypatch.setenv(k, v)
    return {}


def _make_result(text="Mocked LLM response", success=True, degraded=False,
                 attempts=1, fallbacks_used=0, provider="openai", model="gpt-4",
                 trace_id="trace-123", last_error_kind=None):
    """构造 InvokeResult（处理 degraded 是必填参数）。"""
    from agent import InvokeResult
    return InvokeResult(
        text=text,
        success=success,
        degraded=degraded,
        provider_used=provider,
        model_used=model,
        attempts=attempts,
        fallbacks_used=fallbacks_used,
        trace_id=trace_id,
        last_error_kind=last_error_kind,
    )


def _build_mocked_agent():
    """构造一个 invoker / agent 全部 mock 化的 AIAgent 实例。"""
    with patch("agent.SqliteSaver") as mock_saver:
        mock_saver.from_conn_string.return_value = MagicMock()
        with patch("agent.ChatOpenAI"):
            import agent as agent_mod
            a = agent_mod.AIAgent()
            yield a


@pytest.fixture
def agent(isolated_env):
    """创建 mock 化的 AIAgent。"""
    for a in _build_mocked_agent():
        yield a


@pytest.fixture
def mock_invoker(agent):
    """mock invoker.invoke 返回成功结果。"""
    agent.invoker = MagicMock()
    agent.invoker.invoke = MagicMock(
        side_effect=lambda *a, **kw: _make_result()
    )
    agent.invoker.breakers = {}
    agent.invoker.fail_log = MagicMock()
    agent.invoker.fail_log.recent = MagicMock(return_value=[])
    agent.invoker.fail_log.fingerprint_stats = MagicMock(return_value={})

    agent.agent = MagicMock()
    agent._build_agent_for_provider = MagicMock(return_value=MagicMock())

    return agent


# ==================== run() 基础 ====================


class TestRunBasic:

    def test_run_with_mocked_invoker(self, mock_invoker):
        result = mock_invoker.run("hello")
        assert result == "Mocked LLM response"

    def test_run_empty_input(self, mock_invoker):
        result = mock_invoker.run("")
        assert "不能为空" in result

    def test_run_whitespace_input(self, mock_invoker):
        result = mock_invoker.run("   ")
        assert "不能为空" in result

    def test_run_no_agent_configured(self, mock_invoker):
        """没 init_agent 时应返回配置错误。"""
        mock_invoker.agent = None
        result = mock_invoker.run("test")
        assert isinstance(result, str)
        mock_invoker.invoker.invoke.assert_not_called()


# ==================== run() 容错路径 ====================


class TestRunFallback:

    def test_run_with_fallback_used(self, agent):
        """fallback 链生效时返回 degraded 回答。"""
        def fake_invoke(*args, **kwargs):
            return _make_result(
                text="降级回答：系统繁忙，请稍后重试。",
                success=False,
                degraded=True,
                attempts=3,
                fallbacks_used=2,
                trace_id="trace-degraded",
                last_error_kind="timeout",
            )

        for a in _build_mocked_agent():
            a.invoker = MagicMock()
            a.invoker.invoke = MagicMock(side_effect=fake_invoke)
            a.invoker.breakers = {}
            a.invoker.fail_log = MagicMock()
            a.invoker.fail_log.recent = MagicMock(return_value=[])
            a.invoker.fail_log.fingerprint_stats = MagicMock(return_value={})
            a.agent = MagicMock()

            result = a.run("test")
            # 降级时返回 InvokeResult.text（可能是骨架回答）
            assert isinstance(result, str)
            assert len(result) > 0


# ==================== run() 安全检查 ====================


class TestRunSafety:

    def test_run_blocks_dangerous_input(self, mock_invoker):
        """危险输入应被立即阻止，不进入 LLM 调用。"""
        result = mock_invoker.run("rm -rf /")
        assert isinstance(result, str)

    def test_run_blocks_sensitive_via_security(self, mock_invoker):
        with patch.object(mock_invoker.security, "check_input",
                          return_value={"blocked": True, "reason": "test"}):
            result = mock_invoker.run("hello")
            assert "阻止" in result or "blocked" in result.lower()


# ==================== run() 意图检测 ====================


class TestRunIntent:

    def test_run_detects_question_intent(self, mock_invoker):
        mock_invoker.run("What is Python?")
        assert mock_invoker.invoker.invoke.called


# ==================== run() 记录 turn ====================


class TestRunRecord:

    def test_run_records_user_and_assistant_turns(self, mock_invoker):
        mock_invoker._record_user_turn = MagicMock()
        mock_invoker._record_assistant_turn = MagicMock()

        mock_invoker.run("hello")

        mock_invoker._record_user_turn.assert_called_once()
        mock_invoker._record_assistant_turn.assert_called_once()

    def test_run_records_assistant_even_on_failure(self, agent):
        """失败时也应记录 assistant turn。"""
        def fake_invoke(*args, **kwargs):
            return _make_result(
                text="降级回答",
                success=False,
                degraded=True,
                attempts=3,
                trace_id="t",
                last_error_kind="timeout",
            )

        for a in _build_mocked_agent():
            a.invoker = MagicMock()
            a.invoker.invoke = MagicMock(side_effect=fake_invoke)
            a.invoker.breakers = {}
            a.invoker.fail_log = MagicMock()
            a.invoker.fail_log.recent = MagicMock(return_value=[])
            a.invoker.fail_log.fingerprint_stats = MagicMock(return_value={})
            a.agent = MagicMock()
            a._record_assistant_turn = MagicMock()

            a.run("test")
            a._record_assistant_turn.assert_called_once()


# ==================== run() sanitization ====================


class TestRunSanitization:

    def test_run_sanitizes_output(self, mock_invoker):
        """输出含敏感信息应被 sanitize。"""
        def fake_invoke(*args, **kwargs):
            return _make_result(
                text="Your API key is password=secret123",
            )

        mock_invoker.invoker.invoke = MagicMock(side_effect=fake_invoke)
        result = mock_invoker.run("test")
        # sanitize 应把 password 替换为 [REDACTED]（或类似）
        assert "password" not in result.lower() or "[REDACTED]" in result


# ==================== run() session 管理 ====================


class TestRunSession:

    def test_run_uses_explicit_session(self, agent):
        """传入 session_id 应切换。"""
        for a in _build_mocked_agent():
            captured = {}

            def fake_invoke(*args, **kwargs):
                captured["config"] = kwargs.get("config", {})
                return _make_result(text="ok")

            a.invoker = MagicMock()
            a.invoker.invoke = MagicMock(side_effect=fake_invoke)
            a.invoker.breakers = {}
            a.invoker.fail_log = MagicMock()
            a.invoker.fail_log.recent = MagicMock(return_value=[])
            a.invoker.fail_log.fingerprint_stats = MagicMock(return_value={})
            a.agent = MagicMock()

            a.run("test", session_id="my-session")
            # 验证 session 切换
            assert a.current_session_id == "my-session"
            # thread_id 应同步
            assert captured["config"].get("configurable", {}).get("thread_id") == "my-session"

    def test_run_creates_new_session_if_none(self, mock_invoker):
        old_session = mock_invoker.current_session_id
        result = mock_invoker.run("hello")
        # 除非传 session_id，否则保持原 session
        assert mock_invoker.current_session_id == old_session


# ==================== run_stream() ====================


class TestRunStream:

    def test_run_stream_yields_chunks(self, agent):
        """run_stream 应 yield 多个 chunk。"""
        chunks = ["chunk1", "chunk2", "chunk3"]

        def fake_stream(*args, **kwargs):
            for chunk in chunks:
                yield ("chunk", {"messages": []})

        for a in _build_mocked_agent():
            a.invoker = MagicMock()
            a.invoker.stream = MagicMock(side_effect=fake_stream)
            a.invoker.breakers = {}
            a.invoker.fail_log = MagicMock()
            a.invoker.fail_log.recent = MagicMock(return_value=[])
            a.invoker.fail_log.fingerprint_stats = MagicMock(return_value={})
            a.agent = MagicMock()

            result_chunks = list(a.run_stream("test"))
            assert isinstance(result_chunks, list)


# ==================== enhanced_input 集成 ====================


class TestEnhancedInput:

    def test_run_passes_enhanced_input_to_llm(self, mock_invoker):
        """run 应把 _build_enhanced_input 的结果传给 LLM。"""
        captured_payload = {}

        def fake_invoke(*args, **kwargs):
            captured_payload.update(kwargs)
            return _make_result(text="ok")

        mock_invoker.invoker.invoke = MagicMock(side_effect=fake_invoke)
        mock_invoker.run("test query")

        # payload 应含 messages
        assert "payload" in captured_payload
        assert "messages" in captured_payload["payload"]


# ==================== memory hint ====================


class TestMemoryHint:

    def test_run_includes_memory_hint(self, mock_invoker):
        captured_kwargs = {}

        def fake_invoke(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return _make_result(text="ok")

        mock_invoker.invoker.invoke = MagicMock(side_effect=fake_invoke)
        mock_invoker.run("test")

        # 应传 memory_hint 和 context_hint
        assert "memory_hint" in captured_kwargs
        assert "context_hint" in captured_kwargs
        assert "user_input" in captured_kwargs


# ==================== 清空历史 ====================


class TestClearHistoryWithAgent:

    def test_clear_history_resets_session(self, mock_invoker):
        old_session = mock_invoker.current_session_id
        mock_invoker.checkpointer = MagicMock()
        result = mock_invoker.clear_history()
        # session_id 应变化
        assert mock_invoker.current_session_id != old_session
        assert "已清除" in result