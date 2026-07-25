"""
异步任务调度器

提供基于优先级的任务调度、任务队列管理、
超时控制、重试机制、定时任务等功能。
"""

import asyncio
import uuid
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set
from enum import Enum
from dataclasses import dataclass, field
from collections import defaultdict
import heapq

from message_protocol import MessagePriority, MessageType
from message_bus import get_message_bus

logger = logging.getLogger(__name__)


class TaskState(Enum):
    """任务状态"""
    PENDING = "pending"      # 等待调度
    SCHEDULED = "scheduled"  # 已调度
    RUNNING = "running"      # 运行中
    COMPLETED = "completed"  # 完成
    FAILED = "failed"        # 失败
    CANCELLED = "cancelled"  # 取消
    TIMEOUT = "timeout"      # 超时


class ScheduleType(Enum):
    """调度类型"""
    IMMEDIATE = "immediate"  # 立即执行
    DELAYED = "delayed"      # 延迟执行
    PERIODIC = "periodic"    # 周期性执行
    CRON = "cron"            # Cron 表达式调度


@dataclass
class ScheduledTask:
    """调度任务"""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    func: Callable = None
    args: tuple = ()
    kwargs: Dict = field(default_factory=dict)
    
    # 调度配置
    schedule_type: ScheduleType = ScheduleType.IMMEDIATE
    delay_seconds: float = 0  # 延迟时间
    period_seconds: float = 0  # 周期时间
    cron_expr: str = ""  # Cron 表达式（简化版）
    
    # 执行配置
    priority: MessagePriority = MessagePriority.NORMAL
    timeout: float = 60.0  # 任务超时时间
    max_retries: int = 3
    retry_delay: float = 1.0  # 重试延迟
    
    # 状态
    state: TaskState = TaskState.PENDING
    retry_count: int = 0
    result: Any = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    scheduled_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    next_run_at: Optional[str] = None
    
    # 元数据
    metadata: Dict = field(default_factory=dict)
    
    def __lt__(self, other: 'ScheduledTask'):
        """用于优先级队列比较"""
        if self.priority.value != other.priority.value:
            return self.priority.value < other.priority.value
        return self.created_at < other.created_at
    
    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "schedule_type": self.schedule_type.value,
            "priority": self.priority.value,
            "state": self.state.value,
            "retry_count": self.retry_count,
            "created_at": self.created_at,
            "scheduled_at": self.scheduled_at,
            "completed_at": self.completed_at,
            "error": self.error
        }


class TaskScheduler:
    """
    异步任务调度器
    
    功能：
    - 优先级调度
    - 延迟任务
    - 周期性任务
    - 任务超时控制
    - 自动重试
    - 任务取消
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        # 任务存储
        self._tasks: Dict[str, ScheduledTask] = {}
        self._pending_queue: List[ScheduledTask] = []  # 优先级队列
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._periodic_tasks: Dict[str, asyncio.Task] = {}  # 周期性任务
        
        # 回调
        self._completion_callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._state_change_callbacks: List[Callable] = []
        
        # 运行状态
        self._running = False
        self._scheduler_task: Optional[asyncio.Task] = None
        
        # 统计
        self._stats = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "cancelled_tasks": 0
        }
        
        # 消息总线
        self._bus = get_message_bus()
        
        logger.info("TaskScheduler initialized")
    
    @classmethod
    def get_instance(cls) -> 'TaskScheduler':
        return cls()
    
    # ==========================================
    # 任务创建
    # ==========================================
    
    def create_task(
        self,
        func: Callable,
        name: str = "",
        args: tuple = None,
        kwargs: Dict = None,
        schedule_type: ScheduleType = ScheduleType.IMMEDIATE,
        delay_seconds: float = 0,
        period_seconds: float = 0,
        priority: MessagePriority = MessagePriority.NORMAL,
        timeout: float = 60.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        metadata: Dict = None
    ) -> ScheduledTask:
        """创建调度任务"""
        task = ScheduledTask(
            task_id=str(uuid.uuid4()),
            name=name or func.__name__,
            func=func,
            args=args or (),
            kwargs=kwargs or {},
            schedule_type=schedule_type,
            delay_seconds=delay_seconds,
            period_seconds=period_seconds,
            priority=priority,
            timeout=timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
            metadata=metadata or {}
        )
        
        self._tasks[task.task_id] = task
        self._stats["total_tasks"] += 1
        
        logger.debug(f"Task created: {task.task_id} ({task.name})")
        return task
    
    def schedule(
        self,
        func: Callable,
        name: str = "",
        args: tuple = None,
        kwargs: Dict = None,
        delay_seconds: float = 0,
        priority: MessagePriority = MessagePriority.NORMAL,
        timeout: float = 60.0,
        max_retries: int = 3
    ) -> str:
        """调度一次性任务（延迟或立即）"""
        task = self.create_task(
            func=func,
            name=name,
            args=args,
            kwargs=kwargs,
            schedule_type=ScheduleType.DELAYED if delay_seconds > 0 else ScheduleType.IMMEDIATE,
            delay_seconds=delay_seconds,
            priority=priority,
            timeout=timeout,
            max_retries=max_retries
        )
        
        self._add_to_queue(task)
        
        if self._running:
            self._wake_up()
        
        return task.task_id
    
    def schedule_periodic(
        self,
        func: Callable,
        name: str = "",
        args: tuple = None,
        kwargs: Dict = None,
        period_seconds: float = 60.0,
        initial_delay: float = 0,
        priority: MessagePriority = MessagePriority.NORMAL,
        timeout: float = 60.0
    ) -> str:
        """调度周期性任务"""
        task = self.create_task(
            func=func,
            name=name,
            args=args,
            kwargs=kwargs,
            schedule_type=ScheduleType.PERIODIC,
            delay_seconds=initial_delay,
            period_seconds=period_seconds,
            priority=priority,
            timeout=timeout
        )
        
        self._tasks[task.task_id] = task
        
        if self._running:
            self._start_periodic_task(task)
        
        return task.task_id
    
    def _add_to_queue(self, task: ScheduledTask):
        """添加任务到队列"""
        task.state = TaskState.SCHEDULED
        task.scheduled_at = datetime.now().isoformat()
        heapq.heappush(self._pending_queue, task)
    
    def _wake_up(self):
        """唤醒调度器"""
        if self._scheduler_task and not self._scheduler_task.done():
            self._scheduler_task.cancel()
    
    # ==========================================
    # 任务控制
    # ==========================================
    
    def cancel(self, task_id: str) -> bool:
        """取消任务"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        if task.state in (TaskState.COMPLETED, TaskState.CANCELLED):
            return False
        
        # 如果正在运行，取消 asyncio Task
        if task_id in self._running_tasks:
            self._running_tasks[task_id].cancel()
        
        # 如果是周期性任务
        if task_id in self._periodic_tasks:
            self._periodic_tasks[task_id].cancel()
        
        task.state = TaskState.CANCELLED
        self._stats["cancelled_tasks"] += 1
        
        logger.info(f"Task cancelled: {task_id}")
        self._notify_state_change(task)
        
        return True
    
    async def wait_for(self, task_id: str, timeout: float = None) -> Any:
        """等待任务完成"""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        
        start_time = asyncio.get_event_loop().time()
        check_interval = 0.1
        
        while True:
            if task.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.TIMEOUT):
                if task.state == TaskState.COMPLETED:
                    return task.result
                elif task.state == TaskState.FAILED:
                    raise Exception(task.error or "Task failed")
                elif task.state == TaskState.CANCELLED:
                    raise asyncio.CancelledError("Task was cancelled")
                elif task.state == TaskState.TIMEOUT:
                    raise asyncio.TimeoutError("Task timed out")
            
            if timeout and (asyncio.get_event_loop().time() - start_time) >= timeout:
                raise asyncio.TimeoutError(f"Timeout waiting for task: {task_id}")
            
            await asyncio.sleep(check_interval)
    
    # ==========================================
    # 任务执行
    # ==========================================
    
    async def _execute_task(self, task: ScheduledTask):
        """执行单个任务"""
        task.state = TaskState.RUNNING
        task.started_at = datetime.now().isoformat()
        
        logger.debug(f"Executing task: {task.task_id}")
        self._notify_state_change(task)
        
        try:
            # 创建带超时的执行
            if asyncio.iscoroutinefunction(task.func):
                result = await asyncio.wait_for(
                    task.func(*task.args, **task.kwargs),
                    timeout=task.timeout
                )
            else:
                # 同步函数在线程池中执行
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: task.func(*task.args, **task.kwargs)),
                    timeout=task.timeout
                )
            
            task.state = TaskState.COMPLETED
            task.result = result
            task.completed_at = datetime.now().isoformat()
            
            self._stats["completed_tasks"] += 1
            logger.debug(f"Task completed: {task.task_id}")
            
            # 触发回调
            self._trigger_completion_callbacks(task)
            
        except asyncio.TimeoutError:
            task.state = TaskState.TIMEOUT
            task.error = f"Task timeout after {task.timeout}s"
            task.completed_at = datetime.now().isoformat()
            
            logger.warning(f"Task timeout: {task.task_id}")
            await self._handle_task_failure(task, task.error)
            
        except asyncio.CancelledError:
            task.state = TaskState.CANCELLED
            self._stats["cancelled_tasks"] += 1
            logger.info(f"Task cancelled: {task.task_id}")
            
        except Exception as e:
            task.error = str(e)
            logger.error(f"Task error: {task.task_id} - {e}")
            await self._handle_task_failure(task, str(e))
        
        finally:
            self._notify_state_change(task)
            
            # 如果是周期性任务，重新调度
            if task.schedule_type == ScheduleType.PERIODIC and task.state != TaskState.CANCELLED:
                await self._reschedule_periodic(task)
            
            # 从运行任务中移除
            if task.task_id in self._running_tasks:
                del self._running_tasks[task.task_id]
    
    async def _handle_task_failure(self, task: ScheduledTask, error: str):
        """处理任务失败"""
        if task.retry_count < task.max_retries:
            task.retry_count += 1
            task.state = TaskState.SCHEDULED
            
            # 延迟重试
            logger.info(f"Retrying task {task.task_id} (attempt {task.retry_count}/{task.max_retries})")
            
            await asyncio.sleep(task.retry_delay)
            self._add_to_queue(task)
            self._wake_up()
        else:
            task.state = TaskState.FAILED
            task.completed_at = datetime.now().isoformat()
            self._stats["failed_tasks"] += 1
            
            self._trigger_completion_callbacks(task)
    
    async def _reschedule_periodic(self, task: ScheduledTask):
        """重新调度周期性任务"""
        task.next_run_at = (
            datetime.now() + timedelta(seconds=task.period_seconds)
        ).isoformat()
        
        # 延迟后重新调度
        await asyncio.sleep(task.delay_seconds)
        
        if task.task_id in self._tasks and task.state != TaskState.CANCELLED:
            new_task = ScheduledTask(
                task_id=str(uuid.uuid4()),
                name=task.name,
                func=task.func,
                args=task.args,
                kwargs=task.kwargs,
                schedule_type=ScheduleType.PERIODIC,
                period_seconds=task.period_seconds,
                priority=task.priority,
                timeout=task.timeout,
                max_retries=task.max_retries,
                retry_delay=task.retry_delay,
                metadata=task.metadata
            )
            
            self._tasks[new_task.task_id] = new_task
            self._start_periodic_task(new_task)
    
    def _start_periodic_task(self, task: ScheduledTask):
        """启动周期性任务"""
        async def periodic_wrapper():
            # 初始延迟
            if task.delay_seconds > 0:
                await asyncio.sleep(task.delay_seconds)
            
            while task.state != TaskState.CANCELLED:
                # 创建新任务执行
                exec_task = asyncio.create_task(self._execute_task(task))
                self._running_tasks[task.task_id] = exec_task
                
                # 等待当前周期完成
                await asyncio.sleep(task.period_seconds)
        
        self._periodic_tasks[task.task_id] = asyncio.create_task(periodic_wrapper())
    
    # ==========================================
    # 调度循环
    # ==========================================
    
    async def start(self):
        """启动调度器"""
        if self._running:
            return
        
        self._running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("TaskScheduler started")
    
    async def stop(self):
        """停止调度器"""
        self._running = False
        
        # 取消所有任务
        for task_id in list(self._running_tasks.keys()):
            self.cancel(task_id)
        
        for task_id in list(self._periodic_tasks.keys()):
            self.cancel(task_id)
        
        # 取消调度循环
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        
        logger.info("TaskScheduler stopped")
    
    async def _scheduler_loop(self):
        """调度循环"""
        while self._running:
            try:
                # 处理延迟任务
                await self._process_delayed_tasks()
                
                # 从队列中获取任务执行
                while self._pending_queue:
                    task = heapq.heappop(self._pending_queue)
                    
                    if task.state == TaskState.CANCELLED:
                        continue
                    
                    # 执行任务
                    exec_task = asyncio.create_task(self._execute_task(task))
                    self._running_tasks[task.task_id] = exec_task
                
                # 等待一段时间再检查
                await asyncio.sleep(0.1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                await asyncio.sleep(1)
    
    async def _process_delayed_tasks(self):
        """处理延迟任务"""
        current_time = datetime.now()
        
        for task in list(self._tasks.values()):
            if task.state != TaskState.SCHEDULED:
                continue
            
            if task.schedule_type == ScheduleType.DELAYED and task.delay_seconds > 0:
                if not task.scheduled_at:
                    continue
                
                scheduled_time = datetime.fromisoformat(task.scheduled_at)
                elapsed = (current_time - scheduled_time).total_seconds()
                
                if elapsed >= task.delay_seconds:
                    # 延迟时间已过，立即执行
                    task.delay_seconds = 0
                    task.schedule_type = ScheduleType.IMMEDIATE
    
    # ==========================================
    # 回调管理
    # ==========================================
    
    def on_completion(self, task_id: str, callback: Callable):
        """注册任务完成回调"""
        self._completion_callbacks[task_id].append(callback)
    
    def on_state_change(self, callback: Callable):
        """注册状态变化回调"""
        self._state_change_callbacks.append(callback)
    
    def _trigger_completion_callbacks(self, task: ScheduledTask):
        """触发完成回调"""
        callbacks = self._completion_callbacks.get(task.task_id, [])
        
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(task))
                else:
                    callback(task)
            except Exception as e:
                logger.error(f"Completion callback error: {e}")
        
        # 清除回调
        if task.task_id in self._completion_callbacks:
            del self._completion_callbacks[task.task_id]
    
    def _notify_state_change(self, task: ScheduledTask):
        """通知状态变化"""
        for callback in self._state_change_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(task))
                else:
                    callback(task)
            except Exception as e:
                logger.error(f"State change callback error: {e}")
    
    # ==========================================
    # 查询接口
    # ==========================================
    
    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """获取任务"""
        return self._tasks.get(task_id)
    
    def list_tasks(
        self,
        state: TaskState = None,
        limit: int = 100
    ) -> List[ScheduledTask]:
        """列出任务"""
        tasks = list(self._tasks.values())
        
        if state:
            tasks = [t for t in tasks if t.state == state]
        
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)[:limit]
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            **self._stats,
            "pending_tasks": len(self._pending_queue),
            "running_tasks": len(self._running_tasks),
            "periodic_tasks": len(self._periodic_tasks)
        }


def get_scheduler() -> TaskScheduler:
    """获取任务调度器实例"""
    return TaskScheduler.get_instance()


# ==========================================
# 便捷装饰器
# ==========================================

def scheduled(
    name: str = "",
    delay_seconds: float = 0,
    priority: MessagePriority = MessagePriority.NORMAL,
    timeout: float = 60.0,
    max_retries: int = 3
):
    """调度任务的装饰器"""
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            scheduler = get_scheduler()
            task_id = scheduler.schedule(
                func=func,
                name=name or func.__name__,
                args=args,
                kwargs=kwargs,
                delay_seconds=delay_seconds,
                priority=priority,
                timeout=timeout,
                max_retries=max_retries
            )
            return task_id
        
        # 如果是异步函数
        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                scheduler = get_scheduler()
                return scheduler.schedule(
                    func=func,
                    name=name or func.__name__,
                    args=args,
                    kwargs=kwargs,
                    delay_seconds=delay_seconds,
                    priority=priority,
                    timeout=timeout,
                    max_retries=max_retries
                )
            return async_wrapper
        
        return wrapper
    return decorator


def periodic(period_seconds: float = 60.0, initial_delay: float = 0):
    """周期性任务的装饰器"""
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            scheduler = get_scheduler()
            return scheduler.schedule_periodic(
                func=func,
                name=func.__name__,
                args=args,
                kwargs=kwargs,
                period_seconds=period_seconds,
                initial_delay=initial_delay
            )
        return wrapper
    return decorator
