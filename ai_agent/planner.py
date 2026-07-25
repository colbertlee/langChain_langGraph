"""
Planner（任务规划器）

把一个高层级目标拆解为可执行计划（Plan）：
- Plan: 一组 Step + 依赖关系
- Step: 任务步骤（capability / description / deps / status / result）
- PlanExecutor: 按依赖图顺序执行（并行/串行混合）

支持：
- 基于规则的分解（task_intent 触发）
- 关键路径识别（critical path）
- 失败补偿（replan / skip downstream）
- 与现有 Orchestrator / WorkerAgent 协同

使用：
    planner = get_planner()
    plan = planner.create_plan("搜索AI新闻并写报告")
    executor = PlanExecutor(plan, orchestrator)
    result = await executor.run()
"""

import asyncio
import time
import uuid
import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from threading import Lock
from collections import defaultdict

# 自引用（推迟到文件尾部）

logger = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

class StepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"           # deps 都满足，等待执行
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"       # 因 dep 失败被跳过


@dataclass
class Step:
    """计划中的一个步骤"""
    step_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    capability: str = "general"
    description: str = ""
    depends_on: List[str] = field(default_factory=list)  # step_id 列表
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_ms: Optional[float] = None
    assigned_worker: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "step_id": self.step_id,
            "capability": self.capability,
            "description": self.description,
            "depends_on": self.depends_on,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "assigned_worker": self.assigned_worker,
            "metadata": self.metadata,
        }


@dataclass
class Plan:
    """一个完整计划"""
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    goal: str = ""
    steps: List[Step] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "draft"  # draft / executing / completed / failed / replanned

    # 内部索引
    _step_index: Dict[str, Step] = field(default_factory=dict, repr=False)
    _next_id: int = 0

    def add_step(
        self,
        capability: str,
        description: str,
        depends_on: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
    ) -> Step:
        s = Step(
            capability=capability,
            description=description,
            depends_on=depends_on or [],
            metadata=metadata or {},
        )
        self.steps.append(s)
        self._step_index[s.step_id] = s
        return s

    def get_step(self, step_id: str) -> Optional[Step]:
        return self._step_index.get(step_id)

    def critical_path(self) -> List[Step]:
        """最长依赖链（粗略：找没有后继的关键步骤）"""
        # 用反向拓扑：每个 step 的出度
        out_degree = defaultdict(int)
        for s in self.steps:
            for dep in s.depends_on:
                out_degree[dep] += 1
        # 关键路径 = 出度为 0 的步骤（"叶子"）+ 沿依赖回溯
        leaves = [s for s in self.steps if out_degree[s.step_id] == 0]
        # 简化：返回所有叶子，按依赖顺序
        path: List[Step] = []
        visited = set()

        def add_to_path(s):
            if s.step_id in visited:
                return
            visited.add(s.step_id)
            for dep in s.depends_on:
                add_to_path(self._step_index[dep])
            path.append(s)

        for leaf in leaves:
            add_to_path(leaf)
        return path

    def ready_steps(self) -> List[Step]:
        """返回当前可执行的步骤（deps 全部 COMPLETED）"""
        return [
            s for s in self.steps
            if s.status == StepStatus.PENDING
            and all(
                self._step_index.get(d) and self._step_index[d].status == StepStatus.COMPLETED
                for d in s.depends_on
            )
        ]

    def progress(self) -> Tuple[int, int]:
        done = sum(1 for s in self.steps if s.status in {
            StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED
        })
        return done, len(self.steps)

    def to_dict(self) -> Dict:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "status": self.status,
            "created_at": self.created_at,
            "steps": [s.to_dict() for s in self.steps],
            "progress": self.progress(),
            "critical_path": [s.step_id for s in self.critical_path()],
        }


# ============================================================
# Planner（规划器）
# ============================================================

class Planner:
    """
    任务规划器

    提供：
    - create_plan_from_intent():  根据 TaskIntent 创建 Plan
    - create_plan_from_goal():    根据目标字符串创建 Plan
    - replan():                   失败后重新规划（跳过失败的步骤，让下游也跳过）
    """

    def __init__(self):
        self._lock = Lock()
        self._observability = None
        try:
            from observability import get_observability
            self._observability = get_observability()
        except Exception:
            pass

    # ----------------- 规则式 Plan 生成 -----------------

    def create_plan_from_intent(
        self,
        intent,  # TaskIntent（来自 task_intent 模块）
        session_id: Optional[str] = None,
    ) -> Plan:
        """
        根据 TaskIntent 创建一个 Plan。

        逻辑：
        - 如果 intent.decomposition 不为空，按它展开
        - 否则把每个 capability 当作一个步骤
        - 串行串联（不并行）
        """
        plan = Plan(
            goal=intent.task_type + (": " + session_id if session_id else ""),
            metadata={
                "task_type": intent.task_type,
                "session_id": session_id,
                "negotiation_hint": intent.negotiation_hint,
            },
        )

        # 拿到 capability 序列
        if intent.decomposition:
            capabilities = intent.decomposition
        else:
            capabilities = list(intent.capabilities)

        prev_step_id = None
        for i, cap in enumerate(capabilities):
            step = plan.add_step(
                capability=cap,
                description=f"Step {i+1}: {cap}",
                depends_on=[prev_step_id] if prev_step_id else [],
            )
            prev_step_id = step.step_id

        # 如果 intent.task_type 包含 negotiation / auction，附加同步步骤
        if intent.negotiation_hint == "negotiate":
            plan.add_step(
                capability="negotiation",
                description="Negotiate final terms",
                depends_on=[prev_step_id] if prev_step_id else [],
            )
        elif intent.negotiation_hint == "auction":
            plan.add_step(
                capability="auction",
                description="Auction for best fit",
                depends_on=[prev_step_id] if prev_step_id else [],
            )

        self._publish_event("plan_created", plan)
        return plan

    def create_plan_from_goal(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Plan:
        """
        根据目标字符串创建 Plan（用 TaskIntentRegistry 识别 intent）
        """
        from task_intent import get_task_intent_registry
        registry = get_task_intent_registry()
        intent = registry.detect_intent(goal)
        return self.create_plan_from_intent(intent, session_id=context.get("session_id") if context else None)

    def create_research_plan(self, topic: str) -> Plan:
        """内置：研究类 plan"""
        plan = Plan(goal=f"Research: {topic}")
        s_search = plan.add_step(
            capability="search",
            description=f"Search for information about {topic}",
        )
        s_analyze = plan.add_step(
            capability="analysis",
            description=f"Analyze the search results for {topic}",
            depends_on=[s_search.step_id],
        )
        s_write = plan.add_step(
            capability="write",
            description=f"Write the research report on {topic}",
            depends_on=[s_analyze.step_id],
        )
        self._publish_event("plan_created", plan)
        return plan

    def create_code_plan(self, requirement: str) -> Plan:
        """内置：编码类 plan"""
        plan = Plan(goal=f"Code: {requirement}")
        s_design = plan.add_step(
            capability="analysis",
            description=f"Design solution for: {requirement}",
        )
        s_code = plan.add_step(
            capability="code",
            description=f"Implement: {requirement}",
            depends_on=[s_design.step_id],
        )
        s_test = plan.add_step(
            capability="code",  # code agent 测试也行
            description=f"Verify implementation: {requirement}",
            depends_on=[s_code.step_id],
        )
        self._publish_event("plan_created", plan)
        return plan

    def replan(
        self,
        plan: Plan,
        failed_step_id: str,
        strategy: str = "skip_downstream",
    ) -> Plan:
        """
        失败后重新规划：
        - skip_downstream: 把所有依赖 failed 的步骤都标 SKIPPED（failed 本身保持 FAILED）
        - retry: 把 failed 标 PENDING 让其重试
        - abort: 把 plan.status = failed
        """
        failed = plan.get_step(failed_step_id)
        # 保持 failed 状态为 FAILED，不改为 SKIPPED

        if strategy == "skip_downstream":
            # 找所有依赖 failed 的步骤（包括间接）
            affected = set([failed_step_id])

            def collect_dependents(step_id):
                for s in plan.steps:
                    if step_id in s.depends_on and s.step_id not in affected:
                        affected.add(s.step_id)
                        collect_dependents(s.step_id)

            collect_dependents(failed_step_id)
            for sid in affected:
                if sid == failed_step_id:
                    continue  # failed 本身保持 FAILED
                s = plan.get_step(sid)
                if s and s.status in {StepStatus.PENDING, StepStatus.READY}:
                    s.status = StepStatus.SKIPPED

            plan.status = "replanned"

        elif strategy == "retry":
            if failed:
                failed.status = StepStatus.PENDING
                failed.error = None

        elif strategy == "abort":
            # 跳过所有 PENDING/READY，保留 failed
            for s in plan.steps:
                if s.status in {StepStatus.PENDING, StepStatus.READY}:
                    s.status = StepStatus.SKIPPED
            plan.status = "failed"

        self._publish_event("plan_replanned", plan)
        return plan

    # ----------------- 内部 -----------------

    def _publish_event(self, event_type: str, plan: Plan) -> None:
        if not self._observability:
            return
        try:
            self._observability.publish_event(
                event_type,
                source="planner",
                payload={
                    "plan_id": plan.plan_id,
                    "goal": plan.goal,
                    "steps": len(plan.steps),
                },
            )
        except Exception:
            pass


# ============================================================
# PlanExecutor
# ============================================================

class PlanExecutor:
    """
    计划执行器：按依赖图执行 Plan

    阶段：
    1. 把所有 PENDING 步骤中 deps 都满足的标 READY
    2. 并行执行所有 READY 步骤
    3. 每个完成后检查是否解锁新步骤
    4. 失败时可选 replan
    """

    def __init__(
        self,
        plan: Plan,
        step_runner: Callable[[Step], Any],
        on_step_complete: Optional[Callable[[Step], None]] = None,
        on_step_failed: Optional[Callable[[Step], Optional[str]]] = None,
        # on_step_failed 返回 "skip_downstream"/"retry"/"abort"/None
        max_concurrent_steps: int = 4,
    ):
        self.plan = plan
        self.step_runner = step_runner  # async def runner(step) -> result
        self.on_step_complete = on_step_complete
        self.on_step_failed = on_step_failed
        self.max_concurrent_steps = max_concurrent_steps
        self._semaphore = asyncio.Semaphore(max_concurrent_steps)

    async def run(self) -> Plan:
        """执行整个 plan"""
        self.plan.status = "executing"
        sem = self._semaphore

        async def run_step(step: Step):
            async with sem:
                if step.status not in (StepStatus.PENDING, StepStatus.READY):
                    return
                step.status = StepStatus.RUNNING
                step.started_at = time.time()
                try:
                    result = await self.step_runner(step)
                    step.result = result
                    step.status = StepStatus.COMPLETED
                    step.completed_at = time.time()
                    step.duration_ms = (step.completed_at - step.started_at) * 1000.0
                    if self.on_step_complete:
                        try:
                            self.on_step_complete(step)
                        except Exception:
                            pass
                except Exception as e:
                    step.error = str(e)
                    step.completed_at = time.time()
                    step.duration_ms = (step.completed_at - step.started_at) * 1000.0
                    # 先标 FAILED（无论 replan 策略）
                    step.status = StepStatus.FAILED
                    strategy = None
                    if self.on_step_failed:
                        try:
                            strategy = self.on_step_failed(step)
                        except Exception:
                            strategy = None
                    if strategy == "retry":
                        step.status = StepStatus.PENDING
                        step.error = None
                    else:
                        # 默认 skip_downstream
                        Planner().replan(
                            self.plan, step.step_id,
                            strategy=strategy or "skip_downstream",
                        )

        while True:
            ready = self.plan.ready_steps()
            if not ready:
                # 检查是否完成
                done, total = self.plan.progress()
                if done == total:
                    break
                # 还有 PENDING 但没有 READY（说明有环或失败）
                pending_or_ready = [
                    s for s in self.plan.steps
                    if s.status in {StepStatus.PENDING, StepStatus.READY}
                ]
                if not pending_or_ready:
                    break
                # 异常状态：失败 / 死锁
                break

            # 标记为 ready
            for s in ready:
                s.status = StepStatus.READY

            # 并行执行所有 READY
            tasks = [run_step(s) for s in ready]
            await asyncio.gather(*tasks, return_exceptions=True)

        # 完成态
        if any(s.status == StepStatus.FAILED for s in self.plan.steps):
            self.plan.status = "failed"
        else:
            self.plan.status = "completed"

        return self.plan


# ============================================================
# 全局单例
# ============================================================

_planner: Optional[Planner] = None


def get_planner() -> Planner:
    global _planner
    if _planner is None:
        _planner = Planner()
    return _planner


def reset_planner() -> None:
    """重置（测试用）"""
    global _planner
    _planner = None