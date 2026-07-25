"""
多 Agent 集成模块

将多 Agent 消息传递机制集成到 AIAgent 中，
支持 Supervisor 模式、多 Worker 协作、异步任务调度。
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from message_protocol import (
    Message, MessageType, MessagePriority, AgentInfo, AgentRole,
    TaskMessage, create_message, create_task, ConversationContext
)
from message_bus import MessageBus, BaseAgent, get_message_bus
from multi_agent import (
    AgentOrchestrator, OrchestrationMode, TaskStatus,
    WorkerAgent, SupervisorAgent
)
from task_scheduler import TaskScheduler, get_scheduler
from state_manager import StateManager, get_state_manager
from negotiation import (
    NegotiationManager, AuctionManager,
    NegotiationParticipantMixin, NegotiationStrategy, AuctionStrategy,
    NegotiationSession, AuctionSession, Proposal, Bid, BidStatus,
    get_negotiation_manager, get_auction_manager
)

logger = logging.getLogger(__name__)


class AIAgentExtension:
    """
    AIAgent 多 Agent 功能扩展

    扩展 AIAgent 的能力，支持：
    - 多 Agent 消息传递
    - Worker Agent 协作
    - 异步任务调度
    - 状态同步
    """
    
    def __init__(self, agent_instance):
        """
        初始化扩展
        
        Args:
            agent_instance: AIAgent 实例
        """
        self._agent = agent_instance
        self._agent_id = f"main_{agent_instance.current_session_id[:8]}"
        
        # 消息总线
        self._bus = get_message_bus()
        
        # 编排器
        self._orchestrator: Optional[AgentOrchestrator] = None
        
        # 任务调度器
        self._scheduler = get_scheduler()
        
        # 状态管理器
        self._state_manager = get_state_manager()
        
        # Worker Agents
        self._workers: Dict[str, WorkerAgent] = {}

        # 协商与竞价管理器
        self._negotiation_manager: Optional[NegotiationManager] = None
        self._auction_manager: Optional[AuctionManager] = None

        # 可靠性层
        self._reliability: Optional[Any] = None

        # 可观测性层
        self._observability: Optional[Any] = None

        # 已初始化标志
        self._initialized = False
        
        logger.info("AIAgentExtension initialized")
    
    async def initialize(
        self,
        model = None,
        enable_multi_agent: bool = True
    ):
        """初始化多 Agent 系统"""
        if self._initialized:
            return
        
        if enable_multi_agent:
            # 初始化编排器
            self._orchestrator = AgentOrchestrator(
                supervisor_id=self._agent_id,
                supervisor_name="MainSupervisor",
                model=model
            )

            # 初始化协商与竞价管理器
            self._negotiation_manager = get_negotiation_manager()
            self._auction_manager = get_auction_manager()

            # 启用可靠性机制（重试 + 断路器 + DLQ）
            from reliability import get_reliability
            self._reliability = get_reliability()
            self._bus.enable_reliability(self._reliability)

            # 启用可观测性机制（指标 + 链路追踪 + 事件流）
            from observability import get_observability
            self._observability = get_observability()
            self._bus.enable_observability(self._observability)

            # 启用权限机制（默认 enforce=False 仅监视；用户可主动 enable）
            from permission import get_permission_guard
            self._permission_guard = get_permission_guard()
            self._bus.enable_permission(self._permission_guard, enforce=False)

            # 接入流式总线
            try:
                from streaming import get_streaming_bus
                self._streaming_bus = get_streaming_bus()
            except Exception:
                self._streaming_bus = None

            # 创建默认 Worker Agents
            await self._create_default_workers()

            # 启动任务调度器
            await self._scheduler.start()
            
            # 注册 Agent
            agent_info = AgentInfo(
                agent_id=self._agent_id,
                name="MainAgent",
                role=AgentRole.SUPERVISOR,
                capabilities=["orchestration", "coordination", "general"]
            )

            async def _noop_receive(m):
                """主 Agent 不直接处理入站消息（由 Orchestrator 走 callback 机制）"""
                return None

            outer = self  # 捕获扩展实例

            # 创建一个真正的 BaseAgent（带消息处理循环），让 BID / PROPOSE 能被 routing
            from message_bus import BaseAgent

            class SupervisorBusAgent(BaseAgent):
                def __init__(self, agent_id):
                    BaseAgent.__init__(
                        self,
                        agent_id=agent_id,
                        name="MainAgent",
                        role=AgentRole.SUPERVISOR,
                        capabilities=["orchestration", "coordination", "general"],
                    )
                    # 注册 BID handler（用于竞价 / 多 Agent 收集）
                    self._register_bid_handler()

                def _register_bid_handler(self):
                    @self.on(MessageType.BID)
                    async def on_bid(message: Message):
                        if message.correlation_id and outer._bus._callbacks.get(message.correlation_id):
                            outer._bus._callbacks[message.correlation_id](message)

                    @self.on(MessageType.PROPOSE)
                    async def on_propose(message: Message):
                        if message.correlation_id and outer._bus._callbacks.get(message.correlation_id):
                            outer._bus._callbacks[message.correlation_id](message)

                    @self.on(MessageType.COUNTER)
                    async def on_counter(message: Message):
                        if message.correlation_id and outer._bus._callbacks.get(message.correlation_id):
                            outer._bus._callbacks[message.correlation_id](message)

                    @self.on(MessageType.ACCEPT_OFFER)
                    async def on_accept(message: Message):
                        if message.correlation_id and outer._bus._callbacks.get(message.correlation_id):
                            outer._bus._callbacks[message.correlation_id](message)

                    @self.on(MessageType.REJECT_OFFER)
                    async def on_reject(message: Message):
                        if message.correlation_id and outer._bus._callbacks.get(message.correlation_id):
                            outer._bus._callbacks[message.correlation_id](message)

                def get_status(self):
                    return "idle"

            # 存储到扩展，避免后续丢失
            self._supervisor_agent = SupervisorBusAgent(self._agent_id)

            # 启动消息循环
            try:
                loop = asyncio.get_event_loop()
                if not self._supervisor_agent._running:
                    loop.create_task(self._supervisor_agent.run())
                    self._supervisor_agent._running = True
            except Exception as e:
                logger.warning(f"Failed to start supervisor agent: {e}")
        
        self._initialized = True
        logger.info("Multi-agent system initialized")
    
    async def _create_default_workers(self):
        """创建默认的 Worker Agents"""
        # Worker 协商条款配置：reservation_point（保留点）和 initial_terms（初始报价）
        # 用于在竞价/协商中体现 Worker 的"特征"
        worker_terms = {
            "search": {
                "reservation": {"price": 8.0},
                "initial": {"price": 18.0},
                "quality": 0.85, "eta": 4.0,
            },
            "code": {
                "reservation": {"price": 18.0},
                "initial": {"price": 30.0},
                "quality": 0.90, "eta": 8.0,
            },
            "analysis": {
                "reservation": {"price": 10.0},
                "initial": {"price": 20.0},
                "quality": 0.80, "eta": 5.0,
            },
            "write": {
                "reservation": {"price": 9.0},
                "initial": {"price": 16.0},
                "quality": 0.75, "eta": 4.0,
            },
        }

        # 搜索 Worker
        search_worker = self._make_negotiable_worker(
            name="SearchWorker",
            capabilities=["search", "research", "information_retrieval"],
            worker_terms=worker_terms["search"],
            bid_base_price=15.0,
        )
        search_worker.set_executor(self._search_executor)
        self._workers["search"] = search_worker
        self._orchestrator.register_worker(search_worker)

        # 编码 Worker
        code_worker = self._make_negotiable_worker(
            name="CodeWorker",
            capabilities=["coding", "programming", "debugging"],
            worker_terms=worker_terms["code"],
            bid_base_price=25.0,
        )
        code_worker.set_executor(self._code_executor)
        self._workers["code"] = code_worker
        self._orchestrator.register_worker(code_worker)

        # 分析 Worker
        analysis_worker = self._make_negotiable_worker(
            name="AnalysisWorker",
            capabilities=["analysis", "data_analysis", "reasoning"],
            worker_terms=worker_terms["analysis"],
            bid_base_price=18.0,
        )
        analysis_worker.set_executor(self._analysis_executor)
        self._workers["analysis"] = analysis_worker
        self._orchestrator.register_worker(analysis_worker)

        # 写作 Worker
        write_worker = self._make_negotiable_worker(
            name="WriteWorker",
            capabilities=["writing", "content_creation", "documentation"],
            worker_terms=worker_terms["write"],
            bid_base_price=12.0,
        )
        write_worker.set_executor(self._write_executor)
        self._workers["write"] = write_worker
        self._orchestrator.register_worker(write_worker)

        # 启动 Worker 消息循环（否则 BID/PROPOSE 无法被处理）
        for worker in self._workers.values():
            try:
                loop = asyncio.get_event_loop()
                if not worker._running:
                    loop.create_task(worker.run())
                    worker._running = True
            except Exception as e:
                logger.warning(f"Failed to start worker {worker.name}: {e}")

        logger.info(f"Created {len(self._workers)} default workers (negotiable)")

    def _make_negotiable_worker(
        self,
        name: str,
        capabilities: List[str],
        worker_terms: Dict[str, Any],
        bid_base_price: float
    ):
        """
        创建带协商能力的 WorkerAgent

        通过动态创建类的方式混入 NegotiationParticipantMixin，
        保留 WorkerAgent 的所有原有能力，再叠加协商/竞价能力。
        """
        agent_id = name.lower()

        class NegotiableWorker(NegotiationParticipantMixin, WorkerAgent):
            def __init__(self):
                from reliability import RetryPolicy, RetryBackoff
                # 必须显式传入所有 WorkerAgent 字段
                WorkerAgent.__init__(
                    self,
                    agent_id=agent_id,
                    name=name,
                    capabilities=capabilities,
                    retry_policy=RetryPolicy(
                        max_attempts=3,
                        backoff=RetryBackoff.EXP_JITTER,
                        initial_delay=0.1,
                        max_delay=2.0,
                    ),
                    on_failure=self._default_failure_fallback,
                )
                # 显式初始化 mixin 的协商配置
                # 因为多继承 MRO 不会自动调用 NegotiationParticipantMixin.__init__
                self._reservation_point = worker_terms["reservation"]
                self._initial_terms = worker_terms["initial"]
                self._negotiation_strategy = NegotiationStrategy.LINEAR_CONCEDE
                self._active_negotiations: Dict[str, Dict[str, Any]] = {}
                self._bid_base_price = bid_base_price
                self._bid_quality = worker_terms["quality"]
                self._bid_eta = worker_terms["eta"]
                # 注册协商处理器（在 BaseAgent.__init__ 之后，_handlers 已存在）
                self._register_negotiation_handlers()

            async def _default_failure_fallback(self, task_id, error, attempts):
                """默认降级：返回安全结果（不让上层感知失败）"""
                return {
                    "task_id": task_id,
                    "status": "degraded",
                    "message": f"Fallback after {attempts} attempts: {error}",
                    "fallback": True,
                }

            def _build_bid(self, auction_id, request_data):
                """根据自身偏好构造竞价"""
                task_type = request_data.get("task_type", "")
                # 让不同 Worker 出价具有差异
                price = self._bid_base_price
                # 如果任务类型与能力匹配，稍稍加价（更擅长）
                if task_type in self.capabilities:
                    price *= 1.05
                return Bid(
                    auction_id=auction_id,
                    bidder_id=self.agent_id,
                    price=round(price, 2),
                    quality=self._bid_quality,
                    eta_seconds=self._bid_eta,
                )

        # 用工厂方法构建实例（确保 NegotiableWorker.__init__ 被调用）
        worker = NegotiableWorker()
        return worker
    
    # ==========================================
    # Worker 执行器
    # ==========================================
    
    async def _search_executor(self, description: str, data: Dict) -> Any:
        """搜索执行器"""
        logger.info(f"SearchWorker executing: {description}")
        
        # 调用实际的搜索功能
        from tools import get_all_tools
        
        tools = get_all_tools()
        search_tool = next((t for t in tools if t.name == "search_web"), None)
        
        if search_tool:
            query = data.get("user_input", description)
            result = search_tool.invoke(query)
            return result
        
        return f"Search completed for: {description}"
    
    async def _code_executor(self, description: str, data: Dict) -> Any:
        """代码执行器"""
        logger.info(f"CodeWorker executing: {description}")
        
        from tools import get_all_tools
        
        tools = get_all_tools()
        code_tool = next((t for t in tools if t.name == "run_code"), None)
        
        if code_tool and "code" in data:
            result = code_tool.invoke(data["code"])
            return result
        
        return f"Code task completed: {description}"
    
    async def _analysis_executor(self, description: str, data: Dict) -> Any:
        """分析执行器"""
        logger.info(f"AnalysisWorker executing: {description}")
        return f"Analysis completed for: {description}"
    
    async def _write_executor(self, description: str, data: Dict) -> Any:
        """写作执行器"""
        logger.info(f"WriteWorker executing: {description}")
        return f"Writing task completed: {description}"
    
    # ==========================================
    # 多 Agent 协作
    # ==========================================
    
    async def run_multi_agent(
        self,
        user_input: str,
        mode: OrchestrationMode = OrchestrationMode.SUPERVISOR
    ) -> str:
        """
        运行多 Agent 协作
        
        Args:
            user_input: 用户输入
            mode: 编排模式
        
        Returns:
            协作结果
        """
        if not self._initialized:
            await self.initialize(model=self._agent.model)
        
        if self._orchestrator is None:
            return await self._agent.run(user_input)
        
        # 根据模式执行编排
        if mode == OrchestrationMode.SUPERVISOR:
            result = await self._orchestrator.orchestrate_supervisor(
                user_input,
                context={"session_id": self._agent.current_session_id}
            )
        elif mode == OrchestrationMode.PARALLEL:
            result = await self._orchestrator.orchestrate_parallel(user_input)
        elif mode == OrchestrationMode.SEQUENTIAL:
            result = await self._orchestrator.orchestrate_sequential(user_input)
        else:
            result = await self._agent.run(user_input)
        
        return str(result)
    
    async def delegate_to_worker(
        self,
        task: str,
        worker_type: str = "general"
    ) -> Any:
        """
        委托任务给 Worker
        
        Args:
            task: 任务描述
            worker_type: Worker 类型
        
        Returns:
            Worker 执行结果
        """
        worker = self._workers.get(worker_type)
        
        if not worker:
            # 查找通用 Worker
            worker = self._workers.get("general")
        
        if worker:
            task_msg = create_task(
                sender_id=self._agent_id,
                task_type=worker_type,
                task_data={
                    "task": task,
                    "session_id": self._agent.current_session_id
                },
                receiver_id=worker.agent_id
            )
            
            # 发送任务
            await self._bus.send(task_msg)
            
            # 等待结果
            return await self._wait_for_worker_result(worker.agent_id, task_msg.msg_id)
        
        return None
    
    async def _wait_for_worker_result(
        self,
        worker_id: str,
        task_id: str,
        timeout: float = 60.0
    ) -> Any:
        """等待 Worker 结果"""
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            # 检查 Worker 的结果
            worker = self._workers.get(worker_id.split("_")[0])
            if worker:
                result = worker.get_result(task_id)
                if result is not None:
                    return result
            
            await asyncio.sleep(0.5)
        
        return {"error": "Timeout waiting for worker result"}
    
    # ==========================================
    # 消息传递 API
    # ==========================================
    
    async def send_message(
        self,
        receiver_id: str,
        content: Any,
        msg_type: MessageType = MessageType.TEXT,
        priority: MessagePriority = MessagePriority.NORMAL
    ) -> bool:
        """发送消息给指定 Agent"""
        message = create_message(
            msg_type=msg_type,
            sender_id=self._agent_id,
            receiver_id=receiver_id,
            content=content,
            priority=priority
        )
        
        return await self._bus.send(message)
    
    async def broadcast_message(
        self,
        content: Any,
        topic: str = None
    ):
        """广播消息"""
        message = create_message(
            msg_type=MessageType.BROADCAST,
            sender_id=self._agent_id,
            receiver_id="*",
            content=content
        )
        
        await self._bus.broadcast(message, topic)
    
    async def request_worker(
        self,
        worker_id: str,
        content: Any,
        timeout: float = 30.0
    ) -> Optional[Message]:
        """向 Worker 发送请求并等待响应"""
        return await self._bus.request(
            sender_id=self._agent_id,
            receiver_id=worker_id,
            content=content,
            timeout=timeout
        )
    
    # ==========================================
    # 异步任务调度
    # ==========================================
    
    def schedule_task(
        self,
        func: Callable,
        name: str = "",
        delay_seconds: float = 0,
        priority: MessagePriority = MessagePriority.NORMAL,
        callback: Callable = None
    ) -> str:
        """
        调度异步任务
        
        Args:
            func: 异步函数
            name: 任务名称
            delay_seconds: 延迟执行秒数
            priority: 优先级
            callback: 完成回调
        
        Returns:
            任务 ID
        """
        task_id = self._scheduler.schedule(
            func=func,
            name=name or func.__name__,
            delay_seconds=delay_seconds,
            priority=priority
        )
        
        if callback:
            self._scheduler.on_completion(task_id, callback)
        
        return task_id
    
    def schedule_periodic_task(
        self,
        func: Callable,
        name: str = "",
        period_seconds: float = 60.0,
        initial_delay: float = 0
    ) -> str:
        """调度周期性任务"""
        return self._scheduler.schedule_periodic(
            func=func,
            name=name or func.__name__,
            period_seconds=period_seconds,
            initial_delay=initial_delay
        )
    
    def cancel_scheduled_task(self, task_id: str) -> bool:
        """取消调度任务"""
        return self._scheduler.cancel(task_id)
    
    async def wait_for_task(self, task_id: str, timeout: float = None) -> Any:
        """等待任务完成"""
        return await self._scheduler.wait_for(task_id, timeout)
    
    # ==========================================
    # 状态管理
    # ==========================================
    
    def set_agent_state(self, key: str, value: Any):
        """设置 Agent 状态"""
        self._state_manager.set_state(self._agent_id, key, value)
    
    def get_agent_state(self, key: str = None, default: Any = None) -> Any:
        """获取 Agent 状态"""
        return self._state_manager.get_state(self._agent_id, key, default)
    
    def set_global_state(self, key: str, value: Any):
        """设置全局状态"""
        self._state_manager.set_global_state(key, value)
    
    def get_global_state(self, key: str = None, default: Any = None) -> Any:
        """获取全局状态"""
        return self._state_manager.get_global_state(key, default)
    
    def watch_state(
        self,
        agent_id: str,
        key: str,
        callback: Callable
    ):
        """监听状态变更"""
        self._state_manager.watch(agent_id, key, callback)
    
    # ==========================================
    # 分布式锁
    # ==========================================
    
    async def acquire_lock(
        self,
        lock_id: str,
        resource: str = "",
        timeout: float = 10.0,
        is_shared: bool = False
    ) -> bool:
        """获取分布式锁"""
        return await self._state_manager.acquire_lock(
            lock_id=lock_id,
            owner_id=self._agent_id,
            resource=resource,
            timeout=timeout,
            is_shared=is_shared
        )
    
    def release_lock(self, lock_id: str):
        """释放锁"""
        self._state_manager.release_lock(lock_id, self._agent_id)
    
    # ==========================================
    # 协商与竞价 API
    # ==========================================

    async def run_negotiation(
        self,
        candidate_terms: Dict[str, str],
        topic: str = "task_allocation",
        max_rounds: int = 10,
        deadline_seconds: float = 30.0
    ) -> Dict[str, Any]:
        """
        启动主 Agent 与多个 Worker 的协商流程

        Args:
            candidate_terms: 字典 {worker_type: initial_proposed_terms}
                例如：{"search": {"price": 18.0}, "code": {"price": 30.0}}
            topic: 协商主题
            max_rounds: 最大协商轮数
            deadline_seconds: 总截止时间

        Returns:
            协商结果（包含最终方案或失败信息）
        """
        if not self._initialized:
            await self.initialize()

        nm = self._negotiation_manager or get_negotiation_manager()

        # 这里演示一种"双向协商"：
        # 1) 主 Agent 用 initial terms 向每个 Worker 发 PROPOSE
        # 2) Worker 用 NegotiationParticipantMixin 回应（counter / accept / reject）
        # 3) Manager 在 deadline 后收口

        results = {}
        tasks = []
        for worker_type, terms in candidate_terms.items():
            worker = self._workers.get(worker_type)
            if not worker:
                continue
            # 通过 worker 主动 propose_to 主 Agent
            tasks.append(self._run_bilateral_negotiation(
                worker, terms, topic, max_rounds, deadline_seconds
            ))

        bilateral_results = await asyncio.gather(*tasks, return_exceptions=True)
        for worker_type, result in zip(candidate_terms.keys(), bilateral_results):
            results[worker_type] = result if not isinstance(result, Exception) else {"error": str(result)}
        return {
            "topic": topic,
            "bilateral_results": results,
            "best_deal": min(
                (r for r in results.values() if r.get("agreement")),
                key=lambda r: r.get("agreement", {}).get("terms", {}).get("price", 1e9),
                default=None,
            ),
        }

    async def _run_bilateral_negotiation(
        self,
        worker,
        initial_terms: Dict[str, Any],
        topic: str,
        max_rounds: int,
        deadline_seconds: float
    ) -> Dict[str, Any]:
        """与单个 Worker 的一对一协商"""
        nm = self._negotiation_manager or get_negotiation_manager()
        session = nm.create_session(
            initiator_id=self._agent_id,
            participants=[worker.agent_id],
            topic=topic,
            max_rounds=max_rounds,
            deadline_seconds=deadline_seconds,
        )

        # 启动等待 future
        result_future: asyncio.Future = asyncio.get_event_loop().create_future()
        nm._waiters[session.negotiation_id] = result_future

        # 用回调函数跟踪 Worker 的回应：
        # ACCEPT_OFFER -> 收口，agreed
        # COUNTER -> 主 Agent 视为让步响应继续；为简化，超过 3 轮 counter 视为失败
        # REJECT_OFFER -> 收口，rejected
        session_holder = {"agreement": None, "status": "active", "rounds": 1}

        def on_worker_response(message: Message):
            try:
                content = message.content
                if not isinstance(content, dict):
                    return
                if content.get("negotiation_id") != session.negotiation_id:
                    return
                msg_type = message.msg_type
                if msg_type == MessageType.ACCEPT_OFFER:
                    session_holder["status"] = "agreed"
                    session_holder["agreement"] = {
                        "terms": content.get("terms", initial_terms),
                        "accepted_by": content.get("accepted_by", message.sender_id),
                    }
                elif msg_type == MessageType.REJECT_OFFER:
                    session_holder["status"] = "rejected"
                    session_holder["rounds"] += 1
                elif msg_type == MessageType.COUNTER:
                    session_holder["rounds"] += 1
                # 收到终态时收口
                if session_holder["status"] in ("agreed", "rejected") and not result_future.done():
                    proposal = Proposal(
                        negotiation_id=session.negotiation_id,
                        proposer_id=self._agent_id,
                        round=session_holder["rounds"],
                        terms=session_holder["agreement"]["terms"] if session_holder["agreement"] else initial_terms,
                    ) if session_holder["agreement"] else None
                    nm.finalize(
                        session.negotiation_id,
                        proposal,
                        session_holder["status"],
                    )
            except Exception as e:
                logger.warning(f"on_worker_response parse error: {e}")

        # 注册监听 Worker ACKs/REJECTs/COUNTERs
        callback_id = f"neg_resp_{session.negotiation_id}"
        self._bus.set_callback(
            callback_id,
            on_worker_response
        )

        # 发起初始提议
        initial_proposal = Proposal(
            negotiation_id=session.negotiation_id,
            proposer_id=self._agent_id,
            round=1,
            terms=initial_terms,
        )
        nm.add_proposal(session.negotiation_id, initial_proposal)

        propose_msg = Message(
            msg_type=MessageType.PROPOSE,
            sender_id=self._agent_id,
            receiver_id=worker.agent_id,
            content={
                "negotiation_id": session.negotiation_id,
                "proposal_id": initial_proposal.proposal_id,
                "round": 1,
                "terms": initial_terms,
                "proposer_id": self._agent_id,
            },
            correlation_id=callback_id,
            priority=MessagePriority.HIGH,
        )
        await self._bus.send(propose_msg)

        try:
            final_msg = await asyncio.wait_for(result_future, timeout=deadline_seconds + 3)
            return {
                "status": final_msg.get("status"),
                "agreement": final_msg.get("agreement"),
                "rounds": final_msg.get("rounds", 0),
            }
        except asyncio.TimeoutError:
            nm.finalize(session.negotiation_id, None, "expired")
            return {"status": "expired", "agreement": None}

    # ==========================================
    # 可观测性便捷 API
    # ==========================================

    def get_observability_metrics(self) -> Dict[str, Any]:
        """获取可观测性指标"""
        if self._observability:
            return self._observability.get_stats()
        return {}

    def get_prometheus_metrics(self) -> str:
        """获取 Prometheus 文本格式的指标"""
        if self._observability:
            return self._observability.to_prometheus()
        return ""

    def list_recent_events(
        self,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """列出最近的事件"""
        if not self._observability:
            return []
        return [
            e.to_dict() for e in self._observability.events.list_events(
                event_type=event_type, source=source, limit=limit
            )
        ]

    def get_recent_traces(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近 trace 的 span 列表"""
        if not self._observability:
            return []
        return [s.to_dict() for s in self._observability.tracer.list_spans(limit=limit)]

    async def delegate_with_auction(
        self,
        task: str,
        task_type: str,
        task_data: Dict[str, Any] = None,
        strategy: AuctionStrategy = AuctionStrategy.SCORED,
        deadline_seconds: float = 5.0,
        weights: Dict[str, float] = None,
        on_result: Callable = None
    ) -> Dict[str, Any]:
        """
        把任务通过竞价方式分发给最合适的 Worker

        Args:
            task: 任务描述
            task_type: 任务类型（搜索/编码/分析/写作...）
            task_data: 任务数据
            strategy: 拍卖策略
            deadline_seconds: 等待 Bid 的时长
            weights: 综合评分权重
            on_result: 收到结果的回调（可选）

        Returns:
            {"winner_id", "result", "auction_result"}
        """
        if not self._initialized:
            await self.initialize()

        if not self._orchestrator:
            return {"error": "Orchestrator not initialized"}

        # 创建任务并通过竞价分配
        from multi_agent import Task, TaskStatus
        new_task = self._orchestrator.create_task(
            task_type=task_type,
            description=task,
            metadata={"data": task_data or {}},
        )
        self._orchestrator.update_task_status(new_task.task_id, TaskStatus.PENDING)

        winner_id = await self._orchestrator.assign_task_via_auction(
            task=new_task,
            strategy=strategy,
            deadline_seconds=deadline_seconds,
            weights=weights,
        )

        if not winner_id:
            return {"error": "No winner selected", "auction_result": None}

        # 等待 winner 执行任务完成
        result = await self._wait_for_task_result(new_task.task_id, timeout=60.0)
        auction_meta = new_task.metadata.get("auction", {})

        # 通知 winner 通过 AWARD 消息
        try:
            award = Message(
                msg_type=MessageType.AWARD,
                sender_id=self._agent_id,
                receiver_id=winner_id,
                content={
                    "auction_id": auction_meta.get("auction_id"),
                    "task_id": new_task.task_id,
                    "winning_bid": auction_meta.get("winning_bid"),
                    "result": result,
                },
            )
            await self._bus.send(award)
        except Exception:
            pass

        if on_result:
            try:
                await on_result(result) if asyncio.iscoroutinefunction(on_result) else on_result(result)
            except Exception as e:
                logger.warning(f"on_result callback error: {e}")

        return {
            "winner_id": winner_id,
            "result": result,
            "auction_result": auction_meta,
        }

    async def _wait_for_task_result(
        self,
        task_id: str,
        timeout: float = 60.0
    ) -> Any:
        """等待任务完成（基于 Orchestrator._wait_for_result）"""
        if self._orchestrator:
            return await self._orchestrator._wait_for_result(task_id, timeout=timeout)
        return {"error": "No orchestrator"}

    # ==========================================
    # 工作流管理
    # ==========================================
    
    def create_workflow(
        self,
        name: str,
        description: str = "",
        mode: OrchestrationMode = OrchestrationMode.SEQUENTIAL
    ):
        """创建工作流"""
        if self._orchestrator:
            return self._orchestrator.create_workflow(name, description, mode)
        return None
    
    def get_workflow(self, workflow_id: str):
        """获取工作流"""
        if self._orchestrator:
            return self._orchestrator._workflows.get(workflow_id)
        return None
    
    async def execute_workflow(
        self,
        workflow_id: str,
        initial_data: Dict = None
    ) -> Dict:
        """执行工作流"""
        if self._orchestrator:
            return await self._orchestrator.execute_workflow(workflow_id, initial_data)
        return {"error": "Orchestrator not initialized"}
    
    # ==========================================
    # 统计和状态
    # ==========================================
    
    def get_stats(self) -> Dict:
        """获取多 Agent 系统统计"""
        stats = {
            "initialized": self._initialized,
            "agent_id": self._agent_id,
            "workers": {
                w_name: {
                    "agent_id": w.agent_id,
                    "status": w.get_status(),
                    "capabilities": w.capabilities
                }
                for w_name, w in self._workers.items()
            }
        }
        
        if self._scheduler:
            stats["scheduler"] = self._scheduler.get_stats()
        
        if self._state_manager:
            stats["state"] = self._state_manager.get_stats()
        
        if self._orchestrator:
            stats["orchestrator"] = self._orchestrator.get_stats()
        
        if self._bus:
            stats["message_bus"] = self._bus.get_stats()
        
        return stats
    
    def get_worker_status(self) -> Dict[str, str]:
        """获取所有 Worker 状态"""
        return {
            name: worker.get_status()
            for name, worker in self._workers.items()
        }
    
    async def shutdown(self):
        """关闭多 Agent 系统"""
        # 停止调度器
        if self._scheduler:
            await self._scheduler.stop()
        
        # 注销所有 Worker
        for worker in self._workers.values():
            await worker.stop()
        
        # 注销主 Agent
        self._bus.unregister_agent(self._agent_id)
        
        self._initialized = False
        logger.info("Multi-agent system shutdown")

    # ==========================================
    # Planner API (重复以便 AIAgentExtension 直接用)
    # ==========================================

    def create_plan(self, goal: str, session_id=None) -> Dict:
        from planner import get_planner
        plan = get_planner().create_plan_from_goal(goal, context={"session_id": session_id})
        return plan.to_dict()

    def create_research_plan(self, topic: str) -> Dict:
        from planner import get_planner
        return get_planner().create_research_plan(topic).to_dict()

    def create_code_plan(self, requirement: str) -> Dict:
        from planner import get_planner
        return get_planner().create_code_plan(requirement).to_dict()

    async def run_plan(self, goal: str, session_id=None) -> Dict:
        if self._orchestrator is None:
            return {"error": "orchestrator not initialized"}
        return await self._orchestrator.run_plan(goal, session_id=session_id)

    # ==========================================
    # 长期记忆 API (重复以便 AIAgentExtension 直接用)
    # ==========================================

    def remember(self, key, value, memory_type="fact", scope="global",
                 importance=0.5, expires_in_seconds=None, tags=None) -> Dict:
        from memory import get_memory_store, MemoryType
        try:
            mt = MemoryType(memory_type)
        except ValueError:
            mt = MemoryType.FACT
        item = get_memory_store().put(
            key=key, value=value, memory_type=mt, scope=scope,
            importance=importance, expires_in_seconds=expires_in_seconds, tags=tags,
        )
        return item.to_dict()

    def recall(self, key, scope="global"):
        from memory import get_memory_store
        item = get_memory_store().get(key, scope=scope)
        return item.to_dict() if item else None

    def search_memory(self, keyword=None, scope=None, memory_type=None, limit=20):
        from memory import get_memory_store, MemoryType
        try:
            mt = MemoryType(memory_type) if memory_type else None
        except ValueError:
            mt = None
        items = get_memory_store().query(scope=scope, memory_type=mt, keyword=keyword, limit=limit)
        return [i.to_dict() for i in items]

    def forget(self, key, scope="global"):
        from memory import get_memory_store
        return get_memory_store().delete(key, scope=scope)

    def save_memory(self, path="memory.json"):
        from memory import get_memory_store
        get_memory_store().save_to_file(path)
        return {"saved_to": path, "stats": get_memory_store().stats()}

    def load_memory(self, path="memory.json"):
        from memory import get_memory_store
        n = get_memory_store().load_from_file(path)
        return {"loaded": n, "stats": get_memory_store().stats()}

    def get_memory_stats(self):
        from memory import get_memory_store
        return get_memory_store().stats()

    # ==========================================
    # 多模态 API (P2-5) - AIAgentExtension 直接可用
    # ==========================================

    def add_attachment_from_file(self, path, source="user", metadata=None):
        from multimodal import get_attachment_store
        att = get_attachment_store().add_from_file(path, source=source, metadata=metadata)
        return att.to_dict()

    def get_attachment(self, attachment_id):
        from multimodal import get_attachment_store
        att = get_attachment_store().get(attachment_id)
        return att.to_dict() if att else None

    def list_attachments(self, modality=None, mime_prefix=None, limit=100):
        from multimodal import get_attachment_store, Modality
        try:
            mod = Modality(modality) if modality else None
        except ValueError:
            mod = None
        atts = get_attachment_store().query(modality=mod, mime_prefix=mime_prefix, limit=limit)
        return [a.to_dict() for a in atts]

    async def process_attachment(self, attachment_id):
        from multimodal import get_attachment_store, AttachmentProcessor
        att = get_attachment_store().get(attachment_id)
        if att is None:
            return ""
        return await AttachmentProcessor().process(att)

    def get_attachment_stats(self):
        from multimodal import get_attachment_store
        return get_attachment_store().stats()

    async def send_multimodal(self, receiver_id, content="", attachments=None, msg_type="text"):
        from message_bus import get_message_bus
        from message_protocol import Message, MessageType
        try:
            mt = MessageType(msg_type)
        except ValueError:
            mt = MessageType.TEXT
        msg = Message(
            msg_type=mt,
            sender_id=self._agent_id if hasattr(self, '_agent_id') else "main",
            receiver_id=receiver_id,
            content=content,
            attachments=attachments or [],
        )
        try:
            await get_message_bus().send(msg)
            return True
        except Exception as e:
            logger.error(f"send_multimodal error: {e}")
            return False

    # ==========================================
    # 沙箱 API (P2-6) - AIAgentExtension 直接可用
    # ==========================================

    def set_sandbox_policy(self, **kwargs):
        from sandbox import get_sandbox_runner
        current = get_sandbox_runner().policy
        for k, v in kwargs.items():
            if hasattr(current, k):
                setattr(current, k, v)
        return current.to_dict()

    def get_sandbox_policy(self):
        from sandbox import get_sandbox_runner
        return get_sandbox_runner().policy.to_dict()

    def sandbox_check(self, code):
        from sandbox import get_sandbox_runner
        violations = get_sandbox_runner().check(code)
        return {"violations": violations, "blocked": len(violations) > 0}

    async def sandbox_run(self, code):
        from sandbox import get_sandbox_runner
        result = await get_sandbox_runner().run(code)
        return result.to_dict()

    async def sandbox_run_function(self, func, *args, **kwargs):
        from sandbox import get_sandbox_runner
        result = await get_sandbox_runner().run_function(func, *args, **kwargs)
        return result.to_dict()

    # ==========================================
    # Test Agent API (P2-4) - AIAgentExtension 直接可用
    # ==========================================

    def generate_smoke_test(self):
        from test_agent import TestCaseGenerator
        gen = TestCaseGenerator(registry=self)
        return gen.generate_smoke_test(self).to_dict()

    async def run_smoke_test(self):
        from test_agent import TestCaseGenerator
        gen = TestCaseGenerator(registry=self)
        return await gen.generate_smoke_test(self).run()

    def generate_test_for_methods(self, target_object, method_names):
        from test_agent import TestCaseGenerator
        gen = TestCaseGenerator(registry=self)
        return gen.generate_from_methods(target_object, method_names).to_dict()

    def register_test_suite(self, name):
        from test_agent import TestSuite, get_test_runner
        suite = TestSuite(name=name)
        get_test_runner().register(suite)
        return suite.to_dict()

    def add_test_case(self, suite_id, case_name, action,
                      assertion_type="truthy", assertion_arg=None, timeout=10.0):
        from test_agent import (
            get_test_runner, assert_truthy, assert_equals, assert_contains,
            assert_isinstance, assert_matches, assert_greater_than, assert_less_than,
        )
        suite = get_test_runner()._suites.get(suite_id)
        if not suite:
            return {"error": f"suite {suite_id} not found"}
        factories = {
            "truthy": assert_truthy,
            "equals": lambda: assert_equals(assertion_arg),
            "contains": lambda: assert_contains(assertion_arg),
            "isinstance": lambda: assert_isinstance(assertion_arg),
            "matches": lambda: assert_matches(assertion_arg),
            "greater_than": lambda: assert_greater_than(assertion_arg),
            "less_than": lambda: assert_less_than(assertion_arg),
        }
        assertions = [factories[assertion_type]()]
        return suite.add_simple(case_name, action, assertions, timeout=timeout).to_dict()

    async def run_test_suite(self, suite_id):
        from test_agent import get_test_runner
        return await get_test_runner().run_suite(suite_id)

    async def run_all_tests(self, parallel=False):
        from test_agent import get_test_runner
        return await get_test_runner().run_all(parallel=parallel)

    def get_test_report(self, format="json"):
        from test_agent import get_test_runner
        return get_test_runner().generate_report(format=format)

    def get_test_stats(self):
        from test_agent import get_test_runner
        return get_test_runner().stats()

    # ==========================================
    # A/B Test API (P3-16)
    # ==========================================

    def create_experiment(self, name: str, description: str = "",
                          primary_metric: str = "reward",
                          variants: Optional[List[Dict]] = None) -> Dict:
        """创建 A/B 实验"""
        from ab_testing import get_experiment_runner
        runner = get_experiment_runner()
        exp = runner.create(
            name=name,
            description=description,
            primary_metric=primary_metric,
        )
        if variants:
            for v in variants:
                exp.add_variant(
                    name=v["name"],
                    weight=v.get("weight", 1.0),
                    config=v.get("config", {}),
                    description=v.get("description", ""),
                )
        return exp.to_dict()

    def start_experiment(self, experiment_id: str) -> Dict:
        from ab_testing import get_experiment_runner
        return get_experiment_runner().start(experiment_id).to_dict()

    def stop_experiment(self, experiment_id: str) -> Dict:
        from ab_testing import get_experiment_runner
        return get_experiment_runner().stop(experiment_id).to_dict()

    def assign_experiment(
        self,
        experiment_id: str,
        user_id: str,
        context: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """分配 user_id 到变体"""
        from ab_testing import get_experiment_runner
        v = get_experiment_runner().assign(experiment_id, user_id, context)
        return v.to_dict() if v else None

    def record_experiment(
        self,
        experiment_id: str,
        variant_name: str,
        success: Optional[bool] = None,
        reward: Optional[float] = None,
        latency_ms: Optional[float] = None,
        error: bool = False,
    ) -> bool:
        from ab_testing import get_experiment_runner
        return get_experiment_runner().record(
            experiment_id, variant_name,
            success=success, reward=reward, latency_ms=latency_ms, error=error,
        )

    def decide_experiment_winner(self, experiment_id: str) -> Optional[Dict]:
        """决出胜出变体"""
        from ab_testing import get_experiment_runner
        winner_name = get_experiment_runner().decide_winner(experiment_id)
        exp = get_experiment_runner().get(experiment_id)
        return {
            "experiment_id": experiment_id,
            "winner": winner_name,
            "status": exp.status.value if exp else None,
            "variants": [v.to_dict() for v in exp.variants] if exp else [],
        } if exp else None

    def list_experiments(self) -> List[Dict]:
        from ab_testing import get_experiment_runner
        return [e.to_dict() for e in get_experiment_runner().list_experiments()]

    def get_experiment(self, experiment_id: str) -> Optional[Dict]:
        from ab_testing import get_experiment_runner
        exp = get_experiment_runner().get(experiment_id)
        return exp.to_dict() if exp else None

    def get_experiment_stats(self) -> Dict:
        from ab_testing import get_experiment_runner
        return get_experiment_runner().stats()

    # ==========================================
    # 自适应阈值 API (P3-19)
    # ==========================================

    def record_trade(
        self,
        agent_id: str,
        counterparty_id: str,
        task_type: str,
        initial_price: float,
        final_price: float,
        reservation_point: float,
        rounds: int = 0,
        abandoned: bool = False,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """录入一次协商成交记录"""
        from adaptive_threshold import get_threshold_learner
        rec = get_threshold_learner().record_trade(
            agent_id=agent_id, counterparty_id=counterparty_id,
            task_type=task_type, initial_price=initial_price,
            final_price=final_price, reservation_point=reservation_point,
            rounds=rounds, abandoned=abandoned, metadata=metadata,
        )
        return rec.to_dict()

    def learn_threshold(
        self,
        agent_id: str,
        task_type: str,
        default_threshold: float = 0.0,
    ) -> float:
        """学习阈值"""
        from adaptive_threshold import get_threshold_learner
        return get_threshold_learner().learn(agent_id, task_type, default_threshold)

    def recommend_threshold(
        self,
        agent_id: str,
        task_type: str,
        current_bid: float,
        default_threshold: float = 0.0,
    ) -> Dict:
        """推荐阈值"""
        from adaptive_threshold import get_threshold_learner
        return get_threshold_learner().recommend(
            agent_id, task_type, current_bid, default_threshold
        )

    def set_adaptive_strategy(self, strategy: str) -> Dict:
        from adaptive_threshold import get_threshold_learner, AdaptationStrategy
        try:
            s = AdaptationStrategy(strategy)
        except ValueError:
            s = AdaptationStrategy.EWMA
        get_threshold_learner().set_strategy(s)
        return get_threshold_learner().config()

    def configure_adaptive_threshold(self, **kwargs) -> Dict:
        from adaptive_threshold import get_threshold_learner
        get_threshold_learner().set_config(**kwargs)
        return get_threshold_learner().config()

    def get_adaptive_config(self) -> Dict:
        from adaptive_threshold import get_threshold_learner
        return get_threshold_learner().config()

    def get_threshold_stats(self) -> Dict:
        from adaptive_threshold import get_threshold_learner
        return get_threshold_learner().stats()

    def save_threshold_history(self, path: str = "threshold_history.json") -> Dict:
        from adaptive_threshold import get_threshold_learner
        get_threshold_learner().save_to_file(path)
        return {"saved_to": path, "stats": self.get_threshold_stats()}

    def load_threshold_history(self, path: str = "threshold_history.json") -> int:
        from adaptive_threshold import get_threshold_learner
        return get_threshold_learner().load_from_file(path)

    # ==========================================
    # Plugin Manager API (P3-17)
    # ==========================================

    def install_plugin(
        self,
        name: str,
        version: str = "0.1.0",
        entry_point: str = "",
        description: str = "",
        capabilities: Optional[List[str]] = None,
        hooks: Optional[List[str]] = None,
        dependencies: Optional[List[str]] = None,
        config: Optional[Dict] = None,
    ) -> Dict:
        """安装插件"""
        from plugin_manager import PluginManifest, get_plugin_manager
        m = PluginManifest(
            name=name, version=version,
            entry_point=entry_point, description=description,
            capabilities=capabilities or [],
            hooks=hooks or [],
            dependencies=dependencies or [],
        )
        return get_plugin_manager().install(m, config=config).to_dict()

    def enable_plugin(self, name: str) -> Dict:
        from plugin_manager import get_plugin_manager
        return get_plugin_manager().enable(name).to_dict()

    def disable_plugin(self, name: str) -> Dict:
        from plugin_manager import get_plugin_manager
        return get_plugin_manager().disable(name).to_dict()

    def uninstall_plugin(self, name: str) -> bool:
        from plugin_manager import get_plugin_manager
        return get_plugin_manager().uninstall(name)

    def list_plugins(self) -> List[Dict]:
        from plugin_manager import get_plugin_manager
        return [e.to_dict() for e in get_plugin_manager().list_installed()]

    def list_enabled_plugins(self) -> List[Dict]:
        from plugin_manager import get_plugin_manager
        return [e.to_dict() for e in get_plugin_manager().list_enabled()]

    def find_plugins_by_capability(self, capability: str) -> List[Dict]:
        from plugin_manager import get_plugin_manager
        return [e.to_dict() for e in get_plugin_manager().find_by_capability(capability)]

    def get_plugin(self, name: str) -> Optional[Dict]:
        from plugin_manager import get_plugin_manager
        e = get_plugin_manager().get(name)
        return e.to_dict() if e else None

    def save_plugins(self, path: str = "plugins.json") -> Dict:
        from plugin_manager import get_plugin_manager
        get_plugin_manager().save_state(path)
        return {"saved_to": path}

    def load_plugins(self, path: str = "plugins.json") -> int:
        from plugin_manager import get_plugin_manager
        return get_plugin_manager().load_state(path)

    def get_plugin_stats(self) -> Dict:
        from plugin_manager import get_plugin_manager
        return get_plugin_manager().stats()

    async def emit_plugin_hook(self, hook: str, *args, **kwargs) -> List[Any]:
        """触发钩子（异步）"""
        from plugin_manager import PluginHook, get_plugin_manager
        try:
            h = PluginHook(hook)
        except ValueError:
            return []
        return await get_plugin_manager().emit_hook(h, *args, **kwargs)

    def register_plugin_hook(self, hook: str, callback) -> Dict:
        from plugin_manager import PluginHook, get_plugin_manager
        try:
            h = PluginHook(hook)
        except ValueError:
            return {"error": f"unknown hook: {hook}"}
        get_plugin_manager().register_hook(h, callback)
        return {"hook": hook, "registered": True}

    # ==========================================
    # Distributed Bus API (P3-18)
    # ==========================================

    def create_distributed_bus(
        self,
        name: str,
        transport: str = "in_process",
        **kwargs,
    ) -> Dict:
        """创建分布式 bus"""
        from distributed_bus import create_distributed_bus, TransportType, DistributedMessageBus
        try:
            tt = TransportType(transport)
        except ValueError:
            tt = TransportType.IN_PROCESS
        bus = create_distributed_bus(name=name, transport_type=tt, **kwargs)
        return {"name": name, "node_id": bus.node_id, "stats": bus.stats()}

    def start_distributed_bus(self, name: str) -> Dict:
        from distributed_bus import get_distributed_bus
        bus = get_distributed_bus(name)
        if not bus:
            return {"error": f"bus {name} not found"}
        bus.start()
        return {"name": name, "started": True, "stats": bus.stats()}

    def stop_distributed_bus(self, name: str) -> Dict:
        from distributed_bus import get_distributed_bus
        bus = get_distributed_bus(name)
        if not bus:
            return {"error": f"bus {name} not found"}
        bus.stop()
        return {"name": name, "stopped": True, "stats": bus.stats()}

    def send_distributed(
        self,
        bus_name: str,
        payload: Dict,
        target_node: Optional[str] = None,
        target_agent: Optional[str] = None,
    ) -> bool:
        from distributed_bus import get_distributed_bus
        bus = get_distributed_bus(bus_name)
        if not bus:
            return False
        return bus.send(payload, target_node=target_node, target_agent=target_agent)

    def list_distributed_buses(self) -> List[Dict]:
        from distributed_bus import _distributed_buses
        return [
            {"name": n, "stats": b.stats()}
            for n, b in _distributed_buses.items()
        ]

    def get_distributed_bus_stats(self, name: str) -> Optional[Dict]:
        from distributed_bus import get_distributed_bus
        bus = get_distributed_bus(name)
        return bus.stats() if bus else None

def _sync_mixin_to_extension():
    """在 MultiAgentMixin 定义完成后把所有方法复制到 AIAgentExtension"""
    for attr_name in dir(MultiAgentMixin):
        if attr_name.startswith("_"):
            continue
        if hasattr(AIAgentExtension, attr_name):
            continue
        attr = getattr(MultiAgentMixin, attr_name)
        if callable(attr):
            setattr(AIAgentExtension, attr_name, attr)


# 在文件末尾调用
import sys as _sys
_sys.modules[__name__]._sync_extension_pending = _sync_mixin_to_extension


class MultiAgentMixin:
    """
    多 Agent 功能 Mixin
    
    提供给 AIAgent 继承的 Mixin 类，
    添加多 Agent 相关的方法。
    """
    
    def init_multi_agent(self, model=None, enable: bool = True):
        """初始化多 Agent 功能"""
        if not hasattr(self, '_multi_agent'):
            self._multi_agent = AIAgentExtension(self)
        
        if enable:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._multi_agent.initialize(model=model))
                else:
                    loop.run_until_complete(self._multi_agent.initialize(model=model))
            except Exception as e:
                logger.error(f"Failed to initialize multi-agent: {e}")
    
    @property
    def multi_agent(self) -> AIAgentExtension:
        """获取多 Agent 扩展"""
        if not hasattr(self, '_multi_agent'):
            self._multi_agent = AIAgentExtension(self)
        return self._multi_agent
    
    def run_multi_agent(self, user_input: str, mode: str = "supervisor") -> str:
        """运行多 Agent 协作"""
        if not hasattr(self, '_multi_agent') or self._multi_agent._orchestrator is None:
            self.init_multi_agent(model=self.model)
        
        mode_map = {
            "supervisor": OrchestrationMode.SUPERVISOR,
            "parallel": OrchestrationMode.PARALLEL,
            "sequential": OrchestrationMode.SEQUENTIAL
        }
        
        orch_mode = mode_map.get(mode, OrchestrationMode.SUPERVISOR)
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return loop.run_until_complete(
                    self._multi_agent.run_multi_agent(user_input, orch_mode)
                )
            else:
                return loop.run_until_complete(
                    self._multi_agent.run_multi_agent(user_input, orch_mode)
                )
        except Exception as e:
            logger.error(f"Multi-agent run error: {e}")
            return self.run(user_input)
    
    def get_multi_agent_stats(self) -> Dict:
        """获取多 Agent 统计"""
        if hasattr(self, '_multi_agent'):
            return self._multi_agent.get_stats()
        return {"error": "Multi-agent not initialized"}
    
    def shutdown_multi_agent(self):
        """关闭多 Agent 系统"""
        if hasattr(self, '_multi_agent'):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._multi_agent.shutdown())
                else:
                    loop.run_until_complete(self._multi_agent.shutdown())
            except Exception as e:
                logger.error(f"Failed to shutdown multi-agent: {e}")

    def negotiate(
        self,
        candidate_terms: Dict[str, Dict[str, Any]],
        topic: str = "task_allocation",
        max_rounds: int = 10,
        deadline_seconds: float = 30.0
    ) -> Dict[str, Any]:
        """协商同步接口（详见 AIAgentExtension.run_negotiation）"""
        if not hasattr(self, '_multi_agent') or self._multi_agent._orchestrator is None:
            self.init_multi_agent(model=self.model)

        async def _runner():
            return await self._multi_agent.run_negotiation(
                candidate_terms=candidate_terms,
                topic=topic,
                max_rounds=max_rounds,
                deadline_seconds=deadline_seconds,
            )

        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(_runner())
        except Exception as e:
            logger.error(f"negotiate error: {e}")
            return {"error": str(e)}

    def auction_delegate(
        self,
        task: str,
        task_type: str,
        task_data: Dict[str, Any] = None,
        strategy: str = "scored",
        deadline_seconds: float = 5.0,
        weights: Dict[str, float] = None
    ) -> Dict[str, Any]:
        """竞价委托同步接口（详见 AIAgentExtension.delegate_with_auction）"""
        if not hasattr(self, '_multi_agent') or self._multi_agent._orchestrator is None:
            self.init_multi_agent(model=self.model)

        strategy_map = {
            "first_price": AuctionStrategy.FIRST_PRICE,
            "second_price": AuctionStrategy.SECOND_PRICE,
            "english": AuctionStrategy.ENGLISH,
            "dutch": AuctionStrategy.DUTCH,
            "scored": AuctionStrategy.SCORED,
        }
        orch_strategy = strategy_map.get(strategy, AuctionStrategy.SCORED)

        async def _runner():
            return await self._multi_agent.delegate_with_auction(
                task=task,
                task_type=task_type,
                task_data=task_data,
                strategy=orch_strategy,
                deadline_seconds=deadline_seconds,
                weights=weights,
            )

        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(_runner())
        except Exception as e:
            logger.error(f"auction_delegate error: {e}")
            return {"error": str(e)}

    def list_workers(self, capability: str = None) -> List[Dict[str, Any]]:
        """列出 Worker 能力画像（按 capability 过滤可选）"""
        from capability import get_capability_registry
        # 如果还没初始化但有 _multi_agent（通过 _sync_mixin_to_extension 同步过来时），
        # 直接走 agent 的能力注册表
        ma = getattr(self, '_multi_agent', None)
        if ma is not None and getattr(ma, '_capability_registry', None) is not None:
            registry = ma._capability_registry
        else:
            registry = get_capability_registry()
        if capability:
            profiles = registry.find(capability)
        else:
            profiles = registry.list_all()
        return [p.to_dict() for p in profiles]

    def get_load_stats(self) -> Dict[str, Any]:
        """获取负载统计（每个 Worker 当前在执行的任务数 + 历史指标）"""
        from capability import get_capability_registry
        if not hasattr(self, '_multi_agent'):
            self.init_multi_agent(model=self.model)
        registry = get_capability_registry()
        workers = registry.list_all(online_only=False)
        return {
            "stats": registry.stats(),
            "workers": [w.to_dict() for w in workers],
        }

    def set_load_balance_strategy(self, strategy: str, prefer_tags: List[str] = None):
        """切换负载均衡策略（'score_based' | 'least_loaded' | 'wrr' | 'latency_first' | 'cost_first' | 'random')"""
        from capability import LoadBalanceStrategy
        if not hasattr(self, '_multi_agent'):
            self.init_multi_agent(model=self.model)
        try:
            strategy_enum = LoadBalanceStrategy(strategy)
        except ValueError:
            strategy_enum = LoadBalanceStrategy.SCORE_BASED
        self._multi_agent._orchestrator.set_load_balance_strategy(strategy_enum, prefer_tags)
        return {"strategy": strategy_enum.value, "prefer_tags": prefer_tags or []}

    # ==========================================
    # 意图识别 API（单一可靠性真相源）
    # ==========================================

    def detect_intent(self, text: str):
        """识别用户输入的任务意图（统一入口）

        委托给 TaskIntentRegistry，返回 TaskIntent 实例。
        可以通过 .to_dict() 转为 dict，或 .capabilities 列出能力。

        Args:
            text: 用户原始文本

        Returns:
            TaskIntent
        """
        from task_intent import get_task_intent_registry
        registry = get_task_intent_registry()
        return registry.detect_intent(text)

    def route_to_workers(self, text: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """根据用户输入 → 识别 intent → 排序候选 Worker

        Args:
            text: 用户文本
            top_k: 返回前 K 个候选

        Returns:
            候选 Worker 列表（按适合度排序），每个含
            {worker, intent, can_handle, intent_score, metrics}
        """
        intent = self.detect_intent(text)

        candidates = []
        workers_dict = getattr(self, "_workers", {}) or {}
        for worker in workers_dict.values():
            if hasattr(worker, "can_handle_intent") and worker.can_handle_intent(intent):
                candidates.append(worker)

        # 用 worker 的 intent_score + load 排序
        def sort_key(w):
            score = w.get_intent_score(intent) if hasattr(w, "get_intent_score") else 0
            load = w.get_load() if hasattr(w, "get_load") else 0
            return (-score, load)

        sorted_workers = sorted(candidates, key=sort_key)[:top_k]

        return [
            {
                "worker": w.agent_id if hasattr(w, "agent_id") else str(w),
                "name": w.name if hasattr(w, "name") else "",
                "can_handle": True,
                "intent_score": w.get_intent_score(intent),
                "load": w.get_load() if hasattr(w, "get_load") else 0,
                "intent": intent.to_dict(),
            }
            for w in sorted_workers
        ]

    def list_capabilities(self) -> List[Dict[str, Any]]:
        """列出系统中所有已注册的 capability 定义"""
        from task_intent import get_task_intent_registry
        registry = get_task_intent_registry()
        return [
            {
                "name": c.name,
                "description": c.description,
                "keywords": c.keywords,
                "aliases": c.aliases,
                "avg_latency_ms": c.avg_latency_ms,
                "avg_cost": c.avg_cost,
                "preferred_worker_tags": c.preferred_worker_tags,
            }
            for c in registry.list_capabilities()
        ]

    def list_task_types(self) -> List[Dict[str, Any]]:
        """列出系统中所有已注册的 task_type 定义"""
        from task_intent import get_task_intent_registry
        registry = get_task_intent_registry()
        return [
            {
                "name": t.name,
                "description": t.description,
                "default_capability": t.default_capability,
                "needs_decomposition": t.needs_decomposition,
                "priority": t.priority,
            }
            for t in registry.list_task_types()
        ]

    # ==========================================
    # 流式输出 API
    # ==========================================

    async def run_stream(self, prompt: str):
        """流式运行：异步迭代器，每个元素是 dict（含 type/content/source/metadata）

        多 Agent 场景下，每次 worker 完成（或竞价/协商）都会 yield 一个 chunk。
        """
        from streaming import Chunk, get_streaming_bus, ChunkType
        bus = get_streaming_bus()
        agent_id = getattr(self, '_agent_id', None) or getattr(self, 'agent_id', None) or "main"
        # 从 _multi_agent 拿 orchestrator（Mixin 模式）
        orchestrator = getattr(self, '_orchestrator', None)
        if orchestrator is None:
            ma = getattr(self, '_multi_agent', None)
            orchestrator = getattr(ma, '_orchestrator', None) if ma else None

        # 先 yield 一个 run-start 块
        await bus.emit(
            ChunkType.DECISION,
            content=f"Orchestrating: {prompt[:80]}",
            source=agent_id,
            metadata={"stage": "start", "prompt": prompt[:200]},
        )

        if not orchestrator:
            await bus.emit(
                ChunkType.ERROR,
                content="Orchestrator not initialized",
                source=agent_id,
                is_final=True,
            )
            return

        # 用 orchestrator 的流式编排
        try:
            async for chunk in orchestrator.orchestrate_stream(prompt):
                yield chunk.to_dict()
        except Exception as e:
            await bus.emit(
                ChunkType.ERROR,
                content=f"Orchestration error: {e}",
                source=agent_id,
                metadata={"error": str(e)},
                is_final=True,
            )

    def run_stream_sync(self, prompt: str):
        """同步收集所有 chunk 后返回 list（便于非 async 用户）"""
        async def _collect():
            return [c async for c in self.run_stream(prompt)]

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 已经在 event loop 中，用 run_until_complete 不行；
                # 用 create_task + 简单等待
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, _collect()).result()
            else:
                return loop.run_until_complete(_collect())
        except Exception as e:
            logger.error(f"run_stream_sync error: {e}")
            return [{"type": "error", "content": str(e)}]

    def subscribe_to_stream(self, callback):
        """订阅所有 chunk（回调式消费）"""
        from streaming import get_streaming_bus
        bus = get_streaming_bus()
        bus.subscribe(callback)
        return callback

    # ==========================================
    # 权限管理 API
    # ==========================================

    def add_policy(self, agent_id: str, roles=None, capabilities=None,
                   allowed_targets=None, allowed_tools=None, allowed_workers=None):
        """为一个 agent 添加/更新权限策略"""
        from permission import get_permission_guard, Policy, Role
        if not hasattr(self, '_permission_guard'):
            from permission import get_permission_guard
            self._permission_guard = get_permission_guard()
        guard = self._permission_guard
        role_list = []
        for r in (roles or []):
            try:
                role_list.append(Role(r))
            except ValueError:
                pass
        guard.add_policy(Policy(
            agent_id=agent_id,
            roles=role_list,
            capabilities=capabilities or [],
            allowed_targets=allowed_targets,
            allowed_tools=allowed_tools or [],
            allowed_workers=allowed_workers,
        ))
        return {"agent_id": agent_id, "added": True}

    def enable_permission_enforcement(self, enforce: bool = True):
        """开启/关闭权限强制拦截"""
        from permission import get_permission_guard
        from message_bus import get_message_bus
        if not hasattr(self, '_permission_guard'):
            self._permission_guard = get_permission_guard()
        bus = getattr(self, '_bus', None) or get_message_bus()
        bus.enable_permission(self._permission_guard, enforce=enforce)
        return {"enforce": enforce}

    def check_permission(self, agent_id: str, action: str, target: str = "") -> Dict:
        """手动检查一个 agent 的某项权限（action='send'|'capability'|'worker'|'tool'）"""
        from permission import get_permission_guard
        if not hasattr(self, '_permission_guard'):
            self._permission_guard = get_permission_guard()
        guard = self._permission_guard
        if action == "send":
            d = guard.check_send(agent_id, target)
        elif action == "capability":
            d = guard.check_capability(agent_id, target)
        elif action == "worker":
            d = guard.check_worker(agent_id, target)
        elif action == "tool":
            d = guard.check_tool(agent_id, target)
        else:
            return {"error": f"Unknown action: {action}"}
        return d.to_dict()

    def list_policies(self) -> List[Dict]:
        """列出所有权限策略"""
        from permission import get_permission_guard
        if not hasattr(self, '_permission_guard'):
            from permission import get_permission_guard
            self._permission_guard = get_permission_guard()
        return [p.to_dict() for p in self._permission_guard.list_policies()]

    def get_permission_stats(self) -> Dict:
        """权限守卫统计"""
        from permission import get_permission_guard
        if not hasattr(self, '_permission_guard'):
            from permission import get_permission_guard
            self._permission_guard = get_permission_guard()
        return self._permission_guard.stats()

    # ==========================================
    # Human-in-the-Loop API
    # ==========================================

    def set_hitl_policy(self, hook_point: str = "default", policy: str = "auto"):
        """设置 HITL 策略（policy: 'auto' | 'ask' | 'block' | 'disabled'）"""
        from human_in_loop import get_hitl_guard, HITLPolicy
        try:
            policy_enum = HITLPolicy(policy)
        except ValueError:
            policy_enum = HITLPolicy.AUTO
        guard = get_hitl_guard()
        if hook_point == "default":
            guard.set_default_policy(policy_enum)
        else:
            guard.set_hook_policy(hook_point, policy_enum)
        return {"hook_point": hook_point, "policy": policy_enum.value}

    def list_hitl_pending(self, hook_point: Optional[str] = None) -> List[Dict]:
        """列出待审批请求"""
        from human_in_loop import get_hitl_guard
        guard = get_hitl_guard()
        return [r.to_dict() for r in guard.get_pending(hook_point=hook_point)]

    def list_hitl_history(self, hook_point: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """列出已完成的审批"""
        from human_in_loop import get_hitl_guard
        guard = get_hitl_guard()
        return [r.to_dict() for r in guard.get_history(hook_point=hook_point, limit=limit)]

    def decide_hitl(self, request_id: str, status: str = "approved",
                    decided_by: str = "human", notes: str = "") -> Dict:
        """提交一个审批决策"""
        from human_in_loop import get_hitl_guard
        guard = get_hitl_guard()
        ok = guard.decide(
            request_id=request_id,
            status=status,
            decided_by=decided_by,
            notes=notes,
        )
        return {"success": ok, "request_id": request_id}

    def get_hitl_stats(self) -> Dict:
        """HITL 状态"""
        from human_in_loop import get_hitl_guard
        return get_hitl_guard().stats()

    # ==========================================
    # Planner API
    # ==========================================

    def create_plan(self, goal: str, session_id: Optional[str] = None) -> Dict:
        """根据目标创建 Plan（不执行）"""
        from planner import get_planner
        plan = get_planner().create_plan_from_goal(goal, context={"session_id": session_id})
        return plan.to_dict()

    def create_research_plan(self, topic: str) -> Dict:
        """研究类 Plan"""
        from planner import get_planner
        plan = get_planner().create_research_plan(topic)
        return plan.to_dict()

    def create_code_plan(self, requirement: str) -> Dict:
        """编码类 Plan"""
        from planner import get_planner
        plan = get_planner().create_code_plan(requirement)
        return plan.to_dict()

    async def run_plan(self, goal: str, session_id: Optional[str] = None) -> Dict:
        """规划 + 执行"""
        orchestrator = getattr(self, '_orchestrator', None)
        if orchestrator is None:
            ma = getattr(self, '_multi_agent', None)
            orchestrator = getattr(ma, '_orchestrator', None) if ma else None
        if orchestrator is None:
            return {"error": "orchestrator not initialized"}
        return await orchestrator.run_plan(goal, session_id=session_id)

    # ==========================================
    # 长期记忆 API
    # ==========================================

    def remember(
        self,
        key: str,
        value: Any,
        memory_type: str = "fact",
        scope: str = "global",
        importance: float = 0.5,
        expires_in_seconds: Optional[float] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict:
        """添加一条记忆"""
        from memory import get_memory_store, MemoryType
        try:
            mt = MemoryType(memory_type)
        except ValueError:
            mt = MemoryType.FACT
        item = get_memory_store().put(
            key=key,
            value=value,
            memory_type=mt,
            scope=scope,
            importance=importance,
            expires_in_seconds=expires_in_seconds,
            tags=tags,
        )
        return item.to_dict()

    def recall(
        self,
        key: str,
        scope: str = "global",
    ) -> Optional[Dict]:
        """检索一条记忆"""
        from memory import get_memory_store
        item = get_memory_store().get(key, scope=scope)
        return item.to_dict() if item else None

    def search_memory(
        self,
        keyword: Optional[str] = None,
        scope: Optional[str] = None,
        memory_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict]:
        """按条件搜索记忆"""
        from memory import get_memory_store, MemoryType
        try:
            mt = MemoryType(memory_type) if memory_type else None
        except ValueError:
            mt = None
        items = get_memory_store().query(
            scope=scope, memory_type=mt, keyword=keyword, limit=limit,
        )
        return [i.to_dict() for i in items]

    def forget(self, key: str, scope: str = "global") -> bool:
        """删除一条记忆"""
        from memory import get_memory_store
        return get_memory_store().delete(key, scope=scope)

    def save_memory(self, path: str = "memory.json") -> Dict:
        """持久化到文件"""
        from memory import get_memory_store
        get_memory_store().save_to_file(path)
        return {"saved_to": path, "stats": get_memory_store().stats()}

    def load_memory(self, path: str = "memory.json") -> Dict:
        """从文件加载"""
        from memory import get_memory_store
        n = get_memory_store().load_from_file(path)
        return {"loaded": n, "stats": get_memory_store().stats()}

    def get_memory_stats(self) -> Dict:
        """记忆统计"""
        from memory import get_memory_store
        return get_memory_store().stats()

    # ==========================================
    # 多模态 API (P2-5) - AIAgentExtension 直接可用
    # ==========================================

    def add_attachment_from_file(self, path, source="user", metadata=None):
        from multimodal import get_attachment_store
        att = get_attachment_store().add_from_file(path, source=source, metadata=metadata)
        return att.to_dict()

    def get_attachment(self, attachment_id):
        from multimodal import get_attachment_store
        att = get_attachment_store().get(attachment_id)
        return att.to_dict() if att else None

    def list_attachments(self, modality=None, mime_prefix=None, limit=100):
        from multimodal import get_attachment_store, Modality
        try:
            mod = Modality(modality) if modality else None
        except ValueError:
            mod = None
        atts = get_attachment_store().query(modality=mod, mime_prefix=mime_prefix, limit=limit)
        return [a.to_dict() for a in atts]

    async def process_attachment(self, attachment_id):
        from multimodal import get_attachment_store, AttachmentProcessor
        att = get_attachment_store().get(attachment_id)
        if att is None:
            return ""
        return await AttachmentProcessor().process(att)

    def get_attachment_stats(self):
        from multimodal import get_attachment_store
        return get_attachment_store().stats()

    async def send_multimodal(self, receiver_id, content="", attachments=None, msg_type="text"):
        from message_bus import get_message_bus
        from message_protocol import Message, MessageType
        try:
            mt = MessageType(msg_type)
        except ValueError:
            mt = MessageType.TEXT
        msg = Message(
            msg_type=mt,
            sender_id=self._agent_id if hasattr(self, '_agent_id') else "main",
            receiver_id=receiver_id,
            content=content,
            attachments=attachments or [],
        )
        try:
            await get_message_bus().send(msg)
            return True
        except Exception as e:
            logger.error(f"send_multimodal error: {e}")
            return False

    # ==========================================
    # 沙箱 API (P2-6) - AIAgentExtension 直接可用
    # ==========================================

    def set_sandbox_policy(self, **kwargs):
        from sandbox import get_sandbox_runner
        current = get_sandbox_runner().policy
        for k, v in kwargs.items():
            if hasattr(current, k):
                setattr(current, k, v)
        return current.to_dict()

    def get_sandbox_policy(self):
        from sandbox import get_sandbox_runner
        return get_sandbox_runner().policy.to_dict()

    def sandbox_check(self, code):
        from sandbox import get_sandbox_runner
        violations = get_sandbox_runner().check(code)
        return {"violations": violations, "blocked": len(violations) > 0}

    async def sandbox_run(self, code):
        from sandbox import get_sandbox_runner
        result = await get_sandbox_runner().run(code)
        return result.to_dict()

    async def sandbox_run_function(self, func, *args, **kwargs):
        from sandbox import get_sandbox_runner
        result = await get_sandbox_runner().run_function(func, *args, **kwargs)
        return result.to_dict()

    # ==========================================
    # Test Agent API (P2-4) - AIAgentExtension 直接可用
    # ==========================================

    def generate_smoke_test(self):
        from test_agent import TestCaseGenerator
        gen = TestCaseGenerator(registry=self)
        return gen.generate_smoke_test(self).to_dict()

    async def run_smoke_test(self):
        from test_agent import TestCaseGenerator
        gen = TestCaseGenerator(registry=self)
        return await gen.generate_smoke_test(self).run()

    def generate_test_for_methods(self, target_object, method_names):
        from test_agent import TestCaseGenerator
        gen = TestCaseGenerator(registry=self)
        return gen.generate_from_methods(target_object, method_names).to_dict()

    def register_test_suite(self, name):
        from test_agent import TestSuite, get_test_runner
        suite = TestSuite(name=name)
        get_test_runner().register(suite)
        return suite.to_dict()

    def add_test_case(self, suite_id, case_name, action,
                      assertion_type="truthy", assertion_arg=None, timeout=10.0):
        from test_agent import (
            get_test_runner, assert_truthy, assert_equals, assert_contains,
            assert_isinstance, assert_matches, assert_greater_than, assert_less_than,
        )
        suite = get_test_runner()._suites.get(suite_id)
        if not suite:
            return {"error": f"suite {suite_id} not found"}
        factories = {
            "truthy": assert_truthy,
            "equals": lambda: assert_equals(assertion_arg),
            "contains": lambda: assert_contains(assertion_arg),
            "isinstance": lambda: assert_isinstance(assertion_arg),
            "matches": lambda: assert_matches(assertion_arg),
            "greater_than": lambda: assert_greater_than(assertion_arg),
            "less_than": lambda: assert_less_than(assertion_arg),
        }
        assertions = [factories[assertion_type]()]
        return suite.add_simple(case_name, action, assertions, timeout=timeout).to_dict()

    async def run_test_suite(self, suite_id):
        from test_agent import get_test_runner
        return await get_test_runner().run_suite(suite_id)

    async def run_all_tests(self, parallel=False):
        from test_agent import get_test_runner
        return await get_test_runner().run_all(parallel=parallel)

    def get_test_report(self, format="json"):
        from test_agent import get_test_runner
        return get_test_runner().generate_report(format=format)

    def get_test_stats(self):
        from test_agent import get_test_runner
        return get_test_runner().stats()

    # ==========================================
    # 多模态 API (P2-5)
    # ==========================================

    def add_attachment_from_file(
        self,
        path: str,
        source: str = "user",
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """添加附件"""
        from multimodal import get_attachment_store
        att = get_attachment_store().add_from_file(path, source=source, metadata=metadata)
        return att.to_dict()

    def get_attachment(self, attachment_id: str) -> Optional[Dict]:
        from multimodal import get_attachment_store
        att = get_attachment_store().get(attachment_id)
        return att.to_dict() if att else None

    def list_attachments(
        self,
        modality: Optional[str] = None,
        mime_prefix: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        from multimodal import get_attachment_store, Modality
        try:
            mod = Modality(modality) if modality else None
        except ValueError:
            mod = None
        atts = get_attachment_store().query(modality=mod, mime_prefix=mime_prefix, limit=limit)
        return [a.to_dict() for a in atts]

    async def process_attachment(self, attachment_id: str) -> str:
        """处理附件 → 文本提取/caption/转录"""
        from multimodal import get_attachment_store, AttachmentProcessor
        att = get_attachment_store().get(attachment_id)
        if att is None:
            return ""
        proc = AttachmentProcessor()
        return await proc.process(att)

    def get_attachment_stats(self) -> Dict:
        from multimodal import get_attachment_store
        return get_attachment_store().stats()

    async def send_multimodal(
        self,
        receiver_id: str,
        content: str = "",
        attachments: Optional[List[Any]] = None,
        msg_type: str = "text",
    ) -> bool:
        """发送带附件的消息"""
        from message_bus import get_message_bus
        from message_protocol import Message, MessageType

        try:
            mt = MessageType(msg_type)
        except ValueError:
            mt = MessageType.TEXT

        msg = Message(
            msg_type=mt,
            sender_id=self._agent_id if hasattr(self, '_agent_id') else "main",
            receiver_id=receiver_id,
            content=content,
            attachments=attachments or [],
        )
        try:
            bus = get_message_bus()
            await bus.send(msg)
            return True
        except Exception as e:
            logger.error(f"send_multimodal error: {e}")
            return False

    # ==========================================
    # 沙箱 API (P2-6)
    # ==========================================

    def set_sandbox_policy(self, **kwargs):
        """设置沙箱策略参数（timeout/level/allowed_modules等）"""
        from sandbox import SandboxPolicy, get_sandbox_runner
        current = get_sandbox_runner().policy
        for k, v in kwargs.items():
            if hasattr(current, k):
                setattr(current, k, v)
        return current.to_dict()

    def get_sandbox_policy(self) -> Dict:
        from sandbox import get_sandbox_runner
        return get_sandbox_runner().policy.to_dict()

    def sandbox_check(self, code: str) -> Dict:
        """静态检查代码是否会被沙箱拒绝"""
        from sandbox import get_sandbox_runner
        violations = get_sandbox_runner().check(code)
        return {"violations": violations, "blocked": len(violations) > 0}

    async def sandbox_run(self, code: str) -> Dict:
        """在沙箱中执行 Python 代码"""
        from sandbox import get_sandbox_runner
        result = await get_sandbox_runner().run(code)
        return result.to_dict()

    async def sandbox_run_function(self, func, *args, **kwargs) -> Dict:
        """在沙箱中执行 Python callable"""
        from sandbox import get_sandbox_runner
        result = await get_sandbox_runner().run_function(func, *args, **kwargs)
        return result.to_dict()

    # ==========================================
    # Test Agent API (P2-4)
    # ==========================================

    def generate_smoke_test(self) -> Dict:
        """生成 smoke test 套件"""
        from test_agent import TestCaseGenerator
        gen = TestCaseGenerator(registry=self)
        suite = gen.generate_smoke_test(self)
        return suite.to_dict()

    async def run_smoke_test(self) -> Dict:
        """跑 smoke test"""
        from test_agent import TestCaseGenerator, get_test_runner
        gen = TestCaseGenerator(registry=self)
        suite = gen.generate_smoke_test(self)
        result = await suite.run()
        return result

    def generate_test_for_methods(
        self,
        target_object,
        method_names: List[str],
    ) -> Dict:
        """针对指定方法生成 test suite"""
        from test_agent import TestCaseGenerator
        gen = TestCaseGenerator(registry=self)
        suite = gen.generate_from_methods(target_object, method_names)
        return suite.to_dict()

    def register_test_suite(self, name: str) -> Dict:
        """创建一个空 test suite 并注册到全局 runner"""
        from test_agent import TestSuite, get_test_runner
        suite = TestSuite(name=name)
        get_test_runner().register(suite)
        return suite.to_dict()

    def add_test_case(
        self,
        suite_id: str,
        case_name: str,
        action,
        assertion_type: str = "truthy",
        assertion_arg=None,
        timeout: float = 10.0,
    ) -> Dict:
        """添加 test case 到已注册的 suite"""
        from test_agent import (
            get_test_runner, assert_truthy, assert_equals, assert_contains,
            assert_isinstance, assert_matches, assert_greater_than, assert_less_than,
        )
        runner = get_test_runner()
        suite = runner._suites.get(suite_id)
        if not suite:
            return {"error": f"suite {suite_id} not found"}

        assertion_factories = {
            "truthy": assert_truthy,
            "equals": lambda: assert_equals(assertion_arg),
            "contains": lambda: assert_contains(assertion_arg),
            "isinstance": lambda: assert_isinstance(assertion_arg),
            "matches": lambda: assert_matches(assertion_arg),
            "greater_than": lambda: assert_greater_than(assertion_arg),
            "less_than": lambda: assert_less_than(assertion_arg),
        }
        assertions = [assertion_factories[assertion_type]()]
        case = suite.add_simple(
            case_name, action, assertions, timeout=timeout
        )
        return case.to_dict()

    async def run_test_suite(self, suite_id: str) -> Dict:
        """跑指定 suite"""
        from test_agent import get_test_runner
        return await get_test_runner().run_suite(suite_id)

    async def run_all_tests(self, parallel: bool = False) -> List[Dict]:
        """跑所有注册的 suite"""
        from test_agent import get_test_runner
        return await get_test_runner().run_all(parallel=parallel)

    def get_test_report(self, format: str = "json") -> str:
        """生成测试报告"""
        from test_agent import get_test_runner
        return get_test_runner().generate_report(format=format)

    def get_test_stats(self) -> Dict:
        from test_agent import get_test_runner
        return get_test_runner().stats()


# ==========================================
# 在模块末尾同步 MultiAgentMixin 的方法到 AIAgentExtension
# （让 AIAgentExtension 和 MultiAgentMixin 拥有相同的完整 API）
# ==========================================

_sync_mixin_to_extension()



