"""
Pub-Sub 场景示例：多智能体感知同步

展示如何在多智能体系统中使用发布-订阅模式
实现状态同步、任务招募、协作匹配等场景
"""

import asyncio
from typing import Dict, List, Set, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from message_protocol import (
    Message, MessageType, MessagePriority, AgentInfo, AgentRole,
    create_message
)
from message_bus import MessageBus, BaseAgent, get_message_bus


# ==========================================
# 场景 1: 多智能体感知同步
# ==========================================

class PerceptionSync:
    """
    感知同步系统
    
    Agent 通过订阅主题来感知系统状态变化
    """

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.subscribers: Dict[str, Set[str]] = {}
        
        # 定义感知主题
        self.topics = {
            "system.status": "系统状态变更",
            "task.added": "新任务加入",
            "task.completed": "任务完成",
            "task.failed": "任务失败",
            "resource.available": "资源可用",
            "resource.busy": "资源忙碌",
            "agent.online": "Agent 上线",
            "agent.offline": "Agent 离线",
            "alert.warning": "警告信息",
            "alert.critical": "紧急警报"
        }
        
        print("[PerceptionSync] 感知同步系统初始化")
        print(f"  可用主题: {list(self.topics.keys())}")

    def subscribe(self, agent_id: str, topics: List[str]):
        """订阅主题"""
        for topic in topics:
            if topic not in self.subscribers:
                self.subscribers[topic] = set()
            self.subscribers[topic].add(agent_id)
        
        print(f"[{agent_id}] 订阅主题: {topics}")

    def unsubscribe(self, agent_id: str, topics: List[str]):
        """取消订阅"""
        for topic in topics:
            if topic in self.subscribers and agent_id in self.subscribers[topic]:
                self.subscribers[topic].discard(agent_id)

    async def publish(self, topic: str, data: Dict):
        """发布事件"""
        if topic not in self.subscribers:
            print(f"[PerceptionSync] 主题 '{topic}' 无订阅者")
            return
        
        subscribers = self.subscribers[topic].copy()
        print(f"[PerceptionSync] 发布 '{topic}' 到 {len(subscribers)} 个订阅者")
        print(f"  数据: {data}")
        
        # 创建事件消息
        event_msg = create_message(
            msg_type=MessageType.BROADCAST,
            sender_id="system",
            receiver_id="*",
            content=f"事件: {topic}",
            payload={
                "topic": topic,
                "event_data": data,
                "timestamp": datetime.now().isoformat()
            }
        )
        
        # 广播给订阅者
        for subscriber_id in subscribers:
            agent = self.bus.get_agent(subscriber_id)
            if agent:
                await agent.receive(event_msg)

    def get_subscribers(self, topic: str) -> Set[str]:
        """获取主题订阅者"""
        return self.subscribers.get(topic, set())

    def list_all_subscriptions(self, agent_id: str) -> List[str]:
        """列出 Agent 的所有订阅"""
        subscriptions = []
        for topic, subscribers in self.subscribers.items():
            if agent_id in subscribers:
                subscriptions.append(topic)
        return subscriptions


class PerceptionAgent(BaseAgent):
    """具有感知能力的 Agent"""

    def __init__(self, agent_id: str, name: str, interests: List[str]):
        super().__init__(
            agent_id=agent_id,
            name=name,
            capabilities=["perception", "awareness"]
        )
        self.interests = interests  # Agent 感兴趣的主题
        self.received_events: List[Dict] = []
        self.perception_sync: PerceptionSync = None
        
        # 注册感知处理器
        @self.on(MessageType.BROADCAST)
        async def handle_broadcast(msg: Message):
            topic = msg.payload.get("topic", "")
            
            # 检查是否是自己感兴趣的主题
            if self._is_interested(topic):
                event_data = {
                    "topic": topic,
                    "data": msg.payload.get("event_data", {}),
                    "timestamp": msg.payload.get("timestamp", ""),
                    "received_at": datetime.now().isoformat()
                }
                self.received_events.append(event_data)
                
                print(f"[{self.name}] 感知到事件: {topic}")
                print(f"  数据: {event_data['data']}")
                
                # 触发回调
                await self._trigger_event_callback(topic, event_data)
        
        self._event_callbacks: Dict[str, Callable] = {}

    def _is_interested(self, topic: str) -> bool:
        """检查是否对主题感兴趣"""
        for interest in self.interests:
            if interest.endswith("*"):
                # 通配符匹配
                prefix = interest[:-1]
                if topic.startswith(prefix):
                    return True
            elif interest == topic:
                return True
        return False

    def register_callback(self, topic: str, callback: Callable):
        """注册事件回调"""
        self._event_callbacks[topic] = callback

    async def _trigger_event_callback(self, topic: str, event_data: Dict):
        """触发事件回调"""
        callback = self._event_callbacks.get(topic)
        if callback:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event_data)
                else:
                    callback(event_data)
            except Exception as e:
                print(f"[{self.name}] 回调错误: {e}")


# ==========================================
# 场景 2: 任务招募与协作匹配
# ==========================================

class TaskRecruitment:
    """
    任务招募系统
    
    当有新任务时，向具有相关能力的 Agent 发送招募通知，
    Agent 可以响应招募并声明参与协作
    """

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.pending_recruitments: Dict[str, Dict] = {}
        self.recruitment_history: List[Dict] = []
        print("[TaskRecruitment] 任务招募系统初始化")

    async def recruit(
        self,
        task_id: str,
        required_capabilities: List[str],
        task_data: Dict,
        recruiter_id: str
    ) -> List[str]:
        """
        发布任务招募
        
        Args:
            task_id: 任务 ID
            required_capabilities: 所需能力列表
            task_data: 任务数据
            recruiter_id: 招募者 ID
        
        Returns:
            响应的 Agent ID 列表
        """
        print(f"\n[TaskRecruitment] 发布招募:")
        print(f"  任务 ID: {task_id}")
        print(f"  所需能力: {required_capabilities}")
        
        # 创建招募消息
        recruitment_msg = create_message(
            msg_type=MessageType.BROADCAST,
            sender_id=recruiter_id,
            receiver_id="*",
            content=f"任务招募: {task_data.get('description', '')}",
            payload={
                "type": "recruitment",
                "task_id": task_id,
                "required_capabilities": required_capabilities,
                "task_data": task_data,
                "recruiter_id": recruiter_id,
                "timestamp": datetime.now().isoformat()
            },
            priority=MessagePriority.HIGH
        )
        
        # 查找具有所需能力的 Agent
        eligible_agents = []
        for capability in required_capabilities:
            agents = self.bus.list_agents(capability=capability)
            for agent in agents:
                if agent.agent_id != recruiter_id:
                    eligible_agents.append(agent.agent_id)
        
        eligible_agents = list(set(eligible_agents))
        print(f"  符合条件的 Agent: {eligible_agents}")
        
        # 发送招募通知
        for agent_id in eligible_agents:
            agent = self.bus.get_agent(agent_id)
            if agent:
                await agent.receive(recruitment_msg)
        
        # 记录招募信息
        self.pending_recruitments[task_id] = {
            "task_id": task_id,
            "required_capabilities": required_capabilities,
            "eligible_agents": eligible_agents,
            "responses": [],
            "created_at": datetime.now().isoformat()
        }
        
        return eligible_agents

    async def respond_to_recruitment(
        self,
        agent_id: str,
        task_id: str,
        can_participate: bool,
        message: str = "",
        contribution: str = ""
    ) -> bool:
        """
        Agent 响应招募
        
        Args:
            agent_id: Agent ID
            task_id: 任务 ID
            can_participate: 是否能参与
            message: 附加消息
            contribution: 能提供的贡献
        
        Returns:
            是否成功响应
        """
        if task_id not in self.pending_recruitments:
            print(f"[TaskRecruitment] 任务 {task_id} 不存在或招募已结束")
            return False
        
        recruitment = self.pending_recruitments[task_id]
        response = {
            "agent_id": agent_id,
            "can_participate": can_participate,
            "message": message,
            "contribution": contribution,
            "responded_at": datetime.now().isoformat()
        }
        
        recruitment["responses"].append(response)
        self.recruitment_history.append({
            "task_id": task_id,
            "response": response
        })
        
        print(f"[TaskRecruitment] Agent {agent_id} 响应招募:")
        print(f"  能参与: {can_participate}")
        print(f"  能提供的贡献: {contribution}")
        
        return True

    def get_recruitment_status(self, task_id: str) -> Dict:
        """获取招募状态"""
        if task_id in self.pending_recruitments:
            recruitment = self.pending_recruitments[task_id]
            return {
                "task_id": task_id,
                "eligible_agents": recruitment["eligible_agents"],
                "response_count": len(recruitment["responses"]),
                "responses": recruitment["responses"]
            }
        return None

    def select_participants(
        self,
        task_id: str,
        max_participants: int = 3
    ) -> List[str]:
        """选择参与者（基于贡献和能力）"""
        recruitment = self.pending_recruitments.get(task_id)
        if not recruitment:
            return []
        
        # 按贡献排序
        responses = recruitment["responses"]
        capable_responses = [r for r in responses if r["can_participate"]]
        capable_responses.sort(key=lambda x: len(x["contribution"]), reverse=True)
        
        # 选择前 N 个
        selected = [r["agent_id"] for r in capable_responses[:max_participants]]
        
        print(f"[TaskRecruitment] 任务 {task_id} 选择了参与者: {selected}")
        return selected


class RecruitmentAgent(BaseAgent):
    """参与任务招募的 Agent"""

    def __init__(self, agent_id: str, name: str, capabilities: List[str]):
        super().__init__(
            agent_id=agent_id,
            name=name,
            capabilities=capabilities
        )
        self.available = True
        self.current_tasks: List[str] = []
        self.max_concurrent_tasks = 2
        self.recruitment_callbacks: List[Callable] = []
        
        # 注册招募消息处理器
        @self.on(MessageType.BROADCAST)
        async def handle_recruitment(msg: Message):
            payload = msg.payload or {}
            
            if payload.get("type") == "recruitment":
                await self._handle_recruitment(msg)
        
        print(f"[{self.name}] Agent 初始化完成")
        print(f"  能力: {capabilities}")
        print(f"  最大并发任务: {self.max_concurrent_tasks}")

    async def _handle_recruitment(self, msg: Message):
        """处理招募消息"""
        payload = msg.payload
        task_id = payload.get("task_id")
        required_capabilities = payload.get("required_capabilities", [])
        
        print(f"\n[{self.name}] 收到招募通知:")
        print(f"  任务: {task_id}")
        print(f"  所需能力: {required_capabilities}")
        print(f"  我的能力: {self.capabilities}")
        
        # 检查是否有能力满足
        can_satisfy = all(
            cap in self.capabilities for cap in required_capabilities
        )
        
        # 检查是否有空余能力
        can_participate = (
            can_satisfy and 
            self.available and 
            len(self.current_tasks) < self.max_concurrent_tasks
        )
        
        # 构建响应
        contribution = self._evaluate_contribution(required_capabilities)
        
        # 响应招募
        from message_bus import get_message_bus
        bus = get_message_bus()
        
        # 获取招募系统
        recruitment_system = bus._recruitment if hasattr(bus, '_recruitment') else None
        
        if recruitment_system:
            await recruitment_system.respond_to_recruitment(
                agent_id=self.agent_id,
                task_id=task_id,
                can_participate=can_participate,
                message=f"我可以参与此任务" if can_participate else "当前忙碌或能力不匹配",
                contribution=contribution
            )
        
        # 如果参与，更新状态
        if can_participate:
            self.current_tasks.append(task_id)
            print(f"[{self.name}] 决定参与任务 {task_id}")

    def _evaluate_contribution(self, required_capabilities: List[str]) -> str:
        """评估能提供的贡献"""
        contributions = []
        for cap in required_capabilities:
            if cap in self.capabilities:
                contributions.append(f"可提供 {cap} 能力")
        return ", ".join(contributions) if contributions else "无"

    def set_available(self, available: bool):
        """设置可用性"""
        self.available = available
        status = "可用" if available else "忙碌"
        print(f"[{self.name}] 状态更新: {status}")

    def complete_task(self, task_id: str):
        """完成任务"""
        if task_id in self.current_tasks:
            self.current_tasks.remove(task_id)
            print(f"[{self.name}] 完成任务: {task_id}")


# ==========================================
# 场景 3: 协作意愿匹配
# ==========================================

class CollaborationMatcher:
    """
    协作意愿匹配系统
    
    Agent 发布自己的能力、兴趣和可用性，
    系统帮助匹配可以协作的 Agent
    """

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.agent_profiles: Dict[str, Dict] = {}
        self.collaboration_requests: List[Dict] = []
        print("[CollaborationMatcher] 协作匹配系统初始化")

    def register_profile(self, agent_id: str, profile: Dict):
        """注册 Agent 画像"""
        self.agent_profiles[agent_id] = {
            "agent_id": agent_id,
            "name": profile.get("name", ""),
            "capabilities": profile.get("capabilities", []),
            "interests": profile.get("interests", []),
            "availability": profile.get("availability", "available"),
            "workload": profile.get("workload", 0),
            "registered_at": datetime.now().isoformat()
        }
        print(f"[CollaborationMatcher] 注册 Agent 画像: {agent_id}")

    def update_availability(self, agent_id: str, availability: str, workload: int):
        """更新可用性"""
        if agent_id in self.agent_profiles:
            self.agent_profiles[agent_id]["availability"] = availability
            self.agent_profiles[agent_id]["workload"] = workload
            print(f"[{agent_id}] 可用性更新: {availability}, 工作负载: {workload}")

    async def find_collaborators(
        self,
        agent_id: str,
        required_capabilities: List[str],
        interests: List[str] = None,
        max_results: int = 5
    ) -> List[Dict]:
        """查找协作者"""
        print(f"\n[CollaborationMatcher] 查找协作者:")
        print(f"  请求者: {agent_id}")
        print(f"  所需能力: {required_capabilities}")
        print(f"  兴趣: {interests or '无'}")
        
        candidates = []
        
        for profile_agent_id, profile in self.agent_profiles.items():
            if profile_agent_id == agent_id:
                continue
            
            # 检查可用性
            if profile["availability"] == "offline":
                continue
            
            if profile["workload"] >= 100:
                continue
            
            # 计算匹配分数
            score = self._calculate_match_score(
                profile,
                required_capabilities,
                interests
            )
            
            if score > 0:
                candidates.append({
                    "agent_id": profile_agent_id,
                    "profile": profile,
                    "match_score": score
                })
        
        # 按匹配分数排序
        candidates.sort(key=lambda x: x["match_score"], reverse=True)
        
        # 返回前 N 个
        results = candidates[:max_results]
        
        print(f"  找到 {len(results)} 个候选协作者:")
        for c in results:
            print(f"    - {c['agent_id']}: 匹配度 {c['match_score']:.2f}")
        
        return results

    def _calculate_match_score(
        self,
        profile: Dict,
        required_capabilities: List[str],
        interests: List[str]
    ) -> float:
        """计算匹配分数"""
        score = 0.0
        
        # 能力匹配（权重 0.6）
        matched_caps = sum(
            1 for cap in required_capabilities 
            if cap in profile["capabilities"]
        )
        cap_score = matched_caps / len(required_capabilities) if required_capabilities else 0
        score += cap_score * 0.6
        
        # 兴趣匹配（权重 0.2）
        if interests:
            matched_interests = sum(
                1 for interest in interests 
                if any(interest in i for i in profile["interests"])
            )
            interest_score = matched_interests / len(interests)
            score += interest_score * 0.2
        
        # 可用性评分（权重 0.2）
        availability_scores = {
            "available": 1.0,
            "busy": 0.5,
            "limited": 0.3
        }
        avail_score = availability_scores.get(profile["availability"], 0)
        score += avail_score * 0.2
        
        return score

    async def request_collaboration(
        self,
        requester_id: str,
        task_description: str,
        required_capabilities: List[str],
        preferred_collaborators: List[str] = None
    ) -> Dict:
        """发起协作请求"""
        print(f"\n[CollaborationMatcher] 协作请求:")
        print(f"  请求者: {requester_id}")
        print(f"  任务: {task_description}")
        
        # 查找协作者
        collaborators = await self.find_collaborators(
            requester_id,
            required_capabilities,
            max_results=5
        )
        
        # 如果有偏好，优先排序
        if preferred_collaborators:
            for collab in collaborators:
                if collab["agent_id"] in preferred_collaborators:
                    collab["match_score"] += 0.5  # 加权
        
        # 创建协作请求
        request = {
            "request_id": f"collab_{datetime.now().timestamp()}",
            "requester_id": requester_id,
            "task_description": task_description,
            "required_capabilities": required_capabilities,
            "collaborators": collaborators,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        
        self.collaboration_requests.append(request)
        
        # 发送协作请求给候选协作者
        collab_msg = create_message(
            msg_type=MessageType.BROADCAST,
            sender_id=requester_id,
            receiver_id="*",
            content=f"协作请求: {task_description}",
            payload={
                "type": "collaboration_request",
                "request": request
            }
        )
        
        for collab in collaborators:
            agent = self.bus.get_agent(collab["agent_id"])
            if agent:
                await agent.receive(collab_msg)
        
        return request


# ==========================================
# 场景 4: 资源协调与冲突检测
# ==========================================

class ResourceCoordinator:
    """
    资源协调系统
    
    管理共享资源，检测冲突，
    协调 Agent 之间的资源使用
    """

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.resources: Dict[str, Dict] = {}
        self.reservations: Dict[str, List[Dict]] = {}  # resource_id -> reservations
        self.conflicts: List[Dict] = []
        print("[ResourceCoordinator] 资源协调系统初始化")

    def register_resource(
        self,
        resource_id: str,
        resource_type: str,
        capacity: int = 1,
        exclusive: bool = False
    ):
        """注册资源"""
        self.resources[resource_id] = {
            "resource_id": resource_id,
            "type": resource_type,
            "capacity": capacity,
            "exclusive": exclusive,
            "current_usage": 0,
            "registered_at": datetime.now().isoformat()
        }
        self.reservations[resource_id] = []
        print(f"[ResourceCoordinator] 注册资源: {resource_id} ({resource_type})")

    async def reserve(
        self,
        resource_id: str,
        agent_id: str,
        duration: float,
        priority: int = 0
    ) -> bool:
        """预约资源"""
        if resource_id not in self.resources:
            print(f"[ResourceCoordinator] 资源不存在: {resource_id}")
            return False
        
        resource = self.resources[resource_id]
        
        # 检查容量
        if resource["current_usage"] >= resource["capacity"] and not resource["exclusive"]:
            print(f"[ResourceCoordinator] 资源容量已满: {resource_id}")
            return False
        
        # 检查独占性
        if resource["exclusive"]:
            existing = [
                r for r in self.reservations[resource_id]
                if r["agent_id"] != agent_id and not r.get("released", False)
            ]
            if existing:
                print(f"[ResourceCoordinator] 资源独占中: {resource_id}")
                return False
        
        # 创建预约
        reservation = {
            "reservation_id": f"res_{datetime.now().timestamp()}",
            "resource_id": resource_id,
            "agent_id": agent_id,
            "duration": duration,
            "priority": priority,
            "start_time": datetime.now().isoformat(),
            "status": "active",
            "released": False
        }
        
        self.reservations[resource_id].append(reservation)
        resource["current_usage"] += 1
        
        print(f"[ResourceCoordinator] {agent_id} 预约资源 {resource_id}")
        print(f"  时长: {duration}s, 优先级: {priority}")
        
        # 发布资源变更事件
        await self._publish_resource_change(resource_id, "reserved", agent_id)
        
        return True

    def release(self, resource_id: str, agent_id: str) -> bool:
        """释放资源"""
        if resource_id not in self.reservations:
            return False
        
        for reservation in self.reservations[resource_id]:
            if reservation["agent_id"] == agent_id and not reservation["released"]:
                reservation["released"] = True
                reservation["end_time"] = datetime.now().isoformat()
                reservation["status"] = "completed"
                
                if resource_id in self.resources:
                    self.resources[resource_id]["current_usage"] = max(
                        0, 
                        self.resources[resource_id]["current_usage"] - 1
                    )
                
                print(f"[ResourceCoordinator] {agent_id} 释放资源 {resource_id}")
                return True
        
        return False

    def detect_conflicts(self) -> List[Dict]:
        """检测资源冲突"""
        self.conflicts.clear()
        
        for resource_id, reservations in self.reservations.items():
            # 检查时间重叠
            for i, res1 in enumerate(reservations):
                for res2 in reservations[i+1:]:
                    if self._check_overlap(res1, res2):
                        conflict = {
                            "resource_id": resource_id,
                            "conflict_type": "time_overlap",
                            "reservation1": res1,
                            "reservation2": res2,
                            "detected_at": datetime.now().isoformat()
                        }
                        self.conflicts.append(conflict)
                        print(f"[ResourceCoordinator] 检测到冲突:")
                        print(f"  资源: {resource_id}")
                        print(f"  Agent1: {res1['agent_id']}")
                        print(f"  Agent2: {res2['agent_id']}")
        
        return self.conflicts

    def _check_overlap(self, res1: Dict, res2: Dict) -> bool:
        """检查两个预约是否时间重叠"""
        if res1.get("released") or res2.get("released"):
            return False
        
        # 简化检查：同一资源的非exclusive冲突
        return True

    async def _publish_resource_change(
        self,
        resource_id: str,
        change_type: str,
        agent_id: str
    ):
        """发布资源变更事件"""
        change_msg = create_message(
            msg_type=MessageType.BROADCAST,
            sender_id="resource_coordinator",
            receiver_id="*",
            content=f"资源变更: {resource_id}",
            payload={
                "type": "resource_change",
                "resource_id": resource_id,
                "change_type": change_type,
                "agent_id": agent_id,
                "current_usage": self.resources.get(resource_id, {}).get("current_usage", 0)
            }
        )
        
        await self.bus.broadcast(change_msg)


# ==========================================
# 测试场景
# ==========================================

async def test_perception_sync():
    """测试感知同步"""
    print("\n" + "="*60)
    print("测试 1: 多智能体感知同步")
    print("="*60)
    
    bus = get_message_bus()
    bus.reset()
    
    # 创建感知同步系统
    perception = PerceptionSync(bus)
    
    # 创建 Agent 并订阅主题
    agent1 = PerceptionAgent("agent1", "感知者1号", interests=["task.*", "agent.*"])
    agent2 = PerceptionAgent("agent2", "感知者2号", interests=["alert.*"])
    agent3 = PerceptionAgent("agent3", "感知者3号", interests=["*"])  # 订阅所有
    
    # 注册订阅
    perception.subscribe("agent1", ["task.*", "agent.*"])
    perception.subscribe("agent2", ["alert.*"])
    perception.subscribe("agent3", ["*"])
    
    # 发布事件
    await perception.publish("task.added", {"task_id": "task-001", "type": "search"})
    await asyncio.sleep(0.3)
    await perception.publish("alert.critical", {"message": "系统负载过高!", "level": 5})
    await asyncio.sleep(0.3)
    await perception.publish("agent.online", {"agent_id": "new-agent", "name": "新Agent"})
    
    print(f"\n{agent1.name} 收到事件数: {len(agent1.received_events)}")
    print(f"{agent2.name} 收到事件数: {len(agent2.received_events)}")
    print(f"{agent3.name} 收到事件数: {len(agent3.received_events)}")


async def test_task_recruitment():
    """测试任务招募"""
    print("\n" + "="*60)
    print("测试 2: 任务招募与协作匹配")
    print("="*60)
    
    bus = get_message_bus()
    bus.reset()
    
    # 创建招募系统
    recruitment = TaskRecruitment(bus)
    bus._recruitment = recruitment  # 临时绑定
    
    # 创建 Agent
    worker1 = RecruitmentAgent("worker1", "搜索Worker", ["search", "research"])
    worker2 = RecruitmentAgent("worker2", "编码Worker", ["coding", "programming"])
    worker3 = RecruitmentAgent("worker3", "全能Worker", ["search", "coding", "writing"])
    
    # 发布招募
    eligible = await recruitment.recruit(
        task_id="task-001",
        required_capabilities=["search", "coding"],
        task_data={"description": "搜索并分析数据"},
        recruiter_id="supervisor"
    )
    
    # Agent 响应
    await asyncio.sleep(0.5)
    await recruitment.respond_to_recruitment(
        agent_id="worker3",
        task_id="task-001",
        can_participate=True,
        contribution="可提供搜索和编码能力"
    )
    
    # 获取状态
    status = recruitment.get_recruitment_status("task-001")
    print(f"\n招募状态: {status}")
    
    # 选择参与者
    participants = recruitment.select_participants("task-001", max_participants=2)
    print(f"选择的参与者: {participants}")


async def test_collaboration_matching():
    """测试协作匹配"""
    print("\n" + "="*60)
    print("测试 3: 协作意愿匹配")
    print("="*60)
    
    bus = get_message_bus()
    bus.reset()
    
    # 创建匹配系统
    matcher = CollaborationMatcher(bus)
    
    # 注册 Agent 画像
    matcher.register_profile("agent1", {
        "name": "Alice",
        "capabilities": ["python", "ml", "data_analysis"],
        "interests": ["AI", "research"],
        "availability": "available",
        "workload": 30
    })
    
    matcher.register_profile("agent2", {
        "name": "Bob",
        "capabilities": ["frontend", "ui", "design"],
        "interests": ["web", "ux"],
        "availability": "available",
        "workload": 50
    })
    
    matcher.register_profile("agent3", {
        "name": "Charlie",
        "capabilities": ["python", "backend", "ml"],
        "interests": ["AI", "backend"],
        "availability": "busy",
        "workload": 80
    })
    
    # 查找协作者
    collaborators = await matcher.find_collaborators(
        agent_id="agent2",
        required_capabilities=["python", "ml"],
        interests=["AI"],
        max_results=3
    )
    
    print(f"\n为 agent2 找到的协作者:")
    for c in collaborators:
        print(f"  {c['agent_id']} ({c['profile']['name']}): 匹配度 {c['match_score']:.2f}")


async def test_resource_coordination():
    """测试资源协调"""
    print("\n" + "="*60)
    print("测试 4: 资源协调与冲突检测")
    print("="*60)
    
    bus = get_message_bus()
    bus.reset()
    
    coordinator = ResourceCoordinator(bus)
    
    # 注册资源
    coordinator.register_resource("gpu-1", "GPU", capacity=2, exclusive=False)
    coordinator.register_resource("db-1", "Database", capacity=1, exclusive=True)
    
    # 预约资源
    await coordinator.reserve("gpu-1", "agent1", duration=60, priority=1)
    await coordinator.reserve("gpu-1", "agent2", duration=60, priority=2)
    await coordinator.reserve("db-1", "agent3", duration=120, priority=1)
    
    # 检查状态
    print(f"\nGPU-1 当前使用: {coordinator.resources['gpu-1']['current_usage']}")
    print(f"DB-1 当前使用: {coordinator.resources['db-1']['current_usage']}")
    
    # 释放资源
    coordinator.release("gpu-1", "agent1")
    print(f"\nagent1 释放 GPU-1 后:")
    print(f"GPU-1 当前使用: {coordinator.resources['gpu-1']['current_usage']}")


async def main():
    """运行所有测试"""
    print("\n" + "#"*60)
    print("Pub-Sub 场景测试")
    print("#"*60)
    
    await test_perception_sync()
    await test_task_recruitment()
    await test_collaboration_matching()
    await test_resource_coordination()
    
    print("\n" + "#"*60)
    print("所有测试完成!")
    print("#"*60)


if __name__ == "__main__":
    asyncio.run(main())
