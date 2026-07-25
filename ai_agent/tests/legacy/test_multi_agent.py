"""
多 Agent 系统测试

测试消息传递、编排、任务调度等功能
"""

"""Long-running test (>2s). Skipped by default in CI.
Run explicitly with: pytest -m slow

Reason: multi-agent full workflow (multi-round + bus)
"""
import pytest

pytestmark = pytest.mark.slow


import asyncio
import os

# 添加当前目录到路径

from message_protocol import (
    Message, MessageType, MessagePriority, AgentInfo, AgentRole,
    create_message, create_task
)
from message_bus import MessageBus, BaseAgent, get_message_bus
from multi_agent import (
    AgentOrchestrator, OrchestrationMode, TaskStatus,
    WorkerAgent, SupervisorAgent
)
from task_scheduler import TaskScheduler, get_scheduler
from state_manager import StateManager, get_state_manager


class TestAgent(BaseAgent):
    """测试用 Agent"""
    
    def __init__(self, agent_id: str, name: str, capabilities: list = None):
        super().__init__(
            agent_id=agent_id,
            name=name,
            capabilities=capabilities or ["general"]
        )
        self.received_messages = []
        self._register_handlers()
    
    def _register_handlers(self):
        """注册消息处理器"""
        
        @self.on(MessageType.TEXT)
        async def handle_text(message: Message):
            print(f"[{self.name}] Received text: {message.content}")
            self.received_messages.append(message)
            
            # 回复消息
            response = message.create_response(f"Echo: {message.content}")
            await self.send(
                receiver_id=message.sender_id,
                content=response.content,
                msg_type=MessageType.TEXT
            )
        
        @self.on(MessageType.TASK)
        async def handle_task(message: Message):
            print(f"[{self.name}] Received task: {message.content}")
            self.received_messages.append(message)
            
            # 执行任务
            result = f"Task completed by {self.name}: {message.content}"
            
            # 发送结果
            await self.send(
                receiver_id=message.sender_id,
                content=result,
                msg_type=MessageType.RESULT,
                correlation_id=message.msg_id
            )
        
        @self.on(MessageType.REQUEST)
        async def handle_request(message: Message):
            print(f"[{self.name}] Received request: {message.content}")
            response = message.create_response(f"Response from {self.name}")
            await self.send(
                receiver_id=message.sender_id,
                content=response.content,
                msg_type=MessageType.RESPONSE
            )


async def test_message_protocol():
    """测试消息协议"""
    print("\n" + "="*50)
    print("Test 1: Message Protocol")
    print("="*50)
    
    # 创建消息
    msg = create_message(
        msg_type=MessageType.TEXT,
        sender_id="agent1",
        content="Hello, Agent 2!",
        receiver_id="agent2",
        priority=MessagePriority.HIGH
    )
    
    print(f"Created message: {msg.msg_id}")
    print(f"Type: {msg.msg_type.value}")
    print(f"Content: {msg.content}")
    print(f"Priority: {msg.priority.value}")
    
    # 创建任务消息
    task = create_task(
        sender_id="supervisor",
        task_type="search",
        task_data={"query": "Python async"},
        receiver_id="worker1"
    )
    
    print(f"\nCreated task: {task.task_id}")
    print(f"Task type: {task.task_type}")
    print(f"Task data: {task.task_data}")
    
    # 序列化/反序列化
    serialized = msg.to_dict()
    print(f"\nSerialized: {len(serialized)} bytes")
    
    return True


async def test_message_bus():
    """测试消息总线"""
    print("\n" + "="*50)
    print("Test 2: Message Bus")
    print("="*50)
    
    # 获取消息总线
    bus = get_message_bus()
    bus.reset()  # 重置状态
    
    # 创建测试 Agent
    agent1 = TestAgent("agent1", "Agent One", ["messaging"])
    agent2 = TestAgent("agent2", "Agent Two", ["messaging"])
    
    print(f"Registered agents: {agent1.agent_id}, {agent2.agent_id}")
    
    # 列出 Agent
    agents = bus.list_agents()
    print(f"Total agents in bus: {len(agents)}")
    
    # 发送点对点消息
    print("\nSending P2P message...")
    await bus.send(create_message(
        msg_type=MessageType.TEXT,
        sender_id="agent1",
        receiver_id="agent2",
        content="Hello from Agent 1!",
        priority=MessagePriority.HIGH
    ))
    
    # 等待消息处理
    await asyncio.sleep(0.5)
    
    print(f"Agent 2 received {len(agent2.received_messages)} messages")
    
    # 测试广播
    print("\nBroadcasting...")
    await agent1.broadcast("Broadcast from Agent 1!", topic="test")
    
    await asyncio.sleep(0.5)
    
    # 测试请求-响应
    print("\nTesting request-response...")
    response = await bus.request(
        sender_id="agent1",
        receiver_id="agent2",
        content="Please respond",
        timeout=5.0
    )
    
    print(f"Response received: {response.content if response else 'None'}")
    
    return True


async def test_worker_orchestration():
    """测试 Worker 编排"""
    print("\n" + "="*50)
    print("Test 3: Worker Orchestration")
    print("="*50)
    
    # 创建编排器
    orchestrator = AgentOrchestrator(
        supervisor_id="supervisor",
        supervisor_name="TestSupervisor"
    )
    
    # 创建 Worker
    async def search_executor(description: str, data: dict):
        print(f"[SearchWorker] Executing: {description}")
        await asyncio.sleep(0.1)
        return f"Search results for: {data.get('query', description)}"
    
    async def code_executor(description: str, data: dict):
        print(f"[CodeWorker] Executing: {description}")
        await asyncio.sleep(0.1)
        return f"Code completed: {data.get('code', 'N/A')[:50]}..."
    
    search_worker = WorkerAgent(
        name="SearchWorker",
        capabilities=["search", "research"]
    )
    search_worker.set_executor(search_executor)
    
    code_worker = WorkerAgent(
        name="CodeWorker",
        capabilities=["coding", "programming"]
    )
    code_worker.set_executor(code_executor)
    
    # 注册 Worker
    orchestrator.register_worker(search_worker)
    orchestrator.register_worker(code_worker)
    
    print(f"Registered workers: {len(orchestrator.list_workers())}")
    
    # 列出 Worker
    workers = orchestrator.list_workers()
    for w in workers:
        print(f"  - {w.name} ({w.agent_id}): {w.capabilities}")
    
    # 分配任务
    print("\nAssigning tasks...")
    
    task1 = orchestrator.create_task(
        task_type="search",
        description="Search for AI news",
        metadata={"query": "AI news today"}
    )
    
    task2 = orchestrator.create_task(
        task_type="coding",
        description="Write a function",
        metadata={"code": "def hello(): return 'world'"}
    )
    
    print(f"Created tasks: {task1.task_id}, {task2.task_id}")
    
    # 分配给 Worker
    await orchestrator.assign_task(task1, search_worker.agent_id)
    await orchestrator.assign_task(task2, code_worker.agent_id)
    
    # 等待任务完成
    await asyncio.sleep(1)
    
    # 检查任务状态
    task1_status = orchestrator.get_task(task1.task_id)
    task2_status = orchestrator.get_task(task2.task_id)
    
    print(f"\nTask 1 status: {task1_status.status.value if task1_status else 'Not found'}")
    print(f"Task 2 status: {task2_status.status.value if task2_status else 'Not found'}")
    
    # 获取统计
    stats = orchestrator.get_stats()
    print(f"\nOrchestrator stats: {stats}")
    
    return True


async def test_task_scheduler():
    """测试任务调度器"""
    print("\n" + "="*50)
    print("Test 4: Task Scheduler")
    print("="*50)
    
    scheduler = get_scheduler()
    
    # 测试任务
    task_results = []
    
    async def sample_task(task_name: str):
        print(f"[Scheduler] Running task: {task_name}")
        await asyncio.sleep(0.5)
        result = f"Completed: {task_name}"
        task_results.append(result)
        return result
    
    # 调度立即任务
    task_id1 = scheduler.schedule(
        func=sample_task,
        name="Immediate Task",
        priority=MessagePriority.HIGH
    )
    print(f"Scheduled immediate task: {task_id1}")
    
    # 调度延迟任务
    task_id2 = scheduler.schedule(
        func=sample_task,
        name="Delayed Task",
        delay_seconds=0.5,
        priority=MessagePriority.NORMAL
    )
    print(f"Scheduled delayed task: {task_id2}")
    
    # 启动调度器
    await scheduler.start()
    
    # 等待任务完成
    await asyncio.sleep(2)
    
    # 停止调度器
    await scheduler.stop()
    
    print(f"Task results: {task_results}")
    print(f"Scheduler stats: {scheduler.get_stats()}")
    
    return len(task_results) >= 2


async def test_state_manager():
    """测试状态管理器"""
    print("\n" + "="*50)
    print("Test 5: State Manager")
    print("="*50)
    
    state_mgr = get_state_manager()
    state_mgr.reset()
    
    # 设置 Agent 状态
    state_mgr.set_state("agent1", "status", "active")
    state_mgr.set_state("agent1", "location", "server-1")
    state_mgr.set_state("agent2", "status", "idle")
    
    print("Set agent states")
    
    # 获取状态
    agent1_status = state_mgr.get_state("agent1", "status")
    agent1_all = state_mgr.get_state("agent1")
    
    print(f"Agent 1 status: {agent1_status}")
    print(f"Agent 1 all state: {agent1_all}")
    
    # 全局状态
    state_mgr.set_global_state("system_load", 0.75)
    state_mgr.set_global_state("active_agents", 2)
    
    print(f"Global system_load: {state_mgr.get_global_state('system_load')}")
    
    # 版本控制
    v1 = state_mgr.get_version("agent1")
    state_mgr.set_state("agent1", "counter", 1)
    v2 = state_mgr.get_version("agent1")
    
    print(f"Version change: {v1} -> {v2}")
    
    # 状态历史
    history = state_mgr.get_history("agent1")
    print(f"State history length: {len(history)}")
    
    # 分布式锁测试
    print("\nTesting distributed lock...")
    
    lock_acquired = await state_mgr.acquire_lock(
        lock_id="resource_lock",
        owner_id="agent1",
        resource="shared_resource"
    )
    print(f"Lock acquired: {lock_acquired}")
    
    is_locked = state_mgr.is_locked("resource_lock")
    print(f"Is locked: {is_locked}")
    
    state_mgr.release_lock("resource_lock", "agent1")
    
    is_locked_after = state_mgr.is_locked("resource_lock")
    print(f"Is locked after release: {is_locked_after}")
    
    return True


async def test_integration():
    """集成测试"""
    print("\n" + "="*50)
    print("Test 6: Integration Test")
    print("="*50)
    
    # 重置所有组件
    bus = get_message_bus()
    bus.reset()
    
    scheduler = get_scheduler()
    
    state_mgr = get_state_manager()
    state_mgr.reset()
    
    # 创建 Supervisor
    supervisor = SupervisorAgent(
        name="MainSupervisor",
        orchestration_mode=OrchestrationMode.SUPERVISOR
    )
    
    # 创建 Workers
    workers = []
    for i in range(3):
        worker = WorkerAgent(
            name=f"Worker-{i+1}",
            capabilities=["general", "task_execution"]
        )
        workers.append(worker)
        supervisor.orchestrator.register_worker(worker)
    
    print(f"Created supervisor and {len(workers)} workers")
    
    # 注册到消息总线
    bus.register_agent(supervisor)
    for worker in workers:
        bus.register_agent(worker)
    
    # 设置全局状态
    state_mgr.set_global_state("total_tasks", 0)
    
    # 执行任务编排
    print("\nExecuting multi-agent orchestration...")
    
    # 创建工作流
    workflow = supervisor.orchestrator.create_workflow(
        name="TestWorkflow",
        description="Integration test workflow",
        mode=OrchestrationMode.PARALLEL
    )
    
    # 添加任务
    for i, worker in enumerate(workers):
        task = supervisor.orchestrator.create_task(
            task_type="general",
            description=f"Task {i+1}",
            metadata={"data": {"index": i}}
        )
        supervisor.orchestrator.add_task_to_workflow(workflow.workflow_id, task)
        await supervisor.orchestrator.assign_task(task, worker.agent_id)
    
    print(f"Created workflow with {len(workflow.tasks)} tasks")
    
    # 等待任务完成
    await asyncio.sleep(2)
    
    # 获取统计
    print(f"\nMessage Bus stats: {bus.get_stats()}")
    print(f"Scheduler stats: {scheduler.get_stats()}")
    print(f"State Manager stats: {state_mgr.get_stats()}")
    print(f"Orchestrator stats: {supervisor.orchestrator.get_stats()}")
    
    return True


async def main():
    """主测试函数"""
    print("\n" + "#"*60)
    print("Multi-Agent System Tests")
    print("#"*60)
    
    tests = [
        ("Message Protocol", test_message_protocol),
        ("Message Bus", test_message_bus),
        ("Worker Orchestration", test_worker_orchestration),
        ("Task Scheduler", test_task_scheduler),
        ("State Manager", test_state_manager),
        ("Integration", test_integration),
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            success = await test_func()
            results.append((name, success))
            status = "PASSED" if success else "FAILED"
            print(f"\n{'='*40}")
            print(f"Test '{name}': {status}")
            print(f"{'='*40}")
        except Exception as e:
            results.append((name, False))
            print(f"\n{'='*40}")
            print(f"Test '{name}': FAILED (Error)")
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            print(f"{'='*40}")
    
    # 总结
    print("\n" + "#"*60)
    print("Test Summary")
    print("#"*60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "[PASS]" if success else "[FAIL]"
        print(f"  {status} {name}")
    
    print(f"\nTotal: {passed}/{total} passed")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
