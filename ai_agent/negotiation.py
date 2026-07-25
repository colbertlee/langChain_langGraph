"""
协商与竞争机制模块

实现多 Agent 系统中的协商（Negotiation）和竞争/竞价（Bidding/Auction）机制。

核心设计：
1. 协商（Negotiation）：多个 Agent 之间通过交换提议（Propose/Accept/Reject/Counter）
   达成共识或妥协的协议层。
2. 竞争/竞价（Bidding/Auction）：多个 Worker 通过出价竞争任务执行权，
   由 Auctioneer 根据评估策略（最低成本、最高评分、综合评分等）选择赢家。

模块依赖：message_protocol、message_bus
"""

import asyncio
import uuid
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from message_protocol import (
    Message, MessageType, MessagePriority, AgentInfo
)
from message_bus import MessageBus, BaseAgent, get_message_bus

logger = logging.getLogger(__name__)


# ============================================================
# 协商策略
# ============================================================

class NegotiationStrategy(Enum):
    """协商策略"""
    FIXED = "fixed"                    # 固定立场：不接受任何反提议
    LINEAR_CONCEDE = "linear_concede"  # 线性让步：每轮固定降低/提高诉求
    BAZERMAN = "bazeramn"              # Bazeramn 启发式：基于保留点的对数让步
    TIME_DEPENDENT = "time_dependent"  # 时间依赖：越接近 deadline 让步越大
    TIT_FOR_TAT = "tit_for_tat"        # 一报还一报：以对手上次让步幅度回应


class AuctionStrategy(Enum):
    """拍卖/竞价选择策略"""
    FIRST_PRICE = "first_price"        # 第一价格密封：出价最高者按其报价支付
    SECOND_PRICE = "second_price"      # 第二价格（Vickrey）：按次高价结算
    ENGLISH = "english"                # 英式拍卖：公开递增叫价
    DUTCH = "dutch"                    # 荷兰式拍卖：公开递减叫价
    SCORED = "scored"                  # 综合评分（多维：价格、质量、时间）


class ProposalStatus(Enum):
    """协商提议状态"""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COUNTERED = "countered"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class BidStatus(Enum):
    """竞价状态"""
    ACTIVE = "active"
    WINNING = "winning"
    LOSING = "losing"
    AWARDED = "awarded"
    REJECTED = "rejected"


# ============================================================
# 数据模型
# ============================================================

@dataclass
class Proposal:
    """协商提议/方案"""
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    negotiation_id: str = ""
    proposer_id: str = ""
    round: int = 0
    terms: Dict[str, Any] = field(default_factory=dict)  # 提议的条款
    utility: float = 0.0                                # 提议方对该方案的打分
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    parent_proposal_id: str = ""                        # 反提议的源提议
    
    def to_dict(self) -> Dict:
        return {
            "proposal_id": self.proposal_id,
            "negotiation_id": self.negotiation_id,
            "proposer_id": self.proposer_id,
            "round": self.round,
            "terms": self.terms,
            "utility": self.utility,
            "status": self.status.value,
            "created_at": self.created_at,
            "parent_proposal_id": self.parent_proposal_id
        }


@dataclass
class Bid:
    """竞价"""
    bid_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    auction_id: str = ""
    bidder_id: str = ""
    price: float = 0.0                # 报价（成本/价格）
    score: float = 0.0                # 综合评分（可选）
    quality: float = 0.0              # 预估质量
    eta_seconds: float = 0.0          # 预估耗时
    constraints: Dict[str, Any] = field(default_factory=dict)  # 其他约束
    status: BidStatus = BidStatus.ACTIVE
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict:
        return {
            "bid_id": self.bid_id,
            "auction_id": self.auction_id,
            "bidder_id": self.bidder_id,
            "price": self.price,
            "score": self.score,
            "quality": self.quality,
            "eta_seconds": self.eta_seconds,
            "constraints": self.constraints,
            "status": self.status.value,
            "created_at": self.created_at
        }


@dataclass
class NegotiationSession:
    """协商会话"""
    negotiation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    topic: str = ""
    initiator_id: str = ""
    participants: List[str] = field(default_factory=list)
    proposals: List[Proposal] = field(default_factory=list)
    max_rounds: int = 10
    deadline: Optional[str] = None
    final_agreement: Optional[Proposal] = None
    status: str = "active"             # active / agreed / failed / expired
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def latest_proposal(self) -> Optional[Proposal]:
        return self.proposals[-1] if self.proposals else None
    
    def round_count(self) -> int:
        return len(self.proposals)


@dataclass
class AuctionSession:
    """拍卖/竞价会话"""
    auction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    task_type: str = ""
    task_data: Dict[str, Any] = field(default_factory=dict)
    auctioneer_id: str = ""
    strategy: AuctionStrategy = AuctionStrategy.SCORED
    bids: Dict[str, Bid] = field(default_factory=dict)   # bid_id -> Bid
    bidder_ids: List[str] = field(default_factory=list)
    winner_id: Optional[str] = None
    winning_bid: Optional[Bid] = None
    closed: bool = False
    deadline_seconds: float = 30.0
    evaluation_weights: Dict[str, float] = field(
        default_factory=lambda: {"price": 0.5, "quality": 0.3, "eta": 0.2}
    )
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    closed_at: Optional[str] = None


# ============================================================
# 协商管理器
# ============================================================

class NegotiationManager:
    """
    协商管理器（协调者视角）

    负责：
    - 启动/跟踪协商会话
    - 收集提议并触发议价策略
    - 判定达成共识或失败
    - 通知所有参与者最终结果

    注意：协商策略既可以在协调者侧（在 Manager 中决策下一步提议），
    也可以在参与者侧（每个 Agent 实现自己的 _evaluate_proposal）。
    """

    def __init__(self, bus: MessageBus = None):
        self._bus = bus or get_message_bus()
        self._sessions: Dict[str, NegotiationSession] = {}
        self._waiters: Dict[str, asyncio.Future] = {}

        # 跟踪协商相关消息的回调（per-session）
        self._session_callbacks: Dict[str, Callable] = {}

        # 可观测性（可选）
        self._observability = None
        try:
            from observability import get_observability
            self._observability = get_observability()
        except Exception:
            pass

        # 注册默认消息处理器（监听协商类消息）
        # 这里通过 set_callback 模式无法直接订阅 type，
        # 因为我们没有 agent_id。改为在 finalize() 中做广播。
        logger.info("NegotiationManager initialized")

    def create_session(
        self,
        initiator_id: str,
        participants: List[str],
        topic: str,
        max_rounds: int = 10,
        deadline_seconds: Optional[float] = None
    ) -> NegotiationSession:
        """创建协商会话"""
        session = NegotiationSession(
            initiator_id=initiator_id,
            participants=list(set([initiator_id] + participants)),
            topic=topic,
            max_rounds=max_rounds
        )
        if deadline_seconds:
            session.deadline = (datetime.now() + timedelta(seconds=deadline_seconds)).isoformat()

        self._sessions[session.negotiation_id] = session
        logger.info(f"Negotiation created: {session.negotiation_id} topic={topic}")

        # 可观测性
        if self._observability:
            self._observability.negotiations_total.inc(topic=topic)
            self._observability.publish_event(
                "negotiation_started",
                source="negotiation_manager",
                payload={
                    "negotiation_id": session.negotiation_id,
                    "topic": topic,
                    "initiator": initiator_id,
                    "participants": session.participants,
                },
            )

        return session

    def get_session(self, negotiation_id: str) -> Optional[NegotiationSession]:
        return self._sessions.get(negotiation_id)
    
    def add_proposal(self, session_id: str, proposal: Proposal) -> None:
        """记录提议到协商会话中"""
        session = self._sessions.get(session_id)
        if not session:
            logger.error(f"Session not found: {session_id}")
            return
        session.proposals.append(proposal)
        logger.info(f"Proposal {proposal.proposal_id} added to {session_id} round={proposal.round}")
    
    async def start_negotiation(
        self,
        initiator_id: str,
        participants: List[str],
        initial_terms: Dict[str, Any],
        topic: str = "task_allocation",
        max_rounds: int = 10,
        deadline_seconds: float = 60.0
    ) -> Dict[str, Any]:
        """
        启动协商（高层 API）
        
        流程：
        1. 创建协商会话
        2. 发起初始 PROPOSE 给所有参与者
        3. 等待回应（任意一方 ACCEPT/REJECT/COUNTER）
        4. 最多 max_rounds 轮，或达成 ACCEPT 提前结束
        5. 返回最终结果
        
        Args:
            initiator_id: 发起方 Agent ID
            participants: 参与协商的 Agent IDs
            initial_terms: 初始方案条款
            topic: 协商主题
            max_rounds: 最大协商轮数
            deadline_seconds: 总截止时间
            
        Returns:
            最终结果 {"agreement": Proposal or None, "rounds": int, "status": str}
        """
        session = self.create_session(
            initiator_id=initiator_id,
            participants=participants,
            topic=topic,
            max_rounds=max_rounds,
            deadline_seconds=deadline_seconds
        )
        
        # 初始提议
        initial_proposal = Proposal(
            negotiation_id=session.negotiation_id,
            proposer_id=initiator_id,
            round=1,
            terms=initial_terms,
            utility=self._estimate_utility(initial_terms, initiator_role="initiator")
        )
        self.add_proposal(session.negotiation_id, initial_proposal)
        
        # 等待协商最终结果
        result_future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._waiters[session.negotiation_id] = result_future
        
        try:
            final_msg = await asyncio.wait_for(
                result_future,
                timeout=deadline_seconds + 5  # 预留缓冲
            )
            return {
                "negotiation_id": session.negotiation_id,
                "status": final_msg.get("status"),
                "agreement": final_msg.get("agreement"),
                "rounds": final_msg.get("rounds", session.round_count())
            }
        except asyncio.TimeoutError:
            session.status = "expired"
            return {
                "negotiation_id": session.negotiation_id,
                "status": "expired",
                "agreement": None,
                "rounds": session.round_count()
            }
    
    def finalize(self, negotiation_id: str, agreement: Optional[Proposal], status: str) -> None:
        """结束协商会话并通知等待方"""
        session = self._sessions.get(negotiation_id)
        if not session:
            return
        
        session.final_agreement = agreement
        session.status = status
        
        # 通知所有参与者
        end_msg = Message(
            msg_type=MessageType.NEGOTIATION_END,
            sender_id="__negotiation_manager__",
            receiver_id="*",
            content={
                "negotiation_id": negotiation_id,
                "status": status,
                "agreement": agreement.to_dict() if agreement else None,
                "rounds": session.round_count()
            }
        )
        # 通过广播告知参与者
        asyncio.create_task(self._bus.broadcast(end_msg))
        
        # 唤醒等待方
        waiter = self._waiters.pop(negotiation_id, None)
        if waiter and not waiter.done():
            waiter.set_result(end_msg.content)
    
    def _estimate_utility(self, terms: Dict[str, Any], initiator_role: str) -> float:
        """估算方案效用（默认实现，调用方可以覆写）"""
        # 简单启发式：价格越低、成本越低效用越高
        price = terms.get("price", 0)
        return max(0.0, 1.0 - abs(price) * 0.1)
    
    def list_sessions(self) -> List[str]:
        return list(self._sessions.keys())


# ============================================================
# 拍卖/竞价管理器
# ============================================================

class AuctionManager:
    """
    拍卖/竞价管理器

    一个 Auctioneer 通过此管理器发起竞价（task auction），
    所有注册的 Worker 可以提交 Bid，最后根据策略选择 Winner。
    """

    def __init__(self, bus: MessageBus = None):
        self._bus = bus or get_message_bus()
        self._auctions: Dict[str, AuctionSession] = {}
        self._waiters: Dict[str, asyncio.Future] = {}

        # 可观测性（可选）
        self._observability = None
        try:
            from observability import get_observability
            self._observability = get_observability()
        except Exception:
            pass

        logger.info("AuctionManager initialized")
    
    def create_auction(
        self,
        auctioneer_id: str,
        task_id: str,
        task_type: str,
        task_data: Dict[str, Any] = None,
        strategy: AuctionStrategy = AuctionStrategy.SCORED,
        deadline_seconds: float = 30.0,
        weights: Optional[Dict[str, float]] = None
    ) -> AuctionSession:
        """创建拍卖会话"""
        auction = AuctionSession(
            task_id=task_id,
            task_type=task_type,
            task_data=task_data or {},
            auctioneer_id=auctioneer_id,
            strategy=strategy,
            deadline_seconds=deadline_seconds
        )
        if weights:
            auction.evaluation_weights.update(weights)
        
        self._auctions[auction.auction_id] = auction
        logger.info(
            f"Auction created: {auction.auction_id} task={task_type} strategy={strategy.value}"
        )
        return auction
    
    def get_auction(self, auction_id: str) -> Optional[AuctionSession]:
        return self._auctions.get(auction_id)
    
    def add_bid(self, auction_id: str, bid: Bid) -> bool:
        """
        提交一个竞价
        
        Returns:
            True 接收成功；False 拍卖已关闭或竞价方重复
        """
        auction = self._auctions.get(auction_id)
        if not auction or auction.closed:
            logger.warning(f"Auction not active: {auction_id}")
            return False
        
        # 同一 bidder 仅保留最后一次出价
        existing = next(
            (b for b in auction.bids.values() if b.bidder_id == bid.bidder_id),
            None
        )
        if existing:
            del auction.bids[existing.bid_id]
        
        bid.auction_id = auction_id
        auction.bids[bid.bid_id] = bid
        if bid.bidder_id not in auction.bidder_ids:
            auction.bidder_ids.append(bid.bidder_id)

        logger.info(f"Bid received: {bid.bidder_id} -> {auction_id} price={bid.price}")

        # 可观测性
        if self._observability:
            self._observability.auction_bids.inc(strategy=auction.strategy.value)
            self._observability.publish_event(
                "auction_bid_received",
                source="auction_manager",
                payload={
                    "auction_id": auction_id,
                    "bidder_id": bid.bidder_id,
                    "price": bid.price,
                },
            )
        return True
    
    async def run_auction(
        self,
        auctioneer_id: str,
        task_id: str,
        task_type: str,
        task_data: Dict[str, Any],
        candidate_ids: Optional[List[str]] = None,
        strategy: AuctionStrategy = AuctionStrategy.SCORED,
        deadline_seconds: float = 30.0,
        weights: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        完整运行一个拍卖流程（高层 API）
        
        1. 创建拍卖并广播 BID_REQUEST
        2. 等待 deadline 时间内收集 BID
        3. 根据 strategy 选择 winner
        4. 通知 winner (AWARD) 和 loser (BID_REQUEST 类型结果)
        
        注意：在真实场景中，BID 通常通过 WorkerAgent 的处理器异步提交。
        这里为了演示提供了异步等待。
        """
        auction = self.create_auction(
            auctioneer_id=auctioneer_id,
            task_id=task_id,
            task_type=task_type,
            task_data=task_data,
            strategy=strategy,
            deadline_seconds=deadline_seconds,
            weights=weights
        )
        
        # 广播竞价邀请
        bid_request = Message(
            msg_type=MessageType.BID_REQUEST,
            sender_id=auctioneer_id,
            receiver_id="*",
            content={
                "auction_id": auction.auction_id,
                "task_id": task_id,
                "task_type": task_type,
                "task_data": task_data,
                "strategy": strategy.value,
                "deadline_seconds": deadline_seconds
            },
            payload={
                "auction_id": auction.auction_id,
                "required_capability": task_type
            }
        )
        await self._bus.broadcast(bid_request)
        
        # 等待 deadline
        await asyncio.sleep(deadline_seconds)
        
        # 关闭拍卖并选 winner
        return self.close_auction(auction.auction_id)
    
    def close_auction(self, auction_id: str) -> Dict[str, Any]:
        """关闭拍卖并选出 winner"""
        auction = self._auctions.get(auction_id)
        if not auction or auction.closed:
            return {"error": "Auction not found or closed"}
        
        auction.closed = True
        auction.closed_at = datetime.now().isoformat()
        
        # 选择 winner
        winner = self._select_winner(auction)
        if winner:
            auction.winner_id = winner.bidder_id
            auction.winning_bid = winner
            winner.status = BidStatus.AWARDED
            for b in auction.bids.values():
                if b.bid_id != winner.bid_id:
                    b.status = BidStatus.LOSING
        
        result = {
            "auction_id": auction_id,
            "winner_id": auction.winner_id,
            "winning_bid": auction.winning_bid.to_dict() if auction.winning_bid else None,
            "total_bids": len(auction.bids),
            "strategy": auction.strategy.value,
            "status": "awarded" if winner else "no_winner"
        }

        logger.info(
            f"Auction {auction_id} closed: winner={auction.winner_id} bids={len(auction.bids)}"
        )

        # 可观测性：close 事件
        if self._observability:
            self._observability.publish_event(
                "auction_closed",
                source="auction_manager",
                payload={
                    "auction_id": auction_id,
                    "winner_id": auction.winner_id,
                    "total_bids": len(auction.bids),
                    "strategy": auction.strategy.value,
                },
            )

        return result
    
    def _select_winner(self, auction: AuctionSession) -> Optional[Bid]:
        """根据 strategy 选择赢家"""
        if not auction.bids:
            return None
        
        if auction.strategy == AuctionStrategy.FIRST_PRICE:
            # 最低价胜（如果 price 表示成本）；如果是反向（谁出价高谁胜）由调用方解释
            return min(auction.bids.values(), key=lambda b: b.price)
        
        if auction.strategy == AuctionStrategy.SECOND_PRICE:
            # Vickrey：价低者胜，但按次低结算（在 worker 视角外）
            sorted_bids = sorted(auction.bids.values(), key=lambda b: b.price)
            return sorted_bids[0]
        
        if auction.strategy == AuctionStrategy.SCORED:
            # 综合评分：分越高越好
            return max(auction.bids.values(), key=lambda b: self._score_bid(b, auction))
        
        # 默认：第一价格
        return min(auction.bids.values(), key=lambda b: b.price)
    
    def _score_bid(self, bid: Bid, auction: AuctionSession) -> float:
        """为综合评分模式计算竞价得分

        综合评分维度（基于拍卖 evaluation_weights）：
        - price   价格（越低越好）
        - quality 质量（越高越好）
        - eta     预计耗时（越短越好）
        - load    Worker 当前负载（越低越好，注册表中）

        如果用户在 Bid 中已经指定 cost / quality / eta，最终以注册表的实时指标覆盖。
        """
        weights = auction.evaluation_weights

        # 归一化（粗略）：以参与该拍卖中的最大值进行缩放
        all_prices = [b.price for b in auction.bids.values()] or [1.0]
        all_qualities = [b.quality for b in auction.bids.values()] or [1.0]
        all_etas = [b.eta_seconds for b in auction.bids.values()] or [1.0]

        max_p, min_p = max(all_prices), min(all_prices)
        max_q, min_q = max(all_qualities), min(all_qualities)
        max_e, min_e = max(all_etas), min(all_etas)

        # 价格越低越好，质量越高越好，时间越短越好
        price_norm = 1.0 - (bid.price - min_p) / (max_p - min_p + 1e-9)
        quality_norm = (bid.quality - min_q) / (max_q - min_q + 1e-9)
        eta_norm = 1.0 - (bid.eta_seconds - min_e) / (max_e - min_e + 1e-9)

        # 负载：通过注册表补全
        load_norm = 0.5
        try:
            from capability import get_capability_registry
            registry = get_capability_registry()
            profile = registry.get(bid.bidder_id)
            if profile:
                # 当前负载/最大并发，归一化（活跃越多越差）
                active = profile.metrics.active_tasks
                max_c = max((c.max_concurrent for c in profile.capabilities.values()), default=1)
                load_norm = 1.0 - min(1.0, active / max(max_c, 1))
        except Exception:
            pass

        # 评分：默认（用户没显式 load 权重则用 0.1）
        load_weight = weights.get("load", 0.1)
        total = (
            weights.get("price", 0.5) * price_norm
            + weights.get("quality", 0.3) * quality_norm
            + weights.get("eta", 0.2) * eta_norm
            + load_weight * load_norm
        )
        # 归一化总分到 [0, 1]
        return min(1.0, max(0.0, total))


# ============================================================
# 协商参与者 Mixin
# ============================================================

class NegotiationParticipantMixin:
    """
    协商参与者 Mixin（混入到 BaseAgent）
    
    提供给 WorkerAgent 等使用的协商能力：
    - 监听 PROPOSE / COUNTER 消息
    - 实现 make_counter_proposal() 根据策略让步
    - 实现 accept_proposal() / reject_proposal()
    
    使用方式：
        class WorkerAgent(NegotiationParticipantMixin, BaseAgent):
            ...
    """
    
    def __init__(
        self,
        *args,
        reservation_point: Optional[Dict[str, Any]] = None,
        negotiation_strategy: NegotiationStrategy = NegotiationStrategy.LINEAR_CONCEDE,
        initial_terms: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        # 协商策略配置
        self._reservation_point = reservation_point or {}
        self._negotiation_strategy = negotiation_strategy
        self._initial_terms = initial_terms or {}

        # 当前协商状态
        self._active_negotiations: Dict[str, Dict[str, Any]] = {}

        # 协商/竞价 handler 已经注册到 BaseAgent._handlers
        # 但 _handlers 是实例变量，由 BaseAgent.__init__ 初始化。
        # 如果在多层 mixin 的场景下需要再次注册，调用方应显式调用 _register_negotiation_handlers()
    
    def _register_negotiation_handlers(self):
        """注册协商相关消息处理器"""

        @self.on(MessageType.PROPOSE)
        async def on_propose(message: Message):
            await self._handle_propose(message)

        @self.on(MessageType.COUNTER)
        async def on_counter(message: Message):
            await self._handle_propose(message)   # 反提议同提议处理逻辑

        @self.on(MessageType.NEGOTIATION_END)
        async def on_negotiation_end(message: Message):
            await self._handle_negotiation_end(message)

        @self.on(MessageType.BID_REQUEST)
        async def on_bid_request(message: Message):
            await self._handle_bid_request(message)

        @self.on(MessageType.AWARD)
        async def on_award(message: Message):
            self._handle_award(message)
    
    async def _handle_propose(self, message: Message):
        """处理收到的方案"""
        proposal_data = message.content
        negotiation_id = proposal_data.get("negotiation_id")
        terms = proposal_data.get("terms", {})
        round_no = proposal_data.get("round", 0)
        sender_id = message.sender_id
        
        if not negotiation_id:
            return
        
        decision, counter_terms = self._evaluate_proposal(terms, round_no)
        
        if decision == "accept":
            resp = Message(
                msg_type=MessageType.ACCEPT_OFFER,
                sender_id=self.agent_id,
                receiver_id=sender_id,
                content={
                    "negotiation_id": negotiation_id,
                    "terms": terms,
                    "accepted_by": self.agent_id
                },
                correlation_id=message.correlation_id or message.msg_id
            )
            await self.send(
                receiver_id=sender_id,
                content=resp.content,
                msg_type=MessageType.ACCEPT_OFFER,
                correlation_id=message.correlation_id or message.msg_id
            )
        elif decision == "counter" and counter_terms is not None:
            resp = Message(
                msg_type=MessageType.COUNTER,
                sender_id=self.agent_id,
                receiver_id=sender_id,
                content={
                    "negotiation_id": negotiation_id,
                    "parent_proposal_id": proposal_data.get("proposal_id"),
                    "round": round_no + 1,
                    "terms": counter_terms,
                    "proposer_id": self.agent_id
                },
                correlation_id=message.correlation_id or message.msg_id
            )
            await self.send(
                receiver_id=sender_id,
                content=resp.content,
                msg_type=MessageType.COUNTER,
                correlation_id=message.correlation_id or message.msg_id
            )
        else:
            resp = Message(
                msg_type=MessageType.REJECT_OFFER,
                sender_id=self.agent_id,
                receiver_id=sender_id,
                content={
                    "negotiation_id": negotiation_id,
                    "reason": "below_reservation",
                    "rejected_by": self.agent_id
                },
                correlation_id=message.correlation_id or message.msg_id
            )
            await self.send(
                receiver_id=sender_id,
                content=resp.content,
                msg_type=MessageType.REJECT_OFFER,
                correlation_id=message.correlation_id or message.msg_id
            )
    
    def _handle_negotiation_end(self, message: Message):
        """处理协商结束通知"""
        data = message.content if isinstance(message.content, dict) else {}
        neg_id = data.get("negotiation_id")
        if neg_id in self._active_negotiations:
            self._active_negotiations[neg_id]["status"] = data.get("status")
            self._active_negotiations[neg_id]["agreement"] = data.get("agreement")
            logger.info(f"Negotiation {neg_id} ended: status={data.get('status')}")
    
    def _evaluate_proposal(self, terms: Dict[str, Any], round_no: int):
        """
        评估收到的方案
        
        Returns:
            ("accept"|"reject"|"counter", counter_terms)
        """
        # 判定是否达到保留点
        if self._meets_reservation(terms):
            return "accept", None
        
        # 判定是否能反提议
        counter_terms = self._make_counter_proposal(terms, round_no)
        if counter_terms is None:
            return "reject", None
        return "counter", counter_terms
    
    def _meets_reservation(self, terms: Dict[str, Any]) -> bool:
        """判定方案是否达到保留点（必须满足的条件）"""
        for key, min_value in self._reservation_point.items():
            if terms.get(key, 0) < min_value:
                return False
        return True
    
    def _make_counter_proposal(
        self,
        current_terms: Dict[str, Any],
        round_no: int
    ) -> Optional[Dict[str, Any]]:
        """根据策略构造反提议"""
        if self._negotiation_strategy == NegotiationStrategy.FIXED:
            return None
        
        if self._negotiation_strategy == NegotiationStrategy.LINEAR_CONCEDE:
            # 每轮向对方接近 10%
            return self._linear_concede(current_terms)
        
        if self._negotiation_strategy == NegotiationStrategy.BAZERMAN:
            return self._bazeramn_concede(current_terms, round_no)
        
        if self._negotiation_strategy == NegotiationStrategy.TIME_DEPENDENT:
            return self._time_dependent_concede(current_terms, round_no)
        
        return None
    
    def _linear_concede(self, current_terms: Dict[str, Any]) -> Dict[str, Any]:
        """线性让步：取初始值与当前值的中点"""
        counter = dict(current_terms)
        for key, initial_val in self._initial_terms.items():
            current_val = current_terms.get(key, initial_val)
            new_val = current_val + 0.5 * (initial_val - current_val)
            counter[key] = new_val
        return counter
    
    def _bazeramn_concede(
        self,
        current_terms: Dict[str, Any],
        round_no: int
    ) -> Dict[str, Any]:
        """Bazeramn 启发式让步"""
        counter = dict(current_terms)
        for key, initial_val in self._initial_terms.items():
            current_val = current_terms.get(key, initial_val)
            # 简化：让步幅度 = (initial - reservation) / log(round + 2)
            reservation = self._reservation_point.get(key, 0)
            span = abs(initial_val - reservation)
            if span == 0:
                continue
            delta = span / max(1.0, round_no + 1)
            counter[key] = current_val + delta if initial_val > reservation else current_val - delta
        return counter
    
    def _time_dependent_concede(
        self,
        current_terms: Dict[str, Any],
        round_no: int
    ) -> Dict[str, Any]:
        """时间依赖让步：轮数越多让步越大"""
        factor = min(1.0, round_no / 10.0) * 0.3
        counter = dict(current_terms)
        for key, initial_val in self._initial_terms.items():
            current_val = current_terms.get(key, initial_val)
            counter[key] = current_val + factor * (initial_val - current_val)
        return counter
    
    async def propose_to(
        self,
        receiver_id: str,
        terms: Dict[str, Any],
        negotiation_id: str = None,
        round_no: int = 1
    ) -> str:
        """主动发起协商"""
        negotiation_id = negotiation_id or str(uuid.uuid4())
        self._active_negotiations[negotiation_id] = {
            "status": "active",
            "round": round_no,
            "partner": receiver_id
        }
        
        message = Message(
            msg_type=MessageType.PROPOSE,
            sender_id=self.agent_id,
            receiver_id=receiver_id,
            content={
                "negotiation_id": negotiation_id,
                "proposal_id": str(uuid.uuid4()),
                "round": round_no,
                "terms": terms,
                "proposer_id": self.agent_id
            },
            priority=MessagePriority.HIGH
        )
        await self._bus.send(message)
        return negotiation_id
    
    # ==========================================
    # 竞价处理
    # ==========================================
    
    async def _handle_bid_request(self, message: Message):
        """收到竞价请求：构造并提交 Bid"""
        data = message.content
        auction_id = data.get("auction_id")
        if not auction_id:
            return

        # 子类可覆写 _build_bid() 自定义出价策略
        bid = self._build_bid(auction_id, data)
        if bid:
            # 回送 BID 到 BID_REQUEST 的发送者（auctioneer）
            # correlation_id 用 request 的 correlation_id（如果有），
            # 这样 auctioneer 可以通过 set_callback 关联收集
            bid_msg = Message(
                msg_type=MessageType.BID,
                sender_id=self.agent_id,
                receiver_id=message.sender_id,
                content=bid.to_dict(),
                correlation_id=message.correlation_id or message.msg_id,
                payload={
                    "auction_id": auction_id
                }
            )
            await self._bus.send(bid_msg)
    
    def _build_bid(self, auction_id: str, request_data: Dict[str, Any]) -> Optional[Bid]:
        """构造竞价（子类应覆写）"""
        # 默认实现：根据 task_type 评估 cost
        task_type = request_data.get("task_type", "")
        base_cost = {
            "search": 10.0,
            "code": 25.0,
            "analysis": 15.0,
            "write": 12.0
        }.get(task_type, 20.0)
        
        return Bid(
            auction_id=auction_id,
            bidder_id=self.agent_id,
            price=base_cost,
            score=0.5,
            quality=0.8,
            eta_seconds=5.0
        )
    
    def _handle_award(self, message: Message):
        """收到中标通知"""
        data = message.content
        logger.info(
            f"Agent {self.agent_id} awarded auction {data.get('auction_id')}: "
            f"task={data.get('task_id')}"
        )


# ============================================================
# 全局单例
# ============================================================

_negotiation_manager: Optional[NegotiationManager] = None
_auction_manager: Optional[AuctionManager] = None


def get_negotiation_manager() -> NegotiationManager:
    global _negotiation_manager
    if _negotiation_manager is None:
        _negotiation_manager = NegotiationManager()
    return _negotiation_manager


def get_auction_manager() -> AuctionManager:
    global _auction_manager
    if _auction_manager is None:
        _auction_manager = AuctionManager()
    return _auction_manager


def reset_managers():
    """重置全局管理器（测试用）"""
    global _negotiation_manager, _auction_manager
    _negotiation_manager = None
    _auction_manager = None
