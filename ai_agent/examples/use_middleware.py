"""LangChain 1.x AgentMiddleware 完整用法演示。

运行方法::

    python examples/use_middleware.py

依赖:
    pip install langchain>=1.0 langchain-openai>=0.3 prometheus-client redis

本文件演示 5 个核心场景:
1. **零侵入接入**：用默认配置注入全部 hook
2. **PII 扩展**：增加企业内部脱敏模式
3. **分布式限流**：Redis 后端 + 多实例共享 / 独立模式
4. **多 sink 导出**：Prometheus + LangSmith + 自定义 JSONL
5. **自定义 hook**：注册项目独有的"敏感动作审计" hook

每个场景都设计为可独立运行(都有清晰的开关和示例提示)。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# 让 `import agent_middleware` 能找到项目根目录下的源码
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ──────────────────────────────────────────────────────────────────────────
# 统一日志格式
# ──────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(name)-25s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("examples.use_middleware")


# ──────────────────────────────────────────────────────────────────────────
# 0. mock 工具与模型（演示用，无需真实 API key）
# ──────────────────────────────────────────────────────────────────────────
def fake_tools() -> list:
    """构造一组假工具用于演示。"""
    from langchain_core.tools import tool

    @tool
    def get_weather(city: str) -> str:
        """查询城市天气。"""
        return f"{city}: 晴 25°C"

    @tool
    def calc(a: float, b: float) -> float:
        """加法。"""
        return a + b

    return [get_weather, calc]


def fake_model():
    """构造一个不需要真实 API key 的"模型"对象（演示接入流程）。

    真实场景里这里应该是::
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o-mini")

    1.x 的 ``create_agent`` 要求 model 实现 ``bind_tools``；本桩函数给 fake
    model 加上 ``bind_tools``（接受 ``tool_choice`` 等任何参数，直接返回自己），
    让 create_agent 走通；``invoke`` 返回标准的 :class:`AIMessage`，保证
    后续 message 转换不报错。
    """
    from langchain_core.messages import AIMessage

    class _FakeChat:
        def invoke(self, msgs, **kw):
            return AIMessage(content="[fake 模型] 已收到问题")

        def bind_tools(self, tools, **kw):
            return self

        # create_agent 内部还会调 model.bind(stop=...) 等通用绑定
        def bind(self, **kw):
            return self

    return _FakeChat()


def fake_state_with_usage(model_name: str = "demo-model", session_id: str = "demo-session"):
    """构造一条带 usage_metadata 的 AI 消息，用于本地走完 after_model 钩子。"""
    ai = SimpleNamespace(
        type="ai",
        content="hi there",
        tool_calls=[],
        response_metadata={"model_name": model_name},
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "model_name": model_name,
        },
    )
    return {"messages": [ai], "session_id": session_id}


# ──────────────────────────────────────────────────────────────────────────
# 场景 1：零侵入接入（用全部默认 hook）
# ──────────────────────────────────────────────────────────────────────────
def scenario_1_quick_start():
    """最简接入：用 build_default_middleware() 的默认值。"""
    log.info("─── 场景 1：零侵入接入 ───")

    from agent_middleware import build_default_middleware, __version__
    log.info("agent_middleware version: %s", __version__)

    middleware = build_default_middleware()
    log.info("已注入 %d 个 hook：%s",
             len(middleware),
             [type(m).__name__ for m in middleware])

    # 真实场景里这样用：
    #   from langchain.agents import create_agent
    #   agent = create_agent(model=..., tools=..., middleware=middleware)
    log.info("→ 实际接入只需把 middleware=[...] 传给 create_agent()")


# ──────────────────────────────────────────────────────────────────────────
# 场景 2：PII 扩展（增加企业内部模式）
# ──────────────────────────────────────────────────────────────────────────
def scenario_2_pii_extension():
    """演示注入企业内部 PII 模式。"""
    log.info("─── 场景 2：PII 脱敏扩展 ───")

    from agent_middleware import PIIScrubMiddleware, PIIScrubConfig

    cfg = PIIScrubConfig(
        replacement="***",
        # 增加企业内部模式：
        # - 中国身份证号
        # - 订单号（业务前缀 ORD- + 10 位数字）
        # - 内部域名 @corp.local
        extra_patterns=(
            r"\b\d{17}[\dXx]\b",              # 身份证
            r"\bORD-\d{10}\b",                 # 订单号
            r"[\w.+-]+@corp\.local\b",         # 内部邮箱
        ),
    )
    mw = PIIScrubMiddleware(config=cfg)

    human_msg = SimpleNamespace(type="human", content=(
        "我的身份证 11010119900101123X，订单 ORD-2026072801 "
        "有问题，发邮件给 zhang.san@corp.local 谢谢"
    ))
    mw.before_model({"messages": [human_msg]}, runtime=None)
    log.info("原文: %s", "我的身份证 11010119900101123X，订单 ORD-2026072801 有问题，发邮件给 zhang.san@corp.local 谢谢")
    log.info("脱敏: %s", human_msg.content)


# ──────────────────────────────────────────────────────────────────────────
# 场景 3：分布式限流（Redis 后端 + 多实例模式）
# ──────────────────────────────────────────────────────────────────────────
def scenario_3_redis_rate_limit():
    """演示 RateLimitMiddleware 用 Redis 后端。"""
    log.info("─── 场景 3：Redis 限流后端 ───")

    from agent_middleware import (
        RateLimitMiddleware, RateLimitConfig,
        _make_rate_limit_key, _HAS_REDIS,
    )
    log.info("Redis 包是否可用: %s", _HAS_REDIS)

    # key 命名演示：自动混入阈值 + 实例标识
    log.info("key (独立模式): %s", _make_rate_limit_key(
        "rl:myapp", max_calls=100, window_seconds=60,
        instance_id="my-instance-1",
    ))
    log.info("key (共享模式): %s", _make_rate_limit_key(
        "rl:myapp", max_calls=100, window_seconds=60,
        use_shared_instance=True,
    ))
    log.info("key (改阈值后): %s", _make_rate_limit_key(
        "rl:myapp", max_calls=200, window_seconds=60,
        instance_id="my-instance-1",
    ))

    # 用 memory 后端（演示，不需要 Redis）
    mw = RateLimitMiddleware(config=RateLimitConfig(
        max_calls=3, window_seconds=10.0,
        backend="memory",
    ))
    for i in range(5):
        blocked = mw.before_model({"messages": []}, runtime=None)["_hook_rate_limited"]
        log.info("call #%d → rate_limited=%s", i + 1, blocked)


# ──────────────────────────────────────────────────────────────────────────
# 场景 4：多 sink 导出（Prometheus + LangSmith + 自定义 JSONL）
# ──────────────────────────────────────────────────────────────────────────
def scenario_4_multi_sink_export():
    """演示 TokenUsageMiddleware 多 sink 配置。"""
    log.info("─── 场景 4：多 sink 导出 ───")

    import agent_middleware as am
    from agent_middleware import TokenUsageMiddleware, TokenUsageConfig

    log.info("prometheus_client 可用: %s", am._HAS_PROMETHEUS)
    log.info("langsmith 可用: %s", am._HAS_LANGSMITH)

    # ── 自定义 JSONL sink ──
    log_file = Path("logs/token_usage_demo.jsonl")
    log_file.parent.mkdir(parents=True, exist_ok=True)

    def jsonl_sink(usage, *, model=None, session_id=None, parent_run_id=None):
        record = {
            "ts": time.time(),
            "model": model,
            "session_id": session_id,
            "parent_run_id": parent_run_id,
            **usage,
        }
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        log.info("jsonl_sink → %s", record)

    # ── 配置 + 触发 ──
    mw = TokenUsageMiddleware(config=TokenUsageConfig(
        sinks=(jsonl_sink,),   # 仅自定义 sink；prom/langsmith 在依赖可用时自动启用
        prometheus_namespace="demo",
        langsmith_project="demo-project",
    ))

    # 模拟一次模型返回
    state = fake_state_with_usage(model_name="gpt-4o-mini", session_id="alice-1")
    runtime = SimpleNamespace(metadata={"parent_run_id": "run-abc"})
    out = mw.after_model(state, runtime) or {}
    log.info("hook 返回值: %s", out)
    log.info("JSONL 已写入: %s", log_file)


# ──────────────────────────────────────────────────────────────────────────
# 场景 5：自定义 hook（项目独有的"敏感动作审计"）
# ──────────────────────────────────────────────────────────────────────────
def scenario_5_custom_hook():
    """演示零侵入新增 hook：项目独有的敏感动作审计。"""
    log.info("─── 场景 5：自定义 hook（敏感动作审计）───")

    from langchain.agents.middleware import AgentMiddleware
    from agent_middleware import (
        build_default_middleware,
        PIIScrubConfig, RateLimitConfig, OutputSafetyConfig, TokenUsageConfig,
    )

    class SensitiveActionAudit(AgentMiddleware):
        """after_model：检查 AI 输出是否提到"删除/转账/下线"等敏感动作。

        项目里所有这类动作必须进人工审批（Human-in-the-Loop）。
        这里只是记录 + 触发一个回调；真正的审批由 human_in_loop.py 处理。
        """

        SENSITIVE_PATTERNS = (
            r"删除", r"撤回", r"退款",
            r"转账", r"下线", r"离职",
        )

        def __init__(self, on_detect=None):
            import re
            self._patterns = [re.compile(p) for p in self.SENSITIVE_PATTERNS]
            self._on_detect = on_detect or (lambda text, hits: None)

        def after_model(self, state, runtime):
            msgs = state.get("messages") or []
            if not msgs:
                return None
            content = getattr(msgs[-1], "content", "") or ""
            if not isinstance(content, str):
                return None
            hits = [p.pattern for p in self._patterns if p.search(content)]
            if hits:
                self._on_detect(content, hits)
            return None

    detected: list[tuple[str, list[str]]] = []
    mw_audit = SensitiveActionAudit(on_detect=lambda t, h: detected.append((t, h)))

    # 测试输出
    bad_ai = SimpleNamespace(type="ai", content="好的，我帮你删除这个用户并退款 100 元。")
    mw_audit.after_model({"messages": [bad_ai]}, runtime=None)
    log.info("命中敏感词: %s", detected)

    good_ai = SimpleNamespace(type="ai", content="今天天气真好。")
    mw_audit.after_model({"messages": [good_ai]}, runtime=None)
    log.info("未命中: %s", detected)

    # 把这个 hook 塞到 build_default_middleware() 里：
    custom_list = build_default_middleware(
        pii_config=PIIScrubConfig(replacement="***"),
        rate_limit_config=RateLimitConfig(max_calls=100, window_seconds=60.0),
        safety_config=OutputSafetyConfig(mode="redact"),
        token_usage_config=TokenUsageConfig(),
    ) + [mw_audit]   # ← 项目自有 hook，无侵入加进来
    log.info("总计 %d 个 hook（包含自定义 SensitiveActionAudit）", len(custom_list))


# ──────────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────
# 场景 6：真实 e2e（create_agent + ChatOpenAI + middleware 接入）
# ──────────────────────────────────────────────────────────────────────────
def scenario_6_real_e2e():
    """演示完整链路：真实 LangChain 1.x create_agent + middleware 接入。

    行为约定：
    - 有 OPENAI_API_KEY 环境变量 → 用 ChatOpenAI 真模型
    - 否则 → 用 fake_model() 本地桩（保证脚本始终能跑通）
    """
    log.info("─── 场景 6：真实 e2e (create_agent + OpenAI) ───")

    from agent_middleware import (
        build_default_middleware,
        LoggingMiddleware,
        PIIScrubConfig,
        TokenUsageConfig,
    )

    # ── 1. 模型：有 key 走真模型，否则走 fake ──
    has_key = bool(os.getenv("OPENAI_API_KEY"))
    if has_key:
        try:
            from langchain_openai import ChatOpenAI
            model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            log.info("使用真实 ChatOpenAI 模型 (gpt-4o-mini)")
        except Exception as e:
            log.warning("ChatOpenAI 初始化失败: %s → 回退到 fake 模型", e)
            model = fake_model()
    else:
        log.info("未设置 OPENAI_API_KEY，使用 fake 模型（演示流程）")
        model = fake_model()

    # ── 2. 工具 ──
    tools = fake_tools()

    # ── 3. middleware（定制 PII + TokenUsage 双 sink） ──
    middleware = build_default_middleware(
        pii_config=PIIScrubConfig(replacement="[EMAIL]"),
        token_usage_config=TokenUsageConfig(sinks=("state",)),   # 简化：仅写 state
    )
    # 在最后追加一个自定义 hook，演示零侵入扩展
    log_mw = LoggingMiddleware()

    # ── 4. create_agent（LangChain 1.x API）──
    try:
        from langchain.agents import create_agent
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError as e:
        log.warning("create_agent / checkpointer 不可用: %s", e)
        return

    checkpointer = InMemorySaver()  # 演示用，生产建议 SqliteSaver/PostgresSaver
    try:
        agent = create_agent(
            model=model,
            tools=tools,
            system_prompt="你是一个简洁的助手。请用中文回答。",
            checkpointer=checkpointer,
            middleware=middleware,
        )
        log.info("create_agent 调用成功 → 已注入 %d 个 hook", len(middleware))
    except Exception as e:
        log.warning("create_agent 失败: %s", e)
        return

    # ── 5. invoke（带 thread_id；state["session_id"] 由 checkpointer 管理）──
    thread_id = "demo-thread-1"
    config = {"configurable": {"thread_id": thread_id}}

    # 构造 langchain 1.x 标准消息对象
    from langchain_core.messages import HumanMessage

    # 测试问题 1：普通问题
    log.info("Q1: 北京今天天气怎么样？")
    try:
        result = agent.invoke(
            {"messages": [HumanMessage(content="北京今天天气怎么样？")]},
            config=config,
        )
        msgs = result.get("messages", [])
        if msgs:
            last = msgs[-1]
            content = getattr(last, "content", None) or ""
            log.info("A1: %s", str(content)[:200])
            log.info("   (state['_hook_token_usage'] 视 fake 模型而定，真模型会写入)")
    except Exception as e:
        log.warning("Q1 invoke 失败: %s", e)

    # 测试问题 2：含 PII 的问题 → 触发 PIIScrubMiddleware
    log.info("Q2: 请帮我给 alice@example.com 发邮件 → 期望 PII 脱敏")
    try:
        result = agent.invoke(
            {"messages": [HumanMessage(content="请帮我给 alice@example.com 发邮件")]},
            config=config,
        )
        msgs = result.get("messages", [])
        if msgs:
            # 看 hook 是否生效：检查最近 human 消息的 content
            pii_caught = False
            for m in reversed(msgs):
                if getattr(m, "type", None) == "human":
                    content = getattr(m, "content", None) or ""
                    if "alice@example.com" not in content:
                        log.info("✓ PII hook 已生效：'%s'", content[:80])
                        pii_caught = True
                    else:
                        log.warning("✗ PII hook 未生效（fake 模型可能没跑 before_model）")
                    break
            if not pii_caught and msgs:
                log.info("(fake 模型可能跳过 tool_calls 流程)")
    except Exception as e:
        log.warning("Q2 invoke 失败: %s", e)


def main():
    log.info("=" * 60)
    log.info(" LangChain 1.x AgentMiddleware 用法演示")
    log.info("=" * 60)

    scenario_1_quick_start()
    print()
    scenario_2_pii_extension()
    print()
    scenario_3_redis_rate_limit()
    print()
    scenario_4_multi_sink_export()
    print()
    scenario_5_custom_hook()
    print()
    scenario_6_real_e2e()

    log.info("=" * 60)
    log.info(" 所有场景演示完成。详见 agent_middleware.md")
    log.info("=" * 60)


if __name__ == "__main__":
    main()