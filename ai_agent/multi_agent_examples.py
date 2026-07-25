"""
多 Agent 系统使用示例

展示如何使用多 Agent 消息传递机制
"""

import asyncio
from message_protocol import (
    Message, MessageType, MessagePriority, AgentInfo, AgentRole,
    create_message, create_task, MessageBuilder
)
from message_bus import MessageBus, BaseAgent, get_message_bus
from multi_agent import (
    AgentOrchestrator, OrchestrationMode, TaskStatus,
    WorkerAgent, SupervisorAgent
)
from task_scheduler import TaskScheduler, get_scheduler, scheduled, periodic
from state_manager import StateManager, get_state_manager, LockContext


# ==========================================
# 示例 1: 基础消息发送
# ==========================================

async def example_basic_messaging():
    """基础消息发送示例"""
    print("\n" + "="*50)
    print("Example 1: Basic Messaging")
    print("="*50)
    
    bus = get_message_bus()
    bus.reset()
    
    # 创建 Agent
    class SimpleAgent(BaseAgent):
        def __init__(self, agent_id, name):
            super().__init__(agent_id=agent_id, name=name)
            
            @self.on(MessageType.TEXT)
            async def handle_text(msg):
                print(f"[{self.name}] Received: {msg.content}")
                # 回复
                response = msg.create_response(f"Hi! Got your message: {msg.content}")
                await self.send(
                    receiver_id=msg.sender_id,
                    content=response.content,
                    msg_type=MessageType.TEXT
                )
    
    agent1 = SimpleAgent("agent1", "Alice")
    agent2 = SimpleAgent("agent2", "Bob")
    
    # 发送消息
    print("[Alice] Sending message to Bob...")
    await agent1.send(
        receiver_id="agent2",
        content="Hello Bob!",
        msg_type=MessageType.TEXT
    )
    
    await asyncio.sleep(0.5)
    print("[Alice] Message sent successfully!")


# ==========================================
# 示例 2: 消息构建器
# ==========================================

async def example_message_builder():
    """消息构建器示例"""
    print("\n" + "="*50)
    print("Example 2: Message Builder")
    print("="*50)
    
    # 使用链式调用构建复杂消息
    message = (
        MessageBuilder(sender_id="agent1")
        .type(MessageType.TASK)
        .to("worker1")
        .content("Process the data")
        .payload(
            task_type="data_processing",
            data={"records": 100, "format": "json"}
        )
        .priority(MessagePriority.HIGH)
        .require_ack(True)
        .ttl(300)
        .build()
    )
    
    print(f"Message ID: {message.msg_id}")
    print(f"Type: {message.msg_type.value}")
    print(f"To: {message.receiver_id}")
    print(f"Content: {message.content}")
    print(f"Payload: {message.payload}")
    print(f"Priority: {message.priority.value}")
    print(f"ACK Required: {message.ack_required}")


# ==========================================
# 示例 3: Worker Agent 协作
# ==========================================

async def example_worker_collaboration():
    """Worker Agent 协作示例"""
    print("\n" + "="*50)
    print("Example 3: Worker Collaboration")
    print("="*50)
    
    bus = get_message_bus()
    bus.reset()
    
    # 创建编排器
    orchestrator = AgentOrchestrator(
        supervisor_id="supervisor",
        supervisor_name="MainSupervisor"
    )
    
    # 创建执行器
    async def search_executor(description, data):
        print(f"  [Search] Searching for: {data.get('query', description)}")
        await asyncio.sleep(0.2)
        return f"Found 10 results for: {data.get('query', description)}"
    
    async def analyze_executor(description, data):
        print(f"  [Analyze] Analyzing: {data.get('topic', description)}")
        await asyncio.sleep(0.2)
        return f"Analysis complete for: {data.get('topic', description)}"
    
    async def report_executor(description, data):
        print(f"  [Report] Generating report...")
        await asyncio.sleep(0.2)
        return "Report generated successfully!"
    
    # 创建 Workers
    search_worker = WorkerAgent(name="SearchWorker", capabilities=["search"])
    search_worker.set_executor(search_executor)
    
    analyze_worker = WorkerAgent(name="AnalyzeWorker", capabilities=["analysis"])
    analyze_worker.set_executor(analyze_executor)
    
    report_worker = WorkerAgent(name="ReportWorker", capabilities=["reporting"])
    report_worker.set_executor(report_executor)
    
    # 注册 Workers
    orchestrator.register_worker(search_worker)
    orchestrator.register_worker(analyze_worker)
    orchestrator.register_worker(report_worker)
    
    print(f"Registered {len(orchestrator.list_workers())} workers")
    
    # 创建任务
    print("\nCreating tasks...")
    task1 = orchestrator.create_task(
        task_type="search",
        description="Find information about AI",
        metadata={"query": "artificial intelligence trends"}
    )
    
    task2 = orchestrator.create_task(
        task_type="analysis",
        description="Analyze AI trends",
        metadata={"topic": "AI trends 2024"}
    )
    
    task3 = orchestrator.create_task(
        task_type="reporting",
        description="Generate report",
        metadata={"format": "pdf"}
    )
    
    # 分配任务
    print("\nAssigning tasks...")
    await orchestrator.assign_task(task1, search_worker.agent_id)
    await orchestrator.assign_task(task2, analyze_worker.agent_id)
    await orchestrator.assign_task(task3, report_worker.agent_id)
    
    # 等待完成
    await asyncio.sleep(1)
    
    # 检查结果
    print("\nTask Results:")
    for task_id in [task1.task_id, task2.task_id, task3.task_id]:
        task = orchestrator.get_task(task_id)
        if task:
            print(f"  {task.task_type}: {task.status.value} - Result: {task.result}")


# ==========================================
# 示例 4: 任务调度
# ==========================================

async def example_task_scheduler():
    """任务调度示例"""
    print("\n" + "="*50)
    print("Example 4: Task Scheduling")
    print("="*50)
    
    scheduler = get_scheduler()
    
    # 定义异步任务
    async def background_task(task_id: int):
        print(f"  [Scheduler] Running task {task_id}...")
        await asyncio.sleep(0.5)
        return f"Task {task_id} completed"
    
    # 调度立即任务
    task_id1 = scheduler.schedule(
        func=background_task,
        name="Immediate Task",
        args=(1,),
        priority=MessagePriority.HIGH
    )
    print(f"Scheduled immediate task: {task_id1}")
    
    # 调度延迟任务
    task_id2 = scheduler.schedule(
        func=background_task,
        name="Delayed Task",
        args=(2,),
        delay_seconds=0.5,
        priority=MessagePriority.NORMAL
    )
    print(f"Scheduled delayed task: {task_id2}")
    
    # 调度周期性任务
    task_id3 = scheduler.schedule_periodic(
        func=background_task,
        name="Periodic Task",
        args=(3,),
        period_seconds=1.0,
        initial_delay=0.2
    )
    print(f"Scheduled periodic task: {task_id3}")
    
    # 注册完成回调
    completed_tasks = []
    
    def on_complete(task):
        completed_tasks.append(task.name)
        print(f"  [Callback] Task completed: {task.name}")
    
    scheduler.on_completion(task_id1, on_complete)
    
    # 启动调度器
    await scheduler.start()
    await asyncio.sleep(2)
    await scheduler.stop()
    
    print(f"\nCompleted tasks: {completed_tasks}")


# ==========================================
# 示例 5: 状态管理
# ==========================================

async def example_state_management():
    """状态管理示例"""
    print("\n" + "="*50)
    print("Example 5: State Management")
    print("="*50)
    
    state_mgr = get_state_manager()
    state_mgr.reset()
    
    # 设置 Agent 状态
    print("Setting agent states...")
    state_mgr.set_state("agent1", "status", "active")
    state_mgr.set_state("agent1", "location", "server-1")
    state_mgr.set_state("agent1", "load", 0.75)
    
    state_mgr.set_state("agent2", "status", "idle")
    state_mgr.set_state("agent2", "location", "server-2")
    
    # 获取状态
    print(f"\nAgent 1 status: {state_mgr.get_state('agent1', 'status')}")
    print(f"Agent 1 all states: {state_mgr.get_state('agent1')}")
    
    # 版本控制
    v1 = state_mgr.get_version("agent1")
    state_mgr.set_state("agent1", "counter", 42)
    v2 = state_mgr.get_version("agent1")
    print(f"\nVersion control: {v1} -> {v2}")
    
    # 全局状态
    state_mgr.set_global_state("total_agents", 2)
    state_mgr.set_global_state("system_uptime", "24h")
    print(f"\nGlobal total_agents: {state_mgr.get_global_state('total_agents')}")
    
    # 监听状态变更
    def on_status_change(agent_id, key, value):
        print(f"  [Watcher] {agent_id}.{key} changed to {value}")
    
    state_mgr.watch("agent1", "status", on_status_change)
    
    # 触发变更
    print("\nChanging agent1.status...")
    state_mgr.set_state("agent1", "status", "busy")
    
    # 状态历史
    print(f"\nState history length: {len(state_mgr.get_history('agent1'))}")
    
    # 获取所有状态
    print(f"\nAll states: {state_mgr.get_all_states()}")


# ==========================================
# 示例 6: 分布式锁
# ==========================================

async def example_distributed_locks():
    """分布式锁示例"""
    print("\n" + "="*50)
    print("Example 6: Distributed Locks")
    print("="*50)
    
    state_mgr = get_state_manager()
    
    # 获取独占锁
    print("Acquiring exclusive lock...")
    acquired = await state_mgr.acquire_lock(
        lock_id="resource_1",
        owner_id="agent1",
        resource="database_connection"
    )
    print(f"Lock acquired: {acquired}")
    print(f"Is locked: {state_mgr.is_locked('resource_1')}")
    
    # 尝试获取共享锁
    print("\nAcquiring shared lock...")
    shared_acquired = await state_mgr.acquire_lock(
        lock_id="resource_1",
        owner_id="agent2",
        resource="database_connection",
        is_shared=True
    )
    print(f"Shared lock acquired: {shared_acquired}")
    
    # 使用锁上下文管理器
    print("\nUsing lock context manager...")
    try:
        async with LockContext(
            lock_id="resource_2",
            owner_id="agent1",
            resource="file_handle",
            timeout=5.0
        ):
            print("  Inside lock context")
            await asyncio.sleep(0.5)
        print("  Exited lock context")
    except Exception as e:
        print(f"Lock error: {e}")
    
    # 释放锁
    print("\nReleasing locks...")
    state_mgr.release_lock("resource_1", "agent1")
    state_mgr.release_lock("resource_1", "agent2")
    print(f"Is locked after release: {state_mgr.is_locked('resource_1')}")


# ==========================================
# 示例 7: Supervisor 编排模式
# ==========================================

async def example_supervisor_mode():
    """Supervisor 模式示例"""
    print("\n" + "="*50)
    print("Example 7: Supervisor Mode")
    print("="*50)
    
    bus = get_message_bus()
    bus.reset()
    
    # 创建 Supervisor
    supervisor = SupervisorAgent(
        name="MainSupervisor",
        orchestration_mode=OrchestrationMode.SUPERVISOR
    )
    
    # 创建 Workers
    for i, cap in enumerate(["search", "code", "write"]):
        worker = WorkerAgent(
            name=f"{cap.capitalize()}Worker",
            capabilities=[cap, "general"]
        )
        worker.set_executor(
            lambda d, t=cap: f"{t} task completed for: {d}"
        )
        supervisor.orchestrator.register_worker(worker)
    
    print(f"Created supervisor with {len(supervisor.orchestrator.list_workers())} workers")
    
    # 执行协调
    print("\nExecuting supervision...")
    result = await supervisor.coordinate("Search for Python tutorials, write code, and create documentation")
    
    print(f"Supervision result: {result}")


# ==========================================
# 示例 8: 工作流编排
# ==========================================

async def example_workflow():
    """工作流示例"""
    print("\n" + "="*50)
    print("Example 8: Workflow Orchestration")
    print("="*50)
    
    bus = get_message_bus()
    bus.reset()
    
    orchestrator = AgentOrchestrator(supervisor_id="main")
    
    # 创建 Workers
    for i, cap in enumerate(["research", "analyze", "report"]):
        worker = WorkerAgent(
            name=f"{cap.capitalize()}Worker",
            capabilities=[cap]
        )
        worker.set_executor(
            lambda d, t=cap: f"{t} result"
        )
        orchestrator.register_worker(worker)
    
    # 创建工作流
    workflow = orchestrator.create_workflow(
        name="ResearchReport",
        description="Research, analyze, and report workflow",
        mode=OrchestrationMode.SEQUENTIAL
    )
    
    # 添加任务
    tasks = []
    for i, cap in enumerate(["research", "analyze", "report"]):
        task = orchestrator.create_task(
            task_type=cap,
            description=f"{cap.capitalize()} task"
        )
        orchestrator.add_task_to_workflow(workflow.workflow_id, task)
        tasks.append(task)
    
    print(f"Created workflow with {len(workflow.tasks)} tasks")
    
    # 执行工作流
    print("\nExecuting workflow...")
    result = await orchestrator.execute_workflow(
        workflow.workflow_id,
        initial_data={"topic": "AI"}
    )
    
    print(f"Workflow result: {result}")


# ==========================================
# 示例 9: 多 Agent 广播
# ==========================================

async def example_broadcast():
    """广播示例"""
    print("\n" + "="*50)
    print("Example 9: Broadcast")
    print("="*50)
    
    bus = get_message_bus()
    bus.reset()
    
    # 创建多个 Agent
    agents = []
    for i in range(3):
        class ListenerAgent(BaseAgent):
            def __init__(self, idx):
                super().__init__(
                    agent_id=f"listener_{idx}",
                    name=f"Listener {idx+1}"
                )
                self.received = []
                
                @self.on(MessageType.BROADCAST)
                async def handle_broadcast(msg):
                    self.received.append(msg.content)
                    print(f"  [{self.name}] Received broadcast: {msg.content}")
        
        agent = ListenerAgent(i)
        agents.append(agent)
    
    print(f"Created {len(agents)} listener agents")
    
    # 广播消息
    print("\nBroadcasting message...")
    await agents[0].broadcast(
        content="Important announcement!",
        topic="announcements"
    )
    
    await asyncio.sleep(0.5)
    
    # 统计接收
    for agent in agents:
        print(f"{agent.name} received {len(agent.received)} messages")


# ==========================================
# 示例 10: 装饰器方式调度任务
# ==========================================

async def example_decorators():
    """装饰器示例"""
    print("\n" + "="*50)
    print("Example 10: Decorators")
    print("="*50)
    
    scheduler = get_scheduler()
    
    # 使用装饰器定义任务
    @scheduled(name="MyTask", priority=MessagePriority.HIGH)
    async def my_task():
        print("  [Decorator Task] Running...")
        await asyncio.sleep(0.2)
        return "Task completed"
    
    @periodic(period_seconds=1.0, initial_delay=0.3)
    async def periodic_task():
        print("  [Periodic Task] Running...")
        return "Periodic"
    
    print("Created decorated tasks")
    print(f"  my_task: {my_task}")
    print(f"  periodic_task: {periodic_task}")


# ==========================================
# 主函数
# ==========================================

async def main():
    """运行所有示例"""
    print("\n" + "#"*60)
    print("Multi-Agent System Examples")
    print("#"*60)
    
    examples = [
        ("Basic Messaging", example_basic_messaging),
        ("Message Builder", example_message_builder),
        ("Worker Collaboration", example_worker_collaboration),
        ("Task Scheduler", example_task_scheduler),
        ("State Management", example_state_management),
        ("Distributed Locks", example_distributed_locks),
        ("Supervisor Mode", example_supervisor_mode),
        ("Workflow", example_workflow),
        ("Broadcast", example_broadcast),
        ("Decorators", example_decorators),
    ]
    
    for name, example_func in examples:
        try:
            await example_func()
            print(f"\n✓ {name} completed\n")
        except Exception as e:
            print(f"\n✗ {name} failed: {e}\n")
            import traceback
            traceback.print_exc()
    
    print("\n" + "#"*60)
    print("All examples completed!")
    print("#"*60)


if __name__ == "__main__":
    asyncio.run(main())
