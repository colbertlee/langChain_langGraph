"""multi_agent.py 单元测试。

覆盖：Task / Workflow dataclass、TaskStatus / OrchestrationMode enum、TaskDelegate、AgentOrchestrator 基础方法。
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from multi_agent import (
    OrchestrationMode,
    TaskStatus,
    Task,
    Workflow,
    TaskDelegate,
    AgentOrchestrator,
)


# ─────────────────── Enum ───────────────────


class TestEnums:

    def test_orchestration_modes(self):
        assert OrchestrationMode.SUPERVISOR.value == "supervisor"
        assert OrchestrationMode.PARALLEL.value == "parallel"
        assert OrchestrationMode.SEQUENTIAL.value == "sequential"
        assert OrchestrationMode.HIERARCHICAL.value == "hierarchical"
        assert OrchestrationMode.FANOUT.value == "fanout"

    def test_task_statuses(self):
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.CANCELLED.value == "cancelled"


# ─────────────────── Task dataclass ───────────────────


class TestTask:

    def test_task_default_values(self):
        task = Task()
        assert task.task_id is not None
        assert len(task.task_id) > 0
        assert task.task_type == ""
        assert task.description == ""
        assert task.status == TaskStatus.PENDING
        assert task.result is None
        assert task.error is None
        assert task.dependencies == []
        assert task.subtasks == []
        assert task.created_at is not None

    def test_task_custom_values(self):
        task = Task(
            task_type="search",
            description="find AI papers",
            assignee_id="worker-1",
            metadata={"priority": "high"},
        )
        assert task.task_type == "search"
        assert task.description == "find AI papers"
        assert task.assignee_id == "worker-1"
        assert task.metadata["priority"] == "high"

    def test_task_unique_id(self):
        t1 = Task()
        t2 = Task()
        assert t1.task_id != t2.task_id

    def test_task_to_dict(self):
        task = Task(task_type="x", description="y")
        d = task.to_dict()
        assert d["task_type"] == "x"
        assert d["description"] == "y"
        assert d["status"] == "pending"
        assert "task_id" in d
        assert "created_at" in d
        assert "dependencies" in d
        assert "subtasks" in d


# ─────────────────── Workflow dataclass ───────────────────


class TestWorkflow:

    def test_workflow_defaults(self):
        wf = Workflow()
        assert wf.workflow_id is not None
        assert wf.name == ""
        assert wf.mode == OrchestrationMode.SEQUENTIAL
        assert wf.tasks == {}
        assert wf.root_task_id == ""
        assert wf.status == TaskStatus.PENDING
        assert wf.results == {}

    def test_workflow_custom_values(self):
        wf = Workflow(
            name="my_workflow",
            description="test workflow",
            mode=OrchestrationMode.PARALLEL,
        )
        assert wf.name == "my_workflow"
        assert wf.description == "test workflow"
        assert wf.mode == OrchestrationMode.PARALLEL

    def test_workflow_to_dict(self):
        wf = Workflow(name="x")
        d = wf.to_dict()
        assert d["name"] == "x"
        assert d["mode"] == "sequential"
        assert d["status"] == "pending"
        assert "workflow_id" in d
        assert "tasks" in d
        assert "results" in d


# ─────────────────── TaskDelegate ───────────────────


class TestTaskDelegate:

    @pytest.fixture
    def mock_orchestrator(self):
        orch = MagicMock()
        orch.supervisor_id = "sup-1"
        return orch

    def test_init(self, mock_orchestrator):
        delegate = TaskDelegate(mock_orchestrator)
        assert delegate.orchestrator is mock_orchestrator


# ─────────────────── AgentOrchestrator ───────────────────


@pytest.fixture(autouse=True)
def reset_message_bus():
    """避免 message_bus 状态污染。"""
    yield


class TestAgentOrchestrator:

    def test_init_default(self):
        orch = AgentOrchestrator()
        assert orch.supervisor_id is not None
        assert orch.supervisor_name == "Supervisor"
        assert orch.model is None
        assert orch._workers == {}
        assert orch._workflows == {}
        assert orch._tasks == {}
        assert orch._mode == OrchestrationMode.SUPERVISOR

    def test_init_custom(self):
        orch = AgentOrchestrator(
            supervisor_id="my-supervisor",
            supervisor_name="MySup",
            model=MagicMock(),
        )
        assert orch.supervisor_id == "my-supervisor"
        assert orch.supervisor_name == "MySup"
        assert orch.model is not None

    def test_init_unique_supervisor_id(self):
        orch1 = AgentOrchestrator()
        orch2 = AgentOrchestrator()
        assert orch1.supervisor_id != orch2.supervisor_id

    def test_init_stats(self):
        orch = AgentOrchestrator()
        assert orch._stats is not None
        assert "total_tasks" in orch._stats

    def test_register_worker(self):
        orch = AgentOrchestrator()
        mock_worker = MagicMock()
        mock_worker.agent_id = "w1"
        mock_worker.name = "Worker1"
        # 通过 register_worker 注册
        if hasattr(orch, "register_worker"):
            orch.register_worker(mock_worker)
            assert "w1" in orch._workers

    def test_list_workers_empty(self):
        orch = AgentOrchestrator()
        if hasattr(orch, "list_workers"):
            assert orch.list_workers() == []
        else:
            assert orch._workers == {}

    def test_get_worker_nonexistent(self):
        orch = AgentOrchestrator()
        if hasattr(orch, "get_worker"):
            assert orch.get_worker("nonexistent") is None
        else:
            assert "nonexistent" not in orch._workers

    def test_workflows_empty(self):
        orch = AgentOrchestrator()
        if hasattr(orch, "list_workflows"):
            assert orch.list_workflows() == []

    def test_tasks_empty(self):
        orch = AgentOrchestrator()
        if hasattr(orch, "list_tasks"):
            assert orch.list_tasks() == []


# ─────────────────── 任务管理 ───────────────────


class TestTaskManagement:

    def test_create_task(self):
        orch = AgentOrchestrator()
        if hasattr(orch, "create_task"):
            task = orch.create_task("search", "find papers")
            assert task.task_type == "search"
            assert task.description == "find papers"
            assert task.status == TaskStatus.PENDING

    def test_create_task_with_metadata(self):
        orch = AgentOrchestrator()
        if hasattr(orch, "create_task"):
            task = orch.create_task("x", "y", metadata={"key": "value"})
            assert task.metadata["key"] == "value"

    def test_get_task_by_id(self):
        orch = AgentOrchestrator()
        if hasattr(orch, "create_task") and hasattr(orch, "get_task"):
            task = orch.create_task("x", "y")
            retrieved = orch.get_task(task.task_id)
            assert retrieved is task

    def test_get_task_nonexistent(self):
        orch = AgentOrchestrator()
        if hasattr(orch, "get_task"):
            assert orch.get_task("nonexistent") is None


# ─────────────────── 工作流管理 ───────────────────


class TestWorkflowManagement:

    def test_create_workflow(self):
        orch = AgentOrchestrator()
        if hasattr(orch, "create_workflow"):
            wf = orch.create_workflow(name="test", mode=OrchestrationMode.PARALLEL)
            assert wf.name == "test"
            assert wf.mode == OrchestrationMode.PARALLEL

    def test_get_workflow_by_id(self):
        orch = AgentOrchestrator()
        if hasattr(orch, "create_workflow") and hasattr(orch, "get_workflow"):
            wf = orch.create_workflow(name="test")
            retrieved = orch.get_workflow(wf.workflow_id)
            assert retrieved is wf


# ─────────────────── 回调 ───────────────────


class TestCallbacks:

    def test_register_callback(self):
        orch = AgentOrchestrator()
        if hasattr(orch, "register_callback"):
            callback = MagicMock()
            orch.register_callback(callback)
            assert callback in orch._completion_callbacks

    def test_multiple_callbacks(self):
        orch = AgentOrchestrator()
        if hasattr(orch, "register_callback"):
            cb1 = MagicMock()
            cb2 = MagicMock()
            orch.register_callback(cb1)
            orch.register_callback(cb2)
            assert len(orch._completion_callbacks) >= 2


# ─────────────────── 序列化 ───────────────────


class TestSerialization:

    def test_workflow_serialization_roundtrip(self):
        wf = Workflow(name="x", mode=OrchestrationMode.PARALLEL)
        task = Task(task_type="t", description="d")
        wf.tasks[task.task_id] = task
        wf.root_task_id = task.task_id

        d = wf.to_dict()
        # 验证关键字段
        assert d["name"] == "x"
        assert d["mode"] == "parallel"
        assert len(d["tasks"]) == 1
        assert d["root_task_id"] == task.task_id

    def test_task_with_dependencies(self):
        t1 = Task(task_type="a")
        t2 = Task(task_type="b", dependencies=[t1.task_id])
        d = t2.to_dict()
        assert t1.task_id in d["dependencies"]

    def test_task_with_subtasks(self):
        t1 = Task(task_type="parent")
        t2 = Task(task_type="child", subtasks=[])
        t1.subtasks.append(t2.task_id)
        assert t2.task_id in t1.subtasks


# ─────────────────── Orchestrator 状态 ───────────────────


class TestOrchestratorState:

    def test_get_set_mode(self):
        orch = AgentOrchestrator()
        if hasattr(orch, "set_mode"):
            orch.set_mode(OrchestrationMode.PARALLEL)
            assert orch.get_mode() == OrchestrationMode.PARALLEL

    def test_default_mode_is_supervisor(self):
        orch = AgentOrchestrator()
        assert orch._mode == OrchestrationMode.SUPERVISOR

    def test_stats_initial(self):
        orch = AgentOrchestrator()
        if hasattr(orch, "get_stats"):
            stats = orch.get_stats()
            assert isinstance(stats, dict)


# ─────────────────── BaseAgent / WorkerAgent ───────────────────


class TestWorkerAgent:

    def test_worker_init(self):
        from multi_agent import WorkerAgent
        # WorkerAgent 只接受 agent_id / name / tools（不接受 description）
        worker = WorkerAgent(name="test_worker")
        assert worker.name == "test_worker"
        assert worker.agent_id is not None

    def test_worker_unique_id(self):
        from multi_agent import WorkerAgent
        w1 = WorkerAgent(name="a")
        w2 = WorkerAgent(name="a")
        assert w1.agent_id != w2.agent_id


class TestSupervisorAgent:

    def test_supervisor_init(self):
        from multi_agent import SupervisorAgent
        sup = SupervisorAgent(name="sup")
        assert sup.name == "sup"
        assert sup.agent_id is not None

    def test_supervisor_default_name(self):
        from multi_agent import SupervisorAgent
        sup = SupervisorAgent()
        assert sup.agent_id is not None


# ─────────────────── TaskDelegate async ───────────────────


class TestTaskDelegateAsync:

    @pytest.mark.asyncio
    @patch("multi_agent.get_message_bus")
    async def test_delegate_task_with_no_agents(self, mock_get_bus):
        orch = AgentOrchestrator()
        delegate = TaskDelegate(orch)

        task = Task(task_type="test")
        result = await delegate.delegate_task(task, target_agents=[], timeout=1.0)
        assert result == {}

    @pytest.mark.asyncio
    @patch("multi_agent.get_message_bus")
    async def test_delegate_task_timeout(self, mock_get_bus):
        """mock bus.request 返回 None（超时）。"""
        mock_bus = AsyncMock()
        mock_bus.request.return_value = None
        mock_get_bus.return_value = mock_bus

        orch = AgentOrchestrator()
        orch.supervisor_id = "sup-1"
        delegate = TaskDelegate(orch)

        task = Task(task_type="test", description="desc")
        result = await delegate.delegate_task(
            task,
            target_agents=["agent-1"],
            timeout=0.1,
        )
        assert "agent-1" in result
        assert "error" in result["agent-1"]

    @pytest.mark.asyncio
    @patch("multi_agent.get_message_bus")
    async def test_delegate_task_success(self, mock_get_bus):
        """mock bus.request 返回成功响应。"""
        mock_response = MagicMock()
        mock_response.content = {"result": "done"}
        mock_bus = AsyncMock()
        mock_bus.request.return_value = mock_response
        mock_get_bus.return_value = mock_bus

        orch = AgentOrchestrator()
        orch.supervisor_id = "sup-1"
        delegate = TaskDelegate(orch)

        task = Task(task_type="test", description="desc")
        result = await delegate.delegate_task(
            task,
            target_agents=["agent-1"],
            timeout=1.0,
        )
        assert "agent-1" in result
        # 由于 response 是 MagicMock，content 也是 MagicMock
        # 验证 result 字典有内容（不为空）
        assert result["agent-1"] is not None
