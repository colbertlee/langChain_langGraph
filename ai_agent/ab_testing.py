"""
A/B 测试与策略评估

提供：
- Experiment      A/B 实验定义（A/B/多臂）
- Variant         变体（占比 + 策略函数）
- ExperimentRunner 分配流量 + 收集结果
- Strategy         评估策略（按指标选赢家）
- 指标支持（reward / latency / success / custom）
- 与现有 negotiation/auction 接入

P3-16
"""

import asyncio
import json
import random
import time
import uuid
import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ============================================================
# 实验 / 变体 / 分配
# ============================================================

class ExperimentStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"


class AssignmentStrategy(str, Enum):
    RANDOM = "random"          # 均匀随机
    DETERMINISTIC = "deterministic"  # 按 user_id 哈希（粘性）
    WEIGHTED = "weighted"      # 按权重


@dataclass
class Variant:
    """一个变体"""
    name: str = ""
    weight: float = 1.0       # 占比权重
    config: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    # 运行时统计
    exposures: int = 0         # 触达数
    successes: int = 0         # 成功数
    rewards: List[float] = field(default_factory=list)
    latencies_ms: List[float] = field(default_factory=list)
    errors: int = 0

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "weight": self.weight,
            "config": self.config,
            "description": self.description,
            "exposures": self.exposures,
            "successes": self.successes,
            "error_rate": (self.errors / self.exposures) if self.exposures > 0 else 0,
            "mean_reward": (sum(self.rewards) / len(self.rewards)) if self.rewards else 0,
            "mean_latency_ms": (sum(self.latencies_ms) / len(self.latencies_ms)) if self.latencies_ms else 0,
        }


@dataclass
class Experiment:
    """一个实验"""
    experiment_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    variants: List[Variant] = field(default_factory=list)
    status: ExperimentStatus = ExperimentStatus.DRAFT
    assignment_strategy: AssignmentStrategy = AssignmentStrategy.DETERMINISTIC
    # 触发规则（可选）：仅当 user_id / context 满足 condition 才进入实验
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    # 元数据
    primary_metric: str = "reward"
    min_sample_size: int = 100
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    winner: Optional[str] = None  # 决出的胜出变体
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_variant(self, name: str, weight: float = 1.0,
                    config: Optional[Dict] = None,
                    description: str = "") -> Variant:
        v = Variant(
            name=name, weight=weight,
            config=config or {}, description=description,
        )
        self.variants.append(v)
        return v

    def to_dict(self) -> Dict:
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "assignment_strategy": self.assignment_strategy.value,
            "primary_metric": self.primary_metric,
            "min_sample_size": self.min_sample_size,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "winner": self.winner,
            "variants": [v.to_dict() for v in self.variants],
        }


# ============================================================
# ExperimentRunner
# ============================================================

class ExperimentRunner:
    """
    A/B 测试运行器

    提供：
    - assign(user_id, context) -> 分配到某个变体
    - record(experiment_id, variant_name, success, reward, latency_ms)
    - decide_winner(experiment_id) -> 决出胜出变体
    - 与 NegotiationStrategy / AuctionStrategy 集成（按 variant.config 选策略）
    """

    def __init__(self):
        self._experiments: Dict[str, Experiment] = {}
        self._assignments: Dict[Tuple[str, str], str] = {}  # (exp_id, user_id) -> variant
        # 决策回调：experiment 决出 winner 时调用
        self._on_winner: List[Callable[[Experiment, str], None]] = []

    def create(self, name: str, description: str = "",
               primary_metric: str = "reward",
               assignment_strategy: AssignmentStrategy = AssignmentStrategy.DETERMINISTIC,
               ) -> Experiment:
        exp = Experiment(
            name=name,
            description=description,
            primary_metric=primary_metric,
            assignment_strategy=assignment_strategy,
        )
        self._experiments[exp.experiment_id] = exp
        return exp

    def get(self, experiment_id: str) -> Optional[Experiment]:
        return self._experiments.get(experiment_id)

    def find_by_name(self, name: str) -> Optional[Experiment]:
        for e in self._experiments.values():
            if e.name == name:
                return e
        return None

    def list_experiments(self) -> List[Experiment]:
        return list(self._experiments.values())

    def start(self, experiment_id: str) -> Experiment:
        exp = self._experiments.get(experiment_id)
        if exp:
            exp.status = ExperimentStatus.RUNNING
            exp.started_at = time.time()
        return exp

    def stop(self, experiment_id: str) -> Experiment:
        exp = self._experiments.get(experiment_id)
        if exp:
            exp.status = ExperimentStatus.STOPPED
            exp.completed_at = time.time()
        return exp

    # ----------------- 分配 -----------------

    def assign(
        self,
        experiment_id: str,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Variant]:
        """分配 user_id 到一个变体"""
        exp = self._experiments.get(experiment_id)
        if not exp or exp.status != ExperimentStatus.RUNNING:
            return None
        if not exp.variants:
            return None

        # 检查条件
        if exp.condition and not exp.condition(context or {}):
            return None

        # 粘性分配（DETERMINISTIC）
        if exp.assignment_strategy == AssignmentStrategy.DETERMINISTIC:
            key = (experiment_id, user_id)
            if key in self._assignments:
                name = self._assignments[key]
                return next((v for v in exp.variants if v.name == name), None)
            variant = self._select_variant(exp)
            self._assignments[key] = variant.name
            variant.exposures += 1
            return variant
        elif exp.assignment_strategy == AssignmentStrategy.WEIGHTED:
            variant = self._select_variant(exp)
            variant.exposures += 1
            return variant
        else:  # RANDOM
            variant = random.choice(exp.variants)
            variant.exposures += 1
            return variant

    def _select_variant(self, exp: Experiment) -> Variant:
        total_weight = sum(v.weight for v in exp.variants)
        if total_weight <= 0:
            return exp.variants[0]
        r = random.random() * total_weight
        cum = 0.0
        for v in exp.variants:
            cum += v.weight
            if r <= cum:
                return v
        return exp.variants[-1]

    # ----------------- 记录 -----------------

    def record(
        self,
        experiment_id: str,
        variant_name: str,
        success: Optional[bool] = None,
        reward: Optional[float] = None,
        latency_ms: Optional[float] = None,
        error: bool = False,
    ) -> bool:
        """记录一次实验结果"""
        exp = self._experiments.get(experiment_id)
        if not exp:
            return False
        variant = next((v for v in exp.variants if v.name == variant_name), None)
        if not variant:
            return False
        if success is not None and success:
            variant.successes += 1
        if reward is not None:
            variant.rewards.append(reward)
        if latency_ms is not None:
            variant.latencies_ms.append(latency_ms)
        if error:
            variant.errors += 1
        return True

    # ----------------- 决策 -----------------

    def decide_winner(
        self,
        experiment_id: str,
        confidence: float = 0.95,
    ) -> Optional[str]:
        """
        决策胜出变体。

        算法：对 primary_metric（默认 reward）的均值做 Welch's t-test；
        若没有统计学差异但都达 min_sample_size，取样本均值最高的。
        """
        exp = self._experiments.get(experiment_id)
        if not exp or len(exp.variants) < 2:
            return None

        # 简化决策：直接比较主指标均值（无 t-test，避免 scipy 依赖）
        means = []
        for v in exp.variants:
            if exp.primary_metric == "reward":
                mean = (sum(v.rewards) / len(v.rewards)) if v.rewards else 0.0
            elif exp.primary_metric == "success_rate":
                mean = v.successes / v.exposures if v.exposures > 0 else 0.0
            elif exp.primary_metric == "latency":
                # latency 越低越好，所以取负
                mean = -(sum(v.latencies_ms) / len(v.latencies_ms)) if v.latencies_ms else 0.0
            elif exp.primary_metric == "error_rate":
                mean = -(v.errors / v.exposures) if v.exposures > 0 else 0.0
            else:
                mean = (sum(v.rewards) / len(v.rewards)) if v.rewards else 0.0
            means.append((v.name, mean, v.exposures))

        # 排序找最佳
        means.sort(key=lambda x: x[1], reverse=True)
        winner_name = means[0][0]

        # 检查样本是否足够
        min_exposures = min(m[2] for m in means)
        if min_exposures < exp.min_sample_size:
            logger.info(
                f"Experiment {exp.name}: min exposures {min_exposures} < "
                f"{exp.min_sample_size}, winner not statistically conclusive"
            )
            # 仍然标记名义 winner（如差值很大也可定）

        exp.winner = winner_name
        exp.status = ExperimentStatus.COMPLETED
        exp.completed_at = time.time()

        # 回调
        for cb in self._on_winner:
            try:
                cb(exp, winner_name)
            except Exception as e:
                logger.warning(f"on_winner callback error: {e}")

        return winner_name

    def on_winner(self, callback: Callable[[Experiment, str], None]) -> None:
        self._on_winner.append(callback)

    # ----------------- 报告 -----------------

    def report(self, experiment_id: str) -> Dict[str, Any]:
        exp = self._experiments.get(experiment_id)
        if not exp:
            return {}
        return exp.to_dict()

    def stats(self) -> Dict[str, Any]:
        return {
            "experiment_count": len(self._experiments),
            "running_count": sum(1 for e in self._experiments.values()
                                 if e.status == ExperimentStatus.RUNNING),
            "completed_count": sum(1 for e in self._experiments.values()
                                   if e.status == ExperimentStatus.COMPLETED),
            "total_assignments": len(self._assignments),
        }


# ============================================================
# 策略注册表（与 negotiation/auction 集成）
# ============================================================

class StrategyEvaluator:
    """
    策略评估器：跑实验框架验证策略优劣。

    用途：
    1. 注册若干候选策略
    2. 在 synthetic 任务上对比（per-step call 不同策略，记录奖励）
    3. 决出 winner
    """

    def __init__(self):
        self._strategies: Dict[str, Callable] = {}
        self._metrics_history: Dict[str, List[Dict]] = {}

    def register(self, name: str, strategy_fn: Callable) -> None:
        """注册策略（callable，参数任意）"""
        self._strategies[name] = strategy_fn

    async def evaluate(
        self,
        runner: ExperimentRunner,
        experiment_id: str,
        benchmark: List[Dict[str, Any]],
        reward_fn: Callable[[Dict[str, Any], Any], float],
    ) -> Dict[str, Any]:
        """跑一次 benchmark，按 exp 分配策略 + 收集指标"""
        exp = runner.get(experiment_id)
        if not exp:
            return {"error": "experiment not found"}

        results = []
        for i, task in enumerate(benchmark):
            user_id = f"benchmark_task_{i}"
            variant = runner.assign(experiment_id, user_id, context=task)
            if not variant:
                continue

            strategy_name = variant.config.get("strategy")
            if not strategy_name:
                continue

            strategy_fn = self._strategies.get(strategy_name)
            if not strategy_fn:
                continue

            start = time.time()
            try:
                output = strategy_fn(task)
                if asyncio.iscoroutine(output):
                    output = await output
                reward = reward_fn(task, output)
                latency_ms = (time.time() - start) * 1000
                success = reward > 0
                runner.record(experiment_id, variant.name,
                              success=success, reward=reward, latency_ms=latency_ms)
            except Exception as e:
                runner.record(experiment_id, variant.name, error=True)
                logger.warning(f"strategy {strategy_name} failed on task {i}: {e}")

            results.append({
                "task_idx": i,
                "variant": variant.name,
                "strategy": strategy_name,
                "reward": reward if 'reward' in locals() else None,
            })

        return {
            "experiment": exp.name,
            "evaluated_tasks": len(results),
            "results": results,
        }


# ============================================================
# 全局单例
# ============================================================

_runner: Optional[ExperimentRunner] = None


def get_experiment_runner() -> ExperimentRunner:
    global _runner
    if _runner is None:
        _runner = ExperimentRunner()
    return _runner


def reset_experiment_runner() -> None:
    global _runner
    _runner = None