"""security.py 单元测试。

覆盖：SecurityModule 的 check_input / check_output / check_tool_execution / sanitize_output / add_guardrail。
"""
import pytest
from unittest.mock import MagicMock

from security import (
    SecurityModule,
    get_security_instance,
    set_security_instance,
    _detect_intent,
)


@pytest.fixture(autouse=True)
def reset_security():
    """每个测试前重置全局 security。"""
    set_security_instance(None)
    yield
    set_security_instance(None)


# ─────────────────── Intent detection ───────────────────


class TestDetectIntent:

    def test_question_intent(self):
        # "What" 触发 query intent
        assert _detect_intent("What is AI?") == "query"

    def test_command_intent(self):
        # "delete" 触发 command intent
        assert _detect_intent("Delete the file") == "command"

    def test_greeting_intent(self):
        # "hello" 触发 greeting intent
        assert _detect_intent("Hello there") == "greeting"

    def test_other_intent(self):
        # 不属于任何已知意图 → "general"（或 "other"）
        result = _detect_intent("xyz random")
        assert result in ("other", "general")


# ─────────────────── SecurityModule init ───────────────────


class TestSecurityInit:

    def test_init(self):
        sec = SecurityModule()
        assert sec.guardrails == []
        assert isinstance(sec.sensitive_patterns, list)
        assert isinstance(sec.dangerous_patterns, list)

    def test_sensitive_patterns_nonempty(self):
        sec = SecurityModule()
        assert len(sec.sensitive_patterns) > 0

    def test_dangerous_patterns_nonempty(self):
        sec = SecurityModule()
        assert len(sec.dangerous_patterns) > 0


# ─────────────────── check_input ───────────────────


class TestCheckInput:

    def test_safe_input(self):
        sec = SecurityModule()
        result = sec.check_input("Hello, how are you?")
        assert result["blocked"] is False
        assert "reason" in result
        assert "detected_intent" in result

    def test_dangerous_command(self):
        sec = SecurityModule()
        result = sec.check_input("rm -rf /")
        assert result["blocked"] is True
        assert "危险" in result["reason"] or "dangerous" in result["reason"].lower()

    def test_dangerous_eval(self):
        sec = SecurityModule()
        result = sec.check_input("eval('malicious code')")
        assert result["blocked"] is True

    def test_dangerous_import(self):
        sec = SecurityModule()
        result = sec.check_input("import os; os.system('rm')")
        assert result["blocked"] is True

    def test_dangerous_open(self):
        sec = SecurityModule()
        result = sec.check_input("Please open('/etc/passwd')")
        assert result["blocked"] is True

    def test_case_insensitive(self):
        sec = SecurityModule()
        result = sec.check_input("RM -RF /")
        assert result["blocked"] is True

    def test_input_with_intent(self):
        sec = SecurityModule()
        result = sec.check_input("What is Python?")
        # "What" → query intent
        assert result["detected_intent"] == "query"

    def test_input_with_greeting_intent(self):
        sec = SecurityModule()
        result = sec.check_input("Hello there")
        assert result["detected_intent"] == "greeting"


# ─────────────────── check_output ───────────────────


class TestCheckOutput:

    def test_safe_output(self):
        sec = SecurityModule()
        result = sec.check_output("This is a normal response")
        assert result["blocked"] is False

    def test_output_with_password(self):
        sec = SecurityModule()
        result = sec.check_output("Your password is secret123")
        assert result["blocked"] is True

    def test_output_with_api_key(self):
        sec = SecurityModule()
        result = sec.check_output("API_KEY=sk-abc123def456")
        assert result["blocked"] is True

    def test_output_with_token(self):
        sec = SecurityModule()
        result = sec.check_output("token: abc123def456")
        assert result["blocked"] is True

    def test_output_with_db_url(self):
        sec = SecurityModule()
        result = sec.check_output("postgres://user:pass@localhost/db")
        assert result["blocked"] is True

    def test_output_with_env_file(self):
        # sensitive_patterns 中 `cookie` 是直接字面匹配
        sec = SecurityModule()
        result = sec.check_output("Set-Cookie: session=abc123")
        assert result["blocked"] is True


# ─────────────────── sanitize_output ───────────────────


class TestSanitizeOutput:

    def test_sanitize_replaces_password(self):
        sec = SecurityModule()
        result = sec.sanitize_output("password: my_secret_123")
        # "password" 关键词被替换为 [REDACTED]
        assert "[REDACTED]" in result
        # 原始 keyword "password" 不应再出现（但 "secret" 后面的内容保留 — sanitize 只替换匹配部分）
        assert "password" not in result.lower()

    def test_sanitize_replaces_token(self):
        sec = SecurityModule()
        result = sec.sanitize_output("token=abc123")
        assert "[REDACTED]" in result
        assert "token" not in result.lower()

    def test_sanitize_safe_text(self):
        sec = SecurityModule()
        result = sec.sanitize_output("This is a normal sentence.")
        assert result == "This is a normal sentence."

    def test_sanitize_multiple_sensitive(self):
        sec = SecurityModule()
        result = sec.sanitize_output("password=abc api_key=xyz token=qwe")
        assert "[REDACTED]" in result
        # 三个 keyword 都被替换
        assert "password" not in result.lower()
        assert "api_key" not in result.lower().replace("[redacted]", "")
        assert "token" not in result.lower().replace("[redacted]", "")


# ─────────────────── check_tool_execution ───────────────────


class TestCheckToolExecution:

    def test_safe_tool(self):
        sec = SecurityModule()
        result = sec.check_tool_execution("search_web", {"query": "AI"})
        assert result["blocked"] is False

    def test_dangerous_tool_write_file(self):
        sec = SecurityModule()
        result = sec.check_tool_execution("write_file", {"path": "/tmp/x", "content": "y"})
        assert result["blocked"] is True

    def test_dangerous_tool_run_code(self):
        sec = SecurityModule()
        result = sec.check_tool_execution("run_code", {"code": "print(1)"})
        assert result["blocked"] is True

    def test_dangerous_tool_delete(self):
        sec = SecurityModule()
        result = sec.check_tool_execution("delete_file", {"path": "/tmp/x"})
        assert result["blocked"] is True

    def test_read_file_safe_path(self):
        sec = SecurityModule()
        result = sec.check_tool_execution("read_file", {"file_path": "documents/x.txt"})
        assert result["blocked"] is False

    def test_read_file_path_traversal_denied(self):
        sec = SecurityModule()
        result = sec.check_tool_execution("read_file", {"file_path": "../etc/passwd"})
        assert result["blocked"] is True

    def test_read_file_absolute_denied(self):
        sec = SecurityModule()
        result = sec.check_tool_execution("read_file", {"file_path": "/etc/passwd"})
        assert result["blocked"] is True


# ─────────────────── add_guardrail ───────────────────


class TestGuardrails:

    def test_add_guardrail(self):
        sec = SecurityModule()
        func = MagicMock(return_value={"blocked": False})
        sec.add_guardrail("my_guard", func)
        assert len(sec.guardrails) == 1
        assert sec.guardrails[0]["name"] == "my_guard"

    def test_guardrail_blocks(self):
        sec = SecurityModule()

        def block_func(text):
            return {"blocked": True, "reason": "custom rule"}

        sec.add_guardrail("custom", block_func)
        result = sec.check_input("hello")
        assert result["blocked"] is True
        assert result["reason"] == "custom rule"

    def test_guardrail_allows(self):
        sec = SecurityModule()

        def allow_func(text):
            return {"blocked": False}

        sec.add_guardrail("allow_all", allow_func)
        result = sec.check_input("hello")
        assert result["blocked"] is False

    def test_dangerous_pattern_checked_first(self):
        """dangerous_patterns 应在 guardrail 之前检查。"""
        sec = SecurityModule()
        call_count = [0]

        def allow_func(text):
            call_count[0] += 1
            return {"blocked": False}

        sec.add_guardrail("allow_all", allow_func)
        result = sec.check_input("rm -rf /")
        assert result["blocked"] is True
        # 不会调用 guardrail
        assert call_count[0] == 0

    def test_multiple_guardrails(self):
        sec = SecurityModule()
        sec.add_guardrail("g1", lambda t: {"blocked": False})
        sec.add_guardrail("g2", lambda t: {"blocked": False})
        assert len(sec.guardrails) == 2


# ─────────────────── Global instance ───────────────────


class TestGlobalInstance:

    def test_get_singleton(self):
        s1 = get_security_instance()
        s2 = get_security_instance()
        assert s1 is s2

    def test_set_instance(self):
        custom = SecurityModule()
        custom.add_guardrail("custom", lambda t: {"blocked": True})
        set_security_instance(custom)
        instance = get_security_instance()
        assert instance is custom

    def test_reset_instance(self):
        s1 = get_security_instance()
        set_security_instance(None)
        s2 = get_security_instance()
        assert s1 is not s2


# ─────────────────── Edge cases ───────────────────


class TestEdgeCases:

    def test_empty_input(self):
        sec = SecurityModule()
        result = sec.check_input("")
        assert result["blocked"] is False

    def test_unicode_input(self):
        sec = SecurityModule()
        result = sec.check_input("你好世界")
        assert result["blocked"] is False
        assert result["detected_intent"] in ("greeting", "other")

    def test_very_long_input(self):
        sec = SecurityModule()
        text = "a" * 10000
        result = sec.check_input(text)
        assert result["blocked"] is False

    def test_sanitize_empty(self):
        sec = SecurityModule()
        assert sec.sanitize_output("") == ""

    def test_sanitize_no_match(self):
        sec = SecurityModule()
        result = sec.sanitize_output("hello world")
        assert result == "hello world"

    def test_check_output_empty(self):
        sec = SecurityModule()
        result = sec.check_output("")
        assert result["blocked"] is False
