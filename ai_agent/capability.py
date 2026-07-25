"""
能力发现 + 负载均衡模块

两个相互独立又相互协作的组件：
1. CapabilityRegistry  集中存储 worker 能力画像，支持语义匹配和负载查询
2. LoadBalancer         基于多维评分的负载均衡策略

设计目标：
- 解耦 Worker 与 Orchestrator：注册表集中，Worker 只管上报
- 评分透明：选 worker 时能看到评分明细（哪个维度压低了）
- 策略可插拔：least_loaded / score_based / weighted_round_robin

使用流程：
    Worker 上线时：
        registry.register(worker_id, CapabilityProfile(...))
    Worker 状态变化：
        registry.update_metrics(worker_id, ...)
    Orchestrator 选 worker：
        candidates = registry.find(capability="search")
        chosen = load_balancer.select(candidates, strategy="score_based")
"""

import time
import asyncio
import logging
import uuid
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Iterable
from dataclasses import dataclass, field
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)


# ============================================================
# 能力画像
# ============================================================

@dataclass
class CapabilityProfile:
    """一个 Worker 上某项能力的画像"""
    name: str                                         # 能力名（"search", "code", ...）
    quality: float = 0.8                              # 评估质量分 (0-1)
    avg_cost: float = 1.0                             # 单次成本估算（相对值）
    avg_latency_ms: float = 1000.0                    # 平均响应延迟
    error_rate: float = 0.0                           # 历史错误率
    throughput: float = 1.0                           # 吞吐（tasks/sec，相对值）
    max_concurrent: int = 3                           # 最大并发

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "quality": self.quality,
            "avg_cost": self.avg_cost,
            "avg_latency_ms": self.avg_latency_ms,
            "error_rate": self.error_rate,
            "throughput": self.throughput,
            "max_concurrent": self.max_concurrent,
        }


@dataclass
class WorkerMetrics:
    """Worker 运行时指标（动态）"""
    active_tasks: int = 0             # 当前在执行的任务数
    completed_tasks: int = 0          # 历史完成数
    failed_tasks: int = 0             # 历史失败数
    last_task_started_at: Optional[float] = None
    last_task_completed_at: Optional[float] = None
    recent_durations_ms: List[float] = field(default_factory=list)  # 最近 50 次任务耗时
    last_status: str = "idle"         # idle / busy / offline
    last_updated: float = field(default_factory=time.time)

    @property
    def error_rate(self) -> float:
        total = self.completed_tasks + self.failed_tasks
        return self.failed_tasks / total if total > 0 else 0.0

    def record_start(self) -> None:
        self.active_tasks += 1
        self.last_task_started_at = time.time()
        self.last_status = "busy" if self.active_tasks > 0 else "idle"
        self.last_updated = time.time()

    def record_end(self, success: bool, duration_ms: Optional[float] = None) -> None:
        self.active_tasks = max(0, self.active_tasks - 1)
        self.last_task_completed_at = time.time()
        if success:
            self.completed_tasks += 1
        else:
            self.failed_tasks += 1
        if duration_ms is not None and duration_ms >= 0:
            self.recent_durations_ms.append(duration_ms)
            if len(self.recent_durations_ms) > 50:
                self.recent_durations_ms = self.recent_durations_ms[-50:]
        self.last_status = "idle" if self.active_tasks == 0 else "busy"
        self.last_updated = time.time()

    def to_dict(self) -> Dict:
        return {
            "active_tasks": self.active_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "error_rate": self.error_rate,
            "recent_avg_latency_ms": (
                sum(self.recent_durations_ms) / len(self.recent_durations_ms)
                if self.recent_durations_ms else 0.0
            ),
            "last_status": self.last_status,
        }


@dataclass
class WorkerProfile:
    """Worker 的完整画像"""
    worker_id: str
    name: str
    capabilities: Dict[str, CapabilityProfile] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)        # "fast"/"cheap"/"premium"
    metrics: WorkerMetrics = field(default_factory=WorkerMetrics)
    registered_at: float = field(default_factory=time.time)
    online: bool = True

    def has_capability(self, name: str) -> bool:
        return name in self.capabilities

    def can_take_more(self) -> bool:
        """是否可以再接新任务（考虑 active 和 max_concurrent）"""
        if not self.online:
            return False
        # 检查所有能力的 max_concurrent 总和？为简化用全局一个并发量。
        max_for_any = max(
            (c.max_concurrent for c in self.capabilities.values()),
            default=1,
        )
        return self.metrics.active_tasks < max_for_any

    def to_dict(self) -> Dict:
        return {
            "worker_id": self.worker_id,
            "name": self.name,
            "capabilities": {n: c.to_dict() for n, c in self.capabilities.items()},
            "tags": self.tags,
            "online": self.online,
            "metrics": self.metrics.to_dict(),
        }


# ============================================================
# CapabilityRegistry（能力注册表）
# ============================================================

class CapabilityRegistry:
    """
    能力注册表

    角色：
    - 集中存储所有 Worker 的画像
    - 提供查询（find by capability / find best / find by tag）
    - 提供注册 / 注销 / 更新指标
    """

    def __init__(self):
        self._workers: Dict[str, WorkerProfile] = {}
        self._lock = Lock()
        # 能力名索引：capability_name -> set(worker_id)
        self._capability_index: Dict[str, set] = defaultdict(set)
        # tag 索引
        self._tag_index: Dict[str, set] = defaultdict(set)
        # 事件回调：register / unregister / update
        self._on_change: List[Callable] = []

    # ----------------- 注册 -----------------

    def register(self, profile: WorkerProfile) -> None:
        """注册一个 Worker"""
        with self._lock:
            self._workers[profile.worker_id] = profile
            for cap_name in profile.capabilities:
                self._capability_index[cap_name].add(profile.worker_id)
            for tag in profile.tags:
                self._tag_index[tag].add(profile.worker_id)
        logger.info(
            f"[Registry] Registered {profile.worker_id} ({profile.name}) "
            f"capabilities={list(profile.capabilities.keys())}"
        )
        self._notify("registered", profile.worker_id)

    def unregister(self, worker_id: str) -> bool:
        """注销"""
        with self._lock:
            profile = self._workers.pop(worker_id, None)
            if not profile:
                return False
            for cap_name in profile.capabilities:
                self._capability_index[cap_name].discard(worker_id)
                if not self._capability_index[cap_name]:
                    del self._capability_index[cap_name]
            for tag in profile.tags:
                self._tag_index[tag].discard(worker_id)
                if not self._tag_index[tag]:
                    del self._tag_index[tag]
        self._notify("unregistered", worker_id)
        return True

    def set_online(self, worker_id: str, online: bool = True) -> None:
        with self._lock:
            profile = self._workers.get(worker_id)
            if profile:
                profile.online = online
        self._notify("online_changed", worker_id)

    # ----------------- 查询 -----------------

    def get(self, worker_id: str) -> Optional[WorkerProfile]:
        return self._workers.get(worker_id)

    def list_all(self, online_only: bool = True) -> List[WorkerProfile]:
        workers = list(self._workers.values())
        if online_only:
            workers = [w for w in workers if w.online]
        return workers

    def find(self, capability: str, online_only: bool = True) -> List[WorkerProfile]:
        """
        查找具备指定能力的 Worker

        Args:
            capability: 能力名（如 'search', 'code', 'analysis'）
            online_only: 是否仅在线
        """
        ids = self._capability_index.get(capability, set())
        workers = [self._workers[i] for i in ids if i in self._workers]
        if online_only:
            workers = [w for w in workers if w.online]
        return workers

    def find_by_tag(self, tag: str, online_only: bool = True) -> List[WorkerProfile]:
        ids = self._tag_index.get(tag, set())
        workers = [self._workers[i] for i in ids if i in self._workers]
        if online_only:
            workers = [w for w in workers if w.online]
        return workers

    def find_idle(self, capability: Optional[str] = None) -> List[WorkerProfile]:
        """找空闲 Worker（active=0）。capability 给定则按能力过滤"""
        workers = self.find(capability) if capability else self.list_all()
        return [w for w in workers if w.metrics.active_tasks == 0]

    def find_underloaded(self, capability: Optional[str] = None) -> List[WorkerProfile]:
        """找未达到 max_concurrent 的 Worker"""
        workers = self.find(capability) if capability else self.list_all()
        return [w for w in workers if w.can_take_more()]

    # ----------------- 指标更新（Worker 内部调用） -----------------

    def record_task_started(self, worker_id: str) -> None:
        with self._lock:
            profile = self._workers.get(worker_id)
            if profile:
                profile.metrics.record_start()
        self._notify("metrics_changed", worker_id)

    def record_task_ended(
        self,
        worker_id: str,
        success: bool,
        duration_ms: Optional[float] = None,
    ) -> None:
        with self._lock:
            profile = self._workers.get(worker_id)
            if profile:
                profile.metrics.record_end(success, duration_ms)
        self._notify("metrics_changed", worker_id)

    def update_capability(
        self,
        worker_id: str,
        capability_name: str,
        **kwargs,
    ) -> None:
        """更新某个 Worker 的某项能力指标"""
        with self._lock:
            profile = self._workers.get(worker_id)
            if not profile:
                return
            cap = profile.capabilities.get(capability_name)
            if not cap:
                cap = CapabilityProfile(name=capability_name)
                profile.capabilities[capability_name] = cap
                self._capability_index[capability_name].add(worker_id)
            for k, v in kwargs.items():
                if hasattr(cap, k):
                    setattr(cap, k, v)
        self._notify("capability_updated", worker_id)

    # ----------------- 订阅 -----------------

    def subscribe(self, callback: Callable[[str, str], None]) -> None:
        """订阅注册表变化。回调签名：(event_type, worker_id)"""
        self._on_change.append(callback)

    def unsubscribe(self, callback: Callable) -> None:
        if callback in self._on_change:
            self._on_change.remove(callback)

    def _notify(self, event_type: str, worker_id: str) -> None:
        for cb in self._on_change:
            try:
                cb(event_type, worker_id)
            except Exception as e:
                logger.warning(f"Registry callback error: {e}")

    # ----------------- 状态导出 -----------------

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            workers = list(self._workers.values())
        return {
            "total_workers": len(workers),
            "online_workers": sum(1 for w in workers if w.online),
            "capabilities": list(self._capability_index.keys()),
            "tags": list(self._tag_index.keys()),
            "by_capability": {
                cap: len(workers)
                for cap, workers in self._capability_index.items()
            },
        }


# ============================================================
# LoadBalancer（负载均衡）
# ============================================================

class LoadBalanceStrategy(str, Enum):
    LEAST_LOADED = "least_loaded"            # 选 active_tasks 最少的
    WEIGHTED_ROUND_ROBIN = "wrr"            # 按 quality 权重轮转（fairness）
    SCORE_BASED = "score_based"              # 综合评分（多维：质量、负载、错误率）
    LATENCY_FIRST = "latency_first"          # 优选延迟低的
    COST_FIRST = "cost_first"                # 优选成本最低的
    RANDOM = "random"                        # 随机（作为 baseline）


@dataclass
class ScoreDetail:
    """评分明细"""
    worker_id: str
    total: float
    components: Dict[str, float] = field(default_factory=dict)
    explanation: str = ""

    def to_dict(self) -> Dict:
        return {
            "worker_id": self.worker_id,
            "total": self.total,
            "components": self.components,
            "explanation": self.explanation,
        }


class LoadBalancer:
    """
    负载均衡器

    给定候选 Worker 列表 + 任务特征，选出最佳 Worker。
    支持多种策略；SCORE_BASED 默认使用多维评分。
    """

    def __init__(self, strategy: LoadBalanceStrategy = LoadBalanceStrategy.SCORE_BASED):
        self.strategy = strategy
        # SCORE_BASED 默认权重
        self.score_weights = {
            "load": 0.35,       # 负载（active_tasks / max_concurrent）反向
            "quality": 0.25,    # 评估质量分
            "error_rate": 0.15, # 错误率（反向）
            "latency": 0.15,    # 延迟（反向）
            "cost": 0.10,       # 成本（反向）
        }
        self._round_robin_state: Dict[str, int] = defaultdict(int)

    def select(
        self,
        candidates: List[WorkerProfile],
        capability: Optional[str] = None,
        prefer_tags: Optional[List[str]] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> Tuple[Optional[WorkerProfile], Optional[ScoreDetail]]:
        """
        选择最佳 Worker

        Args:
            candidates: 候选 WorkerProfile 列表
            capability: 当前任务的 capability（用于检索 quality/error_rate 等）
            prefer_tags: 偏好 tag（如 ["fast", "premium"]）
            weights: 自定义评分权重（覆盖默认）

        Returns:
            (选中的 WorkerProfile, 评分明细)
        """
        if not candidates:
            return None, None

        # 标记 task started 给 metric
        # （这里只是选，不实际启动任务；executor 启动时才会真增加）

        if self.strategy == LoadBalanceStrategy.LEAST_LOADED:
            return self._select_least_loaded(candidates)
        if self.strategy == LoadBalanceStrategy.WEIGHTED_ROUND_ROBIN:
            return self._select_wrr(candidates, capability)
        if self.strategy == LoadBalanceStrategy.LATENCY_FIRST:
            return self._select_by_field(candidates, capability, "avg_latency_ms", reverse=True)
        if self.strategy == LoadBalanceStrategy.COST_FIRST:
            return self._select_by_field(candidates, capability, "avg_cost", reverse=True)
        if self.strategy == LoadBalanceStrategy.RANDOM:
            import random
            return random.choice(candidates), None

        # 默认 SCORE_BASED
        return self._select_score_based(candidates, capability, prefer_tags, weights)

    # ----- 内部策略 -----

    def _select_least_loaded(
        self,
        candidates: List[WorkerProfile],
    ) -> Tuple[WorkerProfile, ScoreDetail]:
        # active_tasks 最小；并列则按 completed_tasks 最小（让新 Worker 也得到任务）
        sorted_w = sorted(
            candidates,
            key=lambda w: (w.metrics.active_tasks, w.metrics.completed_tasks),
        )
        chosen = sorted_w[0]
        score = ScoreDetail(
            worker_id=chosen.worker_id,
            total=-chosen.metrics.active_tasks,  # 越低越好
            components={"active_tasks": chosen.metrics.active_tasks},
            explanation=f"least_loaded: {chosen.metrics.active_tasks} active tasks",
        )
        return chosen, score

    def _select_wrr(
        self,
        candidates: List[WorkerProfile],
        capability: Optional[str],
    ) -> Tuple[WorkerProfile, ScoreDetail]:
        """按 quality 加权的轮转（fairness）"""
        weights = []
        for w in candidates:
            cap = w.capabilities.get(capability)
            quality = cap.quality if cap else 0.5
            weights.append(max(0.01, quality))

        total = sum(weights)
        # 按 quality 比例分配选择
        # 简化：用 round_robin_counter 累计，超阈值就选
        key = capability or "_global"
        self._round_robin_state[key] += 1  # 简单计数
        counter = self._round_robin_state[key]
        # 用 counter 对 total 取模，按权重匹配
        cumulative = 0.0
        target = (counter % total) if total > 0 else 0
        chosen = None
        for w, w_weight in zip(candidates, weights):
            cumulative += w_weight
            if cumulative > target:
                chosen = w
                break
        if not chosen:
            chosen = candidates[-1]
        score = ScoreDetail(
            worker_id=chosen.worker_id,
            total=w_weight,
            components={"quality": w_weight},
            explanation=f"wrr counter={counter}",
        )
        return chosen, score

    def _select_by_field(
        self,
        candidates: List[WorkerProfile],
        capability: Optional[str],
        field_name: str,
        reverse: bool,
    ) -> Tuple[WorkerProfile, ScoreDetail]:
        """按指定字段排序（reverse=True 表示越小越好 -> 取 min）"""
        def keyfn(w: WorkerProfile):
            cap = w.capabilities.get(capability)
            return getattr(cap, field_name, 0) if cap else 0.0
        sorted_w = sorted(candidates, key=keyfn, reverse=reverse)
        chosen = sorted_w[0]
        score = ScoreDetail(
            worker_id=chosen.worker_id,
            total=-keyfn(chosen) if reverse else keyfn(chosen),
            components={field_name: keyfn(chosen)},
            explanation=f"{field_name}_first",
        )
        return chosen, score

    def _select_score_based(
        self,
        candidates: List[WorkerProfile],
        capability: Optional[str],
        prefer_tags: Optional[List[str]],
        weights: Optional[Dict[str, float]],
    ) -> Tuple[WorkerProfile, ScoreDetail]:
        """综合多维评分"""
        ws = weights or self.score_weights
        scored: List[Tuple[WorkerProfile, ScoreDetail]] = []

        for w in candidates:
            cap = w.capabilities.get(capability)
            if not cap:
                # 没声明该能力的画像，质量按 0.5
                cap_dict = {"quality": 0.5, "avg_latency_ms": 1000.0, "avg_cost": 1.0, "error_rate": 0.0}
            else:
                cap_dict = {
                    "quality": cap.quality,
                    "avg_latency_ms": cap.avg_latency_ms,
                    "avg_cost": cap.avg_cost,
                    "error_rate": cap.error_rate,
                }

            # 各维度归一化得分（0-1，越高越好）
            load_score = 1.0 - w.metrics.active_tasks / max(1, max(
                (c.max_concurrent for c in w.capabilities.values()),
                default=1,
            ))
            quality_score = cap_dict["quality"]
            error_score = 1.0 - cap_dict["error_rate"]
            # 延迟：10000ms -> 0, 100ms -> 1（粗略）
            latency_score = max(0.0, 1.0 - cap_dict["avg_latency_ms"] / 10000.0)
            cost_score = max(0.0, 1.0 - cap_dict["avg_cost"] / 10.0)

            # tag 偏好奖励
            tag_bonus = 0.0
            if prefer_tags and w.tags:
                tag_bonus = 0.1 * sum(1 for t in prefer_tags if t in w.tags)

            components = {
                "load": load_score,
                "quality": quality_score,
                "error_rate": error_score,
                "latency": latency_score,
                "cost": cost_score,
                "tag_bonus": tag_bonus,
            }
            total = (
                ws.get("load", 0) * load_score
                + ws.get("quality", 0) * quality_score
                + ws.get("error_rate", 0) * error_score
                + ws.get("latency", 0) * latency_score
                + ws.get("cost", 0) * cost_score
                + tag_bonus
            )
            explanation = (
                f"load={load_score:.2f} quality={quality_score:.2f} "
                f"err={error_score:.2f} lat={latency_score:.2f} cost={cost_score:.2f} "
                f"+tag={tag_bonus:.2f}"
            )
            scored.append((w, ScoreDetail(w.worker_id, total, components, explanation)))

        # 排序取最高分
        scored.sort(key=lambda x: x[1].total, reverse=True)
        return scored[0]

    # ---- 调度策略切换 ----

    def set_strategy(self, strategy: LoadBalanceStrategy) -> None:
        self.strategy = strategy

    def set_score_weights(self, weights: Dict[str, float]) -> None:
        total = sum(weights.values())
        if abs(total - 1.0) > 0.05:
            logger.warning(
                f"Score weights don't sum to 1.0 (got {total:.3f}), "
                "scores may not be on [0,1] scale"
            )
        self.score_weights = dict(weights)


# ============================================================
# 全局单例
# ============================================================

_capability_registry: Optional[CapabilityRegistry] = None
_load_balancer: Optional[LoadBalancer] = None


def get_capability_registry() -> CapabilityRegistry:
    global _capability_registry
    if _capability_registry is None:
        _capability_registry = CapabilityRegistry()
    return _capability_registry


def get_load_balancer() -> LoadBalancer:
    global _load_balancer
    if _load_balancer is None:
        _load_balancer = LoadBalancer()
    return _load_balancer


def reset_capability() -> None:
    """重置全局单例（测试用）"""
    global _capability_registry, _load_balancer
    _capability_registry = None
    _load_balancer = None
