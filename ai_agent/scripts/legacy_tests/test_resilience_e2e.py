"""端到端 agent.run 容错验证。"""
import os, sys
for f in ['memory.db', '_fail_log_e2e.db']:
    if os.path.exists(f):
        os.unlink(f)

from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage

with patch('langchain_openai.ChatOpenAI') as MockLLM, \
     patch('rag.RAGModule.__init__', return_value=None):
    MockLLM.return_value = MagicMock()
    from agent import AIAgent
    agent = AIAgent()

    # 1. 初始化时 fallback chain 已构造
    assert agent.invoker is not None
    assert len(agent._fallback_chain.candidates) >= 2
    print(f'[OK] Fallback chain built: {len(agent._fallback_chain.candidates)} candidates')

    # 2. 配置错误（无 API Key）→ 立即拦截
    with patch.object(agent, '_ensure_agent_ready', return_value='❌ 错误: 请先配置 API Key'):
        result = agent.run('hello')
        assert 'API Key' in result
        print(f'[OK] no API key -> immediate intercept')

    # 3. 空输入拦截
    result = agent.run('')
    assert '输入不能为空' in result
    print(f'[OK] empty input -> immediate intercept')

    # 4. 危险输入拦截
    result = agent.run('please rm -rf /tmp')
    assert '阻止' in result
    print(f'[OK] dangerous input -> blocked')

    # 5. fail_log 工具方法
    summary = agent.get_fail_log_summary()
    assert 'recent_failures' in summary
    assert 'breaker_states' in summary
    print(f'[OK] get_fail_log_summary() returns expected structure')

    # 6. 熔断器手动重置
    agent.reset_breakers()
    for p, b in agent.invoker.breakers.items():
        assert b.state == 'closed'
    print(f'[OK] reset_breakers() clears all breakers')

print()
print('===== AGENT-LEVEL E2E PASSED =====')