"""
多 Agent 编排器

提供 Supervisor、Worker、Parallel、Hierarchical 等多种编排模式，
支持复杂任务分解、并行执行、结果聚合。
"""

import asyncio
import uuid
import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Type
from enum import Enum
from dataclasses import dataclass, field
from collections import defaultdict

from negotiation import (
    NegotiationParticipantMixin,
    AuctionManager, get_auction_manager, AuctionStrategy, Bid
)
from reliability import (
    RetryPolicy, RetryBackoff, CircuitBreaker,
    DeadLetterQueue, ReliabilityLayer, get_reliability
)
from capability import (
    CapabilityRegistry, WorkerProfile, WorkerMetrics,
    CapabilityProfile, LoadBalancer, LoadBalanceStrategy,
    get_capability_registry, get_load_balancer
)

from message_protocol import (
    Message, MessageType, MessagePriority, AgentInfo, AgentRole,
    TaskMessage, ConversationContext, create_message, create_task
)
from message_bus import MessageBus, BaseAgent, get_message_bus

logger = logging.getLogger(__name__)


class OrchestrationMode(Enum):
    """编排模式"""
    SUPERVISOR = "supervisor"      # Supervisor 模式：一个主 Agent 协调多个专业 Agent
    PARALLEL = "parallel"         # 并行模式：多个 Agent 同时执行子任务
    SEQUENTIAL = "sequential"      # 顺序模式：Agent 按顺序执行任务
    HIERARCHICAL = "hierarchical"  # 层次模式：多层 Agent 协同
    FANOUT = "fanout"              # 扇出模式：一个任务分发给多个 Agent


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"       # 等待中
    RUNNING = "running"       # 运行中
    COMPLETED = "completed"   # 已完成
    FAILED = "failed"         # 失败
    CANCELLED = "cancelled"   # 已取消


@dataclass
class Task:
    """任务定义"""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_type: str = ""              # 任务类型
    description: str = ""            # 任务描述
    assignee_id: str = ""            # 执行者 ID
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None               # 任务结果
    error: Optional[str] = None      # 错误信息
    dependencies: List[str] = field(default_factory=list)  # 依赖的任务 ID
    subtasks: List[str] = field(default_factory=list)       # 子任务 ID
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "description": self.description,
            "assignee_id": self.assignee_id,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "dependencies": self.dependencies,
            "subtasks": self.subtasks,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata
        }


@dataclass
class Workflow:
    """工作流定义"""
    workflow_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    mode: OrchestrationMode = OrchestrationMode.SEQUENTIAL
    tasks: Dict[str, Task] = field(default_factory=dict)
    root_task_id: str = ""           # 根任务 ID
    status: TaskStatus = TaskStatus.PENDING
    results: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "mode": self.mode.value,
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "root_task_id": self.root_task_id,
            "status": self.status.value,
            "results": self.results,
            "created_at": self.created_at,
            "completed_at": self.completed_at
        }


class TaskDelegate:
    """任务委托处理器"""
    
    def __init__(self, orchestrator: 'AgentOrchestrator'):
        self.orchestrator = orchestrator
    
    async def delegate_task(
        self,
        task: Task,
        target_agents: List[str],
        timeout: float = 60.0
    ) -> Dict[str, Any]:
        """委托任务给多个 Agent"""
        results = {}
        tasks = []
        
        for agent_id in target_agents:
            # 创建任务消息
            task_msg = create_task(
                sender_id=self.orchestrator.supervisor_id,
                task_type=task.task_type,
                task_data={
                    "task_id": task.task_id,
                    "description": task.description,
                    "data": task.metadata.get("data", {})
                },
                receiver_id=agent_id,
                timeout=int(timeout)
            )
            
            # 发送并等待响应
            bus = get_message_bus()
            response = await bus.request(
                sender_id=self.orchestrator.supervisor_id,
                receiver_id=agent_id,
                content=task_msg,
                timeout=timeout,
                msg_type=MessageType.DELEGATE
            )
            
            if response:
                results[agent_id] = response.content
            else:
                results[agent_id] = {"error": "Timeout or no response"}
        
        return results


class AgentOrchestrator:
    """
    多 Agent 编排器
    
    核心功能：
    - 任务分解与分配
    - 多 Agent 协调
    - 结果聚合
    - 工作流管理
    """
    
    def __init__(
        self,
        supervisor_id: str = None,
        supervisor_name: str = "Supervisor",
        model = None
    ):
        self.supervisor_id = supervisor_id or str(uuid.uuid4())
        self.supervisor_name = supervisor_name
        self.model = model

        # 消息总线
        self._bus = get_message_bus()

        # Worker Agent 注册
        self._workers: Dict[str, 'WorkerAgent'] = {}

        # 工作流和任务管理
        self._workflows: Dict[str, Workflow] = {}
        self._tasks: Dict[str, Task] = {}

        # 编排模式
        self._mode = OrchestrationMode.SUPERVISOR

        # LLM 用于任务分解
        self._task_delegate = TaskDelegate(self)

        # 回调
        self._completion_callbacks: List[Callable] = []

        # 统计
        self._stats = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0
        }

        # 可观测性（按需导入，避免循环依赖）
        self._observability = None
        try:
            from observability import get_observability
            self._observability = get_observability()
        except Exception:
            pass

        # 负载均衡策略（默认 SCORE_BASED）
        self._load_balancer = get_load_balancer()
        self._lb_strategy = LoadBalanceStrategy.SCORE_BASED
        self._lb_prefer_tags: List[str] = []

        # 流式总线
        self._streaming_bus = None
        try:
            from streaming import get_streaming_bus
            self._streaming_bus = get_streaming_bus()
        except Exception:
            pass

        # Planner
        self._planner = None
        try:
            from planner import get_planner
            self._planner = get_planner()
        except Exception:
            pass

        logger.info(f"Orchestrator initialized: {self.supervisor_id}")
    
    @property
    def bus(self) -> MessageBus:
        return self._bus
    
    @property
    def workers(self) -> Dict[str, 'WorkerAgent']:
        return self._workers
    
    # ==========================================
    # Worker 注册
    # ==========================================
    
    def register_worker(self, worker: 'WorkerAgent'):
        """注册 Worker Agent"""
        self._workers[worker.agent_id] = worker
        logger.info(f"Worker registered: {worker.name} ({worker.agent_id})")
    
    def unregister_worker(self, worker_id: str):
        """注销 Worker Agent"""
        if worker_id in self._workers:
            del self._workers[worker_id]
            logger.info(f"Worker unregistered: {worker_id}")
    
    def get_worker(self, worker_id: str) -> Optional['WorkerAgent']:
        """获取 Worker"""
        return self._workers.get(worker_id)
    
    def list_workers(self, capability: str = None) -> List[AgentInfo]:
        """列出可用的 Worker"""
        workers = [
            AgentInfo(
                agent_id=w.agent_id,
                name=w.name,
                role=AgentRole.WORKER,
                capabilities=w.capabilities,
                status=w.get_status()
            )
            for w in self._workers.values()
        ]
        
        if capability:
            workers = [w for w in workers if capability in w.capabilities]
        
        return workers
    
    # ==========================================
    # 任务管理
    # ==========================================
    
    def create_task(
        self,
        task_type: str,
        description: str,
        assignee_id: str = None,
        dependencies: List[str] = None,
        metadata: Dict = None
    ) -> Task:
        """创建任务"""
        task = Task(
            task_id=str(uuid.uuid4()),
            task_type=task_type,
            description=description,
            assignee_id=assignee_id or "",
            dependencies=dependencies or [],
            metadata=metadata or {}
        )

        self._tasks[task.task_id] = task
        self._stats["total_tasks"] += 1

        # 可观测性埋点
        if self._observability:
            self._observability.task_total.inc(task_type=task_type, status="created")
            self._observability.publish_event(
                "task_created",
                source="orchestrator",
                payload={"task_id": task.task_id, "task_type": task_type},
            )

        logger.info(f"Task created: {task.task_id} ({task_type})")
        return task
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self._tasks.get(task_id)
    
    def update_task_status(self, task_id: str, status: TaskStatus, result: Any = None, error: str = None):
        """更新任务状态"""
        task = self._tasks.get(task_id)
        if not task:
            return
        
        task.status = status
        
        if status == TaskStatus.RUNNING:
            task.started_at = datetime.now().isoformat()
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            task.completed_at = datetime.now().isoformat()
            if result is not None:
                task.result = result
            if error:
                task.error = error
        
        # 更新统计
        if status == TaskStatus.COMPLETED:
            self._stats["completed_tasks"] += 1
        elif status == TaskStatus.FAILED:
            self._stats["failed_tasks"] += 1
        
        logger.debug(f"Task {task_id} status: {status.value}")
    
    async def assign_task(self, task: Task, worker_id: str) -> bool:
        """分配任务给 Worker"""
        worker = self._workers.get(worker_id)
        if not worker:
            logger.error(f"Worker not found: {worker_id}")
            return False

        task.assignee_id = worker_id
        self.update_task_status(task.task_id, TaskStatus.RUNNING)

        # 发送任务消息
        task_msg = create_task(
            sender_id=self.supervisor_id,
            task_type=task.task_type,
            task_data={
                "task_id": task.task_id,
                "description": task.description,
                "data": task.metadata.get("data", {})
            },
            receiver_id=worker_id,
            timeout=task.metadata.get("timeout", 60)
        )

        try:
            await self._bus.send(task_msg)
            logger.info(f"Task {task.task_id} assigned to {worker_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to assign task: {e}")
            self.update_task_status(task.task_id, TaskStatus.FAILED, error=str(e))
            return False

    async def assign_task_via_auction(
        self,
        task: Task,
        strategy: AuctionStrategy = AuctionStrategy.SCORED,
        candidate_ids: Optional[List[str]] = None,
        deadline_seconds: float = 5.0,
        weights: Optional[Dict[str, float]] = None
    ) -> Optional[str]:
        """
        通过竞价（拍卖）选择最佳 Worker 来分配任务

        流程：
        1. 广播 BID_REQUEST，候选 Worker 提交 Bid
        2. 等待 deadline 结束后，AuctionManager 根据 strategy 选 winner
        3. 把 task 派给 winner

        Args:
            task: 要分配的任务
            strategy: 拍卖策略
            candidate_ids: 候选 Worker IDs（None = 所有 Workers）
            deadline_seconds: 等待 Bid 的最大时长

        Returns:
            winner agent_id（如果选出来）或 None
        """
        # 可观测性：开一个 span
        span = None
        if self._observability:
            span = self._observability.tracer.start_span(
                "orchestrator.assign_via_auction",
                tags={"task_id": task.task_id, "task_type": task.task_type, "strategy": strategy.value},
            )
            self._observability.publish_event(
                "auction_started",
                source="orchestrator",
                trace_id=span.trace_id,
                payload={"task_id": task.task_id, "strategy": strategy.value},
            )

        # HITL：BEFORE_BID / BEFORE_DELEGATE 决策前询问
        try:
            from human_in_loop import get_hitl_guard, HookPoint
            hitl = get_hitl_guard()
            bid_req = asyncio.create_task(hitl.request_approval(
                HookPoint.BEFORE_DELEGATE,
                payload={
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "description": task.description,
                    "strategy": strategy.value,
                    "candidates": candidate_ids or "all",
                },
                description=f"委托 {task.task_type} 任务: {task.description[:80]}",
                requested_by=self.supervisor_id,
                timeout=5.0,
            ))
            decision = await bid_req
            if decision.status.value == "rejected":
                self.update_task_status(task.task_id, TaskStatus.FAILED, error="hitl_rejected")
                if span:
                    self._observability.tracer.finish_span(span, status="error", error="hitl_rejected")
                return None
        except Exception:
            pass

        auction_mgr = get_auction_manager()
        auction = auction_mgr.create_auction(
            auctioneer_id=self.supervisor_id,
            task_id=task.task_id,
            task_type=task.task_type,
            task_data=task.metadata.get("data", {}),
            strategy=strategy,
            deadline_seconds=deadline_seconds,
            weights=weights
        )

        # 广播竞价请求
        bid_request = Message(
            msg_type=MessageType.BID_REQUEST,
            sender_id=self.supervisor_id,
            receiver_id="*",
            content={
                "auction_id": auction.auction_id,
                "task_id": task.task_id,
                "task_type": task.task_type,
                "task_data": task.metadata.get("data", {}),
                "strategy": strategy.value,
                "deadline_seconds": deadline_seconds,
            },
            payload={
                "auction_id": auction.auction_id,
                "required_capability": task.task_type,
            }
        )

        # 收集从 Worker 回送的 BID 消息
        # 因为 Worker 的 on_bid_request 通过 self._bus.send(BID, receiver=supervisor) 返回，
        # 而 MessageBus._get_receivers 会找到 receiver，这里 set_callback 实际能工作。
        collected_bids: List[Bid] = []

        def collect_bid(message: Message):
            try:
                content = message.content
                if not isinstance(content, dict):
                    return
                if content.get("auction_id") != auction.auction_id:
                    return
                collected_bids.append(Bid(
                    bid_id=content.get("bid_id", str(uuid.uuid4())),
                    auction_id=content.get("auction_id", auction.auction_id),
                    bidder_id=content.get("bidder_id", message.sender_id),
                    price=float(content.get("price", 0.0)),
                    quality=float(content.get("quality", 0.0)),
                    eta_seconds=float(content.get("eta_seconds", 0.0)),
                ))
            except Exception as e:
                logger.warning(f"Failed to parse incoming bid: {e}")

        # 注册以 correlation_id 关联的回调
        callback_id = f"auction_collect_{auction.auction_id}"
        self._bus.set_callback(callback_id, collect_bid)

        # 让 Worker 回送 BID 时把这个 correlation_id 用上
        bid_request.correlation_id = callback_id

        # 广播竞价请求（排除 supervisor 自己）
        # MessageBus.broadcast 默认排除 sender，这里安全
        await self._bus.broadcast(bid_request)

        # 等待 deadline，期间 BID 会被 collect_bid 处理
        # 用 collector_event 标记"收到首个 bid"
        collector_event = asyncio.Event()

        async def wait_for_bids():
            """在 deadline 范围内尝试收集 Bid"""
            start = asyncio.get_event_loop().time()
            got_first = False
            while True:
                now = asyncio.get_event_loop().time()
                if now - start >= deadline_seconds:
                    return
                # 排除 supervisor 自己的 bid（main agent 不应出价）
                real_bids = [b for b in collected_bids if b.bidder_id != self.supervisor_id]
                if real_bids and not got_first:
                    got_first = True
                    collector_event.set()
                    # 收到首个 bid 后再给一个短暂时间收集其他
                    try:
                        await asyncio.wait_for(collector_event.wait(), timeout=0.3)
                    except asyncio.TimeoutError:
                        pass
                    return
                await asyncio.sleep(0.05)

        await wait_for_bids()

        # 把收集到的 Bid 累加入 AuctionSession
        # 同样排除 supervisor 自己的 bid
        for bid in collected_bids:
            if bid.bidder_id != self.supervisor_id:
                auction_mgr.add_bid(auction.auction_id, bid)

        # 关闭拍卖并选出 winner
        result = auction_mgr.close_auction(auction.auction_id)
        winner_id = result.get("winner_id")

        if not winner_id:
            logger.warning(
                f"Auction {auction.auction_id} produced no winner; falling back to idle worker"
            )
            fallback = self._find_best_worker(task.task_type)
            if fallback:
                winner_id = fallback.agent_id

        if winner_id:
            task.assignee_id = winner_id
            self.update_task_status(task.task_id, TaskStatus.RUNNING)

            # 发送真正的 TASK 消息给 winner
            task_msg = create_task(
                sender_id=self.supervisor_id,
                task_type=task.task_type,
                task_data={
                    "task_id": task.task_id,
                    "description": task.description,
                    "auction_id": auction.auction_id,
                    "winning_bid": result.get("winning_bid"),
                    "data": task.metadata.get("data", {}),
                },
                receiver_id=winner_id,
                timeout=task.metadata.get("timeout", 60)
            )
            await self._bus.send(task_msg)
            logger.info(
                f"Task {task.task_id} auction-won by {winner_id} "
                f"(bids={result.get('total_bids')})"
            )
            task.metadata["auction"] = {
                "auction_id": auction.auction_id,
                "winner_id": winner_id,
                "winning_bid": result.get("winning_bid"),
                "total_bids": result.get("total_bids"),
            }
            # 可观测性收尾
            if span and self._observability:
                self._observability.auctions_total.inc(strategy=strategy.value, outcome="awarded")
                self._observability.publish_event(
                    "auction_awarded",
                    source="orchestrator",
                    trace_id=span.trace_id,
                    payload={
                        "task_id": task.task_id,
                        "winner_id": winner_id,
                        "total_bids": result.get("total_bids"),
                    },
                )
                span.set_tag("winner_id", winner_id)
                self._observability.tracer.finish_span(span)
            return winner_id

        self.update_task_status(task.task_id, TaskStatus.FAILED, error="no_winner")
        # 可观测性收尾（无 winner）
        if span and self._observability:
            self._observability.auctions_total.inc(strategy=strategy.value, outcome="no_winner")
            self._observability.tracer.finish_span(span, status="error", error="no_winner")
        return None
    
    # ==========================================
    # 编排模式
    # ==========================================
    
    async def orchestrate_supervisor(
        self,
        user_input: str,
        context: Dict = None
    ) -> str:
        """
        Supervisor 模式编排

        步骤：
        1. 分析任务，确定需要的专业能力
        2. 将任务分解为子任务
        3. 分配给合适的 Worker
        4. 收集结果并聚合
        5. 生成最终响应
        """
        logger.info("Supervisor mode orchestration started")

        # 1. 任务分析（使用 LLM）
        if self.model:
            analysis = await self._analyze_task(user_input, context)
        else:
            analysis = self._simple_analysis(user_input)

        # 可选：串行收集器
        async def _emit_subtask(subtask, worker):
            from streaming import ChunkType
            if self._streaming_bus:
                await self._streaming_bus.emit(
                    ChunkType.TASK_STARTED,
                    content=f"Subtask: {subtask.get('description', subtask.get('type'))}",
                    source=self.supervisor_id,
                    metadata={
                        "task_type": subtask.get("type"),
                        "worker": worker.agent_id,
                    },
                )

        # 2. 任务分解
        subtasks = self._decompose_task(user_input, analysis)

        # 3. 分配和执行
        results = {}
        for subtask in subtasks:
            # 找到合适的 Worker
            worker = self._find_best_worker(subtask["required_capability"])
            if worker:
                await _emit_subtask(subtask, worker)
                await self.assign_task(
                    self.create_task(
                        task_type=subtask["type"],
                        description=subtask["description"],
                        metadata={"data": subtask.get("data", {})}
                    ),
                    worker.agent_id
                )

                # 等待结果
                result = await self._wait_for_result(subtask["task_id"] if hasattr(subtask, 'task_id') else subtask.get("description", ""))
                results[subtask["type"]] = result

        # 4. 结果聚合
        final_result = await self._aggregate_results(results)

        if self._streaming_bus:
            from streaming import ChunkType
            await self._streaming_bus.emit(
                ChunkType.TEXT,
                content=final_result,
                source=self.supervisor_id,
                metadata={"stage": "final"},
                is_final=True,
            )

        return final_result

    async def orchestrate_stream(self, user_input: str, context: Dict = None):
        """
        流式 Supervisor 编排（async generator）：每完成一步就 yield 一个 Chunk。

        用法：
            async for chunk in orchestrator.orchestrate_stream(user_input):
                send_to_frontend(chunk.to_dict())
        """
        if not self._streaming_bus:
            from streaming import get_streaming_bus
            self._streaming_bus = get_streaming_bus()

        queue: asyncio.Queue = asyncio.Queue()

        def cb(chunk):
            try:
                queue.put_nowait(chunk)
            except asyncio.QueueFull:
                pass

        self._streaming_bus.subscribe(cb)
        try:
            # 启动编排
            task = asyncio.create_task(self.orchestrate_supervisor(user_input, context))

            while True:
                try:
                    chunk = await queue.get()
                except asyncio.CancelledError:
                    task.cancel()
                    break
                if chunk.is_final:
                    yield chunk
                    break
                yield chunk
            await task
        finally:
            self._streaming_bus.unsubscribe(cb)

    async def run_plan(
        self,
        goal: str,
        plan = None,  # Plan from planner
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        执行一个计划：用 Planner 拆解 → PlanExecutor 调度 → Worker 执行。

        Args:
            goal: 高层级目标
            plan: 已有的 Plan（None 则用 Planner 创建）
            session_id: 会话 ID（用于 scope）

        Returns:
            dict {plan_id, status, steps, results}
        """
        from planner import PlanExecutor
        if plan is None:
            if not self._planner:
                from planner import get_planner
                self._planner = get_planner()
            plan = self._planner.create_plan_from_goal(
                goal, context={"session_id": session_id}
            )

        # Step runner: 找到匹配 worker → 派任务 → 等结果
        async def run_step(step):
            worker = self._find_best_worker(step.capability)
            if not worker:
                raise RuntimeError(f"No worker available for capability: {step.capability}")

            step.assigned_worker = worker.agent_id
            task = self.create_task(
                task_type=step.capability,
                description=step.description,
                metadata={
                    "plan_id": plan.plan_id,
                    "step_id": step.step_id,
                    "deps": step.depends_on,
                },
            )
            await self.assign_task(task, worker.agent_id)
            return await self._wait_for_result(task.task_id)

        executor = PlanExecutor(
            plan,
            step_runner=run_step,
            on_step_failed=lambda s: "skip_downstream",
            max_concurrent_steps=3,
        )
        await executor.run()

        # 收集结果
        results = {}
        for s in plan.steps:
            results[s.step_id] = {
                "capability": s.capability,
                "status": s.status.value,
                "result": s.result,
                "error": s.error,
                "duration_ms": s.duration_ms,
                "worker": s.assigned_worker,
            }

        return {
            "plan_id": plan.plan_id,
            "status": plan.status,
            "steps": results,
            "goal": plan.goal,
        }

    async def orchestrate_parallel(
        self,
        user_input: str,
        max_workers: int = 5
    ) -> Dict[str, Any]:
        """
        并行模式编排
        
        将任务分解为独立的子任务，并行执行
        """
        logger.info("Parallel mode orchestration started")
        
        # 分解任务
        subtasks = self._decompose_task(user_input, {"type": "parallel"})
        
        # 分配任务给可用的 Worker
        assignments = []
        for i, subtask in enumerate(subtasks[:max_workers]):
            worker = self._find_best_worker(subtask["required_capability"])
            if worker:
                task = self.create_task(
                    task_type=subtask["type"],
                    description=subtask["description"],
                    metadata={"data": subtask.get("data", {})}
                )
                await self.assign_task(task, worker.agent_id)
                assignments.append(task)
        
        # 并行等待所有任务完成
        results = await asyncio.gather(
            *[self._wait_for_result(task.task_id) for task in assignments],
            return_exceptions=True
        )
        
        return {
            "status": "completed",
            "results": results,
            "completed": len([r for r in results if not isinstance(r, Exception)])
        }
    
    async def orchestrate_sequential(
        self,
        user_input: str
    ) -> str:
        """
        顺序模式编排
        
        按顺序执行任务，每个任务依赖前一个任务的结果
        """
        logger.info("Sequential mode orchestration started")
        
        # 分解任务
        subtasks = self._decompose_task(user_input, {"type": "sequential"})
        
        final_result = ""
        for subtask in subtasks:
            worker = self._find_best_worker(subtask["required_capability"])
            if worker:
                task = self.create_task(
                    task_type=subtask["type"],
                    description=subtask["description"],
                    dependencies=[],  # 前一个任务的结果通过 context 传递
                    metadata={"data": {"context": final_result, **subtask.get("data", {})}}
                )
                
                await self.assign_task(task, worker.agent_id)
                result = await self._wait_for_result(task.task_id)
                final_result = result if result else final_result
        
        return final_result
    
    # ==========================================
    # 工作流管理
    # ==========================================
    
    def create_workflow(
        self,
        name: str,
        description: str = "",
        mode: OrchestrationMode = OrchestrationMode.SEQUENTIAL
    ) -> Workflow:
        """创建工作流"""
        workflow = Workflow(
            workflow_id=str(uuid.uuid4()),
            name=name,
            description=description,
            mode=mode
        )
        self._workflows[workflow.workflow_id] = workflow
        return workflow
    
    def add_task_to_workflow(
        self,
        workflow_id: str,
        task: Task
    ) -> bool:
        """添加任务到工作流"""
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False
        
        workflow.tasks[task.task_id] = task
        
        if not workflow.root_task_id:
            workflow.root_task_id = task.task_id
        
        return True
    
    async def execute_workflow(
        self,
        workflow_id: str,
        initial_data: Dict = None
    ) -> Dict[str, Any]:
        """执行工作流"""
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return {"error": "Workflow not found"}
        
        logger.info(f"Executing workflow: {workflow_id}")
        workflow.status = TaskStatus.RUNNING
        
        try:
            if workflow.mode == OrchestrationMode.SEQUENTIAL:
                result = await self._execute_sequential(workflow, initial_data)
            elif workflow.mode == OrchestrationMode.PARALLEL:
                result = await self._execute_parallel(workflow, initial_data)
            elif workflow.mode == OrchestrationMode.FANOUT:
                result = await self._execute_fanout(workflow, initial_data)
            else:
                result = await self._execute_sequential(workflow, initial_data)
            
            workflow.status = TaskStatus.COMPLETED
            workflow.completed_at = datetime.now().isoformat()
            workflow.results = result
            
            # 触发回调
            for callback in self._completion_callbacks:
                await callback(workflow)
            
            return result
            
        except Exception as e:
            logger.error(f"Workflow execution error: {e}")
            workflow.status = TaskStatus.FAILED
            return {"error": str(e)}
    
    async def _execute_sequential(self, workflow: Workflow, initial_data: Dict) -> Dict:
        """顺序执行工作流"""
        results = {}
        context = initial_data or {}
        
        for task_id, task in workflow.tasks.items():
            # 检查依赖
            if task.dependencies:
                deps_completed = all(
                    workflow.tasks.get(d).status == TaskStatus.COMPLETED
                    for d in task.dependencies if d in workflow.tasks
                )
                if not deps_completed:
                    continue
            
            # 分配并执行
            worker = self._find_best_worker(task.task_type)
            if worker:
                task.metadata["context"] = context
                await self.assign_task(task, worker.agent_id)
                
                result = await self._wait_for_result(task_id)
                results[task_id] = result
                context[task.task_type] = result
        
        return results
    
    async def _execute_parallel(self, workflow: Workflow, initial_data: Dict) -> Dict:
        """并行执行工作流"""
        # 找出没有依赖或依赖已满足的任务
        ready_tasks = [
            task for task_id, task in workflow.tasks.items()
            if not task.dependencies or all(
                workflow.tasks.get(d).status == TaskStatus.COMPLETED
                for d in task.dependencies if d in workflow.tasks
            )
        ]
        
        # 并行执行
        assignments = []
        for task in ready_tasks:
            worker = self._find_best_worker(task.task_type)
            if worker:
                if initial_data:
                    task.metadata["data"] = {**task.metadata.get("data", {}), **initial_data}
                await self.assign_task(task, worker.agent_id)
                assignments.append(task)
        
        # 等待所有任务完成
        results = await asyncio.gather(
            *[self._wait_for_result(task.task_id) for task in assignments],
            return_exceptions=True
        )
        
        return {
            task.task_id: result
            for task, result in zip(assignments, results)
        }
    
    async def _execute_fanout(self, workflow: Workflow, initial_data: Dict) -> Dict:
        """扇出执行工作流（一个任务分发给多个 Agent）"""
        root_task = workflow.tasks.get(workflow.root_task_id)
        if not root_task:
            return {"error": "No root task"}
        
        # 获取所有可用 Worker
        workers = self.list_workers()
        
        # 分发任务给所有 Worker
        results = await self._task_delegate.delegate_task(
            root_task,
            [w.agent_id for w in workers],
            timeout=root_task.metadata.get("timeout", 60)
        )
        
        return results
    
    # ==========================================
    # 辅助方法
    # ==========================================
    
    def _find_best_worker(
        self,
        capability: str,
        strategy: Optional[LoadBalanceStrategy] = None,
        prefer_tags: Optional[List[str]] = None,
    ) -> Optional['WorkerAgent']:
        """找到最适合的 Worker

        Args:
            capability: 任务类型/能力
            strategy: 覆盖默认的 LB 策略
            prefer_tags: 偏好 tag（如 ["fast"]）

        Returns:
            选中的 WorkerAgent（无候选则 None）
        """
        # 同步策略
        original_strategy = self._load_balancer.strategy
        if strategy is not None:
            self._load_balancer.set_strategy(strategy)

        try:
            # 使用 CapabilityRegistry 找候选
            registry = get_capability_registry()
            candidates = registry.find_underloaded(capability)

            # 兜底：如果完全没有匹配，加载任何可用
            if not candidates:
                candidates = registry.list_all(online_only=True)

            if not candidates:
                # 都没有的话，最后再用旧方法（registry 还没注册的情况）
                candidates = [
                    w for w in self._workers.values()
                    if capability in w.capabilities and w.get_status() == "idle"
                ]
                if not candidates:
                    candidates = [
                        w for w in self._workers.values() if w.get_status() == "idle"
                    ]
                if not candidates:
                    return None
                # 兼容路径：直接返回第一个
                return candidates[0]

            # 用 LoadBalancer 选
            chosen_profile, score_detail = self._load_balancer.select(
                candidates,
                capability=capability,
                prefer_tags=prefer_tags or self._lb_prefer_tags,
            )
            if chosen_profile is None:
                return None

            chosen = self._workers.get(chosen_profile.worker_id)
            if chosen is None:
                return None

            # 可观测性：记录评分细节
            if self._observability and score_detail:
                self._observability.publish_event(
                    "worker_selected",
                    source="orchestrator",
                    payload={
                        "worker": chosen_profile.worker_id,
                        "capability": capability,
                        "strategy": self._load_balancer.strategy.value,
                        "score": score_detail.total,
                        "components": score_detail.components,
                    },
                )
            return chosen
        finally:
            if strategy is not None:
                self._load_balancer.set_strategy(original_strategy)

    def set_load_balance_strategy(
        self,
        strategy: LoadBalanceStrategy,
        prefer_tags: Optional[List[str]] = None,
    ) -> None:
        """切换 Orchestrator 默认的负载均衡策略"""
        self._lb_strategy = strategy
        self._load_balancer.set_strategy(strategy)
        if prefer_tags is not None:
            self._lb_prefer_tags = prefer_tags
    
    async def _analyze_task(self, user_input: str, context: Dict = None) -> Dict:
        """使用 LLM 分析任务"""
        if not self.model:
            return self._simple_analysis(user_input)
        
        prompt = f"""分析以下用户输入，确定：
1. 任务类型
2. 需要的专业能力
3. 是否需要分解为子任务

用户输入: {user_input}
上下文: {context or {}}

请返回 JSON 格式的分析结果。"""
        
        try:
            response = await self.model.ainvoke(prompt)
            import json
            return json.loads(response.content)
        except Exception as e:
            logger.error(f"Task analysis error: {e}")
            return self._simple_analysis(user_input)
    
    def _simple_analysis(self, user_input: str) -> Dict:
        """简单任务分析（无需 LLM）

        委托给 TaskIntentRegistry（单一可靠性真相源）。
        所有意图识别走同一套规则，不会产生多处不一致。
        """
        try:
            from task_intent import TaskIntentRegistry
            return TaskIntentRegistry.simple_analysis(user_input)
        except Exception as e:
            logger.warning(f"TaskIntentRegistry.simple_analysis failed: {e}")
            # Fallback：极简兜底
            return {
                "task_type": "general",
                "required_capabilities": ["general"],
                "needs_decomposition": False,
                "negotiation_hint": None,
            }
    
    def _decompose_task(self, user_input: str, analysis: Dict) -> List[Dict]:
        """任务分解"""
        capabilities = analysis.get("required_capabilities", ["general"])
        
        subtasks = []
        for cap in capabilities:
            subtasks.append({
                "type": cap,
                "description": f"{cap} 相关任务: {user_input}",
                "required_capability": cap,
                "data": {"user_input": user_input}
            })
        
        if not subtasks:
            subtasks.append({
                "type": "general",
                "description": user_input,
                "required_capability": "general"
            })
        
        return subtasks
    
    async def _aggregate_results(self, results: Dict[str, Any]) -> str:
        """聚合结果"""
        if not results:
            return "没有可用的结果"
        
        if self.model:
            prompt = f"""将以下多个 Agent 的结果聚合为一个完整的响应：

{results}

请生成一个连贯、完整的回答。"""
            try:
                response = await self.model.ainvoke(prompt)
                return response.content
            except Exception as e:
                logger.error(f"Result aggregation error: {e}")
        
        # 简单聚合
        return "\n\n".join([f"### {k}:\n{v}" for k, v in results.items()])
    
    async def _wait_for_result(self, task_id: str, timeout: float = 60.0) -> Any:
        """等待任务结果"""
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            task = self._tasks.get(task_id)
            if task:
                if task.status == TaskStatus.COMPLETED:
                    return task.result
                elif task.status == TaskStatus.FAILED:
                    return {"error": task.error}
            
            await asyncio.sleep(0.5)
        
        return {"error": "Timeout waiting for result"}
    
    def on_completion(self, callback: Callable):
        """注册工作流完成回调"""
        self._completion_callbacks.append(callback)
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            **self._stats,
            "total_workflows": len(self._workflows),
            "active_workflows": sum(
                1 for w in self._workflows.values()
                if w.status == TaskStatus.RUNNING
            ),
            "total_workers": len(self._workers)
        }


class WorkerAgent(BaseAgent):
    """
    Worker Agent

    执行具体的子任务，支持多种能力
    """

    def __init__(
        self,
        agent_id: str = None,
        name: str = None,
        capabilities: List[str] = None,
        executor: Callable = None,  # 任务执行器
        retry_policy: Optional[RetryPolicy] = None,
        on_failure: Optional[Callable] = None,  # 失败降级：拿到 task_id 和 error -> 返回降级结果
        capability_profiles: Optional[Dict[str, Dict]] = None,
        # 例：{"search": {"quality": 0.9, "avg_cost": 15.0, "avg_latency_ms": 2000}}
        tags: Optional[List[str]] = None,
        max_concurrent: int = 3,
    ):
        super().__init__(
            agent_id=agent_id,
            name=name or f"Worker-{agent_id[:8] if agent_id else 'new'}",
            role=AgentRole.WORKER,
            capabilities=capabilities or ["general"]
        )

        self._executor = executor
        self._task_results: Dict[str, Any] = {}

        # 可靠性配置
        from reliability import RetryPolicy
        self._retry_policy = retry_policy or RetryPolicy(
            max_attempts=3,
            backoff=RetryBackoff.EXP_JITTER,
            initial_delay=0.1,
            max_delay=5.0,
        )
        self._on_failure = on_failure

        # 能力画像 / 标签
        self._capability_profiles = capability_profiles or {}
        self._tags = tags or []
        self._max_concurrent = max_concurrent

        # 自动注册到 CapabilityRegistry
        try:
            self._register_to_registry()
        except Exception:
            pass

        # 注册默认处理器
        self._register_default_handlers()

    def _register_to_registry(self) -> None:
        """注册自身到全局 CapabilityRegistry

        使用 TaskIntentRegistry 作为单一可靠性真相源——能力默认值
        (latency/cost) 从 Capability 定义派生，避免重复硬编码。
        """
        from task_intent import get_task_intent_registry

        intent_reg = get_task_intent_registry()

        # 可选：自动注册 permission 策略（如果全局 guard 配置了 worker 默认角色）
        try:
            from permission import get_permission_guard, Policy, Role
            guard = get_permission_guard()
            if not guard.get_policy(self.agent_id):
                # 默认：worker 角色
                guard.add_policy(Policy(
                    agent_id=self.agent_id,
                    roles=[Role.WORKER],
                    capabilities=list(self.capabilities),
                ))
        except Exception:
            pass

        caps = {}
        for cap_name in self.capabilities:
            user_data = self._capability_profiles.get(cap_name, {})

            # 优先用 user_data，再用 TaskIntentRegistry 的默认值，最后兜底
            cap_def = intent_reg.get_capability(cap_name)
            default_latency = cap_def.avg_latency_ms if cap_def else 1000.0
            default_cost = cap_def.avg_cost if cap_def else 1.0

            caps[cap_name] = CapabilityProfile(
                name=cap_name,
                quality=user_data.get("quality", 0.8),
                avg_cost=user_data.get("avg_cost", default_cost),
                avg_latency_ms=user_data.get("avg_latency_ms", default_latency),
                error_rate=user_data.get("error_rate", 0.0),
                throughput=user_data.get("throughput", 1.0),
                max_concurrent=user_data.get("max_concurrent", self._max_concurrent),
            )

        profile = WorkerProfile(
            worker_id=self.agent_id,
            name=self.name,
            capabilities=caps,
            tags=self._tags,
            metrics=WorkerMetrics(),
        )
        registry = get_capability_registry()
        registry.register(profile)

    def set_executor(self, executor: Callable):
        """设置任务执行器"""
        self._executor = executor

    def set_retry_policy(self, retry_policy: RetryPolicy):
        """设置重试策略"""
        self._retry_policy = retry_policy

    def set_failure_handler(self, handler: Callable):
        """设置失败降级处理器：async def fallback(task_id, error, attempt) -> result"""
        self._on_failure = handler

    def can_handle_intent(self, intent) -> bool:
        """判断该 Worker 能否处理某个 TaskIntent

        Args:
            intent: TaskIntent（来自 task_intent 模块）

        Returns:
            True if 至少一个 capability 能匹配
        """
        if intent is None:
            return False
        # 直接集合相交
        return any(c in self.capabilities for c in intent.capabilities)

    def get_intent_score(self, intent) -> float:
        """评分当前 Worker 处理某 intent 的适合度（用于多维评分 fallback 路径）

        简单启发：匹配的 capability 数越多分越高
        """
        if intent is None or not intent.capabilities:
            return 0.0
        matched = sum(1 for c in intent.capabilities if c in self.capabilities)
        return matched / len(intent.capabilities)

    def get_load(self) -> int:
        """当前在执行任务数"""
        profile = get_capability_registry().get(self.agent_id)
        return profile.metrics.active_tasks if profile else 0

    def get_metrics(self) -> Dict[str, Any]:
        """获取运行指标快照"""
        profile = get_capability_registry().get(self.agent_id)
        return profile.metrics.to_dict() if profile else {}
    
    def _register_default_handlers(self):
        """注册默认消息处理器"""
        
        @self.on(MessageType.TASK)
        async def handle_task(message: Message):
            """处理任务消息"""
            await self.execute_task(message)
        
        @self.on(MessageType.DELEGATE)
        async def handle_delegate(message: Message):
            """处理委托消息"""
            await self.execute_task(message)
        
        @self.on(MessageType.REQUEST)
        async def handle_request(message: Message):
            """处理请求消息"""
            if self._executor:
                try:
                    result = await self._execute(message.content)
                    response = message.create_response(result)
                    await self.send(
                        receiver_id=message.sender_id,
                        content=result,
                        msg_type=MessageType.RESPONSE
                    )
                except Exception as e:
                    response = message.create_response({"error": str(e)})
                    await self.send(
                        receiver_id=message.sender_id,
                        content={"error": str(e)},
                        msg_type=MessageType.ERROR
                    )
    
    async def execute_task(self, message: Message):
        """执行任务

        流程：
        1. 用 _retry_policy 重试执行
        2. 全部失败后，调用 _on_failure 降级（如果有）
        3. 降级也没有 -> 进 DLQ + 返回错误
        4. 成功 -> 存结果 + 发 RESULT 消息
        """
        # 可观测性：开一个 span
        span = None
        obs = None
        try:
            from observability import get_observability
            obs = get_observability()
            span = obs.tracer.start_span(
                "worker.execute_task",
                tags={"worker": self.agent_id, "task_id": message.msg_id},
            )
        except Exception:
            pass

        task_data = message.payload.get("task_data", {})
        task_id = task_data.get("task_id", message.msg_id)
        description = task_data.get("description", str(message.content))

        logger.info(f"Worker {self.name} executing task: {task_id} (retries={self._retry_policy.max_attempts})")

        if obs:
            obs.task_total.inc(task_type="task", status="started")
            obs.publish_event(
                "task_started",
                source="worker",
                trace_id=span.trace_id if span else None,
                payload={"worker": self.agent_id, "task_id": task_id},
            )

        # 上报：任务开始（Registry）
        try:
            get_capability_registry().record_task_started(self.agent_id)
        except Exception:
            pass

        # 权限检查：调用方是否有权用此 capability
        try:
            from permission import get_permission_guard
            guard = get_permission_guard()
            # 把 message 的 sender 当作 caller
            caller = message.sender_id or self.agent_id
            # 任务的 capability 是 task_type
            task_cap = task_data.get("task_type", "")
            decision = guard.check_capability(caller, task_cap)
            if not decision.granted:
                logger.warning(
                    f"[Permission DENIED] {caller} cannot use {task_cap} on {self.agent_id}: {decision.reason}"
                )
                # 发回错误消息
                await self.send(
                    receiver_id=caller,
                    content={"error": f"permission denied: {decision.reason}", "task_id": task_id},
                    msg_type=MessageType.ERROR,
                    correlation_id=message.msg_id,
                )
                self._task_results[task_id] = {"error": f"permission denied: {decision.reason}"}
                if span and obs:
                    obs.tracer.finish_span(span, status="error", error="permission_denied")
                try:
                    get_capability_registry().record_task_ended(
                        self.agent_id, success=False, duration_ms=0
                    )
                except Exception:
                    pass
                self.set_state("current_task", None)
                return
        except Exception:
            pass

        self.set_state("current_task", task_id)
        start_time = time.time()

        result = None
        last_error = None
        attempts_made = 0

        try:
            # 重试循环
            for attempt in range(self._retry_policy.max_attempts):
                attempts_made = attempt + 1
                try:
                    result = await self._execute(description, task_data.get("data", {}))
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"Worker {self.name} task {task_id} attempt {attempts_made} failed: {e}"
                    )
                    if obs:
                        obs.retries_total.inc(op=f"worker:{self.agent_id}")
                    if attempt + 1 < self._retry_policy.max_attempts:
                        delay = self._retry_policy.compute_delay(attempt)
                        if delay > 0:
                            await asyncio.sleep(delay)

            # 全部重试都失败
            if result is None and last_error is not None:
                logger.error(f"Worker {self.name} task {task_id} exhausted retries")
                # 尝试降级
                if self._on_failure is not None:
                    try:
                        result = await self._on_failure(task_id, last_error, attempts_made) \
                                 if asyncio.iscoroutinefunction(self._on_failure) \
                                 else self._on_failure(task_id, last_error, attempts_made)
                        logger.info(f"Worker {self.name} task {task_id} fallback succeeded")
                        # 标记降级结果
                        if isinstance(result, dict):
                            result["_fallback"] = True
                    except Exception as fallback_error:
                        logger.error(f"Fallback handler error: {fallback_error}")

                # 降级也没有 -> DLQ
                if result is None or (isinstance(result, dict) and result.get("error")):
                    self._send_to_dlq(task_id, last_error, attempts_made)
                    result = {
                        "error": str(last_error),
                        "task_id": task_id,
                        "attempts": attempts_made,
                        "dead_lettered": True,
                    }

            # 存储结果
            self._task_results[task_id] = result

            # 发送完成消息
            await self.send(
                receiver_id=message.sender_id,
                content=result,
                msg_type=MessageType.RESULT,
                correlation_id=message.msg_id
            )

            # 可观测性：task 结束
            if obs:
                duration = time.time() - start_time
                obs.task_duration.observe(duration, worker=self.agent_id, status="ok")
                obs.task_total.inc(task_type="task", status="completed")
                status = "fallback" if result and isinstance(result, dict) and result.get("_fallback") else "ok"
                event_type = "task_fallback" if status == "fallback" else "task_completed"
                obs.publish_event(
                    event_type,
                    source="worker",
                    trace_id=span.trace_id if span else None,
                    payload={
                        "worker": self.agent_id,
                        "task_id": task_id,
                        "duration_seconds": duration,
                        "status": status,
                    },
                )
                if span:
                    span.set_tag("status", status)
                    obs.tracer.finish_span(span)

            # 上报：任务结束（Registry）
            try:
                duration_ms = (time.time() - start_time) * 1000.0
                # success 看 result: 含 error 或 dead_lettered 都是失败
                success = (
                    result is not None
                    and not (isinstance(result, dict) and (result.get("error") or result.get("dead_lettered")))
                )
                get_capability_registry().record_task_ended(
                    self.agent_id, success=success, duration_ms=duration_ms
                )
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Task execution outer error: {e}")
            self._task_results[task_id] = {"error": str(e)}
            await self.send(
                receiver_id=message.sender_id,
                content={"error": str(e)},
                msg_type=MessageType.ERROR,
                correlation_id=message.msg_id
            )

        finally:
            self.set_state("current_task", None)

    def _send_to_dlq(self, task_id: str, error: Exception, attempts: int):
        """把失败的任务送进 DLQ"""
        try:
            from reliability import get_reliability
            rl = get_reliability()
            rl.dlq.add(
                msg_id=task_id,
                payload={"worker": self.agent_id, "name": self.name},
                reason="task_exhausted_retries",
                attempts=attempts,
                last_error=str(error),
            )
        except Exception as e:
            logger.warning(f"Failed to dead-letter task: {e}")
    
    async def _execute(self, description: str, data: Dict = None) -> Any:
        """执行任务（调用执行器）"""
        if self._executor:
            return await self._executor(description, data or {})
        return f"Task completed: {description[:50]}..."
    
    def get_result(self, task_id: str) -> Optional[Any]:
        """获取任务结果"""
        return self._task_results.get(task_id)


class SupervisorAgent(BaseAgent):
    """
    Supervisor Agent
    
    负责任务分解和结果聚合
    """
    
    def __init__(
        self,
        agent_id: str = None,
        name: str = None,
        model = None,
        orchestration_mode: OrchestrationMode = OrchestrationMode.SUPERVISOR
    ):
        super().__init__(
            agent_id=agent_id,
            name=name or "Supervisor",
            role=AgentRole.SUPERVISOR,
            capabilities=["coordination", "task_decomposition", "result_aggregation"]
        )
        
        self.model = model
        self.orchestration_mode = orchestration_mode
        
        # 编排器
        self._orchestrator = AgentOrchestrator(
            supervisor_id=self.agent_id,
            supervisor_name=self.name,
            model=model
        )
        
        # 注册处理器
        self._register_handlers()
    
    @property
    def orchestrator(self) -> AgentOrchestrator:
        return self._orchestrator
    
    def _register_handlers(self):
        """注册处理器"""
        
        @self.on(MessageType.REQUEST)
        async def handle_request(message: Message):
            """处理协调请求"""
            result = await self._orchestrate(message.content)
            
            await self.send(
                receiver_id=message.sender_id,
                content=result,
                msg_type=MessageType.RESPONSE,
                correlation_id=message.msg_id
            )
    
    async def _orchestrate(self, task: str) -> str:
        """执行编排"""
        if self.orchestration_mode == OrchestrationMode.SUPERVISOR:
            return await self._orchestrator.orchestrate_supervisor(task)
        elif self.orchestration_mode == OrchestrationMode.PARALLEL:
            result = await self._orchestrator.orchestrate_parallel(task)
            return str(result)
        elif self.orchestration_mode == OrchestrationMode.SEQUENTIAL:
            return await self._orchestrator.orchestrate_sequential(task)
        else:
            return "Unsupported orchestration mode"
    
    async def coordinate(self, user_input: str) -> str:
        """协调处理用户输入"""
        return await self._orchestrate(user_input)
