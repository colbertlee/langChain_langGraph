"""
任务意图注册表（TaskIntentRegistry）测试

覆盖：
1. Capability / TaskType 数据模型
2. 注册 / 查询 / alias
3. detect_capabilities / detect_task_type / detect_negotiation_hint
4. detect_intent 完整意图识别
5. simple_analysis 兼容输出格式
6. WorkerAgent 使用 registry 的默认值
7. Orchestrator._simple_analysis 走 registry
8. AIAgentExtension 暴露的 intent / route_to_workers / list_capabilities
"""

import asyncio
import os
import logging

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
# 1. 数据模型
# ============================================================

def test_capability_matches():
    print("\n[1] Capability.matches()")
    from task_intent import Capability

    cap = Capability(
        name="search",
        keywords=["搜索", "查找", "search"],
        aliases=["信息检索"],
    )
    assert cap.matches("帮我搜索一下 AI 论文")
    assert cap.matches("SEARCH for python")
    assert cap.matches("查找最近的新闻")
    assert cap.matches("需要信息检索")
    assert not cap.matches("计算 1+1")
    print(f"  PASS - keyword + alias 命中")


def test_task_type_matches():
    print("\n[2] TaskType.matches()")
    from task_intent import TaskType

    tt = TaskType(
        name="code_generation",
        default_capability="code",
        keywords=["写代码", "实现", "code"],
        aliases=["implement"],
        needs_decomposition=False,
    )
    assert tt.matches("请写代码生成一个 HTTP 服务")
    assert tt.matches("implement a function")
    assert not tt.matches("计算 1+1")
    print(f"  PASS - task type 匹配")


# ============================================================
# 2. 注册 / 查询
# ============================================================

def test_registry_register_query():
    print("\n[3] TaskIntentRegistry 注册 + 查询")
    from task_intent import (
        TaskIntentRegistry, Capability, TaskType,
        reset_task_intent_registry,
    )
    reset_task_intent_registry()
    import task_intent
    task_intent._task_intent_registry = None

    reg = TaskIntentRegistry()
    cap = Capability(
        name="translate",
        keywords=["翻译"],
        aliases=["translate"],
        typical_task_types=["translation"],
    )
    tt = TaskType(
        name="translation",
        default_capability="translate",
        keywords=["翻译"],
    )
    reg.register_capability(cap)
    reg.register_task_type(tt)

    # 直接查
    c = reg.get_capability("translate")
    assert c is not None
    assert c.name == "translate"

    # 用 alias 查
    c = reg.get_capability("translate")  # 本身
    c2 = reg.get_capability("信息检索")
    # 注意：内置 translate 也有 alias "转换语言"

    # 列出
    caps = reg.list_capabilities()
    names = {c.name for c in caps}
    assert "search" in names and "translate" in names
    print(f"  PASS - {len(caps)} capabilities registered")


# ============================================================
# 3. detect_intent
# ============================================================

def test_detect_capabilities():
    print("\n[4] detect_capabilities")
    from task_intent import reset_task_intent_registry
    reset_task_intent_registry()
    import task_intent
    task_intent._task_intent_registry = None
    from task_intent import get_task_intent_registry

    reg = get_task_intent_registry()
    caps, kw_hits = reg.detect_capabilities("请搜索一下最新的 AI 论文")
    assert "search" in caps
    assert "search" in kw_hits
    print(f"  PASS - matched: {caps}")


def test_detect_negotiation_hint():
    print("\n[5] detect_negotiation_hint")
    from task_intent import reset_task_intent_registry
    reset_task_intent_registry()
    import task_intent
    task_intent._task_intent_registry = None
    from task_intent import get_task_intent_registry

    reg = get_task_intent_registry()
    assert reg.detect_negotiation_hint("帮我协商一下价格") == "negotiate"
    assert reg.detect_negotiation_hint("Try auction for this task") == "auction"
    assert reg.detect_negotiation_hint("请搜索一下新闻") is None
    print(f"  PASS - hint 正确识别")


def test_detect_intent_full():
    print("\n[6] detect_intent 完整意图")
    from task_intent import reset_task_intent_registry
    reset_task_intent_registry()
    import task_intent
    task_intent._task_intent_registry = None
    from task_intent import get_task_intent_registry

    reg = get_task_intent_registry()
    intent = reg.detect_intent("帮我搜索一下 AI 论文并分析结果")
    assert "search" in intent.capabilities or "analysis" in intent.capabilities
    assert intent.task_type in {"information_retrieval", "research"}

    intent2 = reg.detect_intent("请帮我协商价格")
    assert intent2.negotiation_hint == "negotiate"
    assert "negotiation" in intent2.capabilities

    intent3 = reg.detect_intent("竞拍这个任务")
    assert intent3.negotiation_hint == "auction"
    assert "auction" in intent3.capabilities

    print(f"  PASS - intent 涵盖 capabilities/negotiation/decomposition")


def test_simple_analysis_compat():
    print("\n[7] simple_analysis 兼容格式")
    from task_intent import TaskIntentRegistry
    out = TaskIntentRegistry.simple_analysis("搜索 AI 论文")
    assert "task_type" in out
    assert "required_capabilities" in out
    assert "needs_decomposition" in out
    assert "negotiation_hint" in out
    print(f"  PASS - {out}")


# ============================================================
# 4. 自定义注册
# ============================================================

def test_custom_capability():
    print("\n[8] 自定义 capability")
    from task_intent import (
        TaskIntentRegistry, Capability, TaskType,
        reset_task_intent_registry,
    )
    reset_task_intent_registry()
    import task_intent
    task_intent._task_intent_registry = None

    reg = TaskIntentRegistry(
        capabilities=[
            Capability(
                name="ocr",
                description="图片 OCR",
                keywords=["识别图片", "ocr", "extract from image"],
            ),
        ],
        task_types=[
            TaskType(
                name="image_ocr",
                default_capability="ocr",
                keywords=["识别图片"],
            ),
        ],
    )
    intent = reg.detect_intent("请帮我识别图片里的文字")
    assert "ocr" in intent.capabilities
    assert intent.task_type == "image_ocr"
    print(f"  PASS - new capability auto-detected")


# ============================================================
# 5. WorkerAgent 用 registry 默认值
# ============================================================

async def test_worker_uses_registry_defaults():
    print("\n[9] WorkerAgent 从 registry 取默认值")
    from task_intent import reset_task_intent_registry
    reset_task_intent_registry()
    import task_intent
    task_intent._task_intent_registry = None
    from message_bus import get_message_bus
    from multi_agent import WorkerAgent
    from capability import get_capability_registry

    bus = get_message_bus()
    bus.reset()

    # 不传 capability_profiles，应该用 registry 的默认值
    w = WorkerAgent(
        agent_id="w_defaults",
        name="WDefault",
        capabilities=["search"],
    )
    await w.start()

    profile = get_capability_registry().get("w_defaults")
    search_cap = profile.capabilities["search"]
    # registry 的 search 默认 avg_latency_ms=1500
    assert search_cap.avg_latency_ms == 1500.0
    # registry 的 search 默认 avg_cost=8
    assert search_cap.avg_cost == 8.0

    await w.stop()
    print(f"  PASS - latency={search_cap.avg_latency_ms}, cost={search_cap.avg_cost}")


async def test_worker_can_handle_intent():
    print("\n[10] WorkerAgent.can_handle_intent")
    from task_intent import reset_task_intent_registry
    reset_task_intent_registry()
    import task_intent
    task_intent._task_intent_registry = None
    from message_bus import get_message_bus
    from multi_agent import WorkerAgent
    from task_intent import get_task_intent_registry

    bus = get_message_bus()
    bus.reset()

    w = WorkerAgent(
        agent_id="w_intent",
        name="WIntent",
        capabilities=["search"],
    )
    await w.start()

    reg = get_task_intent_registry()
    intent_search = reg.detect_intent("帮我搜索 AI 新闻")
    intent_code = reg.detect_intent("帮我写代码")

    assert w.can_handle_intent(intent_search)
    assert not w.can_handle_intent(intent_code)
    assert w.get_intent_score(intent_search) == 1.0
    assert w.get_intent_score(intent_code) == 0.0

    await w.stop()
    print(f"  PASS - intent match works")


# ============================================================
# 6. Orchestrator._simple_analysis
# ============================================================

async def test_orchestrator_uses_registry():
    print("\n[11] Orchestrator._simple_analysis 走 registry")
    from task_intent import reset_task_intent_registry
    reset_task_intent_registry()
    import task_intent
    task_intent._task_intent_registry = None
    from multi_agent import AgentOrchestrator

    orch = AgentOrchestrator(supervisor_id="sup_ti_test")

    # 中文搜索
    out = orch._simple_analysis("搜索一下AI动态")
    assert out["task_type"] in {"information_retrieval", "search"}
    assert "search" in out["required_capabilities"]

    # 协商
    out = orch._simple_analysis("协商价格")
    assert out["negotiation_hint"] == "negotiate"

    # 竞价
    out = orch._simple_analysis("auction this")
    assert out["negotiation_hint"] == "auction"

    print(f"  PASS - orchestrator 与 registry 一致")


# ============================================================
# 7. AIAgentExtension intent API
# ============================================================

async def test_extension_intent_api():
    print("\n[12] AIAgentExtension 暴露的 intent API")
    from task_intent import reset_task_intent_registry
    reset_task_intent_registry()
    import task_intent
    task_intent._task_intent_registry = None
    from message_bus import get_message_bus
    from multi_agent_integration import AIAgentExtension, MultiAgentMixin

    bus = get_message_bus()
    bus.reset()

    class FakeAgent:
        def __init__(self):
            self.model = None
            self.current_session_id = "intent_test"

        async def run(self, prompt):
            return f"[Agent] {prompt}"

    fake = FakeAgent()

    # 直接构造 MultiAgentMixin 实例（其上有 detect_intent / route_to_workers）
    class _TestExt(MultiAgentMixin):
        def __init__(self):
            self.model = None
            self.current_session_id = "intent_test"

        def run(self, prompt):
            return f"[{self.__class__.__name__}] {prompt}"

        async def arun(self, prompt):
            return f"[async] {prompt}"

    ext = _TestExt()
    ext._multi_agent = AIAgentExtension(fake)
    await ext._multi_agent.initialize()
    ext._multi_agent_initialized = True

    # detect_intent
    intent = ext.detect_intent("搜索 AI 新闻")
    d = intent.to_dict()
    assert "task_type" in d
    assert "search" in d["capabilities"]

    # route_to_workers
    routes = ext.route_to_workers("搜索新闻", top_k=2)
    assert isinstance(routes, list)
    print(f"    route result: {[r['worker'] for r in routes]}")

    # list_capabilities
    caps = ext.list_capabilities()
    assert len(caps) >= 5
    cap_names = {c["name"] for c in caps}
    assert "search" in cap_names

    # list_task_types
    tts = ext.list_task_types()
    assert len(tts) >= 4

    print(f"  PASS - intent/route/list APIs work")


# ============================================================
# 主函数
# ============================================================

async def main():
    print("\n" + "#"*60)
    print(" Task Intent Registry Tests")
    print("#"*60)

    failures = []

    tests = [
        ("capability_matches", test_capability_matches, False),
        ("task_type_matches", test_task_type_matches, False),
        ("registry_register", test_registry_register_query, False),
        ("detect_caps", test_detect_capabilities, False),
        ("detect_neg_hint", test_detect_negotiation_hint, False),
        ("detect_intent", test_detect_intent_full, False),
        ("simple_analysis", test_simple_analysis_compat, False),
        ("custom_cap", test_custom_capability, False),
        ("worker_defaults", test_worker_uses_registry_defaults, True),
        ("worker_intent", test_worker_can_handle_intent, True),
        ("orchestrator", test_orchestrator_uses_registry, True),
        ("extension_api", test_extension_intent_api, True),
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
