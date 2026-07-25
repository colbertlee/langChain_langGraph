"""
hallucination - 幻觉率评估钩子（C4）

背景：
- 13.4.4 模型幻觉率与用户满意度评估需要可测量的指标；
- 现有 observability 只记录 metrics/spans/events，没有专门评估"幻觉"维度；
- 本模块提供：
    1) HallucinationMetric：单次"是否幻觉"的判定结果（severity + 原因）
    2) HallucinationEvaluator：组合多种启发式判定，给出 0~1 的 hallucination_score
    3) HallucinationTracker：累计样本 + 输出聚合统计（命中率、平均分、按意图拆分）

启发式（无 ground-truth 也能跑；如有 ground-truth，可走 RAG 路径升级为有监督评估）：
- (a) 输出含未在 RAG 上下文中出现的具体数字 / URL / 实体（"幻觉实体"）；
- (b) 输出与用户输入语义不相关（关键词重合度 < 阈值）；
- (c) 输出含"我不确定 / 我不知道 / 抱歉"等放弃语 → 不算幻觉（记 None）；
- (d) 输出包含指令性违规内容 → 严重幻觉（severity=high）；
- (e) 输出长度过短（< 5 字） + intent 非 greeting → 可能是"敷衍回答"，记低分。

设计：
- 所有判定都是 best-effort，目标是"覆盖率"而非"绝对准确"；
- 结果入库用 observability.EventBus 写入（可选）；
- 单例 + 可重置，便于测试。
"""
from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class HallucinationMetric:
    """单次评估结果。"""

    sample_id: str
    user_input: str
    output: str
    intent: str
    hallucination_score: float  # 0~1，越高越像幻觉
    severity: str  # 'none' / 'low' / 'medium' / 'high'
    signals: List[str] = field(default_factory=list)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_HEDGE_PATTERNS = [
    r"我不知道", r"我不太确定", r"抱歉.*无法", r"暂无法", r"无法回答",
    r"as an ai", r"i'?m not sure", r"i don'?t know",
]

_UNSURE_RE = re.compile("|".join(_HEDGE_PATTERNS), re.IGNORECASE)


class HallucinationEvaluator:
    """组合启发式评估器。

    用法：
        ev = HallucinationEvaluator()
        metric = ev.evaluate(
            user_input="华为最新手机型号是什么",
            output="华为最新手机型号是 Mate 70 Pro",
            intent="query",
            context_docs=["华为 Mate 60 系列于 2023 年发布..."],  # 可选：RAG 片段
        )
    """

    # 抽取文本中的"看起来很具体"的数字 / URL / 实体（粗筛）
    _URL_RE = re.compile(r"https?://\S+")
    _NUM_RE = re.compile(r"\b\d{2,}\b")

    def __init__(self, keyword_min_overlap: float = 0.1):
        self.keyword_min_overlap = keyword_min_overlap

    def evaluate(
        self,
        user_input: str,
        output: str,
        intent: str = "general",
        context_docs: Optional[List[str]] = None,
    ) -> HallucinationMetric:
        signals: List[str] = []
        score = 0.0

        if not output or not output.strip():
            return HallucinationMetric(
                sample_id=str(uuid.uuid4()),
                user_input=user_input,
                output=output or "",
                intent=intent,
                hallucination_score=0.0,
                severity="none",
                signals=["empty_output"],
            )

        # (c) hedge → 视为"放弃回答"，不算幻觉
        if _UNSURE_RE.search(output):
            return HallucinationMetric(
                sample_id=str(uuid.uuid4()),
                user_input=user_input,
                output=output,
                intent=intent,
                hallucination_score=0.0,
                severity="none",
                signals=["hedge_response"],
            )

        # (e) 输出过短 + 非 greeting
        stripped = output.strip()
        if len(stripped) < 5 and intent not in {"greeting"}:
            score += 0.3
            signals.append("too_short_non_greeting")

        # (a) URL / 大数字未在 context 中出现
        if context_docs:
            joined_ctx = "\n".join(context_docs)
            urls_in_out = self._URL_RE.findall(output)
            urls_in_ctx = set(self._URL_RE.findall(joined_ctx))
            for url in urls_in_out:
                if url not in urls_in_ctx:
                    score += 0.3
                    signals.append(f"url_not_in_context:{url[:40]}")

            nums_in_out = self._NUM_RE.findall(output)
            nums_in_ctx = set(self._NUM_RE.findall(joined_ctx))
            novel_nums = [n for n in nums_in_out if n not in nums_in_ctx]
            if novel_nums and len(nums_in_out) >= 1:
                ratio = len(novel_nums) / len(nums_in_out)
                if ratio > 0.5:
                    score += 0.2
                    signals.append(f"novel_numbers:{len(novel_nums)}/{len(nums_in_out)}")

        # (b) 关键词重合度
        overlap = self._keyword_overlap(user_input, output)
        if overlap < self.keyword_min_overlap and intent in {"query", "analysis", "compare"}:
            score += 0.2
            signals.append(f"low_overlap:{overlap:.2f}")

        # (d) 指令违规（极少见，主要防御 prompt injection 已突破的情形）
        if re.search(r"<\|im_start\|>|<\|im_end\|>|###\s*instruction", output, re.IGNORECASE):
            score += 0.5
            signals.append("instruction_leak")

        # 截断到 [0, 1]
        score = max(0.0, min(1.0, score))

        if score >= 0.7:
            severity = "high"
        elif score >= 0.4:
            severity = "medium"
        elif score >= 0.1:
            severity = "low"
        else:
            severity = "none"

        return HallucinationMetric(
            sample_id=str(uuid.uuid4()),
            user_input=user_input,
            output=output,
            intent=intent,
            hallucination_score=score,
            severity=severity,
            signals=signals,
        )

    @staticmethod
    def _keyword_overlap(a: str, b: str) -> float:
        """两个文本的关键词重合度（基于字符 2-gram 集合的 Jaccard）。"""
        def ngrams(s: str) -> set:
            s = re.sub(r"\s+", "", s)
            return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}
        sa = ngrams(a or "")
        sb = ngrams(b or "")
        if not sa or not sb:
            return 0.0
        inter = sa & sb
        union = sa | sb
        return len(inter) / len(union) if union else 0.0


class HallucinationTracker:
    """累计评估结果，输出聚合统计。"""

    def __init__(self) -> None:
        self._metrics: List[HallucinationMetric] = []
        self._by_intent: Dict[str, List[float]] = defaultdict(list)

    def record(self, metric: HallucinationMetric) -> None:
        self._metrics.append(metric)
        self._by_intent[metric.intent].append(metric.hallucination_score)

    def summary(self) -> Dict[str, Any]:
        if not self._metrics:
            return {
                "total": 0,
                "avg_score": 0.0,
                "hallucination_rate": 0.0,
                "by_intent": {},
                "by_severity": {},
            }
        total = len(self._metrics)
        avg = sum(m.hallucination_score for m in self._metrics) / total
        # "幻觉率"：score >= 0.4 视为疑似幻觉
        hallucinated = sum(1 for m in self._metrics if m.hallucination_score >= 0.4)

        by_intent = {
            intent: {
                "count": len(scores),
                "avg_score": (sum(scores) / len(scores)) if scores else 0.0,
                "hallucination_rate": (
                    sum(1 for s in scores if s >= 0.4) / len(scores)
                ) if scores else 0.0,
            }
            for intent, scores in self._by_intent.items()
        }

        by_severity: Dict[str, int] = defaultdict(int)
        for m in self._metrics:
            by_severity[m.severity] += 1

        return {
            "total": total,
            "avg_score": round(avg, 4),
            "hallucination_rate": round(hallucinated / total, 4),
            "by_intent": by_intent,
            "by_severity": dict(by_severity),
        }

    def reset(self) -> None:
        self._metrics.clear()
        self._by_intent.clear()


# ============================================================
# 单例
# ============================================================

_evaluator_instance: Optional[HallucinationEvaluator] = None
_tracker_instance: Optional[HallucinationTracker] = None


def get_hallucination_evaluator() -> HallucinationEvaluator:
    global _evaluator_instance
    if _evaluator_instance is None:
        _evaluator_instance = HallucinationEvaluator()
    return _evaluator_instance


def get_hallucination_tracker() -> HallucinationTracker:
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = HallucinationTracker()
    return _tracker_instance


def reset_hallucination() -> None:
    global _evaluator_instance, _tracker_instance
    _evaluator_instance = None
    _tracker_instance = None


__all__ = [
    "HallucinationMetric",
    "HallucinationEvaluator",
    "HallucinationTracker",
    "get_hallucination_evaluator",
    "get_hallucination_tracker",
    "reset_hallucination",
]