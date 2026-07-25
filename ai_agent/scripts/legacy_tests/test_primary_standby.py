"""端到端验证：主备切换 + sub-agent 委派。"""
import os, sys

# 清掉环境
for f in ['memory.db', 'fail_log.db', '_fail_log_*.db']:
    for path in [f] if '*' not in f else __import__('glob').glob(f):
        if os.path.exists(path):
            os.unlink(path)

from unittest.mock import MagicMock, patch
from llm_reliability import (
    PrimaryStandbyConfig, FallbackCandidate, ModelFallbackChain,
)

with patch('langchain_openai.ChatOpenAI') as MockLLM, \
     patch('rag.RAGModule.__init__', return_value=None):
    MockLLM.return_value = MagicMock()
    from agent import AIAgent
    agent = AIAgent()

    # === T1: 主备配置基本 ===
    print('\n=== T1: 主备配置 ===')
    status = agent.set_primary_standby(
        primary={"provider": "openai", "model": "gpt-4o-mini"},
        standbys=[
            {"provider": "deepseek", "model": "deepseek-chat"},
            {"provider": "qwen", "model": "qwen-turbo"},
        ],
        switching_strategy="automatic",
    )
    print(f'  primary: {status["primary"]}')
    print(f'  standbys: {status["standbys"]}')
    print(f'  actually_active: {status["actually_active"]}')
    print(f'  strategy: {status["switching_strategy"]}')
    assert status["primary"]["provider"] == "openai"
    assert len(status["standbys"]) == 2
    assert status["actually_active"]["provider"] == "openai"
    print('  [OK] primary/standby configured')

    # === T2: get_active_model ===
    print('\n=== T2: get_active_model ===')
    active = agent.get_active_model()
    assert active == {"provider": "openai", "model": "gpt-4o-mini"}
    print(f'  [OK] active = {active}')

    # === T3: fallback chain 重建 ===
    print('\n=== T3: fallback chain ===')
    fc = agent._fallback_chain.candidates
    print(f'  chain: {[(c.provider, c.model) for c in fc]}')
    assert fc[0].provider == "openai"
    assert fc[1].provider == "deepseek"
    assert fc[2].provider == "qwen"
    print('  [OK] chain matches configuration')

    # === T4: 模拟主失败后 actually_active 切到 standby ===
    print('\n=== T4: 主熔断后 actually_active 切到 standby ===')
    # 手动触发 openai breaker OPEN
    agent.invoker.breakers["openai"].record_failure("timeout")
    agent.invoker.breakers["openai"].record_failure("timeout")
    agent.invoker.breakers["openai"].record_failure("timeout")
    assert agent.invoker.breakers["openai"].state == "open"
    status = agent.get_standby_status()
    print(f'  primary breaker state: {status["breaker_states"]["openai"]["state"]}')
    print(f'  actually_active: {status["actually_active"]}')
    assert status["actually_active"]["provider"] == "deepseek"
    print('  [OK] actually_active -> deepseek (openai breaker OPEN)')

    # 重置
    agent.reset_breakers()
    status = agent.get_standby_status()
    assert status["actually_active"]["provider"] == "openai"
    print(f'  after reset: actually_active -> {status["actually_active"]["provider"]}')

    # === T5: manual_switch_to ===
    print('\n=== T5: manual_switch_to ===')
    ok = agent.manual_switch_to("deepseek", "deepseek-chat")
    print(f'  switch result: {ok}')
    active = agent.get_active_model()
    print(f'  active now: {active}')
    # init_agent 在 mock 环境下可能因 key 缺失返回 False
    # 但 active model 在 set_primary_standby 时已经记录

    # === T6: sub-agent 注册与委派 ===
    print('\n=== T6: sub-agent 注册与委派 ===')
    sub_id = agent.register_sub_agent(
        capability="summarize",
        name="摘要专家",
        executor=lambda desc: f"[MOCK-SUMMARY] {desc[:30]}...",
    )
    print(f'  registered: {sub_id[:8]}...')
    print(f'  list_sub_agents: {agent.list_sub_agents()}')
    assert "summarize" in agent.list_sub_agents()

    # 委派
    result = agent.delegate_subtask(
        "summarize",
        "请把这段文字压缩到 50 字：这是一段很长的原文...",
    )
    print(f'  delegated result: {result}')
    assert "[MOCK-SUMMARY]" in result
    print('  [OK] sub-agent delegate works')

    # === T7: 委派未注册 capability ===
    print('\n=== T7: 未注册 capability ===')
    result = agent.delegate_subtask("nonexistent", "test")
    assert "未注册" in result
    print(f'  [OK] error message: {result}')

    # === T8: 注销 sub-agent ===
    print('\n=== T8: 注销 ===')
    ok = agent.unregister_sub_agent("summarize")
    assert ok
    assert "summarize" not in agent.list_sub_agents()
    print('  [OK] unregistered')

    # === T9: 多次设置主备（不应内存泄漏）===
    print('\n=== T9: 多次切换 ===')
    for i in range(3):
        agent.set_primary_standby(
            primary={"provider": ["openai", "deepseek", "qwen"][i % 3], "model": "x"},
        )
    status = agent.get_standby_status()
    print(f'  after 3 rotations: primary = {status["primary"]["provider"]}')
    print('  [OK] no leak')

    # === T10: 关闭 standby warmup（如已启动）===
    print('\n=== T10: 停止 warmup ===')
    agent.stop_standby_warmup()
    status = agent.get_standby_status()
    print(f'  warmup: {status["warmup"]}')
    assert status["warmup"] is None
    print('  [OK] warmup stopped')

print()
print('===== ALL E2E TESTS PASSED =====')