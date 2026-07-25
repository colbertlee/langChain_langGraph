"""
Agent 消息总线

提供异步消息传递、消息路由、订阅/发布机制，
支持点对点和广播消息传递。
"""

import asyncio
import uuid
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Type
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

from message_protocol import (
    Message, MessageType, MessagePriority, AgentInfo, AgentRole,
    TaskMessage, ConversationContext
)

logger = logging.getLogger(__name__)


class DeliveryStatus(Enum):
    """消息投递状态"""
    PENDING = "pending"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class MessageEnvelope:
    """消息信封 - 包含消息及其元数据"""
    message: Message
    delivery_status: DeliveryStatus = DeliveryStatus.PENDING
    delivery_attempts: int = 0
    delivered_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    error: Optional[str] = None
    
    def mark_delivered(self):
        self.delivery_status = DeliveryStatus.DELIVERED
        self.delivered_at = datetime.now()
    
    def mark_acknowledged(self):
        self.delivery_status = DeliveryStatus.ACKNOWLEDGED
        self.acknowledged_at = datetime.now()
    
    def mark_failed(self, error: str):
        self.delivery_status = DeliveryStatus.FAILED
        self.error = error


class MessageHandler:
    """消息处理器基类"""
    
    def __init__(self, handler_id: str = None):
        self.handler_id = handler_id or str(uuid.uuid4())
        self._handlers: Dict[MessageType, List[Callable]] = defaultdict(list)
    
    def register(self, msg_type: MessageType, handler: Callable):
        """注册消息处理器"""
        self._handlers[msg_type].append(handler)
        logger.debug(f"Registered handler for {msg_type.value}: {handler}")
    
    def unregister(self, msg_type: MessageType, handler: Callable):
        """取消注册消息处理器"""
        if handler in self._handlers[msg_type]:
            self._handlers[msg_type].remove(handler)
    
    async def handle(self, message: Message) -> Any:
        """处理消息"""
        handlers = self._handlers.get(message.msg_type, [])
        if not handlers:
            logger.warning(f"No handler for message type: {message.msg_type}")
            return None
        
        results = []
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(message)
                else:
                    result = handler(message)
                results.append(result)
            except Exception as e:
                logger.error(f"Handler error: {e}")
                results.append({"error": str(e)})
        
        return results[0] if len(results) == 1 else results


class MessageBus:
    """
    Agent 消息总线
    
    核心组件，负责：
    - 消息路由（点对点、广播）
    - 消息订阅/发布
    - 消息队列管理
    - 消息确认机制
    - 异步消息处理
    """
    
    _instance = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return

        self._initialized = True

        # Agent 注册表
        self._agents: Dict[str, 'BaseAgent'] = {}
        self._agent_info: Dict[str, AgentInfo] = {}

        # 消息队列（按优先级）
        self._queues: Dict[MessagePriority, asyncio.PriorityQueue] = {
            priority: asyncio.PriorityQueue()
            for priority in MessagePriority
        }

        # 投递状态追踪
        self._delivery_status: Dict[str, MessageEnvelope] = {}

        # 订阅者
        self._subscribers: Dict[str, Set[str]] = defaultdict(set)  # topic -> agent_ids
        self._type_subscribers: Dict[MessageType, Set[str]] = defaultdict(set)

        # 回调处理器
        self._callbacks: Dict[str, Callable] = {}  # correlation_id -> callback

        # 消息历史
        self._message_history: List[Message] = []
        self._max_history = 1000

        # 运行状态
        self._running = False
        self._processing_task: Optional[asyncio.Task] = None

        # Agent 信息更新回调
        self._agent_update_callbacks: List[Callable] = []

        # 可靠性层（默认不启用，由 enable_reliability() 显式开启）
        self._reliability = None
        self._reliability_enabled = False

        # 可观测性层（默认不启用，由 enable_observability() 显式开启）
        self._observability = None
        self._observability_enabled = False

        # 权限守卫（默认按需加载，不强制）
        self._permission_guard = None
        self._permission_enforced = False

        logger.info("MessageBus initialized")

    def enable_reliability(self, reliability_layer=None):
        """启用可靠性机制（重试 + 断路器 + DLQ）"""
        from reliability import get_reliability
        self._reliability = reliability_layer or get_reliability()
        self._reliability_enabled = True
        logger.info("MessageBus reliability layer enabled")

    def disable_reliability(self):
        """关闭可靠性机制"""
        self._reliability_enabled = False
        logger.info("MessageBus reliability layer disabled")

    def enable_observability(self, observability_layer=None):
        """启用可观测性机制（指标 + 链路追踪 + 事件流）"""
        from observability import get_observability
        self._observability = observability_layer or get_observability()
        self._observability_enabled = True
        logger.info("MessageBus observability layer enabled")

    def disable_observability(self):
        """关闭可观测性"""
        self._observability_enabled = False
        logger.info("MessageBus observability layer disabled")

    def enable_permission(self, permission_guard=None, enforce: bool = True):
        """启用权限拦截（默认开启强制模式）

        Args:
            permission_guard: PermissionGuard 实例（None 则用全局单例）
            enforce: 是否真正拦截；False 仅记录不拒绝
        """
        from permission import get_permission_guard
        self._permission_guard = permission_guard or get_permission_guard()
        self._permission_enforced = enforce
        logger.info(f"MessageBus permission enabled (enforce={enforce})")

    def disable_permission(self):
        """关闭权限拦截"""
        self._permission_enforced = False
    
    @classmethod
    def get_instance(cls) -> 'MessageBus':
        """获取单例实例"""
        return cls()
    
    # ==========================================
    # Agent 注册与管理
    # ==========================================
    
    def register_agent(self, agent: 'BaseAgent', agent_info: AgentInfo = None):
        """注册 Agent"""
        if agent_info is None:
            agent_info = AgentInfo(
                agent_id=agent.agent_id,
                name=agent.name,
                role=AgentRole.WORKER,
                capabilities=agent.capabilities
            )
        
        self._agents[agent.agent_id] = agent
        self._agent_info[agent.agent_id] = agent_info
        
        # 注册该 Agent 的能力到对应的订阅者
        for capability in agent.capabilities:
            self._subscribers[capability].add(agent.agent_id)
        
        logger.info(f"Agent registered: {agent.agent_id} ({agent.name})")
        
        # 触发更新回调
        self._notify_agent_update("registered", agent.agent_id)
    
    def unregister_agent(self, agent_id: str):
        """注销 Agent"""
        if agent_id in self._agents:
            agent = self._agents[agent_id]
            
            # 移除能力订阅
            for capability in agent.capabilities:
                self._subscribers[capability].discard(agent_id)
            
            # 移除消息类型订阅
            for msg_type in self._type_subscribers:
                self._type_subscribers[msg_type].discard(agent_id)
            
            del self._agents[agent_id]
            del self._agent_info[agent_id]
            
            logger.info(f"Agent unregistered: {agent_id}")
            self._notify_agent_update("unregistered", agent_id)
    
    def get_agent(self, agent_id: str) -> Optional['BaseAgent']:
        """获取 Agent 实例"""
        return self._agents.get(agent_id)
    
    def get_agent_info(self, agent_id: str) -> Optional[AgentInfo]:
        """获取 Agent 信息"""
        return self._agent_info.get(agent_id)
    
    def list_agents(self, role: AgentRole = None, capability: str = None) -> List[AgentInfo]:
        """列出 Agent"""
        agents = list(self._agent_info.values())
        
        if role:
            agents = [a for a in agents if a.role == role]
        
        if capability:
            agents = [a for a in agents if capability in a.capabilities]
        
        return agents
    
    def update_agent_status(self, agent_id: str, status: str):
        """更新 Agent 状态"""
        if agent_id in self._agent_info:
            self._agent_info[agent_id].status = status
            self._notify_agent_update("status_changed", agent_id, {"status": status})
    
    def on_agent_update(self, callback: Callable):
        """注册 Agent 更新回调"""
        self._agent_update_callbacks.append(callback)
    
    def _notify_agent_update(self, event: str, agent_id: str, data: Dict = None):
        """通知 Agent 更新"""
        for callback in self._agent_update_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(event, agent_id, data))
                else:
                    callback(event, agent_id, data)
            except Exception as e:
                logger.error(f"Agent update callback error: {e}")
    
    # ==========================================
    # 消息订阅
    # ==========================================
    
    def subscribe(self, agent_id: str, *topics: str):
        """订阅主题"""
        for topic in topics:
            self._subscribers[topic].add(agent_id)
            logger.debug(f"Agent {agent_id} subscribed to {topic}")
    
    def unsubscribe(self, agent_id: str, *topics: str):
        """取消订阅主题"""
        for topic in topics:
            self._subscribers[topic].discard(agent_id)
    
    def subscribe_type(self, agent_id: str, *msg_types: MessageType):
        """订阅消息类型"""
        for msg_type in msg_types:
            self._type_subscribers[msg_type].add(agent_id)
    
    def unsubscribe_type(self, agent_id: str, *msg_types: MessageType):
        """取消订阅消息类型"""
        for msg_type in msg_types:
            self._type_subscribers[msg_type].discard(agent_id)
    
    # ==========================================
    # 消息发送
    # ==========================================
    
    async def send(self, message: Message, timeout: float = 30.0) -> bool:
        """
        发送消息（异步）

        Args:
            message: 要发送的消息
            timeout: 超时时间（秒）

        Returns:
            bool: 是否发送成功
        """
        # 权限检查
        if self._permission_enforced and self._permission_guard:
            try:
                decision = self._permission_guard.check_send(
                    message.sender_id, message.receiver_id
                )
                if not decision.granted:
                    logger.warning(
                        f"[Permission DENIED] {message.sender_id} -> {message.receiver_id}: "
                        f"{decision.reason}"
                    )
                    if self._reliability_enabled and self._reliability:
                        self._reliability.dlq.add(
                            msg_id=message.msg_id,
                            payload={
                                "sender": message.sender_id,
                                "receiver": message.receiver_id,
                                "reason": decision.reason,
                            },
                            reason="permission_denied",
                            attempts=0,
                        )
                    return False
            except Exception as e:
                logger.warning(f"Permission check error: {e}")

        # 可观测性：开启一个 span
        obs_span = None
        if self._observability_enabled and self._observability:
            obs_span = self._observability.tracer.start_span(
                "msg.send",
                tags={
                    "msg_id": message.msg_id,
                    "msg_type": message.msg_type.value,
                    "sender": message.sender_id,
                    "receiver": message.receiver_id,
                },
            )
            self._observability.msg_sent_total.inc(msg_type=message.msg_type.value)
            self._observability.publish_event(
                "msg_sent",
                source="message_bus",
                trace_id=obs_span.trace_id,
                payload={
                    "msg_id": message.msg_id,
                    "msg_type": message.msg_type.value,
                    "sender": message.sender_id,
                    "receiver": message.receiver_id,
                },
            )

        try:
            # 验证消息
            from message_protocol import validate_message
            valid, reason = validate_message(message)
            if not valid:
                logger.error(f"Invalid message: {reason}")
                if self._reliability_enabled and self._reliability:
                    self._reliability.dlq.add(
                        msg_id=message.msg_id,
                        payload={"msg_type": message.msg_type.value, "content": str(message.content)[:200]},
                        reason=f"invalid: {reason}",
                        attempts=0,
                    )
                if obs_span:
                    self._observability.tracer.finish_span(obs_span, status="error", error=f"invalid: {reason}")
                return False

            # 记录消息历史
            self._add_to_history(message)

            # 创建消息信封
            envelope = MessageEnvelope(message=message)
            self._delivery_status[message.msg_id] = envelope

            # 确定接收者
            receivers = self._get_receivers(message)

            if not receivers:
                logger.warning(f"No receivers for message: {message.msg_id}")
                envelope.mark_failed("No receivers")
                if self._reliability_enabled and self._reliability:
                    self._reliability.dlq.add(
                        msg_id=message.msg_id,
                        payload={"msg_type": message.msg_type.value, "content": str(message.content)[:200]},
                        reason="no_receivers",
                        attempts=0,
                    )
                return False

            # 投递消息（启用可靠性时使用断路器）
            delivered = False
            for receiver_id in receivers:
                agent = self._agents.get(receiver_id)
                if not agent:
                    continue
                try:
                    if self._reliability_enabled and self._reliability:
                        # 用可靠性策略包装投递
                        op_name = f"send:{receiver_id}"
                        async def _do_deliver(a=agent, m=message, t=timeout):
                            await asyncio.wait_for(a.receive(m), timeout=t)

                        delivered_ok = await self._reliability.call_with_reliability(
                            op_name, _do_deliver
                        )
                        delivered = delivered or bool(delivered_ok)
                        logger.debug(f"Message {message.msg_id} delivered to {receiver_id} (with reliability)")
                    else:
                        # 原始路径
                        await asyncio.wait_for(
                            agent.receive(message),
                            timeout=timeout
                        )
                        delivered = True
                        logger.debug(f"Message {message.msg_id} delivered to {receiver_id}")
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout delivering to {receiver_id}")
                    if self._reliability_enabled and self._reliability:
                        self._reliability.dlq.add(
                            msg_id=message.msg_id,
                            payload={"receiver": receiver_id, "reason": "timeout"},
                            reason="delivery_timeout",
                            attempts=self._reliability.retry_policy.max_attempts,
                        )
                except Exception as e:
                    logger.error(f"Error delivering to {receiver_id}: {e}")
                    if self._reliability_enabled and self._reliability:
                        self._reliability.dlq.add(
                            msg_id=message.msg_id,
                            payload={"receiver": receiver_id, "error": str(e)[:200]},
                            reason="delivery_error",
                            attempts=self._reliability.retry_policy.max_attempts,
                            last_error=str(e),
                        )

            if delivered:
                envelope.mark_delivered()

                # 如果需要确认，发送 ACK
                if message.ack_required:
                    ack = message.create_ack()
                    await self.send(ack, timeout=5.0)

                # 可观测性：success
                if self._observability_enabled and self._observability:
                    self._observability.msg_delivered_total.inc(msg_type=message.msg_type.value)
                    self._observability.publish_event(
                        "msg_delivered",
                        source="message_bus",
                        trace_id=obs_span.trace_id if obs_span else None,
                        payload={"msg_id": message.msg_id, "msg_type": message.msg_type.value},
                    )
                    if obs_span:
                        self._observability.tracer.finish_span(obs_span)
            else:
                envelope.mark_failed("Delivery failed")
                # 可观测性：failure
                if self._observability_enabled and self._observability:
                    self._observability.msg_failed_total.inc(msg_type=message.msg_type.value)
                    self._observability.publish_event(
                        "msg_delivery_failed",
                        source="message_bus",
                        trace_id=obs_span.trace_id if obs_span else None,
                        payload={"msg_id": message.msg_id, "msg_type": message.msg_type.value},
                    )
                    if obs_span:
                        self._observability.tracer.finish_span(obs_span, status="error", error="delivery_failed")

            return delivered

        except Exception as e:
            logger.error(f"Send error: {e}")
            if self._reliability_enabled and self._reliability:
                self._reliability.dlq.add(
                    msg_id=message.msg_id,
                    payload={"error": str(e)[:200]},
                    reason="unexpected_error",
                    attempts=0,
                    last_error=str(e),
                )
            if obs_span:
                self._observability.tracer.finish_span(obs_span, status="error", error=str(e))
            return False
    
    def send_sync(self, message: Message) -> bool:
        """同步发送消息（包装为事件循环）"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果已经在事件循环中，创建一个新任务
                asyncio.create_task(self.send(message))
                return True
            else:
                return loop.run_until_complete(self.send(message))
        except RuntimeError:
            # 如果没有事件循环，创建并运行
            return asyncio.run(self.send(message))
    
    async def broadcast(self, message: Message, topic: str = None):
        """广播消息"""
        # 设置接收者为广播标识
        original_receiver = message.receiver_id
        message.receiver_id = "*"
        
        # 获取所有在线 Agent
        receivers = [
            agent_id for agent_id, info in self._agent_info.items()
            if info.status != "offline"
        ]
        
        # 如果有主题限制，过滤订阅者
        if topic:
            receivers = [
                r for r in receivers 
                if r in self._subscribers.get(topic, set())
            ]
        
        # 发送到所有接收者
        tasks = []
        for receiver_id in receivers:
            if receiver_id != message.sender_id:  # 不发给自己
                agent = self._agents.get(receiver_id)
                if agent:
                    tasks.append(agent.receive(message))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        message.receiver_id = original_receiver
    
    def _get_receivers(self, message: Message) -> List[str]:
        """获取消息接收者列表"""
        # 广播消息
        if message.receiver_id == "*" or message.msg_type == MessageType.BROADCAST:
            return [
                agent_id for agent_id, info in self._agent_info.items()
                if info.status != "offline" and agent_id != message.sender_id
            ]
        
        # 指定接收者
        if message.receiver_id:
            if message.receiver_id in self._agents:
                return [message.receiver_id]
            return []
        
        # 基于能力路由
        capability = message.payload.get("required_capability")
        if capability:
            return list(self._subscribers.get(capability, set()))
        
        # 基于消息类型订阅
        type_receivers = self._type_subscribers.get(message.msg_type, set())
        if type_receivers:
            return list(type_receivers)
        
        return []
    
    def _add_to_history(self, message: Message):
        """添加消息到历史"""
        self._message_history.append(message)
        if len(self._message_history) > self._max_history:
            self._message_history = self._message_history[-self._max_history:]
    
    # ==========================================
    # 消息回调
    # ==========================================
    
    def set_callback(self, correlation_id: str, callback: Callable):
        """设置消息回调（用于等待响应）"""
        self._callbacks[correlation_id] = callback
    
    def trigger_callback(self, correlation_id: str, response: Message):
        """触发回调"""
        callback = self._callbacks.pop(correlation_id, None)
        if callback:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(response))
                else:
                    callback(response)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    # ==========================================
    # 请求-响应模式
    # ==========================================
    
    async def request(
        self,
        sender_id: str,
        receiver_id: str,
        content: Any,
        timeout: float = 30.0,
        msg_type: MessageType = MessageType.REQUEST,
        **kwargs
    ) -> Optional[Message]:
        """
        发送请求并等待响应
        
        Args:
            sender_id: 发送者 ID
            receiver_id: 接收者 ID
            content: 请求内容
            timeout: 超时时间
            msg_type: 消息类型
        
        Returns:
            响应消息
        """
        request_id = str(uuid.uuid4())
        request = Message(
            msg_type=msg_type,
            sender_id=sender_id,
            receiver_id=receiver_id,
            content=content,
            correlation_id=request_id,
            ack_required=True,
            **kwargs
        )
        
        # 创建未来对象用于接收响应
        response_future: asyncio.Future = asyncio.get_event_loop().create_future()
        
        def response_handler(response: Message):
            if response.correlation_id == request_id:
                if not response_future.done():
                    response_future.set_result(response)
        
        # 设置回调
        self.set_callback(request_id, response_handler)
        
        # 发送请求
        await self.send(request, timeout=timeout)
        
        # 等待响应
        try:
            response = await asyncio.wait_for(response_future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            logger.warning(f"Request timeout: {request_id}")
            return None
    
    # ==========================================
    # 消息队列管理
    # ==========================================
    
    async def enqueue(self, message: Message):
        """将消息加入队列"""
        priority = message.priority.value if isinstance(message.priority, MessagePriority) else 2
        await self._queues[MessagePriority(priority)].put((priority, message))
    
    async def dequeue(self, priority: MessagePriority = None) -> Optional[Message]:
        """从队列取出消息"""
        if priority:
            try:
                _, message = await asyncio.wait_for(
                    self._queues[priority].get(),
                    timeout=0.1
                )
                return message
            except asyncio.TimeoutError:
                return None
        
        # 从高优先级到低优先级检查
        for p in sorted(MessagePriority, key=lambda x: x.value):
            try:
                _, message = await asyncio.wait_for(
                    self._queues[p].get(),
                    timeout=0.1
                )
                return message
            except asyncio.TimeoutError:
                continue
        
        return None
    
    def get_queue_size(self, priority: MessagePriority = None) -> int:
        """获取队列大小"""
        if priority:
            return self._queues[priority].qsize()
        return sum(q.qsize() for q in self._queues.values())
    
    # ==========================================
    # 对话上下文
    # ==========================================
    
    def create_conversation(self, participants: List[str] = None) -> ConversationContext:
        """创建对话上下文"""
        conversation = ConversationContext()
        
        if participants:
            for agent_id in participants:
                info = self._agent_info.get(agent_id)
                if info:
                    conversation.add_participant(info)
        
        return conversation
    
    # ==========================================
    # 消息历史
    # ==========================================
    
    def get_history(
        self,
        agent_id: str = None,
        msg_type: MessageType = None,
        limit: int = 100
    ) -> List[Message]:
        """获取消息历史"""
        history = self._message_history
        
        if agent_id:
            history = [
                m for m in history
                if m.sender_id == agent_id or m.receiver_id == agent_id or m.receiver_id == "*"
            ]
        
        if msg_type:
            history = [m for m in history if m.msg_type == msg_type]
        
        return history[-limit:]
    
    # ==========================================
    # 状态和统计
    # ==========================================
    
    def get_stats(self) -> Dict:
        """获取消息总线统计信息"""
        return {
            "total_agents": len(self._agents),
            "online_agents": sum(1 for a in self._agent_info.values() if a.status != "offline"),
            "total_messages": len(self._message_history),
            "queue_sizes": {p.value: self._queues[p].qsize() for p in MessagePriority},
            "delivery_stats": {
                msg_id: env.delivery_status.value
                for msg_id, env in self._delivery_status.items()
            }
        }
    
    def reset(self):
        """重置消息总线"""
        self._agents.clear()
        self._agent_info.clear()
        self._subscribers.clear()
        self._type_subscribers.clear()
        self._callbacks.clear()
        self._message_history.clear()
        self._delivery_status.clear()
        self._reliability = None
        self._reliability_enabled = False
        self._observability = None
        self._observability_enabled = False
        self._permission_guard = None
        self._permission_enforced = False

        for queue in self._queues.values():
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        
        logger.info("MessageBus reset")


# ==========================================
# BaseAgent 基类
# ==========================================

class BaseAgent:
    """
    Base Agent 基类
    
    所有 Agent 都应继承此类
    """
    
    def __init__(
        self,
        agent_id: str = None,
        name: str = None,
        role: AgentRole = AgentRole.WORKER,
        capabilities: List[str] = None
    ):
        self.agent_id = agent_id or str(uuid.uuid4())
        self.name = name or f"Agent-{self.agent_id[:8]}"
        self.role = role
        self.capabilities = capabilities or []
        
        # 消息处理
        self._handlers: Dict[MessageType, Callable] = {}
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        
        # 状态
        self._state: Dict[str, Any] = {}
        
        # 消息总线
        self._bus = MessageBus.get_instance()
        
        # 注册到消息总线
        self._bus.register_agent(self)
    
    @property
    def bus(self) -> MessageBus:
        return self._bus
    
    @property
    def state(self) -> Dict[str, Any]:
        return self._state
    
    def set_state(self, key: str, value: Any):
        """设置状态"""
        self._state[key] = value
        self._bus.update_agent_status(self.agent_id, self.get_status())
    
    def get_status(self) -> str:
        """获取 Agent 状态"""
        return "busy" if self._running else "idle"
    
    # ==========================================
    # 消息处理
    # ==========================================
    
    def on(self, msg_type: MessageType) -> Callable:
        """装饰器：注册消息处理器"""
        def decorator(handler: Callable) -> Callable:
            self._handlers[msg_type] = handler
            return handler
        return decorator
    
    async def receive(self, message: Message):
        """接收消息"""
        # 将消息加入队列
        await self._message_queue.put(message)
        
        # 如果正在运行，立即处理
        if self._running:
            await self._process_message(message)
    
    async def _process_message(self, message: Message):
        """处理消息"""
        handler = self._handlers.get(message.msg_type)
        
        if handler:
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(message)
                else:
                    result = handler(message)
                
                # 触发回调
                if message.correlation_id:
                    self._bus.trigger_callback(message.correlation_id, message)
                
                return result
            except Exception as e:
                logger.error(f"Message handler error: {e}")
                return None
        
        # 默认处理
        return await self._default_handler(message)
    
    async def _default_handler(self, message: Message):
        """默认消息处理器"""
        logger.debug(f"Agent {self.agent_id} received: {message.msg_type}")
    
    # ==========================================
    # 消息发送
    # ==========================================
    
    async def send(
        self,
        receiver_id: str,
        content: Any,
        msg_type: MessageType = MessageType.TEXT,
        **kwargs
    ) -> bool:
        """发送消息"""
        message = Message(
            msg_type=msg_type,
            sender_id=self.agent_id,
            receiver_id=receiver_id,
            content=content,
            **kwargs
        )
        return await self._bus.send(message)
    
    async def broadcast(self, content: Any, topic: str = None, **kwargs):
        """广播消息"""
        message = Message(
            msg_type=MessageType.BROADCAST,
            sender_id=self.agent_id,
            receiver_id="*",
            content=content,
            **kwargs
        )
        await self._bus.broadcast(message, topic)
    
    async def request(
        self,
        receiver_id: str,
        content: Any,
        timeout: float = 30.0,
        msg_type: MessageType = MessageType.REQUEST,
        **kwargs
    ) -> Optional[Message]:
        """发送请求并等待响应"""
        return await self._bus.request(
            self.agent_id,
            receiver_id,
            content,
            timeout,
            msg_type,
            **kwargs
        )
    
    # ==========================================
    # 生命周期
    # ==========================================
    
    async def start(self):
        """启动 Agent"""
        self._running = True
        self._bus.update_agent_status(self.agent_id, "idle")
        logger.info(f"Agent started: {self.agent_id}")
    
    async def stop(self):
        """停止 Agent"""
        self._running = False
        self._bus.update_agent_status(self.agent_id, "offline")
        self._bus.unregister_agent(self.agent_id)
        logger.info(f"Agent stopped: {self.agent_id}")
    
    async def run(self):
        """运行 Agent（处理消息循环）"""
        await self.start()
        
        try:
            while self._running:
                try:
                    message = await asyncio.wait_for(
                        self._message_queue.get(),
                        timeout=1.0
                    )
                    self._bus.update_agent_status(self.agent_id, "busy")
                    await self._process_message(message)
                    self._bus.update_agent_status(self.agent_id, "idle")
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Agent run error: {e}")
        finally:
            await self.stop()


def get_message_bus() -> MessageBus:
    """获取消息总线实例"""
    return MessageBus.get_instance()
