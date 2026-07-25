"""
P2-4 Test Agent + P2-5 Multimodal + P2-6 Sandbox 测试
"""

"""Long-running test (>2s). Skipped by default in CI.
Run explicitly with: pytest -m slow

Reason: P2 stage extended tests
"""
import pytest

pytestmark = pytest.mark.slow


import asyncio
import os
import logging
import tempfile

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

import functools
_print = print
def print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    _print(*args, **kwargs)


# ============================================================
# P2-5 Multimodal
# ============================================================

def test_multimodal_basic():
    print("\n[1] Modality 推断")
    from multimodal import Modality, detect_modality_from_mime

    assert detect_modality_from_mime("image/png") == Modality.IMAGE
    assert detect_modality_from_mime("audio/mp3") == Modality.AUDIO
    assert detect_modality_from_mime("video/mp4") == Modality.VIDEO
    assert detect_modality_from_mime("text/plain") == Modality.TEXT
    assert detect_modality_from_mime("application/json") == Modality.STRUCTURED
    assert detect_modality_from_mime("application/octet-stream") == Modality.FILE
    print(f"  PASS - MIME detection works")


def test_multimodal_attachment_store():
    print("\n[2] AttachmentStore")
    from multimodal import get_attachment_store, Attachment, Modality, reset_attachment_store
    import multimodal as _m
    _m._attachment_store = None

    store = get_attachment_store()

    # 文本附件
    att1 = Attachment(
        modality=Modality.TEXT,
        mime="text/plain",
        filename="hello.txt",
        size_bytes=11,
        data=b"hello world",
        sha256="2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
    )
    stored1 = store.add(att1)
    assert stored1.attachment_id

    # 查重
    att1_dup = Attachment(
        modality=Modality.TEXT,
        mime="text/plain",
        sha256=att1.sha256,
    )
    stored1_dup = store.add(att1_dup)
    assert stored1_dup.attachment_id == stored1.attachment_id

    # 查询
    texts = store.query(modality=Modality.TEXT)
    assert len(texts) >= 1

    # 删除
    assert store.delete(stored1.attachment_id)
    print(f"  PASS - {store.stats()}")


def test_multimodal_from_file():
    print("\n[3] Attachment.from_file")
    from multimodal import Attachment

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
        f.write("test content")
        path = f.name

    try:
        att = Attachment.from_file(path)
        assert att.size_bytes == len("test content")
        assert att.mime == "text/plain"
        assert att.modality.value == "text"
        assert len(att.sha256) == 64
        print(f"  PASS - loaded {att.size_bytes} bytes, sha={att.sha256[:8]}...")
    finally:
        os.unlink(path)


async def test_multimodal_processor():
    print("\n[4] AttachmentProcessor")
    from multimodal import get_attachment_store, AttachmentProcessor, Attachment, Modality, reset_attachment_store
    import multimodal as _m
    _m._attachment_store = None

    store = get_attachment_store()
    att = Attachment(
        modality=Modality.TEXT,
        mime="text/plain",
        data=b"hello processor",
        filename="x.txt",
        size_bytes=15,
    )
    store.add(att)

    proc = AttachmentProcessor()
    text = await proc.process(att)
    assert text == "hello processor"
    print(f"  PASS - processor extracted: {text!r}")


# ============================================================
# P2-6 Sandbox
# ============================================================

def test_sandbox_static_check_safe():
    print("\n[5] StaticCheck 安全代码")
    from sandbox import SandboxPolicy, static_check

    policy = SandboxPolicy()
    code = """
x = 1 + 2
result = sum([1, 2, 3])
"""
    violations = static_check(code, policy)
    assert len(violations) == 0, f"unexpected violations: {violations}"
    print(f"  PASS - safe code passes")


def test_sandbox_static_check_dangerous():
    print("\n[6] StaticCheck 危险代码")
    from sandbox import SandboxPolicy, static_check

    policy = SandboxPolicy()

    # 危险 1: blocked builtin
    code1 = "eval('1+1')"
    v1 = static_check(code1, policy)
    assert any("blocked builtin" in x for x in v1), f"expected eval to be blocked, got {v1}"

    # 危险 2: blocked module
    code2 = "import os\nos.system('rm -rf /')"
    v2 = static_check(code2, policy)
    assert any("blocked import" in x for x in v2) or any("blocked module" in x for x in v2), \
        f"expected os to be blocked, got {v2}"

    print(f"  PASS - dangerous code is flagged")


async def test_sandbox_thread_safe():
    print("\n[7] ThreadSandbox 安全执行")
    from sandbox import SandboxPolicy, get_sandbox_runner

    runner = get_sandbox_runner()
    code = """
x = 10
y = 20
__return__ = x + y
"""
    result = await runner.run(code)
    assert result.verdict.value == "allowed"
    assert result.return_value == 30
    print(f"  PASS - returned {result.return_value}")


async def test_sandbox_thread_blocks():
    print("\n[8] ThreadSandbox 拒绝危险代码")
    from sandbox import SandboxPolicy, get_sandbox_runner

    runner = get_sandbox_runner()
    code = "import os\nos.listdir('.')"
    result = await runner.run(code)
    assert result.verdict.value == "blocked"
    assert len(result.blocked_reasons) > 0
    print(f"  PASS - blocked: {result.blocked_reasons}")


async def test_sandbox_thread_timeout():
    print("\n[9] ThreadSandbox 超时")
    from sandbox import SandboxPolicy, SandboxRunner

    policy = SandboxPolicy(timeout_seconds=0.2)
    runner = SandboxRunner(policy=policy)

    def slow_func():
        import time
        time.sleep(3)
        return "done"

    result = await runner.run_function(slow_func)
    assert result.verdict.value == "timeout"
    print(f"  PASS - timeout enforced in {result.duration_ms:.0f}ms")


async def test_sandbox_subprocess():
    print("\n[10] SubprocessSandbox 隔离执行")
    from sandbox import SandboxPolicy, SandboxRunner, SandboxLevel

    policy = SandboxPolicy(level=SandboxLevel.SUBPROCESS, timeout_seconds=5.0)
    runner = SandboxRunner(policy=policy)

    code = "print('hello from subprocess'); print(2+3)"
    result = await runner.run(code)
    assert result.verdict.value == "allowed"
    assert "hello from subprocess" in result.stdout
    print(f"  PASS - subprocess output: {result.stdout.strip()[:60]}")


# ============================================================
# P2-4 Test Agent
# ============================================================

async def test_test_case_basic():
    print("\n[11] TestCase 基本")
    from test_agent import TestCase, assert_equals, assert_truthy

    async def my_action():
        return 42

    case = TestCase(
        name="returns_42",
        action=my_action,
        assertions=[assert_equals(42)],
    )
    await case.run()
    assert case.status.value == "passed"
    print(f"  PASS - case {case.name}: {case.status.value}")


async def test_test_case_failure():
    print("\n[12] TestCase 失败")
    from test_agent import TestCase, assert_equals

    def my_action():
        return 100

    case = TestCase(
        name="wrong_value",
        action=my_action,
        assertions=[assert_equals(42)],
    )
    await case.run()
    assert case.status.value == "failed"
    assert "expected 42" in case.error
    print(f"  PASS - failure detected: {case.error}")


async def test_test_suite():
    print("\n[13] TestSuite 多个用例")
    from test_agent import TestSuite, assert_truthy, assert_contains, assert_isinstance

    suite = TestSuite(name="basic_suite")

    suite.add_simple("has_workers", lambda: [{"id": "w1"}], [assert_isinstance(list)])
    suite.add_simple("has_message", lambda: "hello", [assert_contains("hello")])
    suite.add_simple("truthy_value", lambda: 1, [assert_truthy()])

    result = await suite.run()
    assert result["total"] == 3
    assert result["passed"] == 3
    assert result["failed"] == 0
    print(f"  PASS - suite {result['pass_rate']:.0%}")


async def test_test_generator_smoke():
    print("\n[14] TestCaseGenerator smoke test")
    from observability import reset_observability
    reset_observability()
    import observability as _obs
    _obs._observability = None
    from message_bus import get_message_bus
    from multi_agent_integration import AIAgentExtension
    from test_agent import TestCaseGenerator

    bus = get_message_bus()
    bus.reset()

    class FakeAgent:
        def __init__(self):
            self.model = None
            self.current_session_id = "test_agent"

        async def run(self, prompt):
            return f"[Agent] {prompt}"

    fake = FakeAgent()
    ext = AIAgentExtension(fake)
    await ext.initialize()

    gen = TestCaseGenerator(registry=ext)
    suite = gen.generate_smoke_test(ext)
    assert len(suite.cases) >= 3

    result = await suite.run()
    print(f"  PASS - smoke: {result['passed']}/{result['total']} passed")


def test_assertion_helpers():
    print("\n[15] 断言工厂函数")
    from test_agent import (
        assert_equals, assert_contains, assert_truthy,
        assert_matches, assert_greater_than, assert_less_than,
        assert_isinstance,
    )

    a1 = assert_equals(5)
    assert a1.check(5)[0] is True
    assert a1.check(6)[0] is False

    a2 = assert_contains("foo")
    assert a2.check("hello foo bar")[0] is True

    a3 = assert_matches(r"\d+")
    assert a3.check("123")[0] is True

    a4 = assert_greater_than(10)
    assert a4.check(20)[0] is True
    assert a4.check(5)[0] is False

    a5 = assert_isinstance(list)
    assert a5.check([])[0] is True

    print(f"  PASS - all assertion factories work")


async def test_test_runner_register():
    print("\n[16] TestRunner 注册 + 跑")
    from test_agent import TestRunner, TestSuite, assert_truthy, reset_test_runner
    import test_agent as _t
    _t._test_runner = None

    runner = TestRunner()
    suite = TestSuite(name="runner_test")
    suite.add_simple("ok", lambda: True, [assert_truthy()])
    suite.add_simple("failing", lambda: False, [assert_truthy()])

    runner.register(suite)
    assert len(runner.list_suites()) == 1

    result = await runner.run_suite(suite.suite_id)
    assert result["total"] == 2
    assert result["passed"] == 1
    assert result["failed"] == 1

    report = runner.generate_report(format="text")
    assert "Test Report" in report
    assert "Total: 2" in report

    stats = runner.stats()
    assert stats["total_cases"] == 2
    print(f"  PASS - {stats}")


# ============================================================
# AIAgentExtension 集成
# ============================================================

async def test_extension_multimodal_sandbox_test_api():
    print("\n[17] AIAgentExtension 三模块 API 集成")
    from observability import reset_observability
    reset_observability()
    import observability as _obs
    _obs._observability = None
    from message_bus import get_message_bus
    from multi_agent_integration import AIAgentExtension
    from multimodal import reset_attachment_store, get_attachment_store
    from sandbox import reset_sandbox_runner
    from test_agent import reset_test_runner
    import multimodal as _m
    import sandbox as _s
    import test_agent as _t
    _m._attachment_store = None
    _s._sandbox_runner = None
    _t._test_runner = None

    bus = get_message_bus()
    bus.reset()

    class FakeAgent:
        def __init__(self):
            self.model = None
            self.current_session_id = "extension_int"

        async def run(self, prompt):
            return f"[Agent] {prompt}"

    fake = FakeAgent()
    ext = AIAgentExtension(fake)
    await ext.initialize()

    # multimodal: 添加附件（用临时文件）
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
        f.write("attachment content")
        path = f.name
    try:
        att = ext.add_attachment_from_file(path, source="user")
        assert att["filename"].endswith(".txt")
        assert att["size_bytes"] == len("attachment content")
        # 列出
        listed = ext.list_attachments(modality="text")
        assert len(listed) >= 1
        stats = ext.get_attachment_stats()
        assert stats["count"] >= 1
    finally:
        os.unlink(path)

    # sandbox: 静态检查
    safe_check = ext.sandbox_check("x = 1 + 1")
    assert safe_check["blocked"] is False
    bad_check = ext.sandbox_check("import os; os.system('rm -rf /')")
    assert bad_check["blocked"] is True

    # sandbox: 实际运行
    sandbox_result = await ext.sandbox_run("__return__ = 6 * 7")
    assert sandbox_result["verdict"] == "allowed"
    assert sandbox_result["return_value"] == 42

    # test_agent: smoke test
    smoke_result = await ext.run_smoke_test()
    assert smoke_result["total"] >= 3

    # 报告
    report = ext.get_test_report("text")
    assert "Test Report" in report

    # 测试统计（smoke test 直接跑，不经过 runner，所以 suite_count 可能为 0；
    # 注册一个 suite 然后跑）
    suite_info = ext.register_test_suite("extra_test")
    ext.add_test_case(suite_info["suite_id"], "ok", lambda: True, "truthy")
    test_results = await ext.run_test_suite(suite_info["suite_id"])
    assert test_results["passed"] >= 1

    test_stats = ext.get_test_stats()
    assert test_stats["suite_count"] >= 1
    assert test_stats["total_cases"] >= 1

    print(f"  PASS - multimodal + sandbox + test_agent APIs")


# ============================================================
# 主函数
# ============================================================

async def main():
    print("\n" + "#"*60)
    print(" P2-4 + P2-5 + P2-6 Tests")
    print("#"*60)

    failures = []

    tests = [
        ("mm_modality", test_multimodal_basic, False),
        ("mm_store", test_multimodal_attachment_store, False),
        ("mm_file", test_multimodal_from_file, False),
        ("mm_processor", test_multimodal_processor, True),
        ("sb_static_safe", test_sandbox_static_check_safe, False),
        ("sb_static_bad", test_sandbox_static_check_dangerous, False),
        ("sb_thread_safe", test_sandbox_thread_safe, True),
        ("sb_thread_block", test_sandbox_thread_blocks, True),
        ("sb_timeout", test_sandbox_thread_timeout, True),
        ("sb_subprocess", test_sandbox_subprocess, True),
        ("ta_case_basic", test_test_case_basic, True),
        ("ta_case_fail", test_test_case_failure, True),
        ("ta_suite", test_test_suite, True),
        ("ta_gen_smoke", test_test_generator_smoke, True),
        ("ta_assertions", test_assertion_helpers, False),
        ("ta_runner", test_test_runner_register, True),
        ("ext_integration", test_extension_multimodal_sandbox_test_api, True),
    ]

    for name, fn, is_async in tests:
        try:
            if is_async:
                await fn()
            else:
                fn()
        except Exception as e:
            failures.append((name, e))
            print(f"  FAIL: {e}")
            import traceback; traceback.print_exc()

    print("\n" + "#"*60)
    if not failures:
        print(f" All {len(tests)} tests passed")
    else:
        print(f" {len(failures)}/{len(tests)} failed: {[n for n,_ in failures]}")
    print("#"*60)


if __name__ == "__main__":
    asyncio.run(main())