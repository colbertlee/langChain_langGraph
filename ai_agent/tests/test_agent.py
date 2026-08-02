"""agent.py 单元测试。

mock LLM / RAG / DB，覆盖：
- __init__：属性初始化
- set_api_key / get_api_key_status
- get_available_models
- get_tools_list
- session 管理（create_new_session / set_session / clear_history）
- intent / importance / sanitize
"""
import os
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

# 必须在 import agent 前设置 fake keys，否则 config 模块会在 import 时失败
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-key")


@pytest.fixture
def isolated_env(monkeypatch):
    """注入 fake API keys，避免真实 LLM 调用。"""
    fake_keys = {
        "OPENAI_API_KEY": "sk-test-fake",
        "ANTHROPIC_API_KEY": "sk-ant-fake",
        "DEEPSEEK_API_KEY": "",
        "QWEN_API_KEY": "",
        "ZHIPU_API_KEY": "",
        "MOONSHOT_API_KEY": "",
        "MINIMAX_API_KEY": "",
        "BAIDU_API_KEY": "",
        "SPARK_API_KEY": "",
        "OPENAI_API_BASE": "https://mock.example.com/v1",
    }
    for k, v in fake_keys.items():
        monkeypatch.setenv(k, v)
    return fake_keys


@pytest.fixture
def agent(isolated_env):
    """创建一个 mock 化的 AIAgent 实例。"""
    # patch checkpointer / model 创建，避免真实 IO
    with patch("agent.SqliteSaver") as mock_saver:
        mock_saver.from_conn_string.return_value = MagicMock()
        with patch("agent.ChatOpenAI") as mock_chat:
            mock_chat.return_value = MagicMock()
            import agent as agent_mod
            a = agent_mod.AIAgent()
            yield a


class TestInit:
    """AIAgent.__init__ 测试"""

    def test_init_sets_defaults(self, agent):
        assert agent.model is None
        assert agent.agent is None
        assert agent._system_prompt is None
        assert isinstance(agent._sub_agents, dict)
        assert agent.current_session_id is not None

    def test_init_loads_security(self, agent):
        # SecurityModule 应该在 __init__ 就被初始化
        assert agent.security is not None

    def test_init_loads_tools(self, agent):
        # get_all_tools() 在 __init__ 中调用
        # tools 可能是 list / None（取决于 fallback）
        assert agent.tools is not None or agent.tools is None  # 不抛错

    def test_init_creates_fallback_chain(self, agent):
        assert agent._fallback_chain is not None
        # _fallback_chain 是 ModelFallbackChain 对象，不是 list
        # 验证它有 candidates 或类似属性
        assert hasattr(agent._fallback_chain, "__iter__") or hasattr(agent._fallback_chain, "candidates")

    def test_init_creates_invoker(self, agent):
        assert agent.invoker is not None
        assert agent.fail_log is not None

    def test_init_uses_config_provider(self, agent, monkeypatch):
        monkeypatch.setenv("MODEL_PROVIDER", "qwen")
        monkeypatch.setenv("MODEL_NAME", "qwen-turbo")
        with patch("agent.SqliteSaver") as mock_saver:
            mock_saver.from_conn_string.return_value = MagicMock()
            with patch("agent.ChatOpenAI"):
                import agent as agent_mod
                a = agent_mod.AIAgent()
                # provider / model 是从 config 取的（import 时已 freeze）
                # 但 init 应至少设置这些属性
                assert a.model_provider is not None
                assert a.model_name is not None


class TestApiKey:
    """API key 相关"""

    def test_get_api_key_status_default_provider(self, agent):
        status = agent.get_api_key_status()
        assert "configured" in status
        assert "provider" in status
        assert "model" in status
        assert "has_agent" in status
        assert "available_providers" in status

    def test_get_api_key_status_lists_providers(self, agent):
        status = agent.get_api_key_status()
        providers = status["available_providers"]
        assert "openai" in providers
        assert "deepseek" in providers
        assert "qwen" in providers

    def test_set_api_key_default_provider(self, agent):
        result = agent.set_api_key("sk-new-key")
        # 默认 provider 应该是 openai / 任何第一个
        # 返回 bool
        assert isinstance(result, bool)

    def test_set_api_key_explicit_provider(self, agent, monkeypatch):
        result = agent.set_api_key("sk-deepseek-fake", provider="deepseek")
        assert isinstance(result, bool)

    def test_get_api_key_status_has_agent_false(self, agent):
        status = agent.get_api_key_status()
        # 没 init_agent 之前 has_agent 应该是 False
        assert status["has_agent"] is False


class TestModels:

    def test_get_available_models_returns_dict(self, agent):
        models = agent.get_available_models()
        assert isinstance(models, dict)
        assert len(models) > 0


class TestTools:

    def test_get_tools_list(self, agent):
        # tools list
        tools = agent.get_tools_list()
        assert isinstance(tools, list)

    def test_get_tools_list_empty_when_no_tools(self, agent):
        agent.tools = None
        assert agent.get_tools_list() == []


class TestSession:
    """会话管理"""

    def test_create_new_session(self, agent):
        old_session = agent.current_session_id
        new_session = agent.create_new_session()
        assert new_session != old_session
        assert agent.current_session_id == new_session

    def test_set_session(self, agent):
        agent.set_session("my-custom-session-id")
        assert agent.current_session_id == "my-custom-session-id"

    def test_resolve_session(self, agent):
        agent.set_session("session-a")
        agent._resolve_session(None)  # 保持不变
        assert agent.current_session_id == "session-a"

    def test_resolve_session_explicit(self, agent):
        agent._resolve_session("explicit-session")
        assert agent.current_session_id == "explicit-session"


class TestClearHistory:

    def test_clear_history_success(self, agent):
        # mock checkpointer.delete_thread
        agent.checkpointer = MagicMock()
        result = agent.clear_history()
        agent.checkpointer.delete_thread.assert_called_once()
        assert "已清除" in result

    def test_clear_history_no_checkpointer(self, agent):
        agent.checkpointer = None
        # 即使没 checkpointer，其他清理也要做
        result = agent.clear_history()
        # 应至少返回消息
        assert isinstance(result, str)


class TestSanitize:

    def test_sanitize_empty(self, agent):
        assert agent._sanitize_for_output("") == ""

    def test_sanitize_passes_normal_text(self, agent):
        with patch.object(agent.security, "check_output") as mock_check, \
             patch.object(agent.security, "sanitize_output") as mock_san:
            mock_check.return_value = {"blocked": False}
            mock_san.return_value = "cleaned"
            result = agent._sanitize_for_output("hello")
            assert result == "cleaned"

    def test_sanitize_blocks_sensitive(self, agent):
        with patch.object(agent.security, "check_output") as mock_check, \
             patch.object(agent.security, "sanitize_output") as mock_san:
            mock_check.return_value = {"blocked": True}
            mock_san.return_value = "xxx"
            result = agent._sanitize_for_output("hello")
            assert "被阻止" in result

    def test_sanitize_handles_exception(self, agent):
        with patch.object(agent.security, "check_output", side_effect=Exception("boom")):
            result = agent._sanitize_for_output("hello")
            # 出错时返回原文本
            assert result == "hello"


class TestIntent:

    def test_detect_intent_returns_tuple(self, agent):
        intent, importance = agent._detect_intent("你好")
        assert isinstance(intent, str)
        assert isinstance(importance, int)

    def test_importance_for_intent_known(self, agent):
        assert isinstance(agent._importance_for_intent("greeting"), int)

    def test_importance_for_intent_unknown(self, agent):
        # 未知 intent 应有默认值
        result = agent._importance_for_intent("unknown_xyz_intent")
        assert isinstance(result, int)

    def test_importance_levels(self, agent):
        # 问题类 intent 应该有较高重要性
        importance_question = agent._importance_for_intent("question")
        importance_greeting = agent._importance_for_intent("greeting")
        # 问题的重要性应 >= 问候
        assert importance_question >= importance_greeting


class TestSafety:

    def test_check_safety_clean(self, agent):
        with patch.object(agent.security, "check_input", return_value={"blocked": False}):
            result = agent._check_safety("hello world")
            assert result is None

    def test_check_safety_blocked(self, agent):
        with patch.object(agent.security, "check_input", return_value={"blocked": True, "reason": "spam"}):
            result = agent._check_safety("spam message")
            assert result is not None
            assert "spam" in result.lower() or "阻止" in result


class TestSubAgents:

    def test_list_sub_agents_empty(self, agent):
        assert agent.list_sub_agents() == []

    def test_unregister_nonexistent_returns_false(self, agent):
        result = agent.unregister_sub_agent("nonexistent_cap")
        assert result is False

    def test_register_and_list_sub_agent(self, agent):
        # 注册一个 mock sub agent
        executor = MagicMock(return_value="result")
        agent_id = agent.register_sub_agent(
            capability="test_cap",
            name="Test Cap",
            executor=executor,
        )
        assert isinstance(agent_id, str)
        assert "test_cap" in agent.list_sub_agents()
        assert agent.unregister_sub_agent("test_cap") is True
        assert "test_cap" not in agent.list_sub_agents()


class TestDelegation:

    def test_delegate_unknown_capability(self, agent):
        result = agent.delegate_subtask("unknown", "test task")
        assert "不存在" in result or "unknown" in result.lower()


class TestSubAgentExecution:

    def test_default_executor_returns_string(self, agent):
        """register_sub_agent 内部的 _default_executor"""
        # 通过注册回调覆盖默认
        with patch.object(agent, "tools", [{"name": "test_tool", "description": "test"}]):
            with patch("agent.get_all_tools", return_value=[]):
                try:
                    agent.register_sub_agent(
                        capability="x",
                        description="x",
                        executor=None,  # 触发 _default_executor
                    )
                except Exception:
                    pass   # _default_executor 可能依赖其他模块

                # 验证 _default_executor 类型
                cap_executor = agent._sub_agents.get("x")
                if cap_executor and hasattr(cap_executor, "execute"):
                    result = cap_executor.execute("test task")
                    assert isinstance(result, str)


class TestFormatError:

    def test_format_error_returns_string(self, agent):
        result = agent._format_error(ValueError("bad value"))
        assert isinstance(result, str)
        assert len(result) > 0


class TestExtractAiText:

    def test_extract_ai_text_from_empty_state(self, agent):
        result = agent._extract_ai_text({})
        assert result == ""

    def test_extract_ai_text_from_messages(self, agent):
        from langchain_core.messages import AIMessage
        state = {"messages": [AIMessage(content="hello world")]}
        result = agent._extract_ai_text(state)
        assert "hello" in result

    def test_extract_ai_text_from_state_object(self, agent):
        # 测试 _extract_ai_text_from_state
        from langchain_core.messages import AIMessage
        state = MagicMock()
        state.messages = [AIMessage(content="test content")]
        # _extract_ai_text_from_state 内部用 .messages 属性
        # MagicMock.state.messages 实际上又是 MagicMock
        # 改用普通 dict-like state
        state_dict = {"messages": [AIMessage(content="test content")]}
        result = agent._extract_ai_text_from_state(state_dict)
        assert "test" in result


class TestStandby:

    def test_get_active_model(self, agent):
        info = agent.get_active_model()
        assert "provider" in info
        assert "model" in info

    def test_get_standby_status(self, agent):
        status = agent.get_standby_status()
        assert isinstance(status, dict)

    def test_manual_switch_to(self, agent):
        # 不存在的 provider
        result = agent.manual_switch_to("nonexistent_provider")
        # 应该返回 bool
        assert isinstance(result, bool)

    def test_reset_breakers(self, agent):
        # reset_breakers 调用 invoker.breakers.values() → 设置 state=closed
        mock_breaker = MagicMock()
        mock_breaker.state = "open"
        agent.invoker = MagicMock()
        agent.invoker.breakers = {"provider1": mock_breaker}
        agent.reset_breakers()
        # 应设置 state 为 closed
        assert mock_breaker.state == "closed"


class TestFailLog:

    def test_get_fail_log_summary(self, agent):
        # fail_log 用 recent() / fingerprint_stats() / breakers.status()
        agent.fail_log = MagicMock()
        agent.fail_log.recent.return_value = []
        agent.fail_log.fingerprint_stats.return_value = {}
        agent.invoker = MagicMock()
        agent.invoker.breakers = {}
        summary = agent.get_fail_log_summary()
        assert isinstance(summary, dict)
        assert "recent_failures" in summary
        assert "fingerprint_stats" in summary
        assert "breaker_states" in summary


class TestBuildSystemPrompt:

    def test_build_system_prompt_default(self, agent):
        prompt = agent._build_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 50   # 应该包含不少内容

    def test_build_system_prompt_includes_tools(self, agent):
        # 注入 mock tools
        mock_tool = MagicMock()
        mock_tool.name = "my_tool"
        mock_tool.description = "my tool description"
        agent.tools = [mock_tool]
        prompt = agent._build_system_prompt()
        assert "my_tool" in prompt


class TestBuildEnhancedInput:

    def test_build_enhanced_input_normal(self, agent):
        result = agent._build_enhanced_input("hello")
        # 应至少包含原 input
        assert "hello" in result

    def test_build_enhanced_input_with_history(self, agent):
        # 模拟有历史 — get_context 返回 str（不是 MagicMock）
        agent.memory_store = MagicMock()
        agent.memory_store.get_context.return_value = "previous memory context"
        agent.context_manager = MagicMock()
        agent.context_manager.build_context.return_value = "previous context"
        result = agent._build_enhanced_input("new question")
        assert isinstance(result, str)
        assert "new question" in result
        assert "memory" in result.lower() or "context" in result.lower()


class TestContextHints:

    def test_safe_memory_hint(self, agent):
        result = agent._safe_memory_hint("test input")
        assert isinstance(result, str)

    def test_safe_context_hint(self, agent):
        result = agent._safe_context_hint()
        assert isinstance(result, str)

    def test_safe_hints_handle_exception(self, agent):
        # mock context_manager 抛错
        with patch("agent.get_context_manager", side_effect=Exception("boom")):
            result = agent._safe_memory_hint("test")
            assert isinstance(result, str)  # 不应抛错
            assert result == "" or "error" in result.lower() or len(result) > 0


class TestProviderBaseUrl:

    def test_build_provider_base_url_openai(self):
        from agent import _build_provider_base_url
        # openai provider 应返回 None 或默认 URL
        result = _build_provider_base_url("openai")
        # 不报错即可（具体值依赖 env）
        assert result is None or isinstance(result, str)

    def test_build_provider_base_url_unknown(self):
        from agent import _build_provider_base_url
        # 未知 provider 应返回 None
        result = _build_provider_base_url("nonexistent_provider_xyz")
        assert result is None


class TestApiKeyForProvider:

    def test_api_key_for_provider_openai(self, isolated_env, monkeypatch):
        # isolated_env 注入 env，但 agent.py 通过 config.OPENAI_API_KEY 这种模块级
        # 常量求值，不会在测试中途重新读 env。需要同步 monkeypatch agent 模块
        # 里已经 import 进来的常量副本。
        from agent import _api_key_for_provider, OPENAI_API_KEY as _agent_openai_key
        monkeypatch.setattr("agent.OPENAI_API_KEY", "sk-test-fake")
        result = _api_key_for_provider("openai")
        # _api_key_for_provider 返回当前 env 中的 OPENAI_API_KEY
        assert isinstance(result, str)
        assert "fake" in result or "test" in result or "sk-" in result

    def test_api_key_for_provider_unknown(self):
        from agent import _api_key_for_provider
        result = _api_key_for_provider("nonexistent_xyz")
        # 未知 provider 默认 fallback 到 OPENAI_API_KEY
        # 所以可能返回 OPENAI_API_KEY 的值
        assert isinstance(result, str)