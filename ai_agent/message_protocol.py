"""
多 Agent 消息传递协议模块

提供结构化的消息格式、规范化的通信协议，
支持同步/异步消息、消息优先级、消息确认机制。
"""

import uuid
import json
import asyncio
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Union
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """消息类型枚举"""
    # 基础消息类型
    TEXT = "text"                      # 文本消息
    TASK = "task"                      # 任务消息
    RESULT = "result"                  # 结果消息
    ERROR = "error"                    # 错误消息
    
    # Agent 间通信
    REQUEST = "request"                # 请求消息
    RESPONSE = "response"              # 响应消息
    QUERY = "query"                    # 查询消息
    BROADCAST = "broadcast"            # 广播消息
    
    # 协调消息
    INVITE = "invite"                  # 邀请参与任务
    ACCEPT = "accept"                  # 接受邀请
    REJECT = "reject"                  # 拒绝邀请
    DELEGATE = "delegate"              # 委托任务
    TRANSFER = "transfer"              # 转移控制权
    
    # 状态同步
    HEARTBEAT = "heartbeat"            # 心跳消息
    STATE_SYNC = "state_sync"          # 状态同步
    READY = "ready"                    # 就绪消息
    
    # 协商消息
    PROPOSE = "propose"                # 提出方案
    COUNTER = "counter"                # 反提议
    ACCEPT_OFFER = "accept_offer"      # 接受方案
    REJECT_OFFER = "reject_offer"      # 拒绝方案
    NEGOTIATE = "negotiate"            # 协商请求
    COMPROMISE = "compromise"          # 折中方案
    NEGOTIATION_END = "negotiation_end"  # 协商结束

    # 竞争/竞价消息
    BID = "bid"                        # 竞价
    BID_REQUEST = "bid_request"        # 竞价请求
    AWARD = "award"                    # 中标通知
    AUCTION_RESULT = "auction_result"  # 拍卖结果

    # 系统消息
    ACK = "ack"                        # 确认消息
    NACK = "nack"                      # 拒绝确认
    TIMEOUT = "timeout"                # 超时消息
    TERMINATE = "terminate"            # 终止消息


class MessagePriority(Enum):
    """消息优先级"""
    CRITICAL = 0   # 关键消息（最高优先级）
    HIGH = 1       # 高优先级
    NORMAL = 2     # 普通优先级
    LOW = 3        # 低优先级
    BACKGROUND = 4 # 后台任务（最低优先级）


class AgentRole(Enum):
    """Agent 角色"""
    SUPERVISOR = "supervisor"    # 监督者 - 协调其他 Agent
    WORKER = "worker"            # 工作者 - 执行具体任务
    SPECIALIST = "specialist"    # 专家 - 特定领域专家
    COORDINATOR = "coordinator"  # 协调者 - 协调多个 Agent


@dataclass
class AgentInfo:
    """Agent 信息"""
    agent_id: str
    name: str
    role: AgentRole
    capabilities: List[str] = field(default_factory=list)
    status: str = "idle"  # idle, busy, offline
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role.value,
            "capabilities": self.capabilities,
            "status": self.status,
            "metadata": self.metadata
        }


@dataclass
class Message:
    """结构化消息"""
    # 必需字段
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    msg_type: MessageType = MessageType.TEXT
    sender_id: str = ""
    receiver_id: str = ""  # 空字符串表示广播
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # 消息内容
    content: Any = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    # 多模态附件（P2-5）
    attachments: List[Any] = field(default_factory=list)

    # 消息控制
    priority: MessagePriority = MessagePriority.NORMAL
    correlation_id: str = ""  # 用于关联请求和响应
    
    # 可靠性
    ack_required: bool = False
    ttl: int = 300  # 生存时间（秒）
    retry_count: int = 0
    max_retries: int = 3
    
    # 状态
    delivered: bool = False
    acknowledged: bool = False
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "msg_id": self.msg_id,
            "msg_type": self.msg_type.value if isinstance(self.msg_type, MessageType) else self.msg_type,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "timestamp": self.timestamp,
            "content": self.content,
            "payload": self.payload,
            "attachments": [
                a.to_dict() if hasattr(a, "to_dict") else a
                for a in self.attachments
            ],
            "priority": self.priority.value if isinstance(self.priority, MessagePriority) else self.priority,
            "correlation_id": self.correlation_id,
            "ack_required": self.ack_required,
            "ttl": self.ttl,
            "retry_count": self.retry_count,
            "delivered": self.delivered,
            "acknowledged": self.acknowledged
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Message':
        """从字典创建消息"""
        msg_type = MessageType(data.get("msg_type", "text"))
        priority = MessagePriority(data.get("priority", 2))
        
        return cls(
            msg_id=data.get("msg_id", str(uuid.uuid4())),
            msg_type=msg_type,
            sender_id=data.get("sender_id", ""),
            receiver_id=data.get("receiver_id", ""),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            content=data.get("content", ""),
            payload=data.get("payload", {}),
            priority=priority,
            correlation_id=data.get("correlation_id", ""),
            ack_required=data.get("ack_required", False),
            ttl=data.get("ttl", 300),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            delivered=data.get("delivered", False),
            acknowledged=data.get("acknowledged", False)
        )
    
    def is_expired(self) -> bool:
        """检查消息是否过期"""
        try:
            msg_time = datetime.fromisoformat(self.timestamp)
            elapsed = (datetime.now() - msg_time).total_seconds()
            return elapsed > self.ttl
        except:
            return False
    
    def create_response(self, content: Any = "", **kwargs) -> 'Message':
        """创建响应消息"""
        return Message(
            msg_type=MessageType.RESPONSE,
            sender_id=self.receiver_id,
            receiver_id=self.sender_id,
            content=content,
            correlation_id=self.msg_id,
            priority=self.priority,
            **kwargs
        )
    
    def create_ack(self) -> 'Message':
        """创建确认消息"""
        return Message(
            msg_type=MessageType.ACK,
            sender_id=self.receiver_id,
            receiver_id=self.sender_id,
            content="ACK",
            correlation_id=self.msg_id,
            priority=MessagePriority.HIGH
        )


@dataclass
class TaskMessage(Message):
    """任务消息（扩展自 Message）"""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_type: str = ""  # task_type: research, coding, review, etc.
    task_data: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)  # 依赖的任务 ID
    timeout: int = 300  # 任务超时时间（秒）
    
    def to_dict(self) -> Dict:
        base = super().to_dict()
        base.update({
            "task_id": self.task_id,
            "task_type": self.task_type,
            "task_data": self.task_data,
            "dependencies": self.dependencies,
            "timeout": self.timeout
        })
        return base
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TaskMessage':
        """从字典创建任务消息"""
        msg = super().from_dict(data)
        return cls(
            msg_id=msg.msg_id,
            msg_type=msg.msg_type,
            sender_id=msg.sender_id,
            receiver_id=msg.receiver_id,
            timestamp=msg.timestamp,
            content=msg.content,
            payload=msg.payload,
            priority=msg.priority,
            correlation_id=msg.correlation_id,
            ack_required=msg.ack_required,
            ttl=msg.ttl,
            retry_count=msg.retry_count,
            max_retries=msg.max_retries,
            delivered=msg.delivered,
            acknowledged=msg.acknowledged,
            task_id=data.get("task_id", str(uuid.uuid4())),
            task_type=data.get("task_type", ""),
            task_data=data.get("task_data", {}),
            dependencies=data.get("dependencies", []),
            timeout=data.get("timeout", 300)
        )


class MessageProtocol:
    """
    消息协议处理器
    
    提供消息的创建、验证、路由、序列化等功能
    """
    
    # 消息类型与接收者模式映射
    ROUTING_PATTERNS = {
        MessageType.BROADCAST: "*",  # 广播给所有 Agent
        MessageType.HEARTBEAT: "system",  # 心跳给系统
        MessageType.STATE_SYNC: "coordinator",  # 状态同步给协调者
    }
    
    @staticmethod
    def create_message(
        msg_type: Union[MessageType, str],
        sender_id: str,
        content: Any,
        receiver_id: str = "",
        priority: Union[MessagePriority, int] = MessagePriority.NORMAL,
        **kwargs
    ) -> Message:
        """创建消息的工厂方法"""
        if isinstance(msg_type, str):
            msg_type = MessageType(msg_type)
        if isinstance(priority, int):
            priority = MessagePriority(priority)
        
        return Message(
            msg_type=msg_type,
            sender_id=sender_id,
            receiver_id=receiver_id,
            content=content,
            priority=priority,
            **kwargs
        )
    
    @staticmethod
    def create_task_message(
        sender_id: str,
        task_type: str,
        task_data: Dict[str, Any],
        receiver_id: str = "",
        dependencies: List[str] = None,
        timeout: int = 300,
        priority: Union[MessagePriority, int] = MessagePriority.NORMAL,
        **kwargs
    ) -> TaskMessage:
        """创建任务消息的工厂方法"""
        if isinstance(priority, int):
            priority = MessagePriority(priority)
        
        return TaskMessage(
            msg_type=MessageType.TASK,
            sender_id=sender_id,
            receiver_id=receiver_id,
            content=f"Task: {task_type}",
            task_id=str(uuid.uuid4()),
            task_type=task_type,
            task_data=task_data,
            dependencies=dependencies or [],
            timeout=timeout,
            priority=priority,
            **kwargs
        )
    
    @staticmethod
    def validate_message(message: Message) -> tuple[bool, str]:
        """验证消息格式"""
        if not message.msg_id:
            return False, "消息 ID 不能为空"
        
        if not message.sender_id:
            return False, "发送者 ID 不能为空"
        
        if message.msg_type == MessageType.RESPONSE and not message.correlation_id:
            return False, "响应消息必须包含 correlation_id"
        
        if message.retry_count > message.max_retries:
            return False, f"重试次数超过限制 ({message.max_retries})"
        
        return True, "OK"
    
    @staticmethod
    def serialize_message(message: Message) -> str:
        """序列化消息为 JSON"""
        return json.dumps(message.to_dict(), ensure_ascii=False)
    
    @staticmethod
    def deserialize_message(data: str) -> Message:
        """从 JSON 反序列化消息"""
        try:
            msg_dict = json.loads(data)
            if "task_id" in msg_dict:
                return TaskMessage.from_dict(msg_dict)
            return Message.from_dict(msg_dict)
        except Exception as e:
            logger.error(f"Failed to deserialize message: {e}")
            raise ValueError(f"Invalid message format: {e}")
    
    @staticmethod
    def get_routing_target(message: Message) -> str:
        """获取消息路由目标"""
        if message.receiver_id:
            return message.receiver_id
        return MessageProtocol.ROUTING_PATTERNS.get(
            message.msg_type, 
            message.receiver_id
        )


class ConversationContext:
    """
    对话上下文管理器
    
    管理 Agent 之间的对话历史和上下文
    """
    
    def __init__(self, conversation_id: str = None):
        self.conversation_id = conversation_id or str(uuid.uuid4())
        self.messages: List[Message] = []
        self.participants: Dict[str, AgentInfo] = {}
        self.metadata: Dict[str, Any] = {}
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
    
    def add_message(self, message: Message):
        """添加消息到对话"""
        self.messages.append(message)
        self.updated_at = datetime.now()
    
    def get_messages(
        self, 
        participant_id: str = None,
        msg_type: MessageType = None,
        limit: int = 100
    ) -> List[Message]:
        """获取消息历史"""
        filtered = self.messages
        
        if participant_id:
            filtered = [
                m for m in filtered 
                if m.sender_id == participant_id or m.receiver_id == participant_id
            ]
        
        if msg_type:
            filtered = [m for m in filtered if m.msg_type == msg_type]
        
        return filtered[-limit:]
    
    def get_thread(self, correlation_id: str) -> List[Message]:
        """获取同一线程的消息（通过 correlation_id）"""
        return [
            m for m in self.messages 
            if m.correlation_id == correlation_id or m.msg_id == correlation_id
        ]
    
    def add_participant(self, agent_info: AgentInfo):
        """添加参与者"""
        self.participants[agent_info.agent_id] = agent_info
    
    def remove_participant(self, agent_id: str):
        """移除参与者"""
        if agent_id in self.participants:
            del self.participants[agent_id]
    
    def get_context_summary(self, max_messages: int = 50) -> str:
        """生成上下文摘要"""
        recent = self.messages[-max_messages:]
        summary_parts = [f"Conversation: {self.conversation_id}"]
        
        for msg in recent:
            sender = msg.sender_id[:8] if len(msg.sender_id) > 8 else msg.sender_id
            summary_parts.append(f"[{msg.msg_type.value}] {sender}: {msg.content[:100]}")
        
        return "\n".join(summary_parts)


class MessageBuilder:
    """消息构建器 - 链式调用创建复杂消息"""
    
    def __init__(self, sender_id: str):
        self._sender_id = sender_id
        self._msg_type = MessageType.TEXT
        self._receiver_id = ""
        self._content = ""
        self._payload = {}
        self._priority = MessagePriority.NORMAL
        self._correlation_id = ""
        self._ack_required = False
        self._ttl = 300
    
    def type(self, msg_type: MessageType) -> 'MessageBuilder':
        self._msg_type = msg_type
        return self
    
    def to(self, receiver_id: str) -> 'MessageBuilder':
        self._receiver_id = receiver_id
        return self
    
    def content(self, content: Any) -> 'MessageBuilder':
        self._content = content
        return self
    
    def payload(self, **kwargs) -> 'MessageBuilder':
        self._payload.update(kwargs)
        return self
    
    def priority(self, priority: MessagePriority) -> 'MessageBuilder':
        self._priority = priority
        return self
    
    def in_reply_to(self, correlation_id: str) -> 'MessageBuilder':
        self._correlation_id = correlation_id
        return self
    
    def require_ack(self, ack: bool = True) -> 'MessageBuilder':
        self._ack_required = ack
        return self
    
    def ttl(self, seconds: int) -> 'MessageBuilder':
        self._ttl = seconds
        return self
    
    def build(self) -> Message:
        """构建消息"""
        return Message(
            msg_type=self._msg_type,
            sender_id=self._sender_id,
            receiver_id=self._receiver_id,
            content=self._content,
            payload=self._payload,
            priority=self._priority,
            correlation_id=self._correlation_id,
            ack_required=self._ack_required,
            ttl=self._ttl
        )
    
    def build_task(self) -> TaskMessage:
        """构建任务消息"""
        return TaskMessage(
            msg_type=MessageType.TASK,
            sender_id=self._sender_id,
            receiver_id=self._receiver_id,
            content=self._content,
            payload=self._payload,
            priority=self._priority,
            correlation_id=self._correlation_id,
            ack_required=self._ack_required,
            ttl=self._ttl,
            task_type=self._payload.get("task_type", ""),
            task_data=self._payload.get("task_data", {})
        )


# 全局消息协议实例
_protocol = MessageProtocol()


def create_message(
    msg_type: Union[MessageType, str],
    sender_id: str,
    content: Any,
    receiver_id: str = "",
    priority: Union[MessagePriority, int] = MessagePriority.NORMAL,
    **kwargs
) -> Message:
    """创建消息的快捷函数"""
    return _protocol.create_message(msg_type, sender_id, content, receiver_id, priority, **kwargs)


def create_task(
    sender_id: str,
    task_type: str,
    task_data: Dict[str, Any],
    receiver_id: str = "",
    dependencies: List[str] = None,
    timeout: int = 300,
    priority: Union[MessagePriority, int] = MessagePriority.NORMAL
) -> TaskMessage:
    """创建任务消息的快捷函数"""
    return _protocol.create_task_message(
        sender_id, task_type, task_data, receiver_id, dependencies, timeout, priority
    )


def validate_message(message: Message) -> tuple[bool, str]:
    """验证消息的快捷函数"""
    return _protocol.validate_message(message)


def serialize(message: Message) -> str:
    """序列化消息的快捷函数"""
    return _protocol.serialize_message(message)


def deserialize(data: str) -> Message:
    """反序列化消息的快捷函数"""
    return _protocol.deserialize_message(data)
