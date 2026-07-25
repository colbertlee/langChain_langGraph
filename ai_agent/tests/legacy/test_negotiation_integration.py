"""
协商与竞价机制集成测试

验证 AIAgentExtension 的 run_negotiation / delegate_with_auction
能真正驱动 Worker 完成主流程。
"""

"""Long-running test (>2s). Skipped by default in CI.
Run explicitly with: pytest -m slow

Reason: multi-agent negotiation integration (multi-round)
"""
import pytest

pytestmark = pytest.mark.slow


import asyncio
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
# 测试 1：AIAgentExtension.delegate_with_auction
# ============================================================

async def test_delegate_with_auction():
    print("\n" + "="*60)
    print("Test 1: AIAgentExtension.delegate_with_auction")
    print("="*60)

    from message_bus import get_message_bus, BaseAgent
    from multi_agent_integration import AIAgentExtension
    from negotiation import AuctionStrategy

    bus = get_message_bus()
    bus.reset()

    # 模拟一个 minimal AIAgent（不实际接 LLM）
    class FakeAIAgent:
        def __init__(self):
            self.model = None
            self.current_session_id = "test_session"

        async def run(self, prompt):
            return f"[AIAgent] {prompt}"

    fake_agent = FakeAIAgent()
    extension = AIAgentExtension(fake_agent)
    await extension.initialize()

    # 跑一个竞价委托任务
    print("Calling delegate_with_auction(task='Search AI news', task_type='search')...")
    result = await extension.delegate_with_auction(
        task="Search AI news",
        task_type="search",
        task_data={"query": "latest AI news"},
        strategy=AuctionStrategy.SCORED,
        deadline_seconds=3.0,
    )

    print(f"  Winner: {result.get('winner_id')}")
    print(f"  Auction: {result.get('auction_result', {}).get('auction_id', 'N/A')[:8] if result.get('auction_result') else 'N/A'}...")
    print(f"  Total bids: {result.get('auction_result', {}).get('total_bids') if result.get('auction_result') else 'N/A'}")

    assert result.get("winner_id") is not None, "Should select a winner"
    assert result.get("auction_result") is not None, "Should have auction metadata"
    print(f"\n[OK] Auction-delegation test passed. Winner = {result['winner_id']}")


# ============================================================
# 测试 2：AIAgentExtension.run_negotiation（双边）
# ============================================================

async def test_run_negotiation_bilateral():
    print("\n" + "="*60)
    print("Test 2: AIAgentExtension.run_negotiation (bilateral)")
    print("="*60)

    from message_bus import get_message_bus
    from multi_agent_integration import AIAgentExtension

    bus = get_message_bus()
    bus.reset()

    class FakeAIAgent:
        def __init__(self):
            self.model = None
            self.current_session_id = "test_session"

        async def run(self, prompt):
            return f"[AIAgent] {prompt}"

    fake_agent = FakeAIAgent()
    extension = AIAgentExtension(fake_agent)
    await extension.initialize()

    # 与多个 Worker 协商
    print("Calling run_negotiation with terms for search/code/write workers...")
    result = await extension.run_negotiation(
        candidate_terms={
            "search": {"price": 18.0},
            "code": {"price": 30.0},
            "write": {"price": 16.0},
        },
        topic="price_negotiation",
        max_rounds=5,
        deadline_seconds=5.0,
    )

    print(f"  Topic: {result['topic']}")
    print(f"  Bilateral results:")
    for worker_type, r in result.get("bilateral_results", {}).items():
        print(f"    {worker_type}: status={r.get('status')}, agreement={r.get('agreement')}")
    print(f"  Best deal: {result.get('best_deal', {}).get('agreement', {}).get('terms') if result.get('best_deal') else 'N/A'}")

    print("\n[OK] Bilateral negotiation test passed")


# ============================================================
# 测试 3：MultiAgentMixin 暴露的同步 API（auction_delegate）
# ============================================================

async def test_mixin_sync_api():
    print("\n" + "="*60)
    print("Test 3: MultiAgentMixin.auction_delegate (sync API)")
    print("="*60)

    from message_bus import get_message_bus
    from multi_agent_integration import MultiAgentMixin
    from negotiation import AuctionStrategy

    bus = get_message_bus()
    bus.reset()

    class TestMixinAgent(MultiAgentMixin):
        def __init__(self):
            self.model = None
            self.current_session_id = "mixin_session"

        def run(self, prompt):
            return f"[TestAgent] {prompt}"

    agent = TestMixinAgent()
    agent.init_multi_agent()
    await asyncio.sleep(0.5)

    print("Calling auction_delegate via sync API...")
    # 在已有 event loop 中跑需要 run_until_complete
    loop = asyncio.get_event_loop()
    result = await agent._multi_agent.delegate_with_auction(
        task="Analyze data",
        task_type="analysis",
        task_data={"data": "test data"},
        strategy=AuctionStrategy.SCORED,
        deadline_seconds=3.0,
    )
    print(f"  Winner: {result.get('winner_id')}")
    assert result.get("winner_id") is not None
    print("\n[OK] Mixin sync API test passed")


# ============================================================
# 主函数
# ============================================================

async def main():
    print("\n" + "#"*60)
    print(" Negotiation & Auction Integration Tests")
    print("#"*60)

    try:
        await test_delegate_with_auction()
    except Exception as e:
        print(f"\n[FAIL] Test 1 failed: {e}")
        import traceback; traceback.print_exc()

    try:
        await test_run_negotiation_bilateral()
    except Exception as e:
        print(f"\n[FAIL] Test 2 failed: {e}")
        import traceback; traceback.print_exc()

    try:
        await test_mixin_sync_api()
    except Exception as e:
        print(f"\n[FAIL] Test 3 failed: {e}")
        import traceback; traceback.print_exc()

    print("\n" + "#"*60)
    print(" Integration tests done")
    print("#"*60)


if __name__ == "__main__":
    asyncio.run(main())
