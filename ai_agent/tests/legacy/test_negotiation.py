"""
协商与竞争机制测试

验证：
1. 协商（Negotiation）：双方通过提议和反提议达成一致
2. 竞争/竞价（Auction）：多个 Worker 出价，最终选出 winner
3. 与现有 message_bus / message_protocol 集成
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_auction_basic():
    """测试基础竞价：3 个 Worker 竞争同一任务"""
    print("\n" + "="*60)
    print("Test 1: Basic Auction (SCORED strategy)")
    print("="*60)
    
    from negotiation import (
        get_auction_manager, AuctionManager, AuctionStrategy,
        NegotiationParticipantMixin, Bid, BidStatus
    )
    from message_bus import get_message_bus, BaseAgent
    from message_protocol import MessageType, Message
    
    bus = get_message_bus()
    bus.reset()
    
    # 创建 3 个 Worker
    class BidderAgent(NegotiationParticipantMixin, BaseAgent):
        def __init__(self, name, price, quality, eta):
            super().__init__(
                agent_id=name.lower(),
                name=name,
                capabilities=["search", "general"]
            )
            self._my_price = price
            self._my_quality = quality
            self._my_eta = eta
        
        def _build_bid(self, auction_id, request_data):
            return Bid(
                auction_id=auction_id,
                bidder_id=self.agent_id,
                price=self._my_price,
                quality=self._my_quality,
                eta_seconds=self._my_eta
            )
    
    alice = BidderAgent("Alice", price=15.0, quality=0.9, eta=5.0)
    bob = BidderAgent("Bob", price=10.0, quality=0.7, eta=3.0)
    carol = BidderAgent("Carol", price=20.0, quality=0.95, eta=8.0)
    
    print(f"  Alice: price=15.0, quality=0.9, eta=5s")
    print(f"  Bob:   price=10.0, quality=0.7, eta=3s")
    print(f"  Carol: price=20.0, quality=0.95, eta=8s")
    
    # 创建拍卖并启动
    auction_mgr = AuctionManager(bus)
    auction = auction_mgr.create_auction(
        auctioneer_id="supervisor",
        task_id="task_001",
        task_type="search",
        strategy=AuctionStrategy.SCORED,
        deadline_seconds=2.0
    )
    
    # 模拟 Worker 提交 Bid（同步方式）
    await asyncio.sleep(0.2)  # 等待 Agent 注册到 bus
    
    auction_mgr.add_bid(auction.auction_id, Bid(
        auction_id=auction.auction_id,
        bidder_id="alice", price=15.0, quality=0.9, eta_seconds=5.0
    ))
    auction_mgr.add_bid(auction.auction_id, Bid(
        auction_id=auction.auction_id,
        bidder_id="bob", price=10.0, quality=0.7, eta_seconds=3.0
    ))
    auction_mgr.add_bid(auction.auction_id, Bid(
        auction_id=auction.auction_id,
        bidder_id="carol", price=20.0, quality=0.95, eta_seconds=8.0
    ))
    
    result = auction_mgr.close_auction(auction.auction_id)
    print(f"\n  Winner: {result['winner_id']}")
    print(f"  Winning bid: {result['winning_bid']}")
    
    assert result["winner_id"] is not None, "Should have a winner"
    print(f"\n✓ Auction test passed. Winner = {result['winner_id']}")


async def test_negotiation_basic():
    """测试基础协商：双方让步达成一致"""
    print("\n" + "="*60)
    print("Test 2: Basic Negotiation")
    print("="*60)
    
    from negotiation import (
        NegotiationParticipantMixin, NegotiationStrategy
    )
    from message_bus import get_message_bus, BaseAgent
    from message_protocol import MessageType, Message
    
    bus = get_message_bus()
    bus.reset()
    
    results = {}
    
    class Buyer(NegotiationParticipantMixin, BaseAgent):
        def __init__(self):
            super().__init__(
                agent_id="buyer",
                name="Buyer",
                capabilities=["negotiate"],
                initial_terms={"price": 100.0},
                reservation_point={"price": 80.0},
                negotiation_strategy=NegotiationStrategy.LINEAR_CONCEDE
            )
            self.received = []
            
            @self.on(MessageType.ACCEPT_OFFER)
            async def on_accept(msg: Message):
                self.received.append(("accept", msg.content))
                results["buyer_status"] = "agreed"
                results["final_terms"] = msg.content.get("terms")
        
        def _make_counter_proposal(self, terms, round_no):
            return super()._make_counter_proposal(terms, round_no)
    
    class Seller(NegotiationParticipantMixin, BaseAgent):
        def __init__(self):
            super().__init__(
                agent_id="seller",
                name="Seller",
                capabilities=["negotiate"],
                initial_terms={"price": 50.0},      # seller 想卖 50
                reservation_point={"price": 90.0},   # 但接受 >= 90
                negotiation_strategy=NegotiationStrategy.LINEAR_CONCEDE
            )
            self.received = []
            
            @self.on(MessageType.ACCEPT_OFFER)
            async def on_accept(msg: Message):
                self.received.append(("accept", msg.content))
                results["seller_status"] = "agreed"
                results["final_terms"] = msg.content.get("terms")
    
    buyer = Buyer()
    seller = Seller()
    
    # Buyer 发起协商，初始价格 100
    print("  Buyer proposes price=100")
    await buyer.propose_to(
        receiver_id="seller",
        terms={"price": 100.0},
        negotiation_id="neg_001",
        round_no=1
    )
    
    # 等待消息流转
    await asyncio.sleep(1.5)
    
    # 检查结果
    print(f"  Buyer received: {len(buyer.received)} messages")
    print(f"  Seller received: {len(seller.received)} messages")
    print(f"  Status: {results}")


async def test_manager_singletons():
    """测试全局管理器单例"""
    print("\n" + "="*60)
    print("Test 3: Manager Singletons")
    print("="*60)
    
    from negotiation import (
        get_negotiation_manager, get_auction_manager,
        NegotiationManager, AuctionManager
    )
    
    nm1 = get_negotiation_manager()
    nm2 = get_negotiation_manager()
    am1 = get_auction_manager()
    am2 = get_auction_manager()
    
    assert nm1 is nm2, "NegotiationManager should be singleton"
    assert am1 is am2, "AuctionManager should be singleton"
    print(f"  NegotiationManager: {id(nm1)} == {id(nm2)} ✓")
    print(f"  AuctionManager: {id(am1)} == {id(am2)} ✓")


async def main():
    print("\n" + "#"*60)
    print(" Negotiation & Auction Mechanism Tests")
    print("#"*60)
    
    try:
        await test_manager_singletons()
        print("\n✓ Manager singletons test passed")
    except Exception as e:
        print(f"\n✗ Manager singletons test failed: {e}")
        import traceback; traceback.print_exc()
    
    try:
        await test_auction_basic()
    except Exception as e:
        print(f"\n✗ Auction test failed: {e}")
        import traceback; traceback.print_exc()
    
    try:
        await test_negotiation_basic()
    except Exception as e:
        print(f"\n✗ Negotiation test failed: {e}")
        import traceback; traceback.print_exc()
    
    print("\n" + "#"*60)
    print(" All tests done")
    print("#"*60)


if __name__ == "__main__":
    asyncio.run(main())
