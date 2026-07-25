"""
自适应协商阈值（Adaptive Threshold）

提供：
- TradeRecord             历史成交记录
- ThresholdLearner        基于历史学习 reservation_point
- 对接 negotiation.py 的 ReservationPoint 计算

P3-19
"""

import math
import time
import uuid
import json
import os
import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

@dataclass
class TradeRecord:
    """一次成交记录"""
    record_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    agent_id: str = ""
    counterparty_id: str = ""
    task_type: str = ""
    initial_price: float = 0.0       # 初始报价
    final_price: float = 0.0          # 实际成交价
    reservation_point: float = 0.0    # 当时的底线价
    rounds: int = 0                   # 协商轮数
    abandoned: bool = False           # 是否流拍
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "record_id": self.record_id,
            "agent_id": self.agent_id,
            "counterparty_id": self.counterparty_id,
            "task_type": self.task_type,
            "initial_price": self.initial_price,
            "final_price": self.final_price,
            "reservation_point": self.reservation_point,
            "rounds": self.rounds,
            "abandoned": self.abandoned,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @property
    def concession(self) -> float:
        """让步幅度（initial - final / initial）"""
        if self.initial_price <= 0:
            return 0.0
        return max(0.0, (self.initial_price - self.final_price) / self.initial_price)


class AdaptationStrategy(str, Enum):
    """自适应算法"""
    EMPIRICAL = "empirical"           # 经验价（p25）
    MEAN_FALLBACK = "mean_fallback"   # 中位数
    EWMA = "ewma"                     # 指数加权移动平均
    BAYESIAN = "bayesian"             # 贝叶斯（简单 Beta 分布模型）


@dataclass
class AdaptationConfig:
    """自适应配置"""
    strategy: AdaptationStrategy = AdaptationStrategy.EWMA
    # EWMA alpha
    ewma_alpha: float = 0.3
    # 经验 p 分位数
    percentile: float = 25.0       # 25% 分位数
    # 缩放窗口
    lookback_trades: int = 30
    # 边界
    min_threshold: float = 0.0
    max_threshold: float = float('inf')
    # 缩放因子（reservation_point vs 历史成交价）
    safety_margin: float = 0.85     # 默认比历史中位低 15%

    def to_dict(self) -> Dict:
        return {
            "strategy": self.strategy.value,
            "ewma_alpha": self.ewma_alpha,
            "percentile": self.percentile,
            "lookback_trades": self.lookback_trades,
            "min_threshold": self.min_threshold,
            "max_threshold": self.max_threshold,
            "safety_margin": self.safety_margin,
        }


# ============================================================
# ThresholdLearner
# ============================================================

class ThresholdLearner:
    """
    自适应阈值学习器。

    角色：
    - record_trade(...)     录入历史成交
    - learn(agent_id, task_type) -> 新的 reservation_point
    - 持久化 / 加载
    """

    def __init__(self, config: Optional[AdaptationConfig] = None):
        self._records: List[TradeRecord] = []
        self._config = config or AdaptationConfig()
        # 索引：[(agent_id, task_type)] -> [record]
        self._index: Dict[tuple, List[TradeRecord]] = defaultdict(list)
        # EWMA 状态：[(agent_id, task_type)] -> value
        self._ewma_state: Dict[tuple, float] = {}
        # 历史均值缓存
        self._means: Dict[tuple, List[float]] = defaultdict(list)

    # ----------------- 录入 -----------------

    def record_trade(
        self,
        agent_id: str,
        counterparty_id: str,
        task_type: str,
        initial_price: float,
        final_price: float,
        reservation_point: float,
        rounds: int = 0,
        abandoned: bool = False,
        metadata: Optional[Dict] = None,
    ) -> TradeRecord:
        rec = TradeRecord(
            agent_id=agent_id,
            counterparty_id=counterparty_id,
            task_type=task_type,
            initial_price=initial_price,
            final_price=final_price,
            reservation_point=reservation_point,
            rounds=rounds,
            abandoned=abandoned,
            metadata=metadata or {},
        )
        self._records.append(rec)
        key = (agent_id, task_type)
        self._index[key].append(rec)
        # 更新 EWMA
        if not abandoned:
            prev_ewma = self._ewma_state.get(key, final_price)
            alpha = self._config.ewma_alpha
            self._ewma_state[key] = alpha * final_price + (1 - alpha) * prev_ewma
            # 更新历史均值缓存
            self._means[key].append(final_price)
            # 限长
            if len(self._means[key]) > self._config.lookback_trades:
                self._means[key] = self._means[key][-self._config.lookback_trades:]
        return rec

    # ----------------- 学习阈值 -----------------

    def learn(
        self,
        agent_id: str,
        task_type: str,
        default_threshold: float = 0.0,
    ) -> float:
        """
        根据历史学习 agent_id + task_type 的 reservation_point。
        没有足够历史 → 返回 default_threshold。
        """
        key = (agent_id, task_type)
        history = self._index.get(key, [])
        history = [r for r in history if not r.abandoned][-self._config.lookback_trades:]

        if not history:
            return default_threshold

        prices = [r.final_price for r in history]

        threshold = None
        if self._config.strategy == AdaptationStrategy.EMPIRICAL:
            threshold = self._percentile(prices, self._config.percentile)
        elif self._config.strategy == AdaptationStrategy.MEAN_FALLBACK:
            threshold = self._median(prices)
        elif self._config.strategy == AdaptationStrategy.EWMA:
            threshold = self._ewma_state.get(key, prices[-1])
        elif self._config.strategy == AdaptationStrategy.BAYESIAN:
            threshold = self._bayesian_expected(prices)

        if threshold is None:
            return default_threshold

        # 缩放安全边界
        threshold = threshold * self._config.safety_margin

        # 边界
        threshold = max(self._config.min_threshold, threshold)
        if self._config.max_threshold != float('inf'):
            threshold = min(self._config.max_threshold, threshold)

        return threshold

    # ----------------- 推荐 -----------------

    def recommend(
        self,
        agent_id: str,
        task_type: str,
        current_bid: float,
        default_threshold: float = 0.0,
    ) -> Dict[str, Any]:
        """基于当前 bid + 历史给出阈值建议"""
        learned = self.learn(agent_id, task_type, default_threshold)
        key = (agent_id, task_type)
        history = [r for r in self._index.get(key, []) if not r.abandoned]
        return {
            "learned_threshold": learned,
            "default_threshold": default_threshold,
            "history_count": len(history),
            "recent_prices": [r.final_price for r in history[-5:]],
            "mean_price": (sum(r.final_price for r in history) / len(history))
                          if history else 0.0,
            "suggestion": min(current_bid, learned) if learned > 0 else current_bid,
        }

    # ----------------- 策略切换 -----------------

    def set_strategy(self, strategy: AdaptationStrategy) -> None:
        self._config.strategy = strategy

    def set_config(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self._config, k):
                setattr(self._config, k, v)

    def config(self) -> Dict:
        return self._config.to_dict()

    # ----------------- 统计 -----------------

    def stats(self) -> Dict[str, Any]:
        by_agent: Dict[str, int] = defaultdict(int)
        for r in self._records:
            by_agent[r.agent_id] += 1
        abandoned = sum(1 for r in self._records if r.abandoned)
        return {
            "total_records": len(self._records),
            "unique_keys": len(self._index),
            "abandoned": abandoned,
            "abandoned_rate": abandoned / len(self._records) if self._records else 0,
            "by_agent": dict(by_agent),
            "config": self._config.to_dict(),
        }

    def get_records(
        self,
        agent_id: Optional[str] = None,
        task_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[TradeRecord]:
        out = list(self._records)
        if agent_id:
            out = [r for r in out if r.agent_id == agent_id]
        if task_type:
            out = [r for r in out if r.task_type == task_type]
        return out[-limit:]

    # ----------------- 持久化 -----------------

    def save_to_file(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            data = {
                "records": [r.to_dict() for r in self._records],
                "ewma_state": {f"{k[0]}|{k[1]}": v for k, v in self._ewma_state.items()},
                "config": self._config.to_dict(),
            }
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_from_file(self, path: str) -> int:
        if not os.path.exists(path):
            return 0
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        n = 0
        for d in data.get("records", []):
            try:
                rec = TradeRecord(**d)
                self._records.append(rec)
                self._index[(rec.agent_id, rec.task_type)].append(rec)
                n += 1
            except Exception:
                pass
        for k_str, v in data.get("ewma_state", {}).items():
            k_split = k_str.split("|", 1)
            if len(k_split) == 2:
                self._ewma_state[(k_split[0], k_split[1])] = v
        return n

    # ----------------- 内部 -----------------

    @staticmethod
    def _percentile(values: List[float], p: float) -> float:
        """简单 p 分位数"""
        if not values:
            return 0.0
        sorted_v = sorted(values)
        n = len(sorted_v)
        idx = (p / 100.0) * (n - 1)
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return sorted_v[lo]
        frac = idx - lo
        return sorted_v[lo] * (1 - frac) + sorted_v[hi] * frac

    @staticmethod
    def _median(values: List[float]) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        n = len(s)
        if n % 2 == 0:
            return (s[n // 2 - 1] + s[n // 2]) / 2
        return s[n // 2]

    @staticmethod
    def _bayesian_expected(values: List[float]) -> float:
        """简化：假设成交价 Beta-like 分布，返回样本均值 × 置信度折扣"""
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        if len(values) < 5:
            # 样本太少 → 打折扣
            return mean * 0.7
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = math.sqrt(variance)
        # 置信度折扣 = max(0.5, 1 - std / (mean + 1e-6))
        confidence = max(0.5, 1 - std / (mean + 1e-6))
        return mean * confidence


# ============================================================
# 全局单例
# ============================================================

_learner: Optional[ThresholdLearner] = None


def get_threshold_learner() -> ThresholdLearner:
    global _learner
    if _learner is None:
        _learner = ThresholdLearner()
    return _learner


def reset_threshold_learner() -> None:
    global _learner
    _learner = None