"""
Eval Harness 核心:Runner + 数据模型 + 配置。

设计目标:
- 不入侵 AIAgent 核心逻辑,只复用 agent.run(prompt)
- 用例与评分解耦,Scorer 通过注册表插入
- 写盘格式兼容 evals/runs/<run_id>/{cases.jsonl, summary.json}

H1 阶段:KeywordScorer / EmbedScorer / CompositeScorer
H3 后续:LlmJudgeScorer(此处不实现,留给后续 PR)
"""
from __future__ import annotations

import logging
import statistics
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

@dataclass
class HarnessCase:
    """一个评测用例"""
    id: str
    prompt: str
    expected: Optional[str] = None                # 用于 keyword/judge
    reference: Optional[str] = None               # 用于 embedding 相似度
    scorers: List[str] = field(default_factory=lambda: ["keyword"])
    scorer_config: Dict[str, Any] = field(default_factory=dict)
    category: str = "general"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HarnessCase":
        return cls(
            id=str(d.get("id") or d.get("name") or uuid.uuid4().hex[:8]),
            prompt=str(d["prompt"]),
            expected=d.get("expected"),
            reference=d.get("reference"),
            scorers=list(d.get("scorers") or ["keyword"]),
            scorer_config=dict(d.get("scorer_config") or {}),
            category=str(d.get("category") or "general"),
            metadata=dict(d.get("metadata") or {}),
        )


@dataclass
class SubScore:
    """单个评分器的输出"""
    name: str
    value: float                                 # 0~1
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "value": self.value, "detail": self.detail}


@dataclass
class CaseResult:
    """单条用例的运行结果"""
    case_id: str
    category: str
    passed: bool
    score: float
    sub_scores: Dict[str, SubScore]
    observed: Dict[str, Any]
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.case_id,                # 与既有 evals/runs 字段对齐(name 而非 case_id)
            "case_id": self.case_id,
            "category": self.category,
            "passed": self.passed,
            "score": self.score,
            "duration_ms": float(self.observed.get("elapsed_ms", 0.0)),
            "detail": "ok" if self.passed else "fail",
            "sub_scores": {k: v.to_dict() for k, v in self.sub_scores.items()},
            "observed": self.observed,
            "error": self.error,
        }


@dataclass
class HarnessConfig:
    """运行配置"""
    pass_threshold: float = 0.6
    per_case_timeout_s: float = 60.0
    aggregate_weights: Dict[str, float] = field(
        default_factory=lambda: {"keyword": 1.0, "embed": 1.0, "composite": 1.0}
    )
    extra_tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class RunResult:
    """一次 Harness 跑的汇总"""
    run_id: str
    started_at: str
    finished_at: str
    cases_total: int
    cases_passed: int
    cases_failed: int
    cases_errored: int
    pass_rate: float
    mean_score: float
    p50_latency_ms: float
    p95_latency_ms: float
    set_path: str
    config: Dict[str, Any]
    cases: List[CaseResult]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "cases_total": self.cases_total,
            "cases_passed": self.cases_passed,
            "cases_failed": self.cases_failed,
            "cases_errored": self.cases_errored,
            "pass_rate": self.pass_rate,
            "mean_score": self.mean_score,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "set_path": self.set_path,
            "config": self.config,
            "cases": [c.to_dict() for c in self.cases],
        }


# ============================================================
# Scorer 协议与注册表
# ============================================================

class Scorer:
    """评分器基类。子类实现 score() 返回 SubScore(value in [0,1])"""
    name: str = "base"

    def score(self, output: str, case: HarnessCase) -> SubScore:  # pragma: no cover
        raise NotImplementedError


class ScorerRegistry:
    _scorers: Dict[str, Scorer] = {}

    @classmethod
    def register(cls, name: str, scorer: Scorer) -> None:
        cls._scorers[name] = scorer

    @classmethod
    def get(cls, name: str) -> Scorer:
        if name not in cls._scorers:
            raise KeyError(
                f"scorer '{name}' not registered. available={list(cls._scorers)}"
            )
        return cls._scorers[name]

    @classmethod
    def names(cls) -> List[str]:
        return list(cls._scorers.keys())


# ---------- 内置评分器(关键词 / 嵌入 / 复合) ----------

class KeywordScorer(Scorer):
    """统计 expected 中每个 token 在 output 中出现的比例。

    例: expected="echo: hi" → tokens=["echo:", "hi"]; output="echo: hi there"
       → 2/2 = 1.0
    """
    name = "keyword"

    def score(self, output: str, case: HarnessCase) -> SubScore:
        if not case.expected:
            return SubScore(self.name, 0.0, {"reason": "expected is empty"})
        # 用空格切分,空字符串过滤掉
        tokens = [t for t in case.expected.split() if t]
        if not tokens:
            return SubScore(self.name, 0.0, {"reason": "no tokens"})
        hits = sum(1 for t in tokens if t in output)
        value = hits / len(tokens)
        return SubScore(self.name, value, {
            "tokens": len(tokens),
            "hits": hits,
            "expected": case.expected,
        })


class EmbedScorer(Scorer):
    """基于 embedding 余弦相似度。复用 rag.get_embedding_model。

    无 API key 或 embedding 失败时返回 0.0 而非抛异常,保证 Harness 不会因
    单条评分器挂了导致整个 run 失败。
    """
    name = "embed"

    def __init__(self) -> None:
        self._emb = None
        self._load_attempted = False

    def _try_load(self) -> None:
        if self._load_attempted:
            return
        self._load_attempted = True
        try:
            from rag import get_embedding_model  # 延迟导入,避免冷启动开销
            self._emb = get_embedding_model()
        except Exception as e:  # noqa: BLE001
            logger.warning("[harness] EmbedScorer disabled: %s", e)
            self._emb = None

    def score(self, output: str, case: HarnessCase) -> SubScore:
        ref = case.reference or case.expected
        if not ref:
            return SubScore(self.name, 0.0, {"reason": "no reference"})
        self._try_load()
        if self._emb is None:
            return SubScore(self.name, 0.0, {"reason": "embedder unavailable"})
        try:
            v1 = self._emb.embed_query(output)
            v2 = self._emb.embed_query(ref)
            sim = _cosine(v1, v2)
        except Exception as e:  # noqa: BLE001
            logger.warning("[harness] embed failed: %s", e)
            return SubScore(self.name, 0.0, {"reason": f"embed error: {e}"})
        # 把相似度从 [-1,1] 归一到 [0,1]
        norm = max(0.0, min(1.0, (sim + 1.0) / 2.0))
        return SubScore(self.name, norm, {"cosine": sim})


class CompositeScorer(Scorer):
    """按权重聚合多个子评分器。

    用法 (case.scorers=["composite"], case.scorer_config={"weights": {"keyword":1,"embed":2}})
    """
    name = "composite"

    def __init__(self, registry: ScorerRegistry | None = None) -> None:
        self._registry = registry or ScorerRegistry

    def score(self, output: str, case: HarnessCase) -> SubScore:
        weights: Dict[str, float] = (case.scorer_config or {}).get("weights") or {}
        if not weights:
            # 默认聚合 case.scorers 里所有非 composite 项
            weights = {n: 1.0 for n in case.scorers if n != "composite"}
        if not weights:
            return SubScore(self.name, 0.0, {"reason": "no weights"})
        subs: Dict[str, SubScore] = {}
        for name, w in weights.items():
            try:
                subs[name] = self._registry.get(name).score(output, case)
            except KeyError as e:
                subs[name] = SubScore(name, 0.0, {"reason": str(e)})
        total_w = sum(max(0.0, w) for w in weights.values())
        if total_w <= 0:
            return SubScore(self.name, 0.0, {"reason": "zero total weight"})
        value = sum(subs[n].value * max(0.0, w) for n, w in weights.items()) / total_w
        return SubScore(self.name, value, {
            "weights": weights,
            "sub_scores": {n: s.value for n, s in subs.items()},
        })


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# 启动时注册内置评分器
ScorerRegistry.register("keyword", KeywordScorer())
ScorerRegistry.register("embed", EmbedScorer())
ScorerRegistry.register("composite", CompositeScorer())


# ============================================================
# HarnessRunner
# ============================================================

class HarnessRunner:
    """驱动 AIAgent 跑评测用例并打分。"""

    def __init__(
        self,
        agent: Any,                       # AIAgent 实例(duck typing)
        config: Optional[HarnessConfig] = None,
        registry: Optional[ScorerRegistry] = None,
        observability: Any = None,        # 可选:注入自定义 observability(单测用)
    ) -> None:
        self.agent = agent
        self.config = config or HarnessConfig()
        self.registry = registry or ScorerRegistry
        # 显式传 None 表示"不要上报";不传 → lazy load 全局单例
        self._observability = (
            observability if observability is not None
            else _try_load_observability()
        )

    # ---------- 对外 API ----------
    def run(self, cases: Iterable[HarnessCase]) -> RunResult:
        cases_list = list(cases)
        run_id = "harness_" + datetime.utcnow().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        started = datetime.utcnow().isoformat(timespec="seconds")
        results: List[CaseResult] = []
        t_run0 = time.monotonic()

        for c in cases_list:
            r = self._run_one(c, run_id)
            results.append(r)

        finished = datetime.utcnow().isoformat(timespec="seconds")
        latencies = [r.observed.get("elapsed_ms", 0.0) for r in results]
        passed = sum(1 for r in results if r.passed)
        errored = sum(1 for r in results if r.error)
        failed = len(results) - passed
        mean_score = (sum(r.score for r in results) / len(results)) if results else 0.0

        rr = RunResult(
            run_id=run_id,
            started_at=started,
            finished_at=finished,
            cases_total=len(results),
            cases_passed=passed,
            cases_failed=failed,
            cases_errored=errored,
            pass_rate=(passed / len(results)) if results else 0.0,
            mean_score=mean_score,
            p50_latency_ms=_percentile(latencies, 50),
            p95_latency_ms=_percentile(latencies, 95),
            set_path="",
            config=asdict(self.config),
            cases=results,
        )
        # 指标上报(若 observability 可用)
        if self._observability is not None:
            try:
                # 延迟导入,避免冷启动开销
                from harness_observability import record_metric as _rec, record_event as _evt
                tags = {"run_id": run_id, **self.config.extra_tags}
                ok1 = _rec(self._observability, "harness.run.pass_rate", rr.pass_rate,
                           tags=tags, help_text="Eval Harness 通过率")
                ok2 = _rec(self._observability, "harness.run.mean_score", rr.mean_score,
                           tags=tags, help_text="Eval Harness 平均分")
                ok3 = _rec(self._observability, "harness.run.cases_total",
                           float(rr.cases_total), tags=tags,
                           help_text="Eval Harness 用例总数")
                _evt(self._observability, "harness.run.finished", "harness_runner",
                     trace_id=run_id,
                     payload={
                         "pass_rate": rr.pass_rate,
                         "mean_score": rr.mean_score,
                         "cases_total": rr.cases_total,
                         "cases_passed": rr.cases_passed,
                         "p50_latency_ms": rr.p50_latency_ms,
                     })
                if not (ok1 and ok2 and ok3):
                    logger.debug("[harness] observability partial report")
            except Exception as e:  # noqa: BLE001
                logger.debug("[harness] observability record failed: %s", e)
        logger.info(
            "[harness] %s done in %.2fs: %d/%d passed (pass_rate=%.2f)",
            run_id, time.monotonic() - t_run0, passed, len(results), rr.pass_rate,
        )
        return rr

    # ---------- 单条用例 ----------
    def _run_one(self, case: HarnessCase, run_id: str) -> CaseResult:
        session_id = f"harness-{run_id}-{case.id}"
        t0 = time.monotonic()
        output = ""
        error: Optional[str] = None
        try:
            output = self.agent.run(case.prompt, session_id=session_id)
        except Exception as e:  # noqa: BLE001
            error = repr(e)
            output = ""
        elapsed_ms = (time.monotonic() - t0) * 1000.0

        # 评分
        sub_scores: Dict[str, SubScore] = {}
        if error is None:
            for name in case.scorers:
                try:
                    sub_scores[name] = self.registry.get(name).score(output, case)
                except KeyError as e:
                    sub_scores[name] = SubScore(name, 0.0, {"reason": str(e)})
                except Exception as e:  # noqa: BLE001
                    logger.warning("[harness] scorer '%s' failed: %s", name, e)
                    sub_scores[name] = SubScore(name, 0.0, {"reason": repr(e)})

        score = _aggregate(sub_scores, case, self.config)
        passed = (error is None) and (score >= self.config.pass_threshold)

        # per-case 指标
        if self._observability is not None:
            try:
                from harness_observability import record_metric as _rec
                _rec(self._observability, "harness.case.score", score,
                     tags={"case_id": case.id, "category": case.category,
                           "run_id": run_id, **self.config.extra_tags},
                     help_text="Eval Harness 单条用例得分")
            except Exception:  # noqa: BLE001
                pass

        return CaseResult(
            case_id=case.id,
            category=case.category,
            passed=passed,
            score=score,
            sub_scores=sub_scores,
            observed={"final": output, "elapsed_ms": elapsed_ms,
                      "session_id": session_id},
            error=error,
        )


def _aggregate(subs: Dict[str, SubScore], case: HarnessCase, cfg: HarnessConfig) -> float:
    """把多个 SubScore 折成一个 0~1 的综合分。"""
    if not subs:
        return 0.0
    # 单一非 composite → 直接返回
    if len(subs) == 1 and "composite" not in subs:
        return next(iter(subs.values())).value
    # 含 composite → 优先用 composite(它已聚合)
    if "composite" in subs:
        return subs["composite"].value
    # 多评分器无 composite → 等权平均
    return sum(s.value for s in subs.values()) / len(subs)


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    return statistics.quantiles(values, n=100, method="inclusive")[int(p) - 1] \
        if len(values) >= 2 else float(values[0])


def _try_load_observability():
    """尽力加载观测层;失败不影响 Harness 主流程。"""
    try:
        from observability import get_observability
        return get_observability()
    except Exception:  # noqa: BLE001
        return None