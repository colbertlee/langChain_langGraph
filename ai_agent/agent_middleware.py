"""LangChain 1.x AgentMiddleware 集合。

本模块提供一组可插拔的 middleware，演示 LangChain 1.x 官方 hooks
（before_model / after_model / wrap_model_call / before_agent / after_agent）
在本项目里的标准用法。

- LoggingMiddleware：before_model/after_model，记录模型调用耗时与消息摘要。
- ToolCallCounterMiddleware：after_model，统计本轮触发的 tool_calls 数。
- ContextTrimMiddleware：before_model，消息过长时裁剪最旧的非系统消息。
- PIIScrubMiddleware：before_model，对最近 Human 消息做 PII 脱敏。
- RateLimitMiddleware：before_model，按时间窗口/调用次数做滑动限流。
- AuditLogMiddleware：before_agent/after_agent，写入审计轨迹（jsonl 追加）。
- TokenUsageMiddleware：after_model，累加 token 用量到 state + 指标。
- OutputSafetyMiddleware：after_model，对 AI 输出做敏感词/泄露审查，违规抛回。

接入位置见 `agent.py:init_agent` -> `create_agent(..., middleware=[...])`。
"""

from __future__ import annotations

__version__ = "0.4.2"

import logging
import time
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

# LangChain 1.x 官方 middleware 基类与类型。
# 兼容老版本时这里会 ImportError，由调用方做 try/except。
try:  # pragma: no cover - 导入保护
    from langchain.agents.middleware import (
        AgentMiddleware,
        ModelRequest,
        ModelCallResult as ModelResult,  # 1.x 改名
    )
    _HAS_OFFICIAL_MW = True
except Exception:  # noqa: BLE001
    AgentMiddleware = object  # type: ignore[assignment]
    ModelRequest = Any  # type: ignore[assignment]
    ModelResult = Any  # type: ignore[assignment]
    _HAS_OFFICIAL_MW = False


logger = logging.getLogger(__name__)


class LoggingMiddleware(AgentMiddleware if _HAS_OFFICIAL_MW else object):
    """记录每一次模型调用的耗时与消息数量的日志 middleware。"""

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        msgs = (state or {}).get("messages", []) if isinstance(state, dict) else []
        logger.info("[hook/before_model] messages=%d", len(msgs))
        # 写入状态，让 after_model 能读到 start 时间。
        return {"_hook_model_start": time.time()}

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        start = (state or {}).get("_hook_model_start") if isinstance(state, dict) else None
        if isinstance(start, (int, float)):
            logger.info("[hook/after_model] elapsed=%.3fs", time.time() - start)
        return None


class ToolCallCounterMiddleware(AgentMiddleware if _HAS_OFFICIAL_MW else object):
    """在 after_model 钩子里读取本轮 AIMessage 的 tool_calls 并累计。"""

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        msgs = (state or {}).get("messages", []) if isinstance(state, dict) else []
        count = 0
        for m in reversed(msgs):
            tool_calls = getattr(m, "tool_calls", None)
            if tool_calls:
                count = len(tool_calls)
                break
        if count:
            logger.info("[hook/tool_calls] this_turn=%d", count)
        return {"_hook_tool_calls": count}


class ContextTrimMiddleware(AgentMiddleware if _HAS_OFFICIAL_MW else object):
    """消息数超过阈值时，丢弃最早的若干条 Human/AI 消息（保留 system）。"""

    def __init__(self, max_messages: int = 20) -> None:
        self.max_messages = max_messages

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if not isinstance(state, dict):
            return None
        msgs = state.get("messages") or []
        if len(msgs) <= self.max_messages:
            return None
        # 保留首条 system，其余从尾部保留 max_messages-1 条。
        head = msgs[:1]
        tail = msgs[-(self.max_messages - 1):]
        logger.info("[hook/trim] %d -> %d", len(msgs), len(head) + len(tail))
        return {"messages": head + tail}


import re as _re
from dataclasses import dataclass, field


# ───────────────────────── 可注入配置（统一管理 PII / 输出敏感词 / 限流 / 监控后端） ─────────────────────────


@dataclass
class PIIScrubConfig:
    """PII 脱敏配置：可注入到 :class:`PIIScrubMiddleware`。

    默认覆盖邮箱 / 中国大陆手机号 / 13-19 位数字（近似卡号）。
    通过 :attr:`extra_patterns` 可补充企业内部模式（身份证、订单号等）。
    """

    replacement: str = "[REDACTED]"
    extra_patterns: tuple[str, ...] = ()
    # 仅处理 type/role ∈ 这两类消息，避免误改 system / tool 消息
    target_message_types: tuple[str, ...] = ("human", "user")

    def compiled(self) -> tuple[_re.Pattern[str], ...]:
        base = (
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            r"(?<!\d)1[3-9]\d{9}(?!\d)",
            r"(?<!\d)\d{13,19}(?!\d)",
        )
        all_pat = base + tuple(self.extra_patterns)
        return tuple(_re.compile(p) for p in all_pat)


@dataclass
class OutputSafetyConfig:
    """输出安全审查配置：可注入到 :class:`OutputSafetyMiddleware`。

    双模式审查：
    1. 关键词（默认）：``block_words`` + ``case_insensitive``
    2. **LLM-based judge**（可选）：``llm_judge`` 是一个 ``Callable[[str], SafetyVerdict]``
       会替代/补充关键词审查；详见 :class:`SafetyVerdict`

    ``mode``：
    - ``raise``：命中即抛 ValueError（agent 走 error branch）
    - ``redact``：命中即替换为 ``[SAFETY: <categories>] ...` 标记
    """

    mode: str = "raise"   # "raise" | "redact"
    block_words: tuple[str, ...] = (
        "<system>",
        "ignore previous instructions",
        "忽略之前的指令",
        "system prompt:",
    )
    case_insensitive: bool = True
    # ── LLM-based 安全审查 ──
    # 调用签名：``(text: str) -> SafetyVerdict``
    # 不传时跳过 LLM 审查（仅走关键词路径）
    llm_judge: object | None = None
    # LLM 审查失败时的 fallback：True=当作 safe（fail-open）；False=当 unsafe（fail-closed）
    # 默认 fail-closed：LLM 出错 → 视作 unsafe → 走 mode 逻辑
    llm_judge_fail_closed: bool = True
    # LLM judge 调用的超时（秒，None=不限）
    llm_judge_timeout: float | None = None
    # 只在内容长度 >= 这个阈值时才走 LLM judge（节省成本）
    llm_judge_min_length: int = 50
    # ── LLM judge 缓存（避免重复调用 judge） ──
    # 缓存大小（None = 关闭缓存；默认 256）
    llm_judge_cache_size: int | None = 256
    # 缓存 TTL（秒，None = 不过期；默认 300s）
    llm_judge_cache_ttl: float | None = 300.0
    # 自定义 cache key 函数（默认 hash(text)[:16]；返回 str）
    llm_judge_cache_key_fn: object | None = None
    # ── score 与 threshold 联合判定 ──
    # 当 judge 返回 SafetyVerdict(score=0.7, confidence=0.6) 且 threshold=0.5 时：
    #   - score=0.7 ≥ safety_threshold=0.5 → 判 unsafe（独立于 judge 的 safe 字段）
    # - None = 不基于 score 二次判定（仅看 judge.safe）
    #   - 推荐 0.5~0.7；越高越严格
    safety_threshold: float | None = None
    # ── 多 judge 投票（与 llm_judge 二选一或共存） ──
    # list[Callable[[str], SafetyVerdict]]；每个 judge 独立投票
    # 与 llm_judge 共存时：llm_judge 先调，再调 llm_judges
    llm_judges: tuple[object, ...] = ()
    # voting strategy:
    #   "unanimous"：所有 judge 判 unsafe 才算 unsafe（最严格）
    #   "majority"：多数 judge 判 unsafe（默认；>= 50%）
    #   "any"：任一 judge 判 unsafe（最宽松）
    #   "weighted_majority"：按 score 加权；score 求和 > threshold
    llm_voting_strategy: str = "majority"
    # weighted_majority 用的 score 阈值
    llm_voting_score_threshold: float = 0.5
    # weighted_severity threshold：v0.4.13 新增
    # weighted_severity strategy 用 score×confidence 求和超阈值判 unsafe
    # 默认 0.5（兼容 llm_voting_score_threshold）
    llm_voting_weighted_severity_threshold: float = 0.5
    # ── explanation LLM 生成（v0.4.15 新增） ──
    # 当 verdict.safe=False 且 verdict.explanation 为空时，调 explanation_llm 自动生成
    # signature: (text: str, verdict: SafetyVerdict) -> dict[str, str]
    #   返回 dict[category → explanation]，用于填充 verdict.explanation
    # None = 禁用（默认，旧行为；verdict 没有 explanation 字段就跳过）
    explanation_llm: object | None = None
    # explanation_prompt: 自定义 prompt 模板（含 {text} 和 {categories} 占位符）
    # 仅当 explanation_llm 返回 dict 时作为 fallback（自定义 LLM 调用）
    # None = 使用 explanation_llm(verdict, text) 直接调用
    explanation_prompt: str | None = None
    # ── explanation_llm cache（v0.4.16 新增） ──
    # 0 = 禁用（默认，旧行为）
    # >0 = LRU 缓存最近 N 个 (text_hash, categories_tuple) → dict[cat, explanation]
    # 推荐 100~1000；避免重复 LLM 调用（同样的 text + categories 直接走缓存）
    # 注：cache key = sha256(text) + tuple(categories)；不存原 text（省内存）
    explanation_llm_cache_size: int = 0
    # ── category_severity：按严重度过滤 ──
    # safety_min_severity: 低于该严重度的 category 不触发审查
    # "critical" / "high" / "medium" / "low"；None=不过滤
    # 例：safety_min_severity="high" → 只拦 critical + high；low/medium 放过
    safety_min_severity: str | None = None
    # 默认 category 严重度映射（用户可在 safety_min_severity 用）
    category_aliases: dict[str, str] = field(default_factory=dict)
    # ── category_alias_regex（v0.4.15 新增） ──
    # 用 fnmatch 风格通配符映射：{"pii*": "pii_leak", "*_leak": "data_leak"}
    # 与 category_aliases 正交：
    #   - category_aliases: 精确匹配（pii → pii_leak）
    #   - category_alias_regex: 通配符匹配（pii* → pii_leak）
    # 多 regex 命中时取最长的 pattern（更具体优先）
    category_alias_regex: dict[str, str] = field(default_factory=dict)
    # ── category_alias_regex_mode（v0.4.16 新增） ──
    # "fnmatch"（默认，v0.4.15 行为）→ glob 风格通配符（* / ? / [...]）
    # "regex" → re.compile（完整正则语法：^ / $ / \d / \w / | / () / {n,m} 等）
    # 注：regex 模式 pattern 是 raw string（避免 \d / \w 被 Python 字符串转义）
    # 推荐：fnmatch 简单场景；regex 复杂场景
    category_alias_regex_mode: str = "fnmatch"
    # ── category_aliases（v0.4.14 新增） ──
    # category 别名映射：把多种别名映射到 canonical category
    # 例：{"pii": "pii_leak", "personal": "pii_leak", "PII": "pii_leak"}
    # 默认空（不映射）
    # 应用时机：_normalize_verdict + _apply_severity_filter（统一标准化）
    category_severity_map: dict[str, str] = field(default_factory=lambda: {
        "prompt_injection": "critical",
        "jailbreak": "critical",
        "pii_leak": "high",
        "toxicity": "high",
        "bias": "medium",
        "hate_speech": "high",
        "violence": "high",
        "spam": "low",
    })
    # ── judge 异构 timeout ──
    # 每个 judge 独立超时；key = judge id（id(judge) 或 hash(str(judge))）
    # None = 用 llm_judge_timeout；0 = 不超时（同步阻塞）
    # 推荐：小模型用 1.0s，大模型用 5.0s
    llm_judge_timeouts: dict[int, float | None] = field(default_factory=dict)
    # ── judge 异步并发 ──
    # 1 = 顺序（默认，旧行为）；>1 = 用 ThreadPoolExecutor 并发调多个 judge
    # 推荐场景：多 judge voting 时用 4~8 提速；单 judge 时保持 1
    llm_judge_concurrency: int = 1
    # ── per-judge 并发开关 ──
    # llm_judge_per_concurrency: dict[judge_key → bool]
    # True（默认）= 该 judge 与其他 judge 并发（_vote_judgers 用 ThreadPoolExecutor）
    # False = 该 judge 走 sequential 路径（其他 judge 不阻塞）
    # 典型场景：某些 judge 是同步阻塞（Redis 监控、本地脚本）→ False
    #           其他 judge 是网络 IO（OpenAI、Anthropic）→ True
    # key 同 llm_judge_timeouts：id(judge) / str(judge) / judge.__name__
    # 未配置回落到 llm_judge_concurrency > 1 决定
    llm_judge_per_concurrency: dict[Any, bool] = field(default_factory=dict)
    # ── judge 优先级排序（v0.4.13 新增） ──
    # llm_judge_priorities: dict[judge_key, int]
    # 整数，值越大优先级越高（默认 0）。ties 用原始顺序保持稳定
    # 高优先级 judge 先调（sequential 时严格按顺序；concurrent 时仍是并发，但结果排序按优先级）
    # 推荐：安全关键 judge（如 PII 检测）→ 高优先级；辅助 judge（如 style check）→ 低优先级
    llm_judge_priorities: dict[Any, int] = field(default_factory=dict)
    # 也支持以"judge 名字"为 key（适合 judge 是 named function / lambda 难 id 的场景）
    # 实际 key 直接用 id(judge)；命名 lookup 走 _judge_timeout_for

    def __post_init__(self) -> None:
        if self.mode not in ("raise", "redact"):
            raise ValueError(f"invalid mode: {self.mode}")
        if self.llm_voting_strategy not in (
            "unanimous", "majority", "any", "weighted_majority", "weighted_severity",
        ):
            raise ValueError(
                f"invalid llm_voting_strategy: {self.llm_voting_strategy}",
            )


@dataclass
class SafetyVerdict:
    """LLM 安全审查的判定结果。

    Attributes:
        safe: 是否安全
        reason: 简短理由（用于日志）
        categories: 触发的安全类别（如 ``["prompt_injection", "pii_leak"]``）
        score: 0.0~1.0 风险分（None=未知）；越高越危险
        confidence: 0.0~1.0 置信度（None=未知）；judge 自我评价
                  配合 :attr:`OutputSafetyConfig.safety_threshold` 判定：
                  - ``confidence < threshold`` → 信任 score 判定
                  - ``confidence >= threshold`` → 信任 judge 判定
        category_severity: dict[category → severity]，可选
                  严重度："critical" > "high" > "medium" > "low"
                  配合 :attr:`OutputSafetyConfig.safety_min_severity` 过滤
    """
    safe: bool
    reason: str = ""
    categories: list[str] = field(default_factory=list)
    score: float | None = None
    confidence: float | None = None
    category_severity: dict[str, str] = field(default_factory=dict)
    # multi_categories_severity：同 category 多次投票（v0.4.10 新增）
    # 例：5 个 judge 中 3 个判 pii=high + 2 个判 pii=critical
    #   → {"pii": ["high", "high", "high", "critical", "critical"]}
    # 多数决定严重度；_aggregate_verdicts 自动填这个字段
    multi_categories_severity: dict[str, list[str]] = field(default_factory=dict)
    # confidence_per_category: 每个 category 独立 confidence（v0.4.11 新增）
    # 例：{"pii": 0.95, "spam": 0.6}
    # 配合 _apply_severity_filter 做 per-category 二次判定
    # None 的 category 回落 SafetyVerdict.confidence
    confidence_per_category: dict[str, float] = field(default_factory=dict)
    # multi_categories_confidence: 同 category 的多 judge confidence 原始投票（v0.4.12 新增）
    # 例：3 judge 判 pii confidence=[0.9, 0.85, 0.95]
    #   → {"pii": [0.9, 0.85, 0.95]}
    # 配合 confidence_per_category 平均使用
    multi_categories_confidence: dict[str, list[float]] = field(default_factory=dict)
    # weighted_severity: 每 category 的 score × confidence 加权分（v0.4.13 新增）
    # 例：3 judge 判 pii score=[0.9, 0.85, 0.95], confidence=[0.9, 0.8, 0.95]
    #   weighted_severity["pii"] = mean(score × confidence) = mean(0.81, 0.68, 0.9025) ≈ 0.7975
    # 用于排序：weighted_severity 高的 category 优先拦截
    weighted_severity: dict[str, float] = field(default_factory=dict)
    # explanation: 每 category 的 LLM 解释（v0.4.14 新增）
    # 例：{"pii": "Detected phone number 138-1234-5678 in context"}
    # judge 返回 dict 里有 "explanation" 字段时自动抽
    # _aggregate_verdicts 合并时按"最长"规则取（保留最详细解释）
    explanation: dict[str, str] = field(default_factory=dict)


_SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _meets_severity(severity: str, min_severity: str) -> bool:
    """severity 是否 ≥ min_severity。"""
    s = _SEVERITY_ORDER.get(severity.lower(), 0)
    m = _SEVERITY_ORDER.get(min_severity.lower(), 0)
    return s >= m


@dataclass
class RateLimitConfig:
    """限流配置：可注入到 :class:`RateLimitMiddleware`。

    ``backend``：
    - ``"memory"``：进程内滑动窗口（默认，无需额外依赖）
    - ``"redis"``：跨进程/跨实例分布式限流（需安装 ``redis>=5``）

    ``use_shared_instance``（仅 Redis 后端）：
    - ``True``：所有实例共享同一 key（即所有实例合计限流）
    - ``False``（默认）：每个实例独立 key（即每实例各自限流）
      此时 ``instance_id`` 默认取启动时生成的 uuid，前缀可在创建后通过
      :attr:`instance_id` 注入同一值以手动指定共享/拆分。
    """

    max_calls: int = 30
    window_seconds: float = 60.0
    backend: str = "memory"   # "memory" | "redis" | "redis_cluster" | "redis_sentinel"
    # 限流策略（3 种）：
    # - "sliding_window"（默认）：滑动窗口，旧行为
    # - "fixed_window"：固定窗口（按 start_of_window 分桶，边界效应）
    # - "token_bucket"：令牌桶（连续补 token，容许突发）
    # 仅 backend="memory" 时支持；redis 后端仍走 sliding_window（暂未实现）
    rate_limit_strategy: str = "sliding_window"
    redis_url: str | None = None
    # Redis Cluster：传 "redis://node1:6379,redis://node2:6379,redis://node3:6379"
    # 会用 redis.cluster.RedisCluster 自动初始化；hash tag 强制同 slot
    cluster_url: str | None = None
    # Redis Sentinel：传 [(host1, port1), (host2, port2), ...]
    # service_name 是 Sentinel 监控的 master 服务名（如 "mymaster"）
    sentinel_hosts: tuple[tuple[str, int], ...] = ()
    sentinel_service_name: str = "mymaster"
    sentinel_db: int = 0
    sentinel_password: str | None = None
    redis_key_prefix: str = "ratelimit:agent"
    # ── dynamic_strategy：按 key 前缀切换不同策略 ──
    # dict[prefix -> strategy]; redis 后端专用
    # 例: {"chat:": "sliding_window", "embed:": "token_bucket"}
    # 注：dynamic_strategy 的优先级 > rate_limit_strategy（仅 redis 后端生效）
    # memory 后端仍走单一 rate_limit_strategy（多策略请用 redis）
    dynamic_strategy: dict[str, str] = field(default_factory=dict)
    # ── dynamic_strategy_mixed（v0.4.14 新增） ──
    # dynamic_strategy_mixed: dict[prefix → dict[strategy_args]]
    # 与 dynamic_strategy 正交：
    #   - dynamic_strategy: 单 string（如 "token_bucket"）
    #   - dynamic_strategy_mixed: dict[strategy_args]（多参数混合）
    # 例：{
    #   "chat:": {"strategy": "sliding_window_log", "max_window_size": 200},
    #   "embed:": {"strategy": "sliding_window_counter", "max_window_size": 50},
    #   "search:": {"strategy": "token_bucket", "burst_size": 20},
    # }
    # 应用时机：_build_backend 中根据 model_name 决定 strategy
    # 推荐：dynamic_strategy 给简单场景（只换 strategy），mixed 给精细场景（换 strategy + 参数）
    dynamic_strategy_mixed: dict[str, dict[str, Any]] = field(default_factory=dict)
    # ── dynamic_strategy_mixed pubsub 热加载（v0.4.15 新增） ──
    # dynamic_strategy_mixed_pubsub_channel: 订阅的 Redis channel 名（None=禁用）
    # 与 dynamic_strategy_pubsub_channel 复用 watcher：
    #   - 收到 dict（纯 prefix→strategy 字符串映射）→ 覆盖 dynamic_strategy
    #   - 收到 dict[prefix → dict]（含 strategy / max_window_size 等）→ 覆盖 dynamic_strategy_mixed
    # 通过消息内容自动判断（schema 检测）
    # 推荐与 dynamic_strategy_pubsub_channel 用同一 channel；后端通过消息格式分发
    dynamic_strategy_mixed_pubsub_channel: str | None = None
    # ── dynamic_strategy_mixed per-prefix 独立 channel（v0.4.16 新增） ──
    # dynamic_strategy_mixed_per_prefix_channel: dict[prefix → channel]
    # 每个 prefix 独立的 watcher；消息内容只覆盖该 prefix 的 mixed 配置
    # 消息格式：{"strategy": "token_bucket", "burst_size": 100}（直接 dict，不是 dict[prefix → dict]）
    # 推荐场景：高频更新的 prefix（chat:）用独立 channel 避免影响低频 prefix（embed:）
    dynamic_strategy_mixed_per_prefix_channel: dict[str, str] = field(default_factory=dict)
    # ── dynamic_strategy hot-reload（运行时改不重启） ──
    # dynamic_strategy_loader: Callable[[], dict[str, str]]
    # 每次 _maybe_reload_dynamic_strategy 时调用，结果覆盖 self.config.dynamic_strategy
    # 典型实现：从文件 / Redis / 配置中心拉最新
    dynamic_strategy_loader: object | None = None
    # 重新拉取间隔（秒，None = 不轮询；0 = 不轮询；>0 = 启用轮询）
    # 推荐 30~300s；过短会反复 load，过长更新延迟大
    dynamic_strategy_reload_interval: float = 0.0
    # ── 失败 backoff（v0.4.12 新增） ──
    # dynamic_strategy_reload_backoff: (initial_factor, max_factor, multiplier)
    # 例：(2.0, 8.0, 2.0) → 失败后下次 reload 间隔 = current × 2，封顶 8× current
    # 成功后立即重置回 baseline（即 dynamic_strategy_reload_interval）
    # None = 禁用 backoff（失败也不延后）
    dynamic_strategy_reload_backoff: tuple[float, float, float] | None = None
    # 连续失败次数上限；超过后停止重试直到 reload_interval 重新"冷却"
    # None = 无上限
    dynamic_strategy_reload_max_failures: int | None = None
    # ── dynamic_strategy watcher（Redis pub/sub 实时推送） ──
    # dynamic_strategy_pubsub_channel: 订阅的 Redis channel 名（None=禁用）
    # 收到消息后：消息内容解析为 JSON dict → 覆盖 config.dynamic_strategy + 同步 backend
    # 推荐与 dynamic_strategy_loader 共用；watcher 是即时推送，loader 是周期拉
    # 用法：发布端 redis-cli publish my_channel '{"chat:": "token_bucket"}'
    # 注意：必须 backend="redis" / "redis_cluster" / "redis_sentinel"；memory 后端无效
    dynamic_strategy_pubsub_channel: str | None = None
    # ── sliding_window_log 精确内存上限（v0.4.13 新增） ──
    # None = 不限（仅按 window_seconds 砍窗口外，理论上无限增长）
    # >0 = 用 ZREMRANGEBYRANK 保留最新 max_window_size 条历史
    # 推荐：max_calls * 2~5（兼顾精度和内存）
    max_window_size: int | None = None
    # ── sliding_window_log cold-start（v0.4.14 新增） ──
    # cold_start_calls: 前 N 次调用无脑通过（不限流）
    # 0 = 默认（旧行为，不预热）
    # >0 = 推荐场景：新实例启动 / 重启后允许冷流量通过；避免"刚启动就限流"
    # 注意：cold-start 与限流独立；走完 cold-start 后正常进入限流逻辑
    cold_start_calls: int = 0
    # ── burst_size：令牌桶独立 max_burst ──
    # 仅 token_bucket 策略生效：
    # - max_burst=None (默认) → 桶初始容量 = max_calls（满桶启动）
    # - max_burst=int → 桶初始容量 = burst_size（独立设置突发容量）
    # 稳态补 token 速率仍 = max_calls / window_seconds
    # 例：max_calls=60, window_seconds=60 → 1 token/秒；
    #      burst_size=10 → 可一次性消耗 10 个 token（突发 10 次调用）
    burst_size: int | None = None
    # 自定义判定函数（可选）；签名为 (count_in_window: int) -> bool 返回是否触发限流
    predicate: object | None = None
    # 多实例 Redis 模式：所有实例共享同一窗口 / 每实例独立窗口
    use_shared_instance: bool = False
    # 实例标识；None 时自动生成 uuid4；注入相同值可让多个进程共享同一 key。
    instance_id: str | None = None
    # ── model_budget：per-model rate limit ──
    # dict[model_name -> max_calls];key 查不到时回落到 max_calls
    # 抽 model_name 的优先级：
    #   1. state["_hook_model_name"]（TokenUsageMiddleware after_model 写入）
    #   2. runtime.metadata.model_name
    #   3. runtime.config["metadata"]["model_name"]
    model_budget: dict[str, int] = field(default_factory=dict)
    # ── wait_for_retry：被限流后自动 sleep 退避重试 ──
    # 退避：min(base * 2^attempt, cap) + jitter，attempt 从 0 起
    # 0 次或 None 时维持"只观测不重试"（默认行为，向后兼容）
    wait_for_retry_attempts: int = 0
    wait_for_retry_base_seconds: float = 0.1
    wait_for_retry_cap_seconds: float = 5.0
    wait_for_retry_jitter: float = 0.1  # 抖动比例（0~1）


def _make_rate_limit_key(
    prefix: str,
    max_calls: int,
    window_seconds: float,
    instance_id: str | None = None,
    use_shared_instance: bool = False,
) -> str:
    """构造 Redis 限流 key —— 自动混入阈值参数 + 实例标识。

    命名规则::

        {prefix}:{max_calls}per{window_seconds}s[:shared={shared}][:inst={instance_id}]

    - 改 ``max_calls`` / ``window_seconds`` → key 变化 → 旧 key 自然过期，新窗口立即生效
    - ``use_shared_instance=True`` → 跨实例共享
    - ``use_shared_instance=False`` → 每个进程独立（默认；不同实例 uuid 不同则互不干扰）
    """
    # 浮点 → 整数秒，避免 key 出现 "60.0" / "60" 之类的不一致
    w = int(window_seconds)
    if use_shared_instance:
        return f"{prefix}:{max_calls}per{w}s:shared"
    iid = instance_id or _default_instance_id()
    return f"{prefix}:{max_calls}per{w}s:inst={iid}"


_DEFAULT_INSTANCE_ID: str | None = None


def _default_instance_id() -> str:
    """惰性生成进程级 instance_id。"""
    global _DEFAULT_INSTANCE_ID
    if _DEFAULT_INSTANCE_ID is None:
        import uuid as _uuid
        _DEFAULT_INSTANCE_ID = _uuid.uuid4().hex[:8]
    return _DEFAULT_INSTANCE_ID


def _parse_cluster_url(cluster_url: str) -> list[dict[str, Any]]:
    """把 "redis://node1:6379,redis://node2:6379,..." 解析成 startup_nodes 列表。

    返回::
        [{"host": "node1", "port": 6379}, {"host": "node2", "port": 6379}, ...]
    """
    import re as _re2
    nodes: list[dict[str, Any]] = []
    # 匹配 redis://host:port
    pat = _re2.compile(r"(?:redis://)?([^:/]+):(\d+)")
    for m in pat.finditer(cluster_url):
        nodes.append({"host": m.group(1), "port": int(m.group(2))})
    if not nodes:
        raise ValueError(f"cluster_url 中没有找到 redis://host:port 节点: {cluster_url!r}")
    return nodes


@dataclass
class TokenUsageConfig:
    """Token 用量采集配置：可注入到 :class:`TokenUsageMiddleware`。

    ``sinks`` 是导出后端列表（按顺序尝试，失败不抛错）：
    - ``"state"``：写入 state 的 ``_hook_token_usage``（始终启用）
    - ``"prometheus"``：暴露 Counter / Histogram 到本地 8000 端口（可选）
    - ``"langsmith"``：调用 ``langsmith.trace`` / ``langsmith.flush``（可选）
    - 自定义 callable：``sink(usage: dict) -> None``

    ``cost_prices``：model_name → (input_per_1k_usd, output_per_1k_usd)。
    不传则用 :data:`_DEFAULT_MODEL_PRICES` 内置表（OpenAI/Anthropic 主流模型，
    价格以 USD/1K tokens 计）。找不到 model_name 时 cost=0，不抛错。
    """

    sinks: tuple[object, ...] = ("state",)
    prometheus_namespace: str = "ai_agent"
    langsmith_project: str | None = None
    # 价目表：覆盖/扩展默认价
    cost_prices: dict[str, tuple[float, float]] = field(default_factory=dict)
    # 从外部 JSON 文件加载价目（与 cost_prices 合并；文件价优先生效）
    cost_prices_file: str | None = None
    # 关闭 cost 估算（默认开启）
    enable_cost: bool = True
    # 自定义 sink 协议扩展：传入 ``cost_usd`` keyword 参数（默认 False，向后兼容）
    pass_cost_to_sinks: bool = False
    # ── budget 拦截：超过阈值抛 TokenBudgetExceeded ──
    # 单次调用预算（USD，None=不限）
    per_call_budget_usd: float | None = None
    # 累计预算（USD，None=不限；累计 state['_hook_token_cost_usd']）
    cumulative_budget_usd: float | None = None
    # ── daily / monthly budget（scheduler 维护） ──
    # 持久化路径：保存累计 cost（JSON: {day, month, total}）
    # 自动检测日期/月份变化 → 跨天/跨月自动重置
    daily_budget_usd: float | None = None
    monthly_budget_usd: float | None = None
    # 持久化文件路径（None = 进程内仅跟踪；默认 ~/.agent_middleware_budget.json）
    budget_persist_path: str | None = None
    # ── weekly budget：跨 ISO week 自动重置 ──
    # 配合 budget_persist_path；week_cost 在 ISO 周切换时归零
    # budget_week_start: "monday"（默认，ISO 周）| "sunday"（美国周）
    weekly_budget_usd: float | None = None
    budget_week_start: str = "monday"
    # ── alert threshold（scheduler 维护） ──
    # alert_thresholds: list[(ratio, severity)] —— 触发告警的阈值
    # 例：[(0.5, "info"), (0.8, "warn"), (1.0, "critical")]
    # ratio = 当前累计 / budget（自动按 daily / weekly / monthly 中"最近的阈值"算）
    # alert_severity_levels: 触发告警后会 invoke 的级别（"info" / "warn" / "critical"）
    # None = 不发告警
    alert_thresholds: tuple[tuple[float, str], ...] = (
        (0.5, "info"),
        (0.8, "warn"),
        (1.0, "critical"),
    )
    # on_alert: Callable[[AlertInfo], None] —— 告警回调
    on_alert: object | None = None
    # on_alerts: 多 callback 链（tuple[Callable[[AlertInfo], None], ...]）
    # 任一 callback 抛错不影响其他 callback（best-effort fan-out）
    # 优先级：on_alert 先调（向后兼容），再按顺序调 on_alerts
    on_alerts: tuple[object, ...] = ()
    # ── metric_history（v0.4.12 新增） ──
    # alert_history_size: 0 = 不保留历史（默认，旧行为）；>0 = 环形缓冲大小
    # 推荐 50~200；记录最近 N 次触发的 cost 增量
    alert_history_size: int = 0
    # ── alert cooldown（v0.4.13 新增） ──
    # alert_cooldown: dict[severity → seconds]
    # 同 severity 在 N 秒内不重复触发（即使 ratio 仍超阈值）
    # 例：{"warn": 60.0, "critical": 300.0}
    # None / {} = 禁用 cooldown（默认，旧行为；仅靠 fired_alerts 去重）
    # 注：fired_alerts 是"直到跨天/周/月才重置"，cooldown 是"按时间间隔"更细粒度
    alert_cooldown: dict[str, float] = field(default_factory=dict)
    # ── alert_aggregation（v0.4.14 新增） ──
    # alert_aggregation_window: 聚合窗口（秒）
    # 0 = 禁用（默认，旧行为）；>0 = N 秒内多次触发合并成一条
    # 与 alert_cooldown 正交：cooldown 是"不重复触发"；aggregation 是"合并多条触发"
    # 推荐 30~120s（适合批量上报 Prometheus / InfluxDB）
    alert_aggregation_window: float = 0.0
    # ── alert_aggregation_jitter（v0.4.15 新增） ──
    # 0 = 禁用（默认，旧行为）
    # >0 = 在 aggregation_window 基础上增加 ±N% 随机抖动
    # 例：alert_aggregation_window=60, jitter=0.1 → 实际窗口 54~66s 随机
    # 推荐 0.05~0.2；防止多实例同步触发（"thundering herd"）
    alert_aggregation_jitter: float | tuple[float, float] = 0.0
    # ── alert_aggregation_jitter asymmetric（v0.4.16 新增） ──
    # 0 = 禁用（旧行为）
    # float = 对称 jitter（v0.4.15 行为；factor ∈ [1-N, 1+N]）
    # tuple[float, float] = asymmetric（factor ∈ [1-negative, 1+positive]）
    #   推荐用法：alert_aggregation_jitter=(0.3, 0.1)
    #     → 正向 +30%（窗口放大），反向 -10%（窗口收紧）
    #     → 偏向"宽松聚合"：宁可重复聚合也不漏报
    # 反向逻辑：alert_aggregation_jitter=(0.1, 0.3) → 偏向"严格聚合"

    # ── dashboard 历史曲线（v0.5 新增） ──
    # history_max: timeline 环形缓冲条目数（按 bucket_seconds 切桶）
    # 0 = 不记录 timeline（默认不影响旧行为）
    # 历史曲线数据通过 :py:meth:`TokenUsageMiddleware.snapshot` 暴露给前端
    history_max: int = 0
    # history_bucket_seconds: 一个桶覆盖多少秒（默认 60 = 1 分钟）
    history_bucket_seconds: int = 60


# 内置价目表（2026-07 价格，仅供参考）
# tuple: (input_per_1k_usd, output_per_1k_usd)
_DEFAULT_MODEL_PRICES: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-2024-08-06": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "o1": (0.015, 0.06),
    "o1-mini": (0.003, 0.012),
    "o3-mini": (0.0011, 0.0044),
    # Anthropic
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-5-haiku": (0.0008, 0.004),
    "claude-3-opus": (0.015, 0.075),
    "claude-sonnet-4-5": (0.003, 0.015),
    "claude-haiku-4-5": (0.0008, 0.004),
}


class TokenBudgetExceeded(Exception):
    """调用方在 :class:`TokenUsageMiddleware` 配置的 budget 阈值被超过时抛错。

    Attributes:
        scope: ``"per_call"`` 或 ``"cumulative"``
        current_usd: 当前 cost_usd（per_call 时即本次；cumulative 时为累计）
        budget_usd: 配置的阈值
    """
    def __init__(
        self,
        scope: str,
        current_usd: float,
        budget_usd: float,
        msg: str | None = None,
    ) -> None:
        self.scope = scope
        self.current_usd = current_usd
        self.budget_usd = budget_usd
        if msg is None:
            msg = (
                f"token budget exceeded [{scope}]: "
                f"current=${current_usd:.4f} > budget=${budget_usd:.4f}"
            )
        super().__init__(msg)


@dataclass
class AlertInfo:
    """budget 告警信息。

    Attributes:
        scope: ``"daily"`` / ``"weekly"`` / ``"monthly"``
        severity: ``"info"`` / ``"warn"`` / ``"critical"``（按 alert_thresholds 配置）
        current_usd: 当前累计 cost
        budget_usd: 配置的 budget 阈值
        ratio: current_usd / budget_usd（0.0~1.0+，1.0 = 正好达到）
        model_name: 触发本次告警的 model
        trigger_metric: 触发本次告警的"成本增量"（v0.4.11 新增）
            - 第一次触发时 = 当前累计 cost（因为是"从 0 开始累计到 ratio"）
            - 后续触发（去重后又被新阈值触发）= 0（因去重，本次阈值之前已触发过）
            - 跨天/周/月重置后 = 当前累计 cost（重新开始累计）
        trigger_threshold: 触发的具体阈值 ratio（如 0.5 / 0.8 / 1.0）
    """
    scope: str
    severity: str
    current_usd: float
    budget_usd: float
    ratio: float
    model_name: str | None = None
    trigger_metric: float = 0.0
    trigger_threshold: float = 0.0
    # metric_history: 最近 N 次触发的 cost 增量（v0.4.12 新增）
    # 用于审计 / 趋势分析（"今天 80% 告警 5 次，总 delta=0.05"）
    # None = 不保留历史
    metric_history: list[float] | None = None
    # aggregation_count: 本聚合窗口内累计触发次数（v0.4.14 新增）
    # alert_aggregation_window=0 时永远是 1（不聚合）
    # >0 时：首次触发 = 1；窗口内后续触发 = 累加
    aggregation_count: int = 1
    # aggregated_total_metric: 聚合窗口内累计的 cost 增量（v0.4.14 新增）
    aggregated_total_metric: float = 0.0


def _compute_cost_usd(model: str | None, input_tokens: int, output_tokens: int,
                      prices: dict[str, tuple[float, float]]) -> float:
    """按 model_name 查价表，计算 USD 成本。找不到时返回 0。"""
    if not model:
        return 0.0
    # 直接查
    p = prices.get(model)
    # 模糊匹配：去掉日期后缀、版本号
    if p is None:
        # 如 "gpt-4o-2024-08-06" → 查 "gpt-4o"
        base = model.split("-20")[0] if "-20" in model else model
        if base != model:
            p = prices.get(base)
    if p is None:
        return 0.0
    in_price, out_price = p
    return round(input_tokens / 1000.0 * in_price + output_tokens / 1000.0 * out_price, 6)


def load_model_prices_from_json(path: str) -> dict[str, tuple[float, float]]:
    """从外部 JSON 文件加载价目表。

    JSON 格式::

        {
            "gpt-4o": [0.0025, 0.01],
            "gpt-4o-mini": [0.00015, 0.0006]
        }

    或带 metadata 形式（会被忽略）::

        {
            "_meta": {"currency": "USD", "updated": "2026-07-01"},
            "gpt-4o": {"input_per_1k": 0.0025, "output_per_1k": 0.01}
        }

    文件不存在 / 格式错误 → 返回 ``{}``（warn 日志，不抛错）。
    """
    import json as _json
    from pathlib import Path as _Path
    try:
        data = _json.loads(_Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("[hook/tokens] prices file not found: %s", path)
        return {}
    except Exception as e:  # noqa: BLE001
        logger.warning("[hook/tokens] prices file parse failed: %s (%s)", path, e)
        return {}
    out: dict[str, tuple[float, float]] = {}
    for k, v in (data or {}).items():
        if k.startswith("_"):
            continue
        if isinstance(v, (list, tuple)) and len(v) == 2:
            out[k] = (float(v[0]), float(v[1]))
        elif isinstance(v, dict):
            inp = float(v.get("input_per_1k") or v.get("input") or 0)
            outp = float(v.get("output_per_1k") or v.get("output") or 0)
            if inp or outp:
                out[k] = (inp, outp)
    return out


# 兼容旧名（向后兼容）
_DEFAULT_PII_PATTERNS = PIIScrubConfig().compiled()
_DEFAULT_OUTPUT_BLOCK_WORDS = OutputSafetyConfig().block_words


class PIIScrubMiddleware(AgentMiddleware if _HAS_OFFICIAL_MW else object):
    """before_model：对最近一条目标类型消息做轻量 PII 脱敏。

    典型用法::

        cfg = PIIScrubConfig(replacement="***", extra_patterns=(r"\\d{17}[\\dXx]",))
        mw = PIIScrubMiddleware(config=cfg)

    不传 ``config`` 时使用 :data:`PIIScrubConfig` 默认值（邮箱 / 手机 / 卡号）。
    """

    def __init__(self, config: PIIScrubConfig | None = None) -> None:
        self.config = config or PIIScrubConfig()
        self._patterns = self.config.compiled()
        self._targets = self.config.target_message_types

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if not isinstance(state, dict):
            return None
        msgs = state.get("messages") or []
        # 反向查找最近一条目标消息
        for i in range(len(msgs) - 1, -1, -1):
            m = msgs[i]
            t = getattr(m, "type", None) or getattr(m, "role", None)
            if t not in self._targets:
                continue
            content = getattr(m, "content", None)
            if isinstance(content, str):
                new_content = content
                for pat in self._patterns:
                    new_content = pat.sub(self.config.replacement, new_content)
                if new_content != content:
                    logger.info("[hook/pii] redacted on message #%d", i)
                    # langchain Message 是 pydantic 对象，用 model_copy 不可行时
                    # 直接修改 content 字段（1.x 中 message 允许 in-place 替换）。
                    try:
                        m.content = new_content
                    except Exception:  # noqa: BLE001
                        return {"messages": list(msgs[:i]) + [m] + list(msgs[i + 1:])}
            break
        return None


# ───────────────────────── 限流 ─────────────────────────
import time as _time

# Redis 客户端是可选依赖；测试和单机环境不强制安装。
try:  # pragma: no cover - 运行时可选
    from redis import Redis as _Redis
    from redis.exceptions import RedisError as _RedisError
    # Redis Cluster 客户端（redis>=4 提供）
    try:
        from redis.cluster import RedisCluster as _RedisCluster
        _HAS_REDIS_CLUSTER = True
    except Exception:  # noqa: BLE001
        _RedisCluster = None  # type: ignore[assignment]
        _HAS_REDIS_CLUSTER = False
    # Redis Sentinel 客户端（redis>=3 提供）
    try:
        from redis.sentinel import Sentinel as _Sentinel
        _HAS_REDIS_SENTINEL = True
    except Exception:  # noqa: BLE001
        _Sentinel = None  # type: ignore[assignment]
        _HAS_REDIS_SENTINEL = False
    _HAS_REDIS = True
except Exception:  # noqa: BLE001
    _Redis = None  # type: ignore[assignment]
    _RedisCluster = None  # type: ignore[assignment]
    _Sentinel = None  # type: ignore[assignment]
    _RedisError = Exception  # type: ignore[assignment, misc]
    _HAS_REDIS = False
    _HAS_REDIS_CLUSTER = False
    _HAS_REDIS_SENTINEL = False


class _MemoryBackend:
    """进程内限流后端，支持 4 种策略：

    - ``sliding_window`` / ``sliding_window_log``：滑动窗口 log（精确，每条记录时间戳）
    - ``sliding_window_counter``：滑动窗口 counter（精确但内存省，只留最新 max_calls 条）
    - ``fixed_window``：固定窗口（按 start_of_window 分桶）
    - ``token_bucket``：令牌桶（连续补 token）
    """

    def __init__(
        self,
        max_calls: int,
        window_seconds: float,
        strategy: str = "sliding_window",
        # 仅 token_bucket 生效：桶初始容量；None=用 max_calls
        burst_size: int | None = None,
        # sliding_window / sliding_window_log 精确内存上限（v0.4.13 新增）
        # None=不限；>0=保留最新 max_window_size 条历史
        max_window_size: int | None = None,
        # sliding_window cold-start（v0.4.14 新增）
        # 前 cold_start_calls 次调用无脑通过
        cold_start_calls: int = 0,
    ) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.strategy = strategy
        # 桶容量（独立于 max_calls 的突发容量）
        self.burst_size: int = burst_size if burst_size is not None else max_calls
        # 滑动窗口内存上限
        self.max_window_size = max_window_size
        # cold-start 已通过次数（v0.4.14）
        self.cold_start_calls = cold_start_calls
        self._cold_start_counter: int = 0
        # 滑动窗口：时间戳列表（sliding_window / sliding_window_log 共用）
        self._ts: list[float] = []
        # 固定窗口：(window_start_ts, count)
        self._fw_start: float | None = None
        self._fw_count: int = 0
        # 令牌桶：(tokens, last_refill_ts)
        self._tb_tokens: float = float(self.burst_size)
        self._tb_last: float = _time.monotonic()
        # 给 dynamic_strategy hot-reload 用（_MemoryBackend 本身不参与 dynamic_strategy，
        # 但 RateLimitMiddleware 可能给所有 backend 推同一份配置以保持 API 一致）
        self._key_prefix_strategy: dict[str, str] = {}

    def hit_and_check(self) -> bool:
        """返回 True 表示被限流。"""
        if self.strategy in ("sliding_window", "sliding_window_log"):
            return self._hit_sliding()
        if self.strategy == "sliding_window_counter":
            return self._hit_sliding_counter()
        if self.strategy == "fixed_window":
            return self._hit_fixed()
        if self.strategy == "token_bucket":
            return self._hit_token_bucket()
        raise ValueError(f"unknown rate_limit_strategy: {self.strategy}")

    def _hit_sliding(self) -> bool:
        now = _time.monotonic()
        # v0.4.14: cold-start 前 N 次无脑通过
        # 注意：仍 append 到 _ts（保持 zset 状态正确）
        if self._cold_start_counter < self.cold_start_calls:
            self._cold_start_counter += 1
            self._ts.append(now)
            return False
        cutoff = now - self.window_seconds
        self._ts = [t for t in self._ts if t >= cutoff]
        # v0.4.13：精确内存上限
        if self.max_window_size is not None and self.max_window_size > 0:
            if len(self._ts) > self.max_window_size:
                self._ts = self._ts[-self.max_window_size:]
        if len(self._ts) >= self.max_calls:
            return True
        self._ts.append(now)
        return False

    def _hit_sliding_counter(self) -> bool:
        """滑动窗口 counter：内存省版。只留窗口内最新 max_calls 条历史。
        等价 Redis 版：ZREMRANGEBYSCORE 砍窗口外 + ZREMRANGEBYRANK 保留最新 N 条。

        v0.4.14：支持 cold_start_calls（前 N 次无脑通过，sliding_window_log 也支持）。
        """
        now = _time.monotonic()
        # v0.4.14: cold-start
        if self._cold_start_counter < self.cold_start_calls:
            self._cold_start_counter += 1
            self._ts.append(now)
            return False
        cutoff = now - self.window_seconds
        # 砍窗口外
        self._ts = [t for t in self._ts if t >= cutoff]
        # 砍超过 max_calls 的最旧
        if len(self._ts) >= self.max_calls:
            # 限流；同时也砍掉所有超出的（防止后续 list 无限增长）
            # 实际只需保留最新 max_calls - 1 条
            self._ts = self._ts[-(self.max_calls - 1):]
            return True
        self._ts.append(now)
        return False

    def _hit_fixed(self) -> bool:
        """固定窗口：按 start_of_window = floor(now / window) * window 分桶。"""
        # v0.4.14: cold-start
        if self._cold_start_counter < self.cold_start_calls:
            self._cold_start_counter += 1
            return False
        now = _time.monotonic()
        cur_window = int(now // self.window_seconds)
        if self._fw_start != cur_window:
            self._fw_start = cur_window
            self._fw_count = 0
        if self._fw_count >= self.max_calls:
            return True
        self._fw_count += 1
        return False

    def _hit_token_bucket(self) -> bool:
        """令牌桶：每个窗口补 max_calls/window_seconds 个 token；桶容量 = burst_size。"""
        # v0.4.14: cold-start
        if self._cold_start_counter < self.cold_start_calls:
            self._cold_start_counter += 1
            return False
        now = _time.monotonic()
        elapsed = now - self._tb_last
        rate = self.max_calls / self.window_seconds
        # 桶容量上限 = burst_size（独立于 max_calls 的突发能力）
        self._tb_tokens = min(float(self.burst_size), self._tb_tokens + elapsed * rate)
        self._tb_last = now
        if self._tb_tokens >= 1:
            self._tb_tokens -= 1
            return False
        return True


class _RedisBackend:
    """Redis 限流（分布式）。支持 Redis Cluster、3 种策略、per-model CAS。

    实现要点：
    - 策略 1 sliding_window：sorted set + INCR 计数器（原子 Lua）
    - 策略 2 fixed_window：用 sorted set 的 score = floor(now / window)
    - 策略 3 token_bucket：HASH 存 (tokens, last_refill_ts)；每次按 elapsed * rate 补 token
    - **Redis Cluster 兼容**：所有 key 必须哈希到同一 slot（用 hash tag ``{...}`` 强制同 slot）
    - **per-model 独立配额**：传入 ``model_name`` 时 key 加 ``:m:<model>`` 后缀；
      用 ``WATCH/MULTI/EXEC``（乐观锁）防止并发写丢（CAS）

    失败开放（fail-open）：Redis 故障时返回 False（不限流）。
    """

    _SCRIPT_NAME_SLIDING = "ratelimit_sliding_window"
    _SCRIPT_NAME_SLIDING_LOG = "ratelimit_sliding_window_log"
    _SCRIPT_NAME_SLIDING_COUNTER = "ratelimit_sliding_window_counter"
    _SCRIPT_NAME_TOKEN = "ratelimit_token_bucket"
    _SCRIPT_NAME_FIXED = "ratelimit_fixed_window"

    # ── 策略 1：sliding window log（精确，每条记录时间戳） ──
    # KEYS[1]=zset, KEYS[2]=counter
    # ARGV[1]=now, ARGV[2]=cutoff, ARGV[3]=max_calls, ARGV[4]=max_window_size（0=不限）
    # 内存：O(min(window/interval, max_window_size) × max_calls)；最精确（无边界效应）
    # v0.4.13：可选 max_window_size 精确内存上限（ZREMRANGEBYRANK）
    _LUA_SLIDING = """
    redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[2])
    local max_ws = tonumber(ARGV[4])
    if max_ws > 0 then
        redis.call('ZREMRANGEBYRANK', KEYS[1], 0, -max_ws - 1)
    end
    local count = redis.call('ZCARD', KEYS[1])
    if count >= tonumber(ARGV[3]) then
        return 1
    end
    local seq = redis.call('INCR', KEYS[2])
    redis.call('ZADD', KEYS[1], ARGV[1], tostring(seq))
    redis.call('EXPIRE', KEYS[1], math.ceil(tonumber(ARGV[2]) * 2) + 1)
    return 0
    """

    # ── 策略 1b：sliding window counter（精确但内存省，只留最新 N 条） ──
    # KEYS[1]=zset; ARGV[1]=now, ARGV[2]=cutoff, ARGV[3]=max_calls
    # 用 ZREMRANGEBYRANK 保留最新 max_calls 条历史 + ZREMRANGEBYSCORE 砍 window 外
    # 内存：O(max_calls)；最省
    _LUA_SLIDING_COUNTER = """
    redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[2])
    redis.call('ZREMRANGEBYRANK', KEYS[1], 0, -tonumber(ARGV[3]) - 1)
    local count = redis.call('ZCARD', KEYS[1])
    if count >= tonumber(ARGV[3]) then
        return 1
    end
    redis.call('ZADD', KEYS[1], ARGV[1], tostring(ARGV[1]) .. ':' .. tostring(count))
    redis.call('EXPIRE', KEYS[1], math.ceil(tonumber(ARGV[2]) * 2) + 1)
    return 0
    """

    # ── 策略 2：fixed window ──
    # KEYS[1]=zset, KEYS[2]=counter; ARGV[1]=now, ARGV[2]=window_sec, ARGV[3]=max_calls
    # 按 floor(now / window) 分桶 → 同一桶内 ZCARD 判断
    _LUA_FIXED = """
    local bucket = math.floor(tonumber(ARGV[1]) / tonumber(ARGV[2]))
    local seq = redis.call('INCR', KEYS[2])
    redis.call('ZADD', KEYS[1], bucket, tostring(seq))
    redis.call('EXPIRE', KEYS[1], math.ceil(tonumber(ARGV[2]) * 2) + 1)
    redis.call('EXPIRE', KEYS[2], math.ceil(tonumber(ARGV[2]) * 2) + 1)
    local count = redis.call('ZCARD', KEYS[1])
    if count > tonumber(ARGV[3]) then
        return 1
    end
    return 0
    """

    # ── 策略 3：token bucket ──
    # KEYS[1]=hash(tokens, last_ts); ARGV[1]=now, ARGV[2]=max_calls,
    # ARGV[2]=max_calls, ARGV[3]=window_sec, ARGV[4]=min_tokens_to_consume,
    # ARGV[5]=burst_size (桶容量)
    _LUA_TOKEN = """
    local data = redis.call('HMGET', KEYS[1], 'tokens', 'last')
    local tokens = tonumber(data[1])
    local last = tonumber(data[2])
    if tokens == nil then
        tokens = tonumber(ARGV[5])
        last = tonumber(ARGV[1])
    end
    local elapsed = tonumber(ARGV[1]) - last
    if elapsed < 0 then elapsed = 0 end
    local rate = tonumber(ARGV[2]) / tonumber(ARGV[3])
    tokens = math.min(tonumber(ARGV[5]), tokens + elapsed * rate)
    redis.call('HSET', KEYS[1], 'tokens', tokens, 'last', tonumber(ARGV[1]))
    redis.call('EXPIRE', KEYS[1], math.ceil(tonumber(ARGV[3]) * 2) + 1)
    local need = tonumber(ARGV[4])
    if tokens >= need then
        tokens = tokens - need
        redis.call('HSET', KEYS[1], 'tokens', tokens)
        return 0
    end
    return 1
    """

    def __init__(
        self,
        client: Any,
        key: str,
        max_calls: int,
        window_seconds: float,
        # Redis Cluster 兼容：用 hash tag 把多个 key 强制同 slot
        cluster_mode: bool = False,
        # 策略
        strategy: str = "sliding_window",
        # per-model 独立配额（atomic CAS via WATCH）
        model_name: str | None = None,
        # 按 key 前缀动态切换策略：dict[prefix -> strategy]
        # None = 关闭动态切换（保持 self._strategy = strategy 不变）
        key_prefix_strategy: dict[str, str] | None = None,
        # 仅 token_bucket 生效：桶容量（None=用 max_calls）
        burst_size: int | None = None,
        # ── sliding_window_log 精确内存上限（v0.4.13 新增） ──
        # None = 不限（仅按 window_seconds 砍窗口外，理论上无限增长）
        # >0 = 用 ZREMRANGEBYRANK 保留最新 max_window_size 条；超出砍掉最旧
        # 推荐：设到 max_calls * 2~5 倍（兼顾精度和内存）
        max_window_size: int | None = None,
        # cold-start（v0.4.14）：前 cold_start_calls 次调用无脑通过
        cold_start_calls: int = 0,
        # ── dynamic_strategy_mixed 应用（v0.4.14 新增） ──
        # per-prefix 精细化参数覆盖（strategy / max_window_size / burst_size / cold_start_calls）
        # 用 key prefix 匹配本 backend 的 key（key="rl:chat:rate" → 前缀 "rl:chat:" 命中 "chat:"）
        # 如果多个 prefix 都命中 → 取最长 prefix（更具体的优先）
        mixed_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._client = client
        self._cluster_mode = cluster_mode
        self._key_prefix_strategy = key_prefix_strategy or {}
        self.burst_size = burst_size if burst_size is not None else max_calls
        self.max_window_size = max_window_size
        self.cold_start_calls = cold_start_calls
        self._cold_start_counter: int = 0
        self._strategy = strategy
        self._model_name = model_name
        # v0.4.14: 应用 dynamic_strategy_mixed per-prefix 精细化参数
        if mixed_overrides:
            applied = self._resolve_mixed_overrides(key, mixed_overrides)
            if applied:
                if "strategy" in applied:
                    self._strategy = applied["strategy"]
                if "max_window_size" in applied:
                    self.max_window_size = applied["max_window_size"]
                if "burst_size" in applied:
                    self.burst_size = int(applied["burst_size"])
                if "cold_start_calls" in applied:
                    self.cold_start_calls = int(applied["cold_start_calls"])
        # 计算 key：cluster_mode → 加 hash tag；per-model → 加 :m:<model> 后缀
        if cluster_mode:
            if "{" in key:
                base = key
            else:
                prefix = key.split(":", 1)[0] if ":" in key else "rl"
                base = f"{prefix}:{{{key[len(prefix)+1:] if key.startswith(prefix + ':') else key}}}"
            if model_name is not None:
                base = f"{base}:m:{model_name}"
            self._key_zset = f"{base}:zset"
            self._key_counter = f"{base}:seq"
            self._key_hash = base  # token_bucket 用 HASH，base 当 key
        else:
            base = key
            if model_name is not None:
                base = f"{base}:m:{model_name}"
            if strategy == "token_bucket":
                self._key_hash = base
                self._key_zset = f"{base}:zset"
                self._key_counter = f"{base}:seq"
            else:
                self._key_zset = base
                self._key_counter = base + ":seq"
        # 默认 _key_hash（仅 token_bucket 路径会真用；但 dynamic_strategy 需要它存在）
        self._key_hash = getattr(self, "_key_hash", base)
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        # 按 strategy 注册 Lua（best effort）
        self._sha: str | None = None
        # 多 strategy 时每个 strategy 维护独立 sha
        self._sha_by_strategy: dict[str, str | None] = {}
        for strat in {strategy, *self._key_prefix_strategy.values()}:
            lua = {
                "sliding_window": self._LUA_SLIDING,        # 别名：= sliding_window_log
                "sliding_window_log": self._LUA_SLIDING,
                "sliding_window_counter": self._LUA_SLIDING_COUNTER,
                "fixed_window": self._LUA_FIXED,
                "token_bucket": self._LUA_TOKEN,
            }.get(strat)
            if lua:
                try:
                    self._sha_by_strategy[strat] = self._client.script_load(lua)
                except Exception:  # noqa: BLE001
                    self._sha_by_strategy[strat] = None
        self._sha = self._sha_by_strategy.get(strategy)

    def hit_and_check(self) -> bool:
        now = _time.time()
        # ── dynamic_strategy：按 key 前缀查表 ──
        strategy = self._strategy
        if self._key_prefix_strategy:
            for prefix, strat in self._key_prefix_strategy.items():
                if self._key_zset.startswith(prefix) or self._key_hash.startswith(prefix):
                    strategy = strat
                    break
            self._strategy = strategy  # cache
            self._sha = self._sha_by_strategy.get(strategy)
        try:
            if strategy == "token_bucket":
                return self._hit_token_bucket(now)
            if strategy == "fixed_window":
                return self._hit_fixed_window(now)
            if strategy == "sliding_window_counter":
                return self._hit_sliding_window_counter(now)
            return self._hit_sliding_window(now)
        except _RedisError as e:  # noqa: BLE001
            logger.warning("[hook/rate_limit] redis error, fail-open: %s", e)
            return False

    @staticmethod
    def _resolve_mixed_overrides(key: str, mixed: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        """按 key 找最长的匹配 prefix，返回 mixed 参数。

        例：key="rl:chat:rate", mixed={"chat:": {...}, "rate:": {...}}
            → 两个都命中，取更长的 "chat:"（key 中 "chat:" 在 "rate" 之前且更长）

        例：key="rl:embed:rate", mixed={"chat:": {...}, "embed:": {...}}
            → "embed:" 命中
        """
        best_prefix: str | None = None
        best_args: dict[str, Any] | None = None
        for prefix, args in mixed.items():
            if prefix in key:
                if best_prefix is None or len(prefix) > len(best_prefix):
                    best_prefix = prefix
                    best_args = args
        return best_args

    def _hit_sliding_window(self, now: float) -> bool:
        # v0.4.14: cold-start（本地计数器，因为 Redis 不能直接感知 cold-start）
        if self._cold_start_counter < self.cold_start_calls:
            self._cold_start_counter += 1
            return False
        cutoff = now - self.window_seconds
        max_ws_arg = str(self.max_window_size if self.max_window_size is not None else 0)
        if self._sha:
            try:
                res = self._client.evalsha(
                    self._sha, 2, self._key_zset, self._key_counter,
                    str(now), str(cutoff), str(self.max_calls), max_ws_arg,
                )
                return int(res) == 1
            except Exception:  # noqa: BLE001
                self._sha = self._client.script_load(self._LUA_SLIDING)
        # Fallback：CAS via WATCH/MULTI/EXEC（乐观锁）
        # 如果 client 不支持 watch（旧 fake / mock）→ 走传统 pipeline
        if hasattr(self._client, "watch"):
            for _retry in range(3):
                try:
                    self._client.watch(self._key_zset)
                    pipe = self._client.pipeline()
                    pipe.zremrangebyscore(self._key_zset, "-inf", cutoff)
                    if self.max_window_size is not None and self.max_window_size > 0:
                        pipe.zremrangebyrank(
                            self._key_zset, 0, -self.max_window_size - 1,
                        )
                    pipe.zcard(self._key_zset)
                    _, count = pipe.execute()
                    if count >= self.max_calls:
                        self._client.unwatch()
                        return True
                    seq = self._client.incr(self._key_counter)
                    pipe = self._client.pipeline()
                    pipe.zadd(self._key_zset, {str(seq): now})
                    pipe.expire(self._key_zset, int(self.window_seconds) * 2 + 1)
                    pipe.execute()
                    self._client.unwatch()
                    return False
                except _RedisError:
                    continue
            return False
        # 旧路径：传统 pipeline（兼容旧 fake/mock）
        pipe = self._client.pipeline()
        pipe.zremrangebyscore(self._key_zset, "-inf", cutoff)
        if self.max_window_size is not None and self.max_window_size > 0:
            pipe.zremrangebyrank(
                self._key_zset, 0, -self.max_window_size - 1,
            )
        pipe.zcard(self._key_zset)
        _, count = pipe.execute()
        if count >= self.max_calls:
            return True
        seq = self._client.incr(self._key_counter)
        pipe = self._client.pipeline()
        pipe.zadd(self._key_zset, {str(seq): now})
        pipe.expire(self._key_zset, int(self.window_seconds) * 2 + 1)
        pipe.execute()
        return False

    def _hit_fixed_window(self, now: float) -> bool:
        # v0.4.14: cold-start
        if self._cold_start_counter < self.cold_start_calls:
            self._cold_start_counter += 1
            return False
        if self._sha:
            try:
                res = self._client.evalsha(
                    self._sha, 2, self._key_zset, self._key_counter,
                    str(now), str(self.window_seconds), str(self.max_calls),
                )
                return int(res) == 1
            except Exception:  # noqa: BLE001
                self._sha = self._client.script_load(self._LUA_FIXED)
        # Fallback pipeline
        bucket = int(now // self.window_seconds)
        seq = self._client.incr(self._key_counter)
        pipe = self._client.pipeline()
        pipe.zadd(self._key_zset, {str(seq): bucket})
        pipe.expire(self._key_zset, int(self.window_seconds) * 2 + 1)
        pipe.expire(self._key_counter, int(self.window_seconds) * 2 + 1)
        _, _ = pipe.execute()
        pipe = self._client.pipeline()
        pipe.zcard(self._key_zset)
        _, count = pipe.execute()
        return count > self.max_calls

    def _hit_sliding_window_counter(self, now: float) -> bool:
        """sliding window counter（内存省版）：用 ZREMRANGEBYRANK 保留最新 max_calls 条。
        Fallback（无 Lua）：ZREMRANGEBYSCORE + ZREMRANGEBYRANK + ZCARD + ZADD。
        """
        # v0.4.14: cold-start
        if self._cold_start_counter < self.cold_start_calls:
            self._cold_start_counter += 1
            return False
        cutoff = now - self.window_seconds
        if self._sha:
            try:
                # sliding_window_counter Lua 只需要 1 个 key（无需 counter）
                res = self._client.evalsha(
                    self._sha, 1, self._key_zset,
                    str(now), str(cutoff), str(self.max_calls),
                )
                return int(res) == 1
            except Exception:  # noqa: BLE001
                self._sha = self._client.script_load(self._LUA_SLIDING_COUNTER)
        # Fallback
        if hasattr(self._client, "watch"):
            for _retry in range(3):
                try:
                    self._client.watch(self._key_zset)
                    pipe = self._client.pipeline()
                    pipe.zremrangebyscore(self._key_zset, "-inf", cutoff)
                    pipe.zremrangebyrank(self._key_zset, 0, -self.max_calls - 1)
                    pipe.zcard(self._key_zset)
                    _, _, count = pipe.execute()
                    if count >= self.max_calls:
                        self._client.unwatch()
                        return True
                    member = f"{now}:{count}"
                    pipe = self._client.pipeline()
                    pipe.zadd(self._key_zset, {member: now})
                    pipe.expire(self._key_zset, int(self.window_seconds) * 2 + 1)
                    pipe.execute()
                    self._client.unwatch()
                    return False
                except _RedisError:
                    continue
            return False
        # 不支持 watch：传统 pipeline
        pipe = self._client.pipeline()
        pipe.zremrangebyscore(self._key_zset, "-inf", cutoff)
        pipe.zremrangebyrank(self._key_zset, 0, -self.max_calls - 1)
        pipe.zcard(self._key_zset)
        _, _, count = pipe.execute()
        if count >= self.max_calls:
            return True
        member = f"{now}:{count}"
        pipe = self._client.pipeline()
        pipe.zadd(self._key_zset, {member: now})
        pipe.expire(self._key_zset, int(self.window_seconds) * 2 + 1)
        pipe.execute()
        return False

    def _hit_token_bucket(self, now: float) -> bool:
        # v0.4.14: cold-start
        if self._cold_start_counter < self.cold_start_calls:
            self._cold_start_counter += 1
            return False
        if self._sha:
            try:
                res = self._client.evalsha(
                    self._sha, 1, self._key_hash,
                    str(now), str(self.max_calls),
                    str(self.window_seconds), "1",
                    str(self.burst_size),
                )
                return int(res) == 1
            except Exception:  # noqa: BLE001
                self._sha = self._client.script_load(self._LUA_TOKEN)
        # Fallback：HGETALL + 算补 token + HSET（无原子性，best effort）
        data = self._client.hgetall(self._key_hash) or {}
        tokens = float(data.get("tokens") or self.burst_size)
        last = float(data.get("last") or now)
        elapsed = max(0.0, now - last)
        rate = self.max_calls / self.window_seconds
        tokens = min(float(self.burst_size), tokens + elapsed * rate)
        if tokens >= 1:
            tokens -= 1
            self._client.hset(self._key_hash, mapping={"tokens": tokens, "last": now})
            self._client.expire(self._key_hash, int(self.window_seconds) * 2 + 1)
            return False
        # 不足 1 个 token → 写回 last 让下次能继续补
        self._client.hset(self._key_hash, mapping={"tokens": tokens, "last": now})
        self._client.expire(self._key_hash, int(self.window_seconds) * 2 + 1)
        return True


class RateLimitMiddleware(AgentMiddleware if _HAS_OFFICIAL_MW else object):
    """滑动窗口限流：单位时间内最多 N 次模型调用。

    通过 ``RateLimitConfig.backend`` 切换后端：
    - ``"memory"``：进程内（默认，零依赖）
    - ``"redis"``：跨进程/跨实例分布式限流（需 ``pip install redis>=5``）

    触发限流时返回 ``_hook_rate_limited=True``，调用方可决定终止或退避
    （本 hook 仅做观测与记录，不主动抛错，避免误伤生产）。
    """

    def __init__(
        self,
        config: RateLimitConfig | None = None,
        # 兼容旧签名
        max_calls: int | None = None,
        window_seconds: float | None = None,
    ) -> None:
        if config is None:
            config = RateLimitConfig(
                max_calls=max_calls if max_calls is not None else 30,
                window_seconds=window_seconds if window_seconds is not None else 60.0,
            )
        elif max_calls is not None or window_seconds is not None:
            config = RateLimitConfig(
                max_calls=max_calls if max_calls is not None else config.max_calls,
                window_seconds=window_seconds if window_seconds is not None else config.window_seconds,
                backend=config.backend,
                redis_url=config.redis_url,
                redis_key_prefix=config.redis_key_prefix,
                predicate=config.predicate,
            )
        self.config = config
        self._backend = self._build_backend()
        # per-model backend 缓存：model_name → backend 实例
        # 避免每次 before_model 都重建 backend（贵）
        self._backend_by_model: dict[str | None, Any] = {None: self._backend}
        # hot-reload：上次 reload 的时间戳（_time.monotonic）
        self._last_dynamic_strategy_reload: float = 0.0
        # hot-reload：连续失败计数（backoff 用）
        self._dynamic_strategy_consecutive_failures: int = 0
        # pub/sub watcher：后台线程
        self._watcher_thread: Any = None
        self._watcher_stop_event: Any = None
        # per-prefix 独立 watcher（v0.4.16）：dict[prefix → (thread, stop_event)]
        self._per_prefix_watchers: dict[str, tuple[Any, Any]] = {}
        self._start_dynamic_strategy_watcher()
        self._start_per_prefix_watchers()

    # 允许测试通过注入 redis 客户端覆盖默认 URL
    _redis_factory = staticmethod(lambda url: _Redis.from_url(url)) if _HAS_REDIS else staticmethod(lambda _url: None)

    def _build_backend(self, model_name: str | None = None) -> Any:
        # per-model 限流：model_name 命中 model_budget → 用该 model 的 max_calls
        # 否则回落到 self.config.max_calls
        effective_max = self.config.max_calls
        if model_name is not None and self.config.model_budget:
            mb = self.config.model_budget.get(model_name)
            if mb is not None:
                effective_max = mb
        if self.config.backend == "memory":
            return _MemoryBackend(
                effective_max, self.config.window_seconds,
                strategy=self.config.rate_limit_strategy,
                burst_size=self.config.burst_size,
                max_window_size=self.config.max_window_size,
                cold_start_calls=self.config.cold_start_calls,
            )
        if self.config.backend in ("redis", "redis_cluster"):
            if not _HAS_REDIS:
                logger.warning(
                    "[hook/rate_limit] '%s' 后端需要 redis>=5，但未安装。"
                    "已降级为 memory 后端。", self.config.backend,
                )
                return _MemoryBackend(effective_max, self.config.window_seconds)
            # 自动混入阈值参数 + 实例标识：
            # - 改 max_calls / window_seconds → key 自动变化 → 新窗口立即生效
            # - 不同进程实例 → 用 instance_id 隔离（共享 vs 拆分由 use_shared_instance 决定）
            key = _make_rate_limit_key(
                self.config.redis_key_prefix,
                effective_max,
                self.config.window_seconds,
                instance_id=self.config.instance_id,
                use_shared_instance=self.config.use_shared_instance,
            )

            if self.config.backend == "redis_cluster":
                if not _HAS_REDIS_CLUSTER:
                    logger.warning(
                        "[hook/rate_limit] 'redis_cluster' 后端需要 redis>=4 的 RedisCluster，"
                        "但当前环境未安装。已降级为单 redis 后端。"
                    )
                url = self.config.cluster_url or self.config.redis_url
                if url is None:
                    logger.warning(
                        "[hook/rate_limit] redis_cluster 需要传 cluster_url 或 redis_url，"
                        "已降级为 memory 后端"
                    )
                    return _MemoryBackend(effective_max, self.config.window_seconds)
                # 解析 "redis://node1:6379,redis://node2:6379,..." → startup_nodes
                nodes = _parse_cluster_url(url)
                try:
                    client = _RedisCluster(startup_nodes=nodes, decode_responses=False)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "[hook/rate_limit] RedisCluster init failed: %s → 降级 memory",
                        e,
                    )
                    return _MemoryBackend(effective_max, self.config.window_seconds)
                # cluster 模式：开启 hash tag 强制同 slot
                return _RedisBackend(
                    client, key, effective_max, self.config.window_seconds,
                    cluster_mode=True,
                    strategy=self.config.rate_limit_strategy,
                    model_name=model_name,
                    key_prefix_strategy=self.config.dynamic_strategy or None,
                    burst_size=self.config.burst_size,
                    max_window_size=self.config.max_window_size,
                    cold_start_calls=self.config.cold_start_calls,
                    mixed_overrides=self.config.dynamic_strategy_mixed or None,
                )

            # backend == "redis"（单 redis）
            client = self._redis_factory(self.config.redis_url) if self.config.redis_url else _Redis()
            return _RedisBackend(
                client, key, effective_max, self.config.window_seconds,
                strategy=self.config.rate_limit_strategy,
                model_name=model_name,
                key_prefix_strategy=self.config.dynamic_strategy or None,
                burst_size=self.config.burst_size,
                max_window_size=self.config.max_window_size,
                cold_start_calls=self.config.cold_start_calls,
                mixed_overrides=self.config.dynamic_strategy_mixed or None,
            )
        if self.config.backend == "redis_sentinel":
            if not _HAS_REDIS_SENTINEL:
                logger.warning(
                    "[hook/rate_limit] 'redis_sentinel' 后端需要 redis>=3 的 Sentinel，"
                    "但当前环境未安装。已降级为 memory 后端。"
                )
                return _MemoryBackend(effective_max, self.config.window_seconds)
            if not self.config.sentinel_hosts:
                logger.warning(
                    "[hook/rate_limit] redis_sentinel 需要传 sentinel_hosts，"
                    "已降级为 memory 后端"
                )
                return _MemoryBackend(effective_max, self.config.window_seconds)
            try:
                sentinel = _Sentinel(
                    list(self.config.sentinel_hosts),
                    socket_timeout=2.0,
                    password=self.config.sentinel_password,
                )
                # master_for() 返回 master 的 Redis client（自动故障转移）
                client = sentinel.master_for(
                    self.config.sentinel_service_name,
                    db=self.config.sentinel_db,
                )
                logger.info(
                    "[hook/rate_limit] redis_sentinel connected: hosts=%s service=%s",
                    self.config.sentinel_hosts, self.config.sentinel_service_name,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "[hook/rate_limit] Sentinel init failed: %s → 降级 memory",
                    e,
                )
                return _MemoryBackend(effective_max, self.config.window_seconds)
            key = _make_rate_limit_key(
                self.config.redis_key_prefix,
                effective_max,
                self.config.window_seconds,
                instance_id=self.config.instance_id,
                use_shared_instance=self.config.use_shared_instance,
            )
            # Sentinel 模式下 master 自动切换，无需 hash tag（单 master 视角）
            return _RedisBackend(
                client, key, effective_max, self.config.window_seconds,
                strategy=self.config.rate_limit_strategy,
                model_name=model_name,
                key_prefix_strategy=self.config.dynamic_strategy or None,
                burst_size=self.config.burst_size,
                max_window_size=self.config.max_window_size,
                cold_start_calls=self.config.cold_start_calls,
                mixed_overrides=self.config.dynamic_strategy_mixed or None,
            )
        raise ValueError(f"unknown backend: {self.config.backend}")

    def _get_or_build_backend(self, model_name: str | None) -> Any:
        """按 model_name 缓存 backend；首次访问时构造。

        注意：memory backend 进程内天然按实例隔离，redis backend 用 model_name 后缀区分。
        """
        if model_name in self._backend_by_model:
            return self._backend_by_model[model_name]
        # 缓存上限（避免无限增长）
        if len(self._backend_by_model) >= 128:
            # 删最旧条目
            self._backend_by_model.pop(next(iter(self._backend_by_model)))
        backend = self._build_backend(model_name)
        self._backend_by_model[model_name] = backend
        return backend

    def _maybe_reload_dynamic_strategy(self) -> None:
        """按 dynamic_strategy_reload_interval 间隔重拉 dynamic_strategy。

        重拉后：覆盖 self.config.dynamic_strategy + 每个 backend 的 _key_prefix_strategy。

        失败 backoff：连续失败按 dynamic_strategy_reload_backoff 指数延后；
        成功后立即重置 baseline。
        """
        loader = self.config.dynamic_strategy_loader
        baseline = self.config.dynamic_strategy_reload_interval
        if not loader or not callable(loader) or baseline <= 0:
            return
        # 当前 effective interval（backoff 后）
        effective = self._current_dynamic_strategy_reload_interval()
        now = _time.monotonic()
        if (now - self._last_dynamic_strategy_reload) < effective:
            return
        self._last_dynamic_strategy_reload = now
        # max_failures 检查
        if (
            self.config.dynamic_strategy_reload_max_failures is not None
            and self._dynamic_strategy_consecutive_failures
            >= self.config.dynamic_strategy_reload_max_failures
        ):
            logger.warning(
                "[hook/rate_limit] dynamic_strategy loader stopped after %d failures",
                self._dynamic_strategy_consecutive_failures,
            )
            return
        try:
            new_strategy = loader()
        except Exception as e:  # noqa: BLE001
            self._dynamic_strategy_consecutive_failures += 1
            logger.warning(
                "[hook/rate_limit] dynamic_strategy_loader error (%d consecutive): %s",
                self._dynamic_strategy_consecutive_failures, e,
            )
            return
        if not isinstance(new_strategy, dict):
            self._dynamic_strategy_consecutive_failures += 1
            logger.warning(
                "[hook/rate_limit] dynamic_strategy_loader returned %s, expected dict (fail %d)",
                type(new_strategy).__name__, self._dynamic_strategy_consecutive_failures,
            )
            return
        # 成功 → 重置 backoff
        if self._dynamic_strategy_consecutive_failures > 0:
            logger.info(
                "[hook/rate_limit] dynamic_strategy loader recovered after %d failures",
                self._dynamic_strategy_consecutive_failures,
            )
        self._dynamic_strategy_consecutive_failures = 0
        if new_strategy == self.config.dynamic_strategy:
            return
        logger.info(
            "[hook/rate_limit] dynamic_strategy hot-reload: %d → %d entries",
            len(self.config.dynamic_strategy), len(new_strategy),
        )
        # 1. 覆盖 config
        try:
            self.config.dynamic_strategy = dict(new_strategy)
        except Exception:  # noqa: BLE001
            pass
        # 2. 把新 strategy 推给所有 backend
        for backend in self._backend_by_model.values():
            if hasattr(backend, "_key_prefix_strategy"):
                backend._key_prefix_strategy = dict(new_strategy)
                if hasattr(backend, "_strategy"):
                    backend._strategy = self.config.rate_limit_strategy

    def _current_dynamic_strategy_reload_interval(self) -> float:
        """根据 consecutive failures 计算当前 effective reload interval（含 backoff）。"""
        baseline = self.config.dynamic_strategy_reload_interval
        bo = self.config.dynamic_strategy_reload_backoff
        if not bo or self._dynamic_strategy_consecutive_failures == 0:
            return baseline
        # bo = (min_factor, max_factor, multiplier)
        min_factor, max_factor, multiplier = bo
        factor = min(max_factor, min_factor * (multiplier ** (self._dynamic_strategy_consecutive_failures - 1)))
        return baseline * factor

    # ── pub/sub watcher ──

    def _start_dynamic_strategy_watcher(self) -> None:
        """启动 Redis pub/sub 订阅线程（仅 backend 是 redis 时生效）。"""
        channel = self.config.dynamic_strategy_pubsub_channel
        if not channel:
            return
        if self.config.backend not in ("redis", "redis_cluster", "redis_sentinel"):
            logger.warning(
                "[hook/rate_limit] dynamic_strategy_pubsub_channel only works with redis backend, not %s",
                self.config.backend,
            )
            return
        if not _HAS_REDIS:
            logger.warning(
                "[hook/rate_limit] redis not installed, pubsub watcher disabled",
            )
            return
        # 启动后台线程
        import threading as _th
        self._watcher_stop_event = _th.Event()
        thread = _th.Thread(
            target=self._watcher_loop,
            args=(channel, self._watcher_stop_event),
            daemon=True,
            name="rate_limit_pubsub_watcher",
        )
        self._watcher_thread = thread
        thread.start()
        logger.info(
            "[hook/rate_limit] dynamic_strategy watcher started, channel=%s",
            channel,
        )

    def _watcher_loop(self, channel: str, stop_event: Any) -> None:
        """watcher 后台循环：订阅 channel，收到消息后覆盖 strategy。"""
        try:
            url = self.config.redis_url
            client = _Redis.from_url(url) if url else None
            if client is None:
                logger.warning("[hook/rate_limit] watcher: no redis client")
                return
            pubsub = client.pubsub()
            pubsub.subscribe(channel)
            logger.info("[hook/rate_limit] watcher subscribed: %s", channel)
            for message in pubsub.listen():
                if stop_event.is_set():
                    break
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                self._apply_dynamic_strategy_watcher_message(data)
        except Exception as e:  # noqa: BLE001
            logger.warning("[hook/rate_limit] watcher loop error: %s", e)
        finally:
            try:
                pubsub.close()
                client.close()
            except Exception:  # noqa: BLE001
                pass

    def _apply_dynamic_strategy_watcher_message(self, raw: str) -> None:
        """解析 watcher 收到的消息，覆盖 dynamic_strategy。

        v0.4.15：支持 dynamic_strategy_mixed 热加载
        - 消息内容 schema 自动检测：
          - 纯 dict[prefix → str]（每个 value 是字符串）→ 视为 dynamic_strategy
          - dict[prefix → dict]（每个 value 是 dict）→ 视为 dynamic_strategy_mixed

        v0.4.16：加 list schema 支持
          - dict[prefix → list[strategy_args]]（每个 value 是 list）→ 视为 dynamic_strategy_list
            用于"多 prefix 共享 args"的场景（例：所有 "embed:*" 共享同一组 args）
          - 例：`{"embed:": ["token_bucket", {"burst_size": 50}], "chat:": ["sliding_window_log"]}`
            → {"embed:": {"strategy": "token_bucket", "burst_size": 50},
               "chat:": {"strategy": "sliding_window_log"}}
        """
        import json as _json
        try:
            new_data = _json.loads(raw)
        except Exception as e:  # noqa: BLE001
            logger.warning("[hook/rate_limit] watcher: invalid JSON: %s", e)
            return
        if not isinstance(new_data, dict):
            logger.warning(
                "[hook/rate_limit] watcher: expected dict, got %s",
                type(new_data).__name__,
            )
            return
        # v0.4.16: schema 检测（4 种）
        # - 全是 str → dynamic_strategy
        # - 全是 dict → dynamic_strategy_mixed
        # - 全是 list → dynamic_strategy_list（[strategy, args...] → dict[strategy_args]）
        # - 混合 → warn 跳过
        if not new_data:
            return  # 空 dict：no-op
        values_are_dicts = all(isinstance(v, dict) for v in new_data.values())
        values_are_strs = all(isinstance(v, str) for v in new_data.values())
        values_are_lists = all(isinstance(v, list) for v in new_data.values())
        if values_are_lists:
            # v0.4.16: list → mixed（list[0] 是 strategy, list[1:] 是 kwargs）
            mixed = {}
            for prefix, lst in new_data.items():
                if not lst:
                    continue
                strategy = str(lst[0])
                args = dict(lst[1]) if len(lst) > 1 and isinstance(lst[1], dict) else {}
                args["strategy"] = strategy
                mixed[prefix] = args
            if mixed == self.config.dynamic_strategy_mixed:
                return
            logger.info(
                "[hook/rate_limit] dynamic_strategy_list watcher update: %d → %d entries",
                len(self.config.dynamic_strategy_mixed), len(mixed),
            )
            try:
                self.config.dynamic_strategy_mixed = mixed
            except Exception:  # noqa: BLE001
                pass
            self._backend_by_model.clear()
            self._backend_by_model[None] = self._backend
            return
        if values_are_dicts:
            # 覆盖 dynamic_strategy_mixed
            if new_data == self.config.dynamic_strategy_mixed:
                return
            logger.info(
                "[hook/rate_limit] dynamic_strategy_mixed watcher update: %d → %d entries",
                len(self.config.dynamic_strategy_mixed), len(new_data),
            )
            try:
                self.config.dynamic_strategy_mixed = {
                    k: dict(v) for k, v in new_data.items()
                }
            except Exception:  # noqa: BLE001
                pass
            # 注：mixed 的更新需要重建 backend（因为 _RedisBackend.__init__ 已固化）
            # 下次 _build_backend 时自动应用新 mixed 配置
            self._backend_by_model.clear()
            self._backend_by_model[None] = self._backend
            return
        if values_are_strs:
            # 覆盖 dynamic_strategy（旧行为）
            if new_data == self.config.dynamic_strategy:
                return
            logger.info(
                "[hook/rate_limit] dynamic_strategy watcher update: %d → %d entries",
                len(self.config.dynamic_strategy), len(new_data),
            )
            try:
                self.config.dynamic_strategy = dict(new_data)
            except Exception:  # noqa: BLE001
                pass
            for backend in self._backend_by_model.values():
                if hasattr(backend, "_key_prefix_strategy"):
                    backend._key_prefix_strategy = dict(new_data)
                    if hasattr(backend, "_strategy"):
                        backend._strategy = self.config.rate_limit_strategy
            return
        # 混合 schema
        logger.warning(
            "[hook/rate_limit] watcher: mixed schema (not all str/dict/list), ignored",
        )

    # ── per-prefix 独立 watcher（v0.4.16 新增） ──

    def _start_per_prefix_watchers(self) -> None:
        """启动 per-prefix 独立 watcher 线程。"""
        cfg = self.config.dynamic_strategy_mixed_per_prefix_channel
        if not cfg:
            return
        if self.config.backend not in ("redis", "redis_cluster", "redis_sentinel"):
            logger.warning(
                "[hook/rate_limit] per-prefix channel only works with redis backend, not %s",
                self.config.backend,
            )
            return
        if not _HAS_REDIS:
            logger.warning(
                "[hook/rate_limit] redis not installed, per-prefix watcher disabled",
            )
            return
        import threading as _th
        for prefix, channel in cfg.items():
            stop_event = _th.Event()
            thread = _th.Thread(
                target=self._watcher_loop_per_prefix,
                args=(prefix, channel, stop_event),
                daemon=True,
                name=f"rate_limit_pubsub_per_prefix_{prefix}",
            )
            self._per_prefix_watchers[prefix] = (thread, stop_event)
            thread.start()
            logger.info(
                "[hook/rate_limit] per-prefix watcher started: prefix=%s channel=%s",
                prefix, channel,
            )

    def _watcher_loop_per_prefix(
        self, prefix: str, channel: str, stop_event: Any,
    ) -> None:
        """per-prefix watcher 后台循环。"""
        try:
            url = self.config.redis_url
            client = _Redis.from_url(url) if url else None
            if client is None:
                return
            pubsub = client.pubsub()
            pubsub.subscribe(channel)
            for message in pubsub.listen():
                if stop_event.is_set():
                    break
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                self._apply_per_prefix_watcher_message(prefix, data)
        except Exception as e:  # noqa: BLE001
            logger.warning("[hook/rate_limit] per-prefix watcher %s error: %s", prefix, e)
        finally:
            try:
                pubsub.close()
                client.close()
            except Exception:  # noqa: BLE001
                pass

    def _apply_per_prefix_watcher_message(self, prefix: str, raw: str) -> None:
        """解析 per-prefix 消息，覆盖 dynamic_strategy_mixed[prefix]。"""
        import json as _json
        try:
            new_args = _json.loads(raw)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[hook/rate_limit] per-prefix watcher %s: invalid JSON: %s", prefix, e,
            )
            return
        if not isinstance(new_args, dict):
            logger.warning(
                "[hook/rate_limit] per-prefix watcher %s: expected dict, got %s",
                prefix, type(new_args).__name__,
            )
            return
        # 覆盖该 prefix
        logger.info(
            "[hook/rate_limit] per-prefix watcher update: prefix=%s, args=%s",
            prefix, new_args,
        )
        try:
            # 注意：dict 是 mutable；copy 一份避免外部 mutation
            self.config.dynamic_strategy_mixed[prefix] = dict(new_args)
        except Exception:  # noqa: BLE001
            pass
        # 重建 backend（mixed 已固化到 _RedisBackend.__init__）
        self._backend_by_model.clear()
        self._backend_by_model[None] = self._backend

    @staticmethod
    def _extract_model_name(state: Any, runtime: Any) -> str | None:
        """从 state / runtime 抽当前 model name。"""
        # 1. state["_hook_model_name"]（TokenUsageMiddleware after_model 写入）
        if isinstance(state, dict):
            v = state.get("_hook_model_name")
            if v:
                return str(v)
        # 2. runtime.metadata.model_name
        if runtime is not None:
            meta = getattr(runtime, "metadata", None)
            if isinstance(meta, dict):
                v = meta.get("model_name") or meta.get("model")
                if v:
                    return str(v)
            # 3. runtime.config["metadata"]["model_name"]
            cfg = getattr(runtime, "config", None)
            if isinstance(cfg, dict):
                m2 = cfg.get("metadata")
                if isinstance(m2, dict):
                    v = m2.get("model_name") or m2.get("model")
                    if v:
                        return str(v)
        return None

    def close(self) -> None:
        """优雅关闭 middleware：停止 watcher 线程 + 关闭 pub/sub + close redis 连接。

        可重复调用；幂等。
        """
        if self._watcher_stop_event is not None:
            try:
                self._watcher_stop_event.set()
            except Exception:  # noqa: BLE001
                pass
        if self._watcher_thread is not None:
            try:
                self._watcher_thread.join(timeout=2.0)  # 最多等 2s
            except Exception:  # noqa: BLE001
                logger.warning("[hook/rate_limit] watcher join failed")
            self._watcher_thread = None
        if self._watcher_stop_event is not None:
            self._watcher_stop_event = None
        # v0.4.16: stop per-prefix watchers
        for prefix, (thread, stop_event) in list(self._per_prefix_watchers.items()):
            try:
                stop_event.set()
            except Exception:  # noqa: BLE001
                pass
            try:
                thread.join(timeout=1.0)
            except Exception:  # noqa: BLE001
                logger.warning("[hook/rate_limit] per-prefix watcher %s join failed", prefix)
        self._per_prefix_watchers.clear()
        logger.info("[hook/rate_limit] middleware closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        cfg = self.config
        # ── hot-reload dynamic_strategy（运行时改不重启） ──
        self._maybe_reload_dynamic_strategy()
        # per-model rate limit：抽 model_name → 决定 backend
        model_name = self._extract_model_name(state, runtime)
        if cfg.model_budget:
            backend = self._get_or_build_backend(model_name)
        else:
            backend = self._backend
        for attempt in range(cfg.wait_for_retry_attempts + 1):
            blocked = backend.hit_and_check()
            if not blocked:
                return {"_hook_rate_limited": False}
            # 被限流
            if attempt < cfg.wait_for_retry_attempts:
                # 计算退避时间
                import random as _rand
                base = cfg.wait_for_retry_base_seconds
                cap = cfg.wait_for_retry_cap_seconds
                delay = min(base * (2 ** attempt), cap)
                if cfg.wait_for_retry_jitter > 0:
                    delay += delay * cfg.wait_for_retry_jitter * _rand.random()
                logger.warning(
                    "[hook/rate_limit] blocked (attempt %d/%d): sleeping %.3fs",
                    attempt + 1, cfg.wait_for_retry_attempts + 1, delay,
                )
                _time.sleep(delay)
                # 进入下一轮 attempt；loop 重新 hit_and_check
                continue
            # 已用尽所有 attempts → 最终返回限流
            logger.warning(
                "[hook/rate_limit] blocked after %d attempts: backend=%s max=%d window=%.1fs",
                cfg.wait_for_retry_attempts + 1,
                cfg.backend, cfg.max_calls, cfg.window_seconds,
            )
            return {"_hook_rate_limited": True}
        # 不可达兜底
        return {"_hook_rate_limited": True}


# ───────────────────────── 审计日志 ─────────────────────────
import json as _json
from pathlib import Path as _Path


class AuditLogMiddleware(AgentMiddleware if _HAS_OFFICIAL_MW else object):
    """把每次 agent 调用前后的事件写入 jsonl 审计文件。

    - `audit_path`：默认写入 `./logs/audit.jsonl`，可注入自定义路径
    - before_agent/after_agent 写入 session_id、起止时间、消息条数
    """

    def __init__(self, audit_path: str | None = None) -> None:
        self.audit_path = audit_path or "logs/audit.jsonl"
        _Path(self.audit_path).parent.mkdir(parents=True, exist_ok=True)

    def _append(self, event: dict[str, Any]) -> None:
        try:
            with open(self.audit_path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:  # noqa: BLE001
            logger.warning("[hook/audit] write failed: %s", e)

    def before_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        sid = (state or {}).get("session_id", "unknown") if isinstance(state, dict) else "unknown"
        msgs = (state or {}).get("messages", []) if isinstance(state, dict) else []
        self._append({"event": "agent_start", "session_id": sid, "messages": len(msgs)})
        return None

    def after_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        sid = (state or {}).get("session_id", "unknown") if isinstance(state, dict) else "unknown"
        msgs = (state or {}).get("messages", []) if isinstance(state, dict) else []
        self._append({"event": "agent_end", "session_id": sid, "messages": len(msgs)})
        return None


# ───────────────────────── token 用量 ─────────────────────────

# 可选依赖：prometheus_client / langsmith / opentelemetry
try:  # pragma: no cover
    import prometheus_client as _prom
    _HAS_PROMETHEUS = True
except Exception:  # noqa: BLE001
    _prom = None  # type: ignore[assignment]
    _HAS_PROMETHEUS = False

# OpenTelemetry（可选；未装时只走 prometheus_client 路径）
try:  # pragma: no cover
    from opentelemetry import metrics as _otel_metrics
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter as _OTLPMetricExporter,
    )
    from opentelemetry.sdk.metrics import MeterProvider as _MeterProvider
    from opentelemetry.sdk.metrics.export import (
        PeriodicExportingMetricReader as _PeriodicExportingMetricReader,
    )
    from opentelemetry.sdk.resources import Resource as _Resource
    _HAS_OPENTELEMETRY = True
except Exception:  # noqa: BLE001
    _otel_metrics = None  # type: ignore[assignment]
    _OTLPMetricExporter = None  # type: ignore[assignment]
    _MeterProvider = None  # type: ignore[assignment]
    _PeriodicExportingMetricReader = None  # type: ignore[assignment]
    _Resource = None  # type: ignore[assignment]
    _HAS_OPENTELEMETRY = False

try:  # pragma: no cover
    import langsmith as _langsmith
    _HAS_LANGSMITH = True
except Exception:  # noqa: BLE001
    _langsmith = None  # type: ignore[assignment]
    _HAS_LANGSMITH = False


class _PrometheusSink:
    """导出 token 用量到 prometheus_client 指标，支持 labels + 高基数防爆 + Pushgateway。

    暴露指标：
    - ``{namespace}_tokens_input_total{model, session_id="__overflow__"}``
    - ``{namespace}_tokens_output_total{model, session_id="__overflow__"}``
    - ``{namespace}_tokens_per_call{model, session_id="__overflow__"}`` (Histogram)

    Label 控制（防高基数爆炸）：
    - ``enable_model_label`` (默认 True):把 ``model`` 作为 label 值
    - ``enable_session_label`` (默认 True):把 ``session_id`` 作为 label 值
    - ``max_session_cardinality`` (默认 1000):session 数量超过阈值后，
      新 session 落到 ``__overflow__``，避免 Prometheus TSDB 内存/查询压力

    上报后端（互斥，按优先级）：
    - ``http_port``:启动 :class:`prometheus_client.MetricsHandler`（pull 模型）
    - ``pushgateway_url``:累计 N 次后 push 到 Pushgateway（短命任务/CI 友好）

    sink 协议：``__call__(usage, *, model=None, session_id=None, parent_run_id=None)``
    - 当传 ``model=None`` 时使用 ``"unknown"``
    - 当传 ``session_id=None`` 时使用 ``"unknown"``
    """

    OVERFLOW_LABEL = "__overflow__"
    DEFAULT_MAX_CARDINALITY = 1000
    DEFAULT_PUSH_EVERY_N = 50

    def __init__(
        self,
        namespace: str = "ai_agent",
        http_port: int | None = None,
        enable_model_label: bool = True,
        enable_session_label: bool = True,
        max_session_cardinality: int = DEFAULT_MAX_CARDINALITY,
        # ── Pushgateway（短命任务上报）──
        pushgateway_url: str | None = None,
        pushgateway_job: str | None = None,
        push_to_gateway_every_n: int = DEFAULT_PUSH_EVERY_N,
        grouping_key: dict[str, str] | None = None,
        # 脚本退出自动 push（仅 Pushgateway 模式下有效）
        auto_flush_on_exit: bool = True,
        # ── only_real_session：session_id 为 None / 空字符串时不写 session_id label ──
        # True（默认）：空 session 折叠到 __none__，避免 series 充满 "unknown"
        # False：维持原行为（仍写 "unknown"）
        only_real_session: bool = True,
        # ── OpenTelemetry 导出 ──
        # 与 prometheus_client 并行上报（metrics 同时写两边）。
        # otel_exporter_endpoint: 例如 "http://localhost:4318/v1/metrics"
        # otel_exporter_protocol: 保留位（当前实现只走 HTTP/protobuf；grpc 可加）
        otel_exporter_endpoint: str | None = None,
        otel_resource_attrs: dict[str, str] | None = None,
        otel_export_interval_seconds: float = 10.0,
    ) -> None:
        if http_port is not None and pushgateway_url is not None:
            logger.warning(
                "[hook/prometheus] http_port 和 pushgateway_url 同时设置，"
                "http_port 会被忽略（pull vs push 互斥）"
            )
        self._ns = namespace
        self._enable_model = enable_model_label
        self._enable_session = enable_session_label
        self._only_real_session = only_real_session
        self._max_cardinality = max_session_cardinality
        # OpenTelemetry
        self._otel_endpoint = otel_exporter_endpoint
        self._otel_attrs = otel_resource_attrs or {}
        self._otel_interval = otel_export_interval_seconds
        self._otel_meter = None
        self._otel_in_counter = None
        self._otel_out_counter = None
        self._otel_histogram = None
        self._otel_provider = None

        # Pushgateway 状态
        self._pg_url = pushgateway_url
        self._pg_job = pushgateway_job or f"agent_{namespace}"
        self._pg_every_n = max(1, push_to_gateway_every_n)
        self._pg_grouping = grouping_key or {}
        self._call_count: int = 0
        self._auto_flush = auto_flush_on_exit
        self._atexit_registered: bool = False

        # 构造 labels 元组（顺序固定，避免 series 命名错乱）
        labels: list[str] = []
        if enable_model_label:
            labels.append("model")
        if enable_session_label:
            labels.append("session_id")

        # Counter / Histogram 都用同一组 labels
        common = tuple(labels)
        self._in_counter = _prom.Counter(
            f"{namespace}_tokens_input_total",
            "Total input tokens consumed",
            common,
        )
        self._out_counter = _prom.Counter(
            f"{namespace}_tokens_output_total",
            "Total output tokens consumed",
            common,
        )
        self._histogram = _prom.Histogram(
            f"{namespace}_tokens_per_call",
            "Token count per model call",
            common,
            buckets=(1, 10, 50, 100, 500, 1000, 5000, 10000),
        )

        # 用 LRU 计数控制高基数
        self._seen_sessions: set[str] = set()
        self._session_overflow: bool = False

        if http_port is not None:
            try:
                _prom.start_http_server(http_port)
                logger.info("[hook/prometheus] http exporter on :%d", http_port)
            except Exception as e:  # noqa: BLE001
                logger.warning("[hook/prometheus] start_http_server failed: %s", e)

        if pushgateway_url is not None:
            logger.info(
                "[hook/prometheus] pushgateway enabled: url=%s job=%s every=%d",
                pushgateway_url, self._pg_job, self._pg_every_n,
            )

        if otel_exporter_endpoint is not None:
            self._init_otel()

    def _init_otel(self) -> None:
        """初始化 OpenTelemetry Meter + Counter/Histogram + OTLP exporter。

        注意：失败仅 warn，不影响 prometheus_client 路径。
        """
        if not _HAS_OPENTELEMETRY:
            logger.warning(
                "[hook/prometheus] otel exporter requested but opentelemetry "
                "package not installed; skipping. pip install opentelemetry-sdk "
                "opentelemetry-exporter-otlp-proto-http"
            )
            return
        try:
            exporter = _OTLPMetricExporter(
                endpoint=self._otel_endpoint,
            )
            reader = _PeriodicExportingMetricReader(
                exporter,
                export_interval_millis=int(self._otel_interval * 1000),
            )
            resource = _Resource.create(self._otel_attrs) if self._otel_attrs else None
            self._otel_provider = _MeterProvider(
                resource=resource,
                metric_readers=[reader],
            )
            _otel_metrics.set_meter_provider(self._otel_provider)
            meter = _otel_metrics.get_meter(self._ns)
            self._otel_meter = meter
            self._otel_in_counter = meter.create_counter(
                f"{self._ns}.tokens.input",
                description="Total input tokens consumed",
                unit="token",
            )
            self._otel_out_counter = meter.create_counter(
                f"{self._ns}.tokens.output",
                description="Total output tokens consumed",
                unit="token",
            )
            self._otel_histogram = meter.create_histogram(
                f"{self._ns}.tokens.per_call",
                description="Token count per model call",
                unit="token",
            )
            logger.info(
                "[hook/prometheus] otel enabled: endpoint=%s interval=%.1fs",
                self._otel_endpoint, self._otel_interval,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[hook/prometheus] otel init failed: %s", e)
            self._otel_meter = None

    def _otel_emit(
        self,
        usage: dict[str, Any],
        model: str | None,
        session_id: str | None,
    ) -> None:
        """向 OTel Meter 写入用量。失败仅 warn。"""
        if self._otel_meter is None:
            return
        try:
            attrs: dict[str, str] = {}
            if model:
                attrs["model"] = model
            real_sid = session_id if (session_id and str(session_id).strip()) else None
            attrs["session_id"] = real_sid if real_sid else "__none__"
            self._otel_in_counter.add(usage.get("input", 0), attributes=attrs)
            self._otel_out_counter.add(usage.get("output", 0), attributes=attrs)
            self._otel_histogram.record(usage.get("total", 0), attributes=attrs)
        except Exception as e:  # noqa: BLE001
            logger.warning("[hook/prometheus] otel emit error: %s", e)

    # ── 高基数防爆 ──
    def _normalize_session(self, sid: str | None) -> str:
        """如果 session 数量已超阈值，把所有新 session 折叠到 ``__overflow__``。"""
        if sid is None:
            return "unknown"
        if self._session_overflow:
            return self.OVERFLOW_LABEL
        if sid not in self._seen_sessions:
            if len(self._seen_sessions) >= self._max_cardinality:
                logger.warning(
                    "[hook/prometheus] session cardinality hit %d, "
                    "folding new sessions into %s",
                    self._max_cardinality, self.OVERFLOW_LABEL,
                )
                self._session_overflow = True
                return self.OVERFLOW_LABEL
            self._seen_sessions.add(sid)
        return sid

    def _label_values(self, model: str | None, session_id: str | None) -> dict[str, str]:
        vals: dict[str, str] = {}
        if self._enable_model:
            vals["model"] = model or "unknown"
        if self._enable_session:
            real_sid = session_id if (session_id and str(session_id).strip()) else None
            if real_sid is None and self._only_real_session:
                # 空 session → 折叠到固定 "__none__" 桶
                # 这样 prometheus 只有一条 series（不会膨胀）
                vals["session_id"] = "__none__"
            else:
                vals["session_id"] = self._normalize_session(real_sid)
        return vals

    # ── Pushgateway 上报 ──
    def _maybe_push_to_gateway(self) -> None:
        """累计调用次数达到阈值时，push 到 Pushgateway。失败仅 warn。"""
        if self._pg_url is None:
            return
        # 第一次 push 时注册 atexit（脚本退出自动 flush）
        if self._auto_flush and not self._atexit_registered:
            self._register_atexit()
        self._call_count += 1
        if self._call_count % self._pg_every_n != 0:
            return
        try:
            # push_to_gateway 是 prometheus_client 提供的同步 API
            # 在 push 前把 Counter / Histogram 都打包
            registry = _prom.REGISTRY  # 默认全局 registry
            _prom.push_to_gateway(
                self._pg_url,
                job=self._pg_job,
                registry=registry,
                grouping_key=self._pg_grouping or None,
            )
            logger.debug(
                "[hook/prometheus] pushed to gateway %s job=%s (call #%d)",
                self._pg_url, self._pg_job, self._call_count,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[hook/prometheus] push_to_gateway failed: %s", e)

    def flush(self) -> None:
        """短命任务结束时调用，把剩余指标 push 到 Pushgateway。

        同时强制 OTel MeterProvider shutdown，把缓冲 flush 到 collector。
        """
        if self._pg_url is None and self._otel_provider is None:
            return
        if self._pg_url is not None:
            try:
                _prom.push_to_gateway(
                    self._pg_url,
                    job=self._pg_job,
                    registry=_prom.REGISTRY,
                    grouping_key=self._pg_grouping or None,
                )
                logger.info("[hook/prometheus] flushed to gateway %s", self._pg_url)
            except Exception as e:  # noqa: BLE001
                logger.warning("[hook/prometheus] flush failed: %s", e)
        if self._otel_provider is not None:
            try:
                self._otel_provider.shutdown()
                logger.info("[hook/prometheus] otel provider shutdown")
            except Exception as e:  # noqa: BLE001
                logger.warning("[hook/prometheus] otel shutdown failed: %s", e)

    def _register_atexit(self) -> None:
        """脚本退出时自动 flush（仅一次）。"""
        import atexit as _atexit
        if self._atexit_registered:
            return
        # atexit 回调里捕获 sink 自身，避免闭包泄漏
        sink_ref = self

        def _on_exit():
            try:
                sink_ref.flush()
            except Exception:  # noqa: BLE001
                pass

        _atexit.register(_on_exit)
        self._atexit_registered = True
        logger.info(
            "[hook/prometheus] atexit hook registered for auto-flush (job=%s)",
            self._pg_job,
        )

    def __call__(
        self,
        usage: dict[str, Any],
        *,
        model: str | None = None,
        session_id: str | None = None,
        parent_run_id: str | None = None,
    ) -> None:
        try:
            labels = self._label_values(model, session_id)
            # prometheus_client.labels(**labels) 在没有 label 的情况下必须传空字典
            if labels:
                self._in_counter.labels(**labels).inc(usage.get("input", 0))
                self._out_counter.labels(**labels).inc(usage.get("output", 0))
                self._histogram.labels(**labels).observe(usage.get("total", 0))
            else:
                self._in_counter.inc(usage.get("input", 0))
                self._out_counter.inc(usage.get("output", 0))
                self._histogram.observe(usage.get("total", 0))
            # Pushgateway 上报（如果启用）
            self._maybe_push_to_gateway()
            # OpenTelemetry emit（如果启用）
            self._otel_emit(usage, model, session_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[hook/prometheus] sink error: %s", e)


class _LangSmithSink:
    """把每次 token 用量作为子 run 喂给 LangSmith，关联到主 agent run。

    关键能力：
    - ``parent_run_id``：在主 agent run 上下文里创建子 run，避免孤立的 token 计数
    - 若不提供 ``parent_run_id``，则用 :func:`_langsmith.get_current_run_tree()`
      自动取当前线程的 run tree（LangSmith 默认上下文）
    - ``session_id`` / ``model`` 会写入 run metadata / tags，便于 LangSmith UI 过滤
    - 若 LangSmith 没装 / 没配 API key，会安静降级（warn 日志，不抛错）
    - **client 注入**：通过 ``client`` 参数传入预构造的 ``langsmith.Client``，
      避免每次 sink 重新初始化（节省连接 / 线程开销）；默认 ``None`` → 内部懒创建

    sink 协议：``__call__(usage, *, model=None, session_id=None, parent_run_id=None)``
    """

    def __init__(
        self,
        project: str | None = None,
        # run 名字前缀（默认 agent_token_usage）
        run_name: str = "agent_token_usage",
        # client 注入：传入已构造好的 langsmith.Client，避免内部重 init
        client: object | None = None,
        # parent_run_id_fallback：当 caller 没传 parent_run_id 时被调用
        # 签名为 (state, runtime) -> str | None
        # - 默认 None → 不做 fallback（行为同 v0.4.3）
        # - 传 callable → 自定义查找策略（推荐项目里注入业务级 lookup）
        # - 传 "thread_id" 字符串 → 使用内置查找：根据 state/runtime 抽 thread_id，
        #   用 client.list_runs(query='eq(metadata.thread_id, ...)', is_root=True, limit=1)
        #   查主 run id（缓存避免重复查）
        parent_run_id_fallback: object | None = None,
        # 内置 thread_id fallback 缓存条数（避免同一 thread 多次 API 查询）
        fallback_cache_size: int = 1000,
    ) -> None:
        self._project = project
        self._run_name = run_name
        # 注入或延迟创建；首次调用 __call__ 时若仍 None 则用默认 Client()
        self._client = client
        self._client_lazy = client is None  # True 表示 __call__ 时尝试懒创建
        # pending runs：未提交成功的 RunTree 在 flush() 时强制提交
        self._pending_runs: list[Any] = []
        # 异常计数：连续失败太多时自动 disable sink（避免拖垮主链路）
        self._err_count: int = 0
        self._max_err: int = 10
        # parent_run_id_fallback
        self._parent_fallback = parent_run_id_fallback
        self._fallback_cache_size = fallback_cache_size
        # thread_id → parent_run_id 缓存（FIFO）
        self._fallback_cache: dict[str, str] = {}

    def _get_client(self) -> object | None:
        """懒获取 LangSmith client。失败返回 None（不影响主链路）。"""
        if self._client is not None:
            return self._client
        if not self._client_lazy:
            return None
        if hasattr(_langsmith, "Client"):
            try:
                self._client = _langsmith.Client()
            except Exception as e:  # noqa: BLE001
                logger.warning("[hook/langsmith] Client() init failed: %s", e)
                self._client_lazy = False  # 不要再试
                return None
        return self._client

    def _resolve_parent_run_id(
        self,
        state: Any,
        runtime: Any,
    ) -> str | None:
        """根据 ``self._parent_fallback`` 解析 parent_run_id。

        支持的字符串模式：
        - ``"thread_id"`` → 在 state/runtime 里抽 thread_id，按 ``metadata.thread_id`` 查
        - ``"metadata.<key>"`` → 按 ``metadata.<key>`` 查（任意 metadata 字段）
        - callable → 自定义 ``fallback(state, runtime) -> str | None``
        """
        if self._parent_fallback is None:
            return None
        # 模式 1：自定义 callable
        if callable(self._parent_fallback):
            try:
                return self._parent_fallback(state, runtime)  # type: ignore[operator]
            except Exception as e:  # noqa: BLE001
                logger.warning("[hook/langsmith] parent_run_id_fallback error: %s", e)
                return None
        # 模式 2：字符串
        if isinstance(self._parent_fallback, str):
            if self._parent_fallback == "thread_id":
                key_value = self._extract_thread_id(state, runtime)
                meta_key = "thread_id"
            elif self._parent_fallback.startswith("metadata."):
                # metadata.foo / metadata.user_id / metadata.session_xyz
                meta_key = self._parent_fallback[len("metadata."):]
                if not meta_key:
                    logger.warning(
                        "[hook/langsmith] invalid parent_run_id_fallback: %r",
                        self._parent_fallback,
                    )
                    return None
                key_value = self._extract_metadata_value(state, runtime, meta_key)
            else:
                logger.warning(
                    "[hook/langsmith] unknown parent_run_id_fallback: %r",
                    self._parent_fallback,
                )
                return None
            if not key_value:
                return None
            return self._query_parent_run_id(meta_key, key_value)
        logger.warning(
            "[hook/langsmith] unknown parent_run_id_fallback: %r",
            self._parent_fallback,
        )
        return None

    def _extract_thread_id(self, state: Any, runtime: Any) -> str | None:
        """从 state / runtime 抽 thread_id（按优先级）。"""
        if runtime is not None:
            cfg = getattr(runtime, "configurable", None)
            if isinstance(cfg, dict) and cfg.get("thread_id"):
                return cfg["thread_id"]
            rcfg = getattr(runtime, "config", None)
            if isinstance(rcfg, dict):
                configurable = rcfg.get("configurable")
                if isinstance(configurable, dict) and configurable.get("thread_id"):
                    return configurable["thread_id"]
        if isinstance(state, dict):
            cfg = state.get("configurable")
            if isinstance(cfg, dict) and cfg.get("thread_id"):
                return cfg["thread_id"]
            if state.get("thread_id"):
                return state["thread_id"]
        return None

    def _extract_metadata_value(
        self,
        state: Any,
        runtime: Any,
        key: str,
    ) -> str | None:
        """从 state / runtime 抽自定义 metadata value（按优先级）。

        查找路径：
        1. ``state[key]``
        2. ``state["metadata"][key]``
        3. ``runtime.metadata[key]``（如果 runtime 是对象）
        4. ``runtime.config["metadata"][key]``
        """
        if isinstance(state, dict):
            v = state.get(key)
            if v is not None:
                return str(v)
            meta = state.get("metadata")
            if isinstance(meta, dict) and meta.get(key) is not None:
                return str(meta[key])
        if runtime is not None:
            meta = getattr(runtime, "metadata", None)
            if isinstance(meta, dict) and meta.get(key) is not None:
                return str(meta[key])
            cfg = getattr(runtime, "config", None)
            if isinstance(cfg, dict):
                m2 = cfg.get("metadata")
                if isinstance(m2, dict) and m2.get(key) is not None:
                    return str(m2[key])
        return None

    def _query_parent_run_id(
        self,
        meta_key: str,
        value: str,
    ) -> str | None:
        """通过 ``metadata.<meta_key>=value`` 查 LangSmith 主 run（带 FIFO 缓存）。"""
        cache_key = f"meta.{meta_key}={value}"
        if cache_key in self._fallback_cache:
            return self._fallback_cache[cache_key]
        cli = self._get_client()
        if cli is None or not hasattr(cli, "list_runs"):
            return None
        try:
            runs_iter = cli.list_runs(
                project_name=self._project,
                is_root=True,
                limit=1,
                query=f'eq(metadata.{meta_key}, "{value}")',
            )
            runs = list(runs_iter) if hasattr(runs_iter, "__iter__") else []
            if not runs:
                return None
            run_id = str(getattr(runs[0], "id", None) or "")
            if run_id:
                if len(self._fallback_cache) >= self._fallback_cache_size:
                    self._fallback_cache.pop(next(iter(self._fallback_cache)))
                self._fallback_cache[cache_key] = run_id
            return run_id or None
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[hook/langsmith] list_runs(metadata.%s=%s) failed: %s",
                meta_key, value, e,
            )
            return None

    def __call__(
        self,
        usage: dict[str, Any],
        *,
        model: str | None = None,
        session_id: str | None = None,
        parent_run_id: str | None = None,
    ) -> None:
        try:
            inputs = {"usage": usage, "model": model, "session_id": session_id}
            tags = ["token_usage"]
            if model:
                tags.append(f"model:{model}")
            if session_id:
                tags.append(f"session:{session_id}")

            # ── parent_run_id_fallback ──
            # 如果 caller 没传 parent_run_id，尝试 fallback 解析
            # （参数 _state 和 _runtime 通过 after_model 调用方塞进 usage 里，
            #  避免破坏 sink(usage, *, model=, session_id=, parent_run_id=) 协议）
            if parent_run_id is None and self._parent_fallback is not None:
                state_hint = usage.get("_state") if isinstance(usage, dict) else None
                runtime_hint = usage.get("_runtime") if isinstance(usage, dict) else None
                parent_run_id = self._resolve_parent_run_id(state_hint, runtime_hint)
                if parent_run_id:
                    logger.debug(
                        "[hook/langsmith] fallback parent_run_id resolved: %s",
                        parent_run_id,
                    )

            # 优先用新版 langsmith.trace（langsmith>=0.2 用 parent=；老版用 parent_run_id=）
            if hasattr(_langsmith, "trace"):
                # 新版 langsmith 推荐用法：嵌套在已有 run tree 上下文里
                # （不显式传 parent_run_id，避免 DeprecationWarning）
                if parent_run_id is None:
                    # 普通情况：在当前 run tree 下创建子 run
                    with _langsmith.trace(
                        name=self._run_name,
                        project_name=self._project,
                        inputs=inputs,
                        run_type="tool",
                        tags=tags,
                    ) as run:
                        if run is not None:
                            try:
                                run.end(outputs={"usage": usage})
                            except Exception:  # noqa: BLE001
                                pass
                else:
                    # 有显式 parent_run_id → 用 RunTree 直接构造子 run
                    if hasattr(_langsmith, "RunTree"):
                        parent_rt = None
                        if hasattr(_langsmith, "get_run_tree"):
                            try:
                                # 如果 client 已注入，用它来取 parent run
                                cli = self._get_client()
                                if cli is not None and hasattr(cli, "read_run"):
                                    try:
                                        parent_rt = cli.read_run(parent_run_id)
                                    except Exception:  # noqa: BLE001
                                        parent_rt = None
                                if parent_rt is None:
                                    parent_rt = _langsmith.get_run_tree(parent_run_id)
                            except Exception:  # noqa: BLE001
                                parent_rt = None
                        # 如果拿到 parent_rt（RunTree 对象），用它构造子 run
                        try:
                            client = self._get_client()
                            tree_kwargs: dict[str, Any] = dict(
                                name=self._run_name,
                                run_type="tool",
                                inputs=inputs,
                                tags=tags,
                                project_name=self._project,
                                parent=parent_rt,  # 新 API 用 RunTree 对象作 parent
                            )
                            # 注入 client（避免内部重 init）
                            if client is not None:
                                tree_kwargs["client"] = client
                            child = _langsmith.RunTree(**tree_kwargs)
                            child.end(outputs={"usage": usage})
                            posted = False
                            if hasattr(child, "post"):
                                try:
                                    child.post()
                                    posted = True
                                except Exception:  # noqa: BLE001
                                    posted = False
                            # 跟踪未提交成功的 run，留给 flush() 重试
                            if not posted:
                                self._pending_runs.append((child, inputs, tags))
                        except Exception:  # noqa: BLE001
                            # parent_rt=None 时也能 work：fallback 到 metadata 模式
                            logger.debug(
                                "[hook/langsmith] RunTree(parent=...) failed, "
                                "fallback to metadata"
                            )
                            if hasattr(_langsmith, "get_current_run_tree"):
                                rt = _langsmith.get_current_run_tree()
                                if rt is not None:
                                    rt.add_metadata({
                                        "token_usage": usage,
                                        "token_usage_parent": parent_run_id,
                                    })
                    else:
                        # 没有 RunTree → 用 metadata 方式
                        if hasattr(_langsmith, "get_current_run_tree"):
                            rt = _langsmith.get_current_run_tree()
                            if rt is not None:
                                rt.add_metadata({
                                    "token_usage": usage,
                                    "token_usage_parent": parent_run_id,
                                })
                return

            # Fallback：老 API - 直接挂 metadata 到当前 run tree
            if hasattr(_langsmith, "get_current_run_tree"):
                rt = _langsmith.get_current_run_tree()
                if rt is not None:
                    if parent_run_id is not None and hasattr(rt, "id"):
                        # 仅当没传 parent 且 rt 已是子 run 时不动；否则用 metadata 标识
                        rt.add_metadata({"token_usage_parent": parent_run_id})
                    rt.add_metadata({"token_usage": usage})
        except Exception as e:  # noqa: BLE001
            self._err_count += 1
            if self._err_count >= self._max_err:
                logger.warning(
                    "[hook/langsmith] sink errored %d times, disable sink: %s",
                    self._err_count, e,
                )
            else:
                logger.warning("[hook/langsmith] sink error: %s", e)

    def flush(self) -> None:
        """强制提交所有 pending runs。短命任务退出 / 关键路径结束时调用。

        行为：
        - 遍历 ``self._pending_runs`` 列表，挨个尝试 ``post()``
        - 成功的从列表中移除；失败的保留（下次 flush 再试）
        - 如果持续失败超过 ``_max_err`` 次，会自动 disable sink
        """
        if not self._pending_runs:
            return
        if self._err_count >= self._max_err:
            logger.warning(
                "[hook/langsmith] sink disabled (err_count=%d); skip flush of %d runs",
                self._err_count, len(self._pending_runs),
            )
            return
        # 第一次 flush 时绑 atexit：进程退出自动 flush
        if not getattr(self, "_atexit_registered", False):
            try:
                import atexit as _atexit
                sink_ref = self
                def _on_exit():
                    try:
                        sink_ref.flush()
                    except Exception:  # noqa: BLE001
                        pass
                _atexit.register(_on_exit)
                self._atexit_registered = True
            except Exception:  # noqa: BLE001
                pass
        remaining: list[Any] = []
        for run, inputs, tags in self._pending_runs:
            try:
                if hasattr(run, "post"):
                    run.post()
                else:
                    # 没有 post 方法的退回：把 metadata 写入当前 run tree
                    if hasattr(_langsmith, "get_current_run_tree"):
                        rt = _langsmith.get_current_run_tree()
                        if rt is not None and hasattr(rt, "add_metadata"):
                            rt.add_metadata({"token_usage": inputs})
            except Exception as e:  # noqa: BLE001
                self._err_count += 1
                remaining.append((run, inputs, tags))
                logger.warning(
                    "[hook/langsmith] flush failed for 1 run: %s (kept for retry)",
                    e,
                )
                if self._err_count >= self._max_err:
                    logger.warning(
                        "[hook/langsmith] err_count hit %d; disable sink",
                        self._err_count,
                    )
                    # 保留所有剩余的 pending，但不再尝试
                    remaining.extend(self._pending_runs[len(remaining) + 1:])
                    break
        self._pending_runs = remaining
        # 简化：只打 final 状态
        logger.info(
            "[hook/langsmith] flush done: %d still pending",
            len(remaining),
        )


def _build_sink(name_or_callable: object, config: TokenUsageConfig) -> object | None:
    """把 :class:`TokenUsageConfig.sinks` 里的字符串解析成具体 sink 实例。"""
    if callable(name_or_callable):
        return name_or_callable
    if name_or_callable == "state":
        return None  # state sink 内置处理
    if name_or_callable == "prometheus":
        if not _HAS_PROMETHEUS:
            logger.warning("[hook/tokens] prometheus_client 未安装，跳过 prometheus sink")
            return None
        return _PrometheusSink(namespace=config.prometheus_namespace)
    if name_or_callable == "langsmith":
        if not _HAS_LANGSMITH:
            logger.warning("[hook/tokens] langsmith 未安装，跳过 langsmith sink")
            return None
        return _LangSmithSink(project=config.langsmith_project)
    logger.warning("[hook/tokens] unknown sink: %r", name_or_callable)
    return None


class TokenUsageMiddleware(AgentMiddleware if _HAS_OFFICIAL_MW else object):
    """after_model：从最新 AIMessage 的 usage_metadata 累加 token 用量。

    兼容 langchain 1.x 标准字段：
    - input_tokens / output_tokens / total_tokens
    - 老版本可能用 prompt_tokens / completion_tokens，做兜底读取

    通过 :class:`TokenUsageConfig.sinks` 配置导出后端：
    - ``"state"``(默认):写入 state 的 ``_hook_token_usage``(始终启用,不算在 sinks 内也可)
    - ``"prometheus"``:暴露 Counter / Histogram;依赖 ``prometheus_client``
    - ``"langsmith"``:把每次用量写入 LangSmith;依赖 ``langsmith>=0.2``
    - 自定义 ``callable``:签名 ``sink(usage: dict) -> None``
    """

    def __init__(
        self,
        config: TokenUsageConfig | None = None,
        # 简化调用
        prometheus: bool = False,
        prometheus_http_port: int | None = None,
        langsmith_project: str | None = None,
    ) -> None:
        if config is None:
            sinks: tuple[object, ...] = ()
            if prometheus:
                if not _HAS_PROMETHEUS:
                    logger.warning("[hook/tokens] prometheus_client 未安装，跳过 prometheus sink")
                else:
                    sinks = sinks + (_PrometheusSink(),)
            if langsmith_project is not None:
                if not _HAS_LANGSMITH:
                    logger.warning("[hook/tokens] langsmith 未安装，跳过 langsmith sink")
                else:
                    sinks = sinks + (_LangSmithSink(project=langsmith_project),)
            config = TokenUsageConfig(sinks=sinks)
        else:
            # 兼容：如果显式传了简化参数且 config 为默认空 sinks，则合并
            extra: list[object] = []
            if prometheus and not any(_is_named(s, "prometheus") for s in config.sinks):
                if _HAS_PROMETHEUS:
                    extra.append(_PrometheusSink())
            if langsmith_project is not None and not any(
                _is_named(s, "langsmith") for s in config.sinks
            ):
                if _HAS_LANGSMITH:
                    extra.append(_LangSmithSink(project=langsmith_project))
            if extra:
                config = TokenUsageConfig(
                    sinks=config.sinks + tuple(extra),
                    prometheus_namespace=config.prometheus_namespace,
                    langsmith_project=config.langsmith_project,
                )
        self.config = config
        self._sinks: list[object] = []
        for s in self.config.sinks:
            built = _build_sink(s, self.config)
            if built is not None:
                self._sinks.append(built)
        # cost 价目：默认 + 用户传入 + 文件加载（文件价优先生效 → 用户覆盖默认）
        file_prices: dict[str, tuple[float, float]] = {}
        if self.config.cost_prices_file:
            file_prices = load_model_prices_from_json(self.config.cost_prices_file)
        self._prices: dict[str, tuple[float, float]] = {
            **_DEFAULT_MODEL_PRICES,
            **file_prices,
            **self.config.cost_prices,
        }
        # ── daily/monthly budget 持久化 ──
        self._budget_path: str | None = (
            self.config.budget_persist_path
            or (str(Path.home() / ".agent_middleware_budget.json")
                if (self.config.daily_budget_usd or self.config.monthly_budget_usd)
                else None)
        )
        self._budget_state: dict[str, Any] = self._load_budget_state()
        # 已触发 alert 去重（用于 on_alert 防止重复告警）
        self._fired_alerts: set[tuple[str, str]] = set()
        # 最近 N 次触发的 cost 增量（环形缓冲；size=0 → 不启用）
        self._metric_history: list[float] = []
        # alert cooldown：上次触发时间戳（v0.4.13）
        self._last_fired_at: dict[tuple[str, str], float] = {}
        # alert aggregation：pending 累积（v0.4.14）
        # {(scope, severity): {count, total_metric, first_fired_at, last_fired_at}}
        self._aggregation_pending: dict[tuple[str, str], dict[str, Any]] = {}
        self._last_alert_day: str = self._budget_state["day"]
        self._last_alert_month: str = self._budget_state["month"]
        self._last_alert_week: str = self._budget_state["week"]

        # ── dashboard 状态（v0.5 新增） ──
        # by_model 累计：{model_name: {input, output, total, cost_usd, calls}}
        self._by_model: dict[str, dict[str, float | int]] = {}
        # 全局累计 input/output/total/cost_usd
        self._totals: dict[str, float] = {
            "input": 0.0, "output": 0.0, "total": 0.0, "cost_usd": 0.0,
        }
        # 上次告警（最近一次 on_alert 触发）
        self._last_alert: dict[str, Any] | None = None
        # timeline 环形缓冲：[{bucket_ts, input, output, total, cost_usd, by_model:{...}}]
        self._timeline: list[dict[str, Any]] = []
        # 当前 bucket 指针（避免每条 call 都 append）
        self._cur_bucket_ts: int = 0
        # 注册到全局（运行期热更新 / 取 snapshot 用）
        try:
            _TOKEN_USAGE_REGISTRY.append(self)
        except Exception:  # noqa: BLE001
            pass

    def _load_budget_state(self) -> dict[str, Any]:
        """从持久化文件加载 budget 状态。"""
        empty = {
            "day": "", "month": "", "week": "",
            "day_cost": 0.0, "month_cost": 0.0, "week_cost": 0.0,
        }
        if not self._budget_path:
            return empty
        try:
            with open(self._budget_path, "r", encoding="utf-8") as f:
                data = json.loads(f.read())
            # 兼容旧文件（v0.4.7 没 week / week_cost）
            for k, v in empty.items():
                if k not in data:
                    data[k] = v
            return data
        except (FileNotFoundError, json.JSONDecodeError):
            return empty

    def _save_budget_state(self) -> None:
        if not self._budget_path:
            return
        try:
            with open(self._budget_path, "w", encoding="utf-8") as f:
                json.dump(self._budget_state, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            logger.warning("[hook/tokens] budget persist failed: %s", e)

    # 已触发阈值集合（按 (scope, severity) 去重，避免每次 after_model 都重发）
    _fired_alerts: set[tuple[str, str]] = set()

    def _reset_fired_alerts(self) -> None:
        """跨天/周/月重置已触发集合。"""
        self._fired_alerts = set()

    def _get_on_alert_callbacks(self) -> list[Any]:
        """返回所有 on_alert + on_alerts 回调（去 None + 过滤非 callable）。"""
        cbs: list[Any] = []
        if self.config.on_alert is not None and callable(self.config.on_alert):
            cbs.append(self.config.on_alert)
        for cb in self.config.on_alerts:
            if callable(cb):
                cbs.append(cb)
        return cbs

    def _fire_alerts(self, model_name: str | None, cost_usd: float) -> None:
        """按 alert_thresholds 检查 + 触发 on_alert。"""
        # 跨天/周/月 → 重置
        self._check_daily_monthly_budget()  # 顺便重置 _budget_state
        # 重置 _fired_alerts
        if self._budget_state["day"] != self._last_alert_day:
            self._fired_alerts = set()
            self._last_alert_day = self._budget_state["day"]
        if self._budget_state["month"] != self._last_alert_month:
            self._fired_alerts = set()
            self._last_alert_month = self._budget_state["month"]
        if self._budget_state["week"] != self._last_alert_week:
            self._fired_alerts = set()
            self._last_alert_week = self._budget_state["week"]
        cbs = self._get_on_alert_callbacks()
        # 没有任何 callback → 仍要 keep _last_alert 给 dashboard，但跳过后续的 callback / 日志
        if not cbs:
            for scope, cost, budget in (
                ("daily", self._budget_state["day_cost"], self.config.daily_budget_usd),
                ("weekly", self._budget_state["week_cost"], self.config.weekly_budget_usd),
                ("monthly", self._budget_state["month_cost"], self.config.monthly_budget_usd),
            ):
                if budget is None or budget <= 0:
                    continue
                ratio = cost / budget
                for th_ratio, severity in self.config.alert_thresholds:
                    if ratio >= th_ratio:
                        key = (scope, severity)
                        if key in self._fired_alerts:
                            continue
                        # cooldown 跳过（但已在 _fired_alerts）
                        cooldown_sec = self.config.alert_cooldown.get(severity)
                        if cooldown_sec is not None and cooldown_sec > 0:
                            last_fired = self._last_fired_at.get(key)
                            if last_fired is not None:
                                elapsed = time.time() - last_fired
                                if elapsed < cooldown_sec:
                                    continue
                        self._fired_alerts.add(key)
                        self._last_fired_at[key] = time.time()
                        self._record_last_alert(AlertInfo(
                            scope=scope,
                            severity=severity,
                            current_usd=cost,
                            budget_usd=budget,
                            ratio=ratio,
                            model_name=None,
                            trigger_metric=cost_usd,
                            trigger_threshold=th_ratio,
                            aggregation_count=1,
                            aggregated_total_metric=cost_usd,
                        ))
            return
        for scope, cost, budget in (
            ("daily", self._budget_state["day_cost"], self.config.daily_budget_usd),
            ("weekly", self._budget_state["week_cost"], self.config.weekly_budget_usd),
            ("monthly", self._budget_state["month_cost"], self.config.monthly_budget_usd),
        ):
            if budget is None or budget <= 0:
                continue
            ratio = cost / budget
            for th_ratio, severity in self.config.alert_thresholds:
                if ratio >= th_ratio:
                    key = (scope, severity)
                    if key in self._fired_alerts:
                        continue
                    # ── alert cooldown 检查 ──
                    cooldown_sec = self.config.alert_cooldown.get(severity)
                    if cooldown_sec is not None and cooldown_sec > 0:
                        last_fired = self._last_fired_at.get(key)
                        if last_fired is not None:
                            elapsed = time.time() - last_fired
                            if elapsed < cooldown_sec:
                                # cooldown 内跳过（但 _fired_alerts 已加，不重复触发）
                                continue
                    self._fired_alerts.add(key)
                    self._last_fired_at[key] = time.time()
                    # ── v0.4.14 alert aggregation：累计本窗口内触发 ──
                    # v0.4.15：加 jitter（防止多实例同步触发）
                    agg_count = 1
                    agg_total = cost_usd
                    agg_window = self.config.alert_aggregation_window
                    if agg_window > 0:
                        # v0.4.15/16: jitter 应用（支持 asymmetric）
                        jitter = self.config.alert_aggregation_jitter
                        if jitter:
                            import random as _rnd
                            if isinstance(jitter, (tuple, list)) and len(jitter) == 2:
                                # asymmetric: (negative_factor, positive_factor)
                                neg, pos = float(jitter[0]), float(jitter[1])
                                factor = 1.0 + _rnd.uniform(-neg, pos)
                            elif isinstance(jitter, (int, float)) and jitter > 0:
                                # 对称（v0.4.15 行为）
                                factor = 1.0 + _rnd.uniform(-jitter, jitter)
                            else:
                                factor = 1.0
                            effective_window = agg_window * factor
                        else:
                            effective_window = agg_window
                        pending = self._aggregation_pending.get(key)
                        now = time.time()
                        if pending and (now - pending["last_fired_at"]) <= effective_window:
                            # 在聚合窗口内 → 累加
                            agg_count = pending["count"] + 1
                            agg_total = pending["total_metric"] + cost_usd
                            self._aggregation_pending[key] = {
                                "count": agg_count,
                                "total_metric": agg_total,
                                "first_fired_at": pending["first_fired_at"],
                                "last_fired_at": now,
                            }
                        else:
                            # 窗口外或首次 → 重置
                            self._aggregation_pending[key] = {
                                "count": 1,
                                "total_metric": cost_usd,
                                "first_fired_at": now,
                                "last_fired_at": now,
                            }
                    info = AlertInfo(
                        scope=scope,
                        severity=severity,
                        current_usd=cost,
                        budget_usd=budget,
                        ratio=ratio,
                        model_name=model_name,
                        trigger_metric=cost_usd,         # 本次 after_model 的成本增量
                        trigger_threshold=th_ratio,       # 触发的具体阈值
                        aggregation_count=agg_count,      # v0.4.14 聚合计数
                        aggregated_total_metric=agg_total, # v0.4.14 聚合总 metric
                    )
                    # ── 记录最近一次告警（dashboard 用） ──
                    self._record_last_alert(info)
                    # ── 维护 metric_history（环形缓冲） ──
                    if self.config.alert_history_size > 0:
                        self._metric_history.append(cost_usd)
                        if len(self._metric_history) > self.config.alert_history_size:
                            self._metric_history.pop(0)
                        # AlertInfo 拿一份 copy（避免外部 mutation 污染内部缓冲）
                        info.metric_history = list(self._metric_history)
                    for cb in cbs:
                        try:
                            cb(info)
                        except Exception as e:  # noqa: BLE001
                            logger.warning("[hook/tokens] on_alert callback error: %s", e)
                    logger.warning(
                        "[hook/tokens] alert %s/%s: $%.4f / $%.4f (%.1f%%, delta=%.4f)",
                        scope, severity, cost, budget, ratio * 100, cost_usd,
                    )

    @staticmethod
    def _iso_week_key(t: float | None = None, week_start: str = "monday") -> str:
        """算 ISO week key。week_start='monday' → 周一开始;'sunday' → 周日开始。"""
        import datetime as _dt
        d = _dt.datetime.fromtimestamp(t if t is not None else time.time())
        if week_start == "sunday":
            # 美国式：周日为一周开始
            # isocalendar 周一为开始 → 美国 ISO 周 = 周日所在 ISO 周
            return d.isocalendar()[:2]
        # 默认 ISO（周一开始）
        return d.isocalendar()[:2]

    def _check_daily_monthly_budget(self) -> None:
        """检查 daily / weekly / monthly budget；超额抛 TokenBudgetExceeded。"""
        if not (
            self.config.daily_budget_usd
            or self.config.monthly_budget_usd
            or self.config.weekly_budget_usd
        ):
            return
        today = time.strftime("%Y-%m-%d", time.localtime())
        this_month = today[:7]
        this_week = str(self._iso_week_key(week_start=self.config.budget_week_start))
        # 检测日期变化 → 重置
        if self._budget_state["day"] != today:
            self._budget_state["day"] = today
            self._budget_state["day_cost"] = 0.0
        if self._budget_state["month"] != this_month:
            self._budget_state["month"] = this_month
            self._budget_state["month_cost"] = 0.0
        if self._budget_state["week"] != this_week:
            self._budget_state["week"] = this_week
            self._budget_state["week_cost"] = 0.0

    @staticmethod
    def _extract_usage(msg: Any) -> dict[str, int]:
        """从 AI 消息抽取 token 用量，兼容多种响应格式。

        优先级（从高到低）：
        1. ``msg.usage_metadata``（langchain 1.x 标准字段）
        2. ``msg.response_metadata.token_usage``（OpenAI 旧路径）
        3. ``msg.response_metadata.usage``（Anthropic 原生字段）
        4. ``msg.response_metadata['token_usage']``（同上兜底）

        各字段映射:
        - input:  ``input_tokens`` / ``prompt_tokens``
        - output: ``output_tokens`` / ``completion_tokens``
        - total:  ``total_tokens``（缺则 input + output 累加）

        返回 ``{"input": int, "output": int, "total": int}``，都缺失则全 0。
        """
        # 来源 1: usage_metadata（langchain 标准）
        usage = getattr(msg, "usage_metadata", None) or {}
        if not isinstance(usage, dict):
            usage = {}

        # 来源 2/3/4: response_metadata 多种形态
        if not usage:
            resp_meta = getattr(msg, "response_metadata", None) or {}
            if isinstance(resp_meta, dict):
                # OpenAI 路径
                usage = resp_meta.get("token_usage") or {}
                # Anthropic 路径
                if not usage:
                    usage = resp_meta.get("usage") or {}

        if not isinstance(usage, dict) or not usage:
            return {"input": 0, "output": 0, "total": 0}

        input_t = (
            usage.get("input_tokens")
            or usage.get("prompt_tokens")
            or 0
        )
        output_t = (
            usage.get("output_tokens")
            or usage.get("completion_tokens")
            or 0
        )
        total_t = usage.get("total_tokens") or (input_t + output_t)
        return {"input": input_t, "output": output_t, "total": total_t}

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if not isinstance(state, dict):
            return None
        msgs = state.get("messages") or []
        # 从 runtime / state / 最后一条 AI 消息里抓 model / session_id 用于 label
        runtime_metadata = getattr(runtime, "metadata", None) if runtime else None
        session_id = (
            (isinstance(runtime_metadata, dict) and runtime_metadata.get("session_id"))
            or state.get("session_id")
        )
        # 父 run id（用于 LangSmith 关联）
        parent_run_id = (
            (isinstance(runtime_metadata, dict) and runtime_metadata.get("parent_run_id"))
            or state.get("parent_run_id")
        )
        # 找最近一条带 token 用量的 AI 消息（兼容 OpenAI / Anthropic 路径）
        for m in reversed(msgs):
            usage_meta = getattr(m, "usage_metadata", None)
            resp_meta = getattr(m, "response_metadata", None) or {}
            has_usage = bool(usage_meta) or bool(
                isinstance(resp_meta, dict) and (
                    resp_meta.get("token_usage") or resp_meta.get("usage")
                )
            )
            if not has_usage:
                continue
            u = self._extract_usage(m)
            # 全部 0 → 视为无效，跳过
            if u["input"] == 0 and u["output"] == 0 and u["total"] == 0:
                continue
            # model_name 兼容：OpenAI standard / Anthropic / runtime metadata
            model_name = (
                (usage_meta.get("model_name") if isinstance(usage_meta, dict) else None)
                or (usage_meta.get("model") if isinstance(usage_meta, dict) else None)
                or (isinstance(runtime_metadata, dict) and runtime_metadata.get("model"))
                or resp_meta.get("model_name")
                or resp_meta.get("model")        # OpenAI 旧字段
                or resp_meta.get("model_id")      # Anthropic 字段
            )
            prev = state.get("_hook_token_usage") or {"input": 0, "output": 0, "total": 0}
            prev_cost = state.get("_hook_token_cost_usd") or 0.0
            logger.info(
                "[hook/tokens] delta in=%d out=%d total=%d",
                u["input"], u["output"], u["total"],
            )
            # cost 估算（默认开启，可关闭）
            cost_usd = 0.0
            if self.config.enable_cost:
                cost_usd = _compute_cost_usd(
                    model_name, u["input"], u["output"], self._prices,
                )
                if cost_usd > 0:
                    logger.info(
                        "[hook/tokens] cost=$%.6f (model=%s)",
                        cost_usd, model_name,
                    )
            # ── budget 拦截 ──
            # per_call：本次 cost 超阈值 → 抛错（state 不写入累计）
            if (
                self.config.per_call_budget_usd is not None
                and cost_usd > self.config.per_call_budget_usd
            ):
                logger.warning(
                    "[hook/tokens] per_call budget exceeded: $%.6f > $%.6f",
                    cost_usd, self.config.per_call_budget_usd,
                )
                raise TokenBudgetExceeded(
                    scope="per_call",
                    current_usd=cost_usd,
                    budget_usd=self.config.per_call_budget_usd,
                )
            # cumulative：累计 cost 超阈值 → 抛错
            new_total = prev_cost + cost_usd
            if (
                self.config.cumulative_budget_usd is not None
                and new_total > self.config.cumulative_budget_usd
            ):
                logger.warning(
                    "[hook/tokens] cumulative budget exceeded: $%.6f > $%.6f",
                    new_total, self.config.cumulative_budget_usd,
                )
                raise TokenBudgetExceeded(
                    scope="cumulative",
                    current_usd=new_total,
                    budget_usd=self.config.cumulative_budget_usd,
                )
            # ── daily / monthly budget ──
            self._check_daily_monthly_budget()
            today = self._budget_state["day"]
            this_month = self._budget_state["month"]
            # 先累计，再判超额
            self._budget_state["day_cost"] += cost_usd
            self._budget_state["month_cost"] += cost_usd
            self._budget_state["week_cost"] += cost_usd
            if (
                self.config.daily_budget_usd is not None
                and self._budget_state["day_cost"] > self.config.daily_budget_usd
            ):
                logger.warning(
                    "[hook/tokens] daily budget exceeded: $%.6f > $%.6f",
                    self._budget_state["day_cost"], self.config.daily_budget_usd,
                )
                self._save_budget_state()
                raise TokenBudgetExceeded(
                    scope="daily",
                    current_usd=self._budget_state["day_cost"],
                    budget_usd=self.config.daily_budget_usd,
                )
            if (
                self.config.weekly_budget_usd is not None
                and self._budget_state["week_cost"] > self.config.weekly_budget_usd
            ):
                logger.warning(
                    "[hook/tokens] weekly budget exceeded: $%.6f > $%.6f",
                    self._budget_state["week_cost"], self.config.weekly_budget_usd,
                )
                self._save_budget_state()
                raise TokenBudgetExceeded(
                    scope="weekly",
                    current_usd=self._budget_state["week_cost"],
                    budget_usd=self.config.weekly_budget_usd,
                )
            if (
                self.config.monthly_budget_usd is not None
                and self._budget_state["month_cost"] > self.config.monthly_budget_usd
            ):
                logger.warning(
                    "[hook/tokens] monthly budget exceeded: $%.6f > $%.6f",
                    self._budget_state["month_cost"], self.config.monthly_budget_usd,
                )
                self._save_budget_state()
                raise TokenBudgetExceeded(
                    scope="monthly",
                    current_usd=self._budget_state["month_cost"],
                    budget_usd=self.config.monthly_budget_usd,
                )
            self._save_budget_state()
            # ── dashboard 累计（by_model / totals / timeline） ──
            self._record_dashboard(model_name, cost_usd, u)
            # ── alert thresholds ──
            self._fire_alerts(model_name, cost_usd)
            # 写到所有 sinks
            # 把 state / runtime 注入 usage 副本（key 用 _ 开头避开真实 token 字段）
            # _LangSmithSink 会读 _state / _runtime 做 parent_run_id fallback；
            # 其它 sink 看到下划线开头 key 应当忽略
            u_for_sink = dict(u)
            u_for_sink["_state"] = state
            u_for_sink["_runtime"] = runtime
            u_for_sink["_cost_usd"] = cost_usd
            u_for_sink["_model"] = model_name
            for sink in self._sinks:
                try:
                    # 优先用 keyword-only 协议 sink(usage, *, model=, session_id=, parent_run_id=)；
                    # 旧的自定义 callable 只接受 positional(usage) 时降级
                    try:
                        if self.config.pass_cost_to_sinks:
                            sink(  # type: ignore[call-arg]
                                u_for_sink,
                                model=model_name,
                                session_id=session_id,
                                parent_run_id=parent_run_id,
                                cost_usd=cost_usd,
                            )
                        else:
                            sink(  # type: ignore[call-arg]
                                u_for_sink,
                                model=model_name,
                                session_id=session_id,
                                parent_run_id=parent_run_id,
                            )
                    except TypeError:
                        sink(u_for_sink)  # type: ignore[operator]
                except Exception as e:  # noqa: BLE001
                    logger.warning("[hook/tokens] sink %r error: %s", sink, e)
            return {
                "_hook_token_usage": {
                    "input": prev["input"] + u["input"],
                    "output": prev["output"] + u["output"],
                    "total": prev["total"] + u["total"],
                },
                "_hook_token_cost_usd": round(prev_cost + cost_usd, 6),
            }
        return None

    # ─────────────────────── dashboard 后台状态（v0.5 新增） ───────────────────────
    def _record_dashboard(
        self,
        model_name: str | None,
        cost_usd: float,
        u: dict[str, int],
    ) -> None:
        """after_model 通过后调用：累加 by_model / totals / timeline。

        - 进程内全局 totals（小写 key 兼容前端）
        - 按 model 分桶
        - timeline：按 history_bucket_seconds 切桶，环形缓冲 history_max
        """
        m = model_name or "unknown"
        bucket_size = max(1, int(self.config.history_bucket_seconds))
        now_ts = int(time.time())
        bucket_ts = (now_ts // bucket_size) * bucket_size

        # ── by_model 累计 ──
        bm = self._by_model.get(m)
        if bm is None:
            bm = {"input": 0, "output": 0, "total": 0, "cost_usd": 0.0, "calls": 0}
            self._by_model[m] = bm
        bm["input"] = int(bm["input"]) + int(u.get("input", 0))
        bm["output"] = int(bm["output"]) + int(u.get("output", 0))
        bm["total"] = int(bm["total"]) + int(u.get("total", 0))
        bm["cost_usd"] = round(float(bm["cost_usd"]) + float(cost_usd), 6)
        bm["calls"] = int(bm["calls"]) + 1

        # ── totals 累计 ──
        self._totals["input"] += int(u.get("input", 0))
        self._totals["output"] += int(u.get("output", 0))
        self._totals["total"] += int(u.get("total", 0))
        self._totals["cost_usd"] = round(
            float(self._totals["cost_usd"]) + float(cost_usd), 6
        )

        # ── timeline 环形缓冲 ──
        if self.config.history_max > 0:
            if self._cur_bucket_ts == bucket_ts and self._timeline:
                last = self._timeline[-1]
            else:
                last = {
                    "bucket_ts": bucket_ts,
                    "input": 0,
                    "output": 0,
                    "total": 0,
                    "cost_usd": 0.0,
                    "by_model": {},
                }
                self._timeline.append(last)
                self._cur_bucket_ts = bucket_ts
                # 环形截断
                if len(self._timeline) > self.config.history_max:
                    self._timeline = self._timeline[-self.config.history_max:]
            last["input"] += int(u.get("input", 0))
            last["output"] += int(u.get("output", 0))
            last["total"] += int(u.get("total", 0))
            last["cost_usd"] = round(float(last["cost_usd"]) + float(cost_usd), 6)
            bm_in_bucket = last["by_model"].get(m)
            if bm_in_bucket is None:
                bm_in_bucket = {"input": 0, "output": 0, "total": 0, "cost_usd": 0.0}
                last["by_model"][m] = bm_in_bucket
            bm_in_bucket["input"] += int(u.get("input", 0))
            bm_in_bucket["output"] += int(u.get("output", 0))
            bm_in_bucket["total"] += int(u.get("total", 0))
            bm_in_bucket["cost_usd"] = round(
                float(bm_in_bucket["cost_usd"]) + float(cost_usd), 6
            )

    def _record_last_alert(self, info: "AlertInfo") -> None:
        """记录最近一次告警（来自 _fire_alerts）。"""
        self._last_alert = {
            "scope": info.scope,
            "severity": info.severity,
            "current_usd": round(float(info.current_usd), 6),
            "budget_usd": round(float(info.budget_usd), 6),
            "ratio": round(float(info.ratio), 4),
            "model_name": info.model_name,
            "at": time.time(),
            "trigger_metric": round(float(info.trigger_metric), 6),
            "trigger_threshold": float(info.trigger_threshold),
            "aggregation_count": int(info.aggregation_count),
        }

    # ── 公开 API：snapshot / 运行时更新 ──
    def snapshot(self) -> dict[str, Any]:
        """返回 dashboard 需要的快照（dict）。可序列化 JSON。"""
        self._check_daily_monthly_budget()
        # scope 摘要（daily / weekly / monthly / per_call / cumulative）
        def _scope(budget: float | None, used: float) -> dict[str, Any]:
            if budget is None or budget <= 0:
                return {"used": round(used, 6), "budget": None, "ratio": None, "left": None}
            r = used / budget if budget > 0 else 0.0
            return {
                "used": round(used, 6),
                "budget": round(budget, 6),
                "ratio": round(r, 4),
                "left": round(max(budget - used, 0.0), 6),
            }

        # 累计 cost（per-call / cumulative 没用 per-call 字段，按 memory 算）
        per_call_used = float(self._metric_history[-1]) if self._metric_history else 0.0
        cumulative_used = float(self._totals["cost_usd"])
        scope = {
            "daily": _scope(
                self.config.daily_budget_usd,
                float(self._budget_state.get("day_cost", 0.0)),
            ),
            "weekly": _scope(
                self.config.weekly_budget_usd,
                float(self._budget_state.get("week_cost", 0.0)),
            ),
            "monthly": _scope(
                self.config.monthly_budget_usd,
                float(self._budget_state.get("month_cost", 0.0)),
            ),
            "per_call": _scope(self.config.per_call_budget_usd, per_call_used),
            "cumulative": _scope(self.config.cumulative_budget_usd, cumulative_used),
        }
        # 暴露当前 Prometheus / Pushgateway 状态
        prom_info = self._prometheus_runtime_info()
        return {
            "ok": True,
            "totals": {
                "input": int(self._totals["input"]),
                "output": int(self._totals["output"]),
                "total": int(self._totals["total"]),
                "cost_usd": round(float(self._totals["cost_usd"]), 6),
            },
            "by_model": [
                {
                    "model": m,
                    "input": int(v["input"]),
                    "output": int(v["output"]),
                    "total": int(v["total"]),
                    "cost_usd": round(float(v["cost_usd"]), 6),
                    "calls": int(v["calls"]),
                }
                for m, v in sorted(
                    self._by_model.items(),
                    key=lambda kv: float(kv[1]["cost_usd"]),
                    reverse=True,
                )
            ],
            "scope": scope,
            "last_alert": self._last_alert,
            "history": list(self._timeline),
            "history_max": int(self.config.history_max),
            "history_bucket_seconds": int(self.config.history_bucket_seconds),
            "prometheus": prom_info,
            "config": {
                "alert_thresholds": list(self.config.alert_thresholds),
                "alert_cooldown": dict(self.config.alert_cooldown),
                "alert_aggregation_window": float(self.config.alert_aggregation_window),
                "alert_aggregation_jitter": (
                    list(self.config.alert_aggregation_jitter)
                    if isinstance(self.config.alert_aggregation_jitter, tuple)
                    else float(self.config.alert_aggregation_jitter)
                ),
                "budget_persist_path": self._budget_path,
            },
        }

    def _prometheus_runtime_info(self) -> dict[str, Any]:
        """从 sinks 中提取 prometheus / pushgateway 状态。"""
        info: dict[str, Any] = {
            "enabled": False,
            "http_port": None,
            "pushgateway_url": None,
            "pushgateway_job": None,
            "push_to_gateway_every_n": None,
            "grouping_key": {},
        }
        for s in self._sinks:
            try:
                if getattr(s, "_ns", None) is None:
                    continue
                # _PrometheusSink 有 _pg_url / _pg_job / _pg_every_n / _pg_grouping
                info["enabled"] = True
                if hasattr(s, "_ns"):
                    info["namespace"] = getattr(s, "_ns", None)
                if hasattr(s, "_pg_url"):
                    info["pushgateway_url"] = getattr(s, "_pg_url", None)
                if hasattr(s, "_pg_job"):
                    info["pushgateway_job"] = getattr(s, "_pg_job", None)
                if hasattr(s, "_pg_every_n"):
                    info["push_to_gateway_every_n"] = getattr(s, "_pg_every_n", None)
                if hasattr(s, "_pg_grouping"):
                    info["grouping_key"] = dict(getattr(s, "_pg_grouping", {}) or {})
                # http_port 是暴露在 params 范畴（外部 register_http_start 单独管）
                # 这里尝试从已启动的 MetricsHandler 端口表获取（若 _prom 模块存在）
                try:
                    import prometheus_client as _pc  # type: ignore
                    # 找任意 MetricsHandler 端口（HTTP 服务）
                    for handler, server in list(_pc.REGISTRY._collector_to_names.items()):
                        pass
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001
                continue
        return info

    def update_budget(self, patch: dict[str, Any]) -> dict[str, Any]:
        """运行期更新预算 + 告警相关字段（立刻生效）。

        支持 patch keys：
        - per_call_budget_usd / cumulative_budget_usd
        - daily_budget_usd / weekly_budget_usd / monthly_budget_usd
        - alert_thresholds: list[[ratio, severity]] 或 [[ratio, severity], ...]
        - alert_cooldown: dict[severity, seconds]
        - alert_aggregation_window: float
        - alert_aggregation_jitter: float | [neg, pos]
        - history_max: int
        - history_bucket_seconds: int
        """
        # dataclass 不可变 → 重建。但我们要保留 sinks / prices / 注册表等运行时引用，
        # 因此只覆盖 config 的字段。
        for k in (
            "per_call_budget_usd",
            "cumulative_budget_usd",
            "daily_budget_usd",
            "weekly_budget_usd",
            "monthly_budget_usd",
            "alert_aggregation_window",
            "history_max",
            "history_bucket_seconds",
        ):
            if k in patch and patch[k] is not None:
                setattr(self.config, k, patch[k])
        if "alert_thresholds" in patch and patch["alert_thresholds"]:
            t = patch["alert_thresholds"]
            # 接受 list[list|tuple] 与 list[(ratio, severity)]
            norm = tuple(
                (float(a), str(b))
                for a, b in (
                    tt if isinstance(tt, (list, tuple)) else (tt[0], tt[1])
                    for tt in t
                )
            )
            self.config.alert_thresholds = norm
        if "alert_cooldown" in patch and patch["alert_cooldown"] is not None:
            self.config.alert_cooldown = {
                str(k): float(v) for k, v in patch["alert_cooldown"].items()
            }
        if "alert_aggregation_jitter" in patch and patch["alert_aggregation_jitter"] is not None:
            j = patch["alert_aggregation_jitter"]
            if isinstance(j, (list, tuple)):
                self.config.alert_aggregation_jitter = (float(j[0]), float(j[1]))
            else:
                self.config.alert_aggregation_jitter = float(j)
        # budget_persist_path 切换：写现有状态到旧位置，再 reload
        if "budget_persist_path" in patch and patch["budget_persist_path"]:
            old = self._budget_path
            self.config.budget_persist_path = patch["budget_persist_path"]
            self._budget_path = patch["budget_persist_path"]
            if old and old != self._budget_path:
                self._save_budget_state()
        return self.snapshot()["config"]

    def update_prometheus(self, patch: dict[str, Any]) -> dict[str, Any]:
        """运行期更新 Prometheus / Pushgateway 配置。"""
        from agent_middleware import _HAS_PROMETHEUS  # noqa: F401  -- 只为校验
        for s in self._sinks:
            if not hasattr(s, "_pg_url"):
                continue
            url = patch.get("pushgateway_url", "__KEEP__")
            job = patch.get("pushgateway_job", "__KEEP__")
            every = patch.get("push_to_gateway_every_n", "__KEEP__")
            gk = patch.get("grouping_key", "__KEEP__")
            if url != "__KEEP__":
                s._pg_url = url or None
            if job != "__KEEP__":
                s._pg_job = job or None
            if every != "__KEEP__" and every is not None:
                s._pg_every_n = max(1, int(every))
            if gk != "__KEEP__" and gk is not None:
                s._pg_grouping = {str(k): str(v) for k, v in gk.items()}
        return self._prometheus_runtime_info()

    def push_now(self) -> dict[str, Any]:
        """主动 push 一次到 Pushgateway（返回 ok / 错误信息）。

        - pushed: 真正执行了 push_to_gateway 的次数（不是 sink 调用次数）
        - errors: 失败信息（push_to_gateway 抛错或 connection_error）

        实现：直接走 prometheus_client.push_to_gateway，绕开 call_count 节流。
        """
        pushed = 0
        errors: list[str] = []
        for s in self._sinks:
            if not hasattr(s, "_pg_url"):
                continue
            if getattr(s, "_pg_url", None) is None:
                continue
            try:
                import prometheus_client as _pc  # type: ignore
                _pc.push_to_gateway(
                    s._pg_url,
                    job=s._pg_job,
                    registry=_pc.REGISTRY,
                    grouping_key=(s._pg_grouping or None),
                )
                pushed += 1
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
        return {
            "pushed": pushed,
            "errors": errors,
            "info": self._prometheus_runtime_info(),
        }

    def reset_last_alert(self) -> None:
        """清空 _last_alert（用于 UI 确认告警）。"""
        self._last_alert = None


# ───────────────────────── 模块级注册表（v0.5 新增） ─────────────────────────
_TOKEN_USAGE_REGISTRY: list[TokenUsageMiddleware] = []


def get_token_usage_registry() -> list[TokenUsageMiddleware]:
    """返回所有已实例化的 :class:`TokenUsageMiddleware`（快照）。"""
    return list(_TOKEN_USAGE_REGISTRY)


def get_token_usage_snapshot() -> dict[str, Any]:
    """聚合所有实例的 snapshot（取最近 active 一份 + 兜底空 schema）。"""
    if not _TOKEN_USAGE_REGISTRY:
        return {
            "ok": False,
            "totals": {"input": 0, "output": 0, "total": 0, "cost_usd": 0.0},
            "by_model": [],
            "scope": {},
            "last_alert": None,
            "history": [],
            "history_max": 0,
            "history_bucket_seconds": 60,
            "prometheus": {
                "enabled": False, "http_port": None,
                "pushgateway_url": None, "pushgateway_job": None,
                "push_to_gateway_every_n": None, "grouping_key": {},
            },
            "config": {
                "alert_thresholds": [],
                "alert_cooldown": {},
                "alert_aggregation_window": 0.0,
                "alert_aggregation_jitter": 0.0,
                "budget_persist_path": None,
            },
        }
    # 多个实例（如每次重启 create_agent）→ 优先挑最近启动的、有数据的
    chosen = _TOKEN_USAGE_REGISTRY[-1]
    snap = chosen.snapshot()
    snap["ok"] = True
    return snap


def update_token_budget(patch: dict[str, Any]) -> dict[str, Any]:
    """运行期更新所有实例的预算 / 告警字段。"""
    if not _TOKEN_USAGE_REGISTRY:
        return {"ok": False, "error": "no TokenUsageMiddleware registered"}
    last_cfg: dict[str, Any] = {}
    for inst in _TOKEN_USAGE_REGISTRY:
        last_cfg = inst.update_budget(patch)
    return {"ok": True, "config": last_cfg}


def update_token_prometheus(patch: dict[str, Any]) -> dict[str, Any]:
    """运行期更新所有实例的 Prometheus / Pushgateway 配置。"""
    if not _TOKEN_USAGE_REGISTRY:
        return {"ok": False, "error": "no TokenUsageMiddleware registered"}
    last_info: dict[str, Any] = {}
    for inst in _TOKEN_USAGE_REGISTRY:
        last_info = inst.update_prometheus(patch)
    return {"ok": True, "prometheus": last_info}


def push_token_prometheus_now() -> dict[str, Any]:
    """手动 push 一次到 Pushgateway。"""
    if not _TOKEN_USAGE_REGISTRY:
        return {"ok": False, "error": "no TokenUsageMiddleware registered"}
    total_pushed = 0
    last_info: dict[str, Any] = {}
    errors: list[str] = []
    for inst in _TOKEN_USAGE_REGISTRY:
        r = inst.push_now()
        total_pushed += int(r.get("pushed", 0))
        errors.extend(r.get("errors", []))
        last_info = r.get("info", {})
    return {
        "ok": True,
        "pushed": total_pushed,
        "errors": errors,
        "prometheus": last_info,
    }


def _is_named(sink: object, name: str) -> bool:
    return isinstance(sink, str) and sink == name


# ───────────────────────── 输出安全 ─────────────────────────


class OutputSafetyMiddleware(AgentMiddleware if _HAS_OFFICIAL_MW else object):
    """after_model：审查最新 AI 文本输出，命中敏感词时抛错或截断。

    典型用法::

        cfg = OutputSafetyConfig(
            mode="redact",
            block_words=("<system>", "ignore previous", "公司机密："),
        )
        mw = OutputSafetyMiddleware(config=cfg)

    不传 ``config`` 时使用 :class:`OutputSafetyConfig` 默认值。
    """

    def __init__(
        self,
        config: OutputSafetyConfig | None = None,
        # 向后兼容旧签名（mode 字符串）
        mode: str | None = None,
    ) -> None:
        if config is None:
            config = OutputSafetyConfig(mode=mode or "raise")
        elif mode is not None:
            # 显式 mode 覆盖 config.mode（兼容旧调用）
            config = OutputSafetyConfig(
                mode=mode,
                block_words=config.block_words,
                case_insensitive=config.case_insensitive,
            )
        self.config = config
        # LLM judge 缓存：(key, ts) → SafetyVerdict
        # 默认 size=256 → 关闭时设置 None
        self._judge_cache: dict[str, tuple[SafetyVerdict, float]] = {}
        # explanation LLM cache（v0.4.16）：FIFO（size=0 禁用）
        # key = (sha256(text)[:16], tuple(categories))；value = dict[cat, explanation]
        self._explanation_llm_cache: dict[tuple[str, tuple[str, ...]], dict[str, str]] = {}

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if not isinstance(state, dict):
            return None
        msgs = state.get("messages") or []
        if not msgs:
            return None
        last = msgs[-1]
        content = getattr(last, "content", None)
        if not isinstance(content, str):
            return None
        # ── 关键词审查 ──
        words = self.config.block_words
        haystack = content.lower() if self.config.case_insensitive else content
        hit = next(
            (w for w in words if (w.lower() if self.config.case_insensitive else w) in haystack),
            None,
        )
        trigger_kind = "keyword"
        trigger_info: list[str] = []
        if hit:
            trigger_info = [hit]
        else:
            # ── LLM judge 审查（单 judge + 多 judge voting 统一入口） ──
            if len(content) >= self.config.llm_judge_min_length:
                verdict = self._vote_judges(content)
                # 应用 score+threshold 二次判定
                verdict = self._apply_threshold(verdict)
                # v0.4.14：应用 category_aliases（标准化）
                verdict = self._apply_category_aliases(verdict)
                # 应用 category_severity 过滤
                verdict = self._apply_severity_filter(verdict)
                # v0.4.15：自动 LLM 生成 explanation（如果 verdict.explanation 为空）
                if not verdict.safe and self.config.explanation_llm is not None:
                    verdict = self._enrich_explanations(verdict, content)
                if not verdict.safe:
                    trigger_kind = "llm_judge"
                    trigger_info = verdict.categories or [verdict.reason or "unsafe"]
                    logger.warning(
                        "[hook/output_safety] llm_judge unsafe: %s (score=%s)",
                        verdict.reason, verdict.score,
                    )
        if not trigger_info:
            return None
        # 命中 → 按 mode 处理
        label = "[SAFETY] " + ",".join(trigger_info)
        logger.warning("[hook/output_safety] %s: %r", trigger_kind, trigger_info)
        if self.config.mode == "raise":
            raise ValueError(
                f"output blocked by safety middleware ({trigger_kind}): {trigger_info}"
            )
        # redact 模式：覆盖原 content
        try:
            last.content = label + " " + content
        except Exception:  # noqa: BLE001
            return {"messages": list(msgs[:-1]) + [last]}
        return None

    def _call_judge(self, judge: Any, text: str) -> SafetyVerdict:
        """调用 LLM judge；处理超时、异常、缓存。"""
        # ── 缓存命中检查 ──
        cache_key = self._cache_key(judge, text)
        if cache_key is not None:
            cached = self._judge_cache_get(cache_key)
            if cached is not None:
                return cached
        # ── 缓存 miss → 实际调用 ──
        verdict = self._invoke_judge(judge, text)
        # 写回缓存
        if cache_key is not None and self.config.llm_judge_cache_size:
            self._judge_cache_put(cache_key, verdict)
        return verdict

    def _judge_timeout_for(self, judge: Any) -> float | None:
        """查 judge 的 per-judge timeout；未配置回落到 llm_judge_timeout。

        支持 key：id(judge) / str(judge) / judge.__name__（named function）
        """
        t = self.config.llm_judge_timeouts
        for key in (id(judge), str(judge), getattr(judge, "__name__", None)):
            if key is not None and key in t:
                return t[key]
        return self.config.llm_judge_timeout

    def _judge_concurrency_for(self, judge: Any) -> bool:
        """查 judge 是否参与并发（per-judge 配置）。

        未配置回落到 llm_judge_concurrency > 1 → True；= 1 → False
        """
        c = self.config.llm_judge_per_concurrency
        for key in (id(judge), str(judge), getattr(judge, "__name__", None)):
            if key is not None and key in c:
                return bool(c[key])
        return self.config.llm_judge_concurrency > 1

    def _judge_priority_for(self, judge: Any) -> int:
        """查 judge 的优先级。默认 0。"""
        p = self.config.llm_judge_priorities
        for key in (id(judge), str(judge), getattr(judge, "__name__", None)):
            if key is not None and key in p:
                return int(p[key])
        return 0

    def _invoke_judge(self, judge: Any, text: str) -> SafetyVerdict:
        """实际调 judge（带超时 / 异常处理）。"""
        import concurrent.futures as _cf
        timeout = self._judge_timeout_for(judge)

        def _invoke():
            return judge(text)

        if timeout is None:
            try:
                v = _invoke()
                return self._normalize_verdict(v)
            except Exception as e:  # noqa: BLE001
                logger.warning("[hook/output_safety] llm_judge error: %s", e)
                return SafetyVerdict(
                    safe=not self.config.llm_judge_fail_closed,
                    reason=f"judge_error:{e}",
                    categories=["judge_error"],
                )
        try:
            with _cf.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_invoke)
                v = future.result(timeout=timeout)
            return self._normalize_verdict(v)
        except _cf.TimeoutError:
            logger.warning(
                "[hook/output_safety] llm_judge timeout after %.1fs (judge=%r)",
                timeout, getattr(judge, "__name__", judge),
            )
            return SafetyVerdict(
                safe=not self.config.llm_judge_fail_closed,
                reason="judge_timeout",
                categories=["judge_timeout"],
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[hook/output_safety] llm_judge error: %s", e)
            return SafetyVerdict(
                safe=not self.config.llm_judge_fail_closed,
                reason=f"judge_error:{e}",
                categories=["judge_error"],
            )

    def _cache_key(self, judge: Any, text: str) -> str | None:
        """根据 (judge, text) 算 cache key。cache 关闭时返回 None。

        注：v0.4.9 起 cache key 必须含 judge id，避免多 judge voting 时
        A 判 safe 缓存后覆盖 B 的 unsafe 判定（这是 v0.4.8 的 bug）。
        """
        if not self.config.llm_judge_cache_size:
            return None
        key_fn = self.config.llm_judge_cache_key_fn
        if key_fn is not None and callable(key_fn):
            try:
                # 自定义 key_fn 只看 text；prefix 加 judge id 保证隔离
                return f"{id(judge)}:{key_fn(text)}"
            except Exception:  # noqa: BLE001
                pass
        return f"{id(judge)}:{str(hash(text))[:16]}"

    def _judge_cache_get(self, key: str) -> SafetyVerdict | None:
        ttl = self.config.llm_judge_cache_ttl
        if key in self._judge_cache:
            verdict, ts = self._judge_cache[key]
            if ttl is None or (_time.time() - ts) < ttl:
                return verdict
            # 过期
            del self._judge_cache[key]
        return None

    def _judge_cache_put(self, key: str, verdict: SafetyVerdict) -> None:
        size = self.config.llm_judge_cache_size
        if size and len(self._judge_cache) >= size:
            # FIFO：删最旧条目
            self._judge_cache.pop(next(iter(self._judge_cache)))
        self._judge_cache[key] = (verdict, _time.time())

    @staticmethod
    def _normalize_verdict(v: Any) -> SafetyVerdict:
        """把 judge 返回值统一成 SafetyVerdict。

        v0.4.14：抽 explanation 字段。
        应用 category_aliases 在 _vote_judgers 之后用 _apply_category_aliases。
        """
        if isinstance(v, SafetyVerdict):
            return v
        if isinstance(v, dict):
            return SafetyVerdict(
                safe=bool(v.get("safe", False)),
                reason=str(v.get("reason", "")),
                categories=list(v.get("categories") or []),
                score=v.get("score"),
                confidence=v.get("confidence"),
                category_severity=dict(v.get("category_severity") or {}),
                confidence_per_category=dict(v.get("confidence_per_category") or {}),
                multi_categories_confidence=dict(v.get("multi_categories_confidence") or {}),
                weighted_severity=dict(v.get("weighted_severity") or {}),
                explanation=dict(v.get("explanation") or {}),
            )
        # 其他类型：truthy → safe
        return SafetyVerdict(safe=bool(v))

    def _resolve_category(self, category: str) -> str:
        """应用 category_aliases + category_alias_regex 解析 category 到 canonical name。

        优先级：
        1. category_aliases（精确匹配）
        2. category_alias_regex（fnmatch / regex，多命中时取最长 pattern）
        3. category 原样返回

        v0.4.16：category_alias_regex_mode 控制 pattern 解释方式
        """
        # 1. 精确匹配
        if category in self.config.category_aliases:
            return self.config.category_aliases[category]
        # 2. regex fallback（多命中取最长）
        if self.config.category_alias_regex:
            best_pattern: str | None = None
            best_canonical: str | None = None
            for pattern, canonical in self.config.category_alias_regex.items():
                matched = False
                try:
                    if self.config.category_alias_regex_mode == "regex":
                        import re as _re
                        matched = bool(_re.search(pattern, category))
                    else:  # fnmatch 默认
                        import fnmatch as _fn
                        matched = _fn.fnmatchcase(category, pattern)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "[hook/output_safety] regex pattern %r error: %s", pattern, e,
                    )
                    continue
                if matched:
                    if best_pattern is None or len(pattern) > len(best_pattern):
                        best_pattern = pattern
                        best_canonical = canonical
            if best_canonical is not None:
                return best_canonical
        return category

    def _enrich_explanations(
        self, verdict: SafetyVerdict, text: str,
    ) -> SafetyVerdict:
        """调 explanation_llm 自动生成每个 category 的解释。

        v0.4.15：
        - 仅对 verdict.safe=False 且 verdict.explanation 为空的 category 生效
        - 已经有的 explanation 保留
        - explanation_llm 返回 dict[category → str]，填充到 verdict.explanation
        - 抛错不影响主流程（best-effort）

        v0.4.16：加 LRU cache（explanation_llm_cache_size>0）
        - cache key = (sha256(text)[:16], tuple(categories))
        - 命中 → 直接返回；未命中 → 调 LLM + 写缓存
        - 缓存命中时不调 LLM
        """
        llm = self.config.explanation_llm
        if llm is None or not callable(llm):
            return verdict
        # 计算需要生成的 categories
        missing = [
            c for c in verdict.categories
            if c not in (verdict.explanation or {}) or not verdict.explanation[c]
        ]
        if not missing:
            return verdict
        # v0.4.16: cache lookup
        new_exps: dict[str, str] | None = None
        cache_size = self.config.explanation_llm_cache_size
        if cache_size > 0:
            import hashlib as _hl
            text_hash = _hl.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
            cache_key = (text_hash, tuple(missing))
            cached = self._explanation_llm_cache.get(cache_key)
            if cached is not None:
                new_exps = dict(cached)  # copy，避免外部 mutation
        if new_exps is None:
            try:
                new_exps = llm(text, verdict)
            except Exception as e:  # noqa: BLE001
                logger.warning("[hook/output_safety] explanation_llm error: %s", e)
                return verdict
            if not isinstance(new_exps, dict):
                logger.warning(
                    "[hook/output_safety] explanation_llm returned %s, expected dict",
                    type(new_exps).__name__,
                )
                return verdict
            # 写缓存
            if cache_size > 0:
                if len(self._explanation_llm_cache) >= cache_size:
                    # FIFO: pop 最旧
                    self._explanation_llm_cache.pop(next(iter(self._explanation_llm_cache)))
                self._explanation_llm_cache[cache_key] = {
                    k: v for k, v in new_exps.items() if k in missing and v
                }
        # 合并：已有不覆盖，新生成的填充
        merged = dict(verdict.explanation or {})
        for cat, exp in new_exps.items():
            if cat in missing and exp:
                merged[cat] = str(exp)
        return SafetyVerdict(
            safe=verdict.safe,
            reason=verdict.reason,
            categories=verdict.categories,
            score=verdict.score,
            confidence=verdict.confidence,
            category_severity=verdict.category_severity,
            multi_categories_severity=verdict.multi_categories_severity,
            confidence_per_category=verdict.confidence_per_category,
            multi_categories_confidence=verdict.multi_categories_confidence,
            weighted_severity=verdict.weighted_severity,
            explanation=merged,
        )

    def _apply_category_aliases(self, verdict: SafetyVerdict) -> SafetyVerdict:
        """应用 category_aliases：替换 categories + category_severity + 同步多 judge 字段。

        v0.4.14：用于 _vote_judges 之后 / _apply_severity_filter 之前。
        """
        if not self.config.category_aliases:
            return verdict
        aliases = self.config.category_aliases

        def resolve(c):
            return aliases.get(c, c)

        # 1. categories list
        new_cats = [resolve(c) for c in verdict.categories]
        # 2. category_severity dict
        new_cat_sev = {resolve(c): sev for c, sev in verdict.category_severity.items()}
        # 3. confidence_per_category dict
        new_cat_conf = {resolve(c): conf for c, conf in verdict.confidence_per_category.items()}
        # 4. multi_categories_severity dict
        new_multi_sev = {resolve(c): sevs for c, sevs in verdict.multi_categories_severity.items()}
        # 5. multi_categories_confidence dict
        new_multi_conf = {resolve(c): confs for c, confs in verdict.multi_categories_confidence.items()}
        # 6. weighted_severity dict
        new_weighted = {resolve(c): ws for c, ws in verdict.weighted_severity.items()}
        # 7. explanation dict
        new_explanation = {resolve(c): exp for c, exp in (verdict.explanation or {}).items()}

        return SafetyVerdict(
            safe=verdict.safe,
            reason=verdict.reason,
            categories=new_cats,
            score=verdict.score,
            confidence=verdict.confidence,
            category_severity=new_cat_sev,
            multi_categories_severity=new_multi_sev,
            confidence_per_category=new_cat_conf,
            multi_categories_confidence=new_multi_conf,
            weighted_severity=new_weighted,
            explanation=new_explanation if new_explanation else verdict.explanation,
        )

    def _apply_threshold(self, verdict: SafetyVerdict) -> SafetyVerdict:
        """基于 score + threshold 二次判定；返回 (可能修改过 safe 字段的) verdict。"""
        th = self.config.safety_threshold
        if th is None or verdict.score is None:
            return verdict
        if verdict.score >= th and verdict.safe:
            # score 远超阈值 → 强制判 unsafe
            logger.warning(
                "[hook/output_safety] score %.2f >= threshold %.2f → force unsafe",
                verdict.score, th,
            )
            return SafetyVerdict(
                safe=False,
                reason=verdict.reason or f"score_exceeded:{verdict.score:.2f}",
                categories=list(verdict.categories) + ["high_risk_score"],
                score=verdict.score,
                confidence=verdict.confidence,
            )
        if verdict.score < th and not verdict.safe:
            # score 远低于阈值 + judge 判 unsafe → 反向校正
            logger.warning(
                "[hook/output_safety] score %.2f < threshold %.2f but judge unsafe → flip to safe",
                verdict.score, th,
            )
            return SafetyVerdict(
                safe=True,
                reason=verdict.reason or f"score_below_threshold:{verdict.score:.2f}",
                categories=list(verdict.categories),
                score=verdict.score,
                confidence=verdict.confidence,
            )
        return verdict

    def _vote_judges(self, text: str) -> SafetyVerdict:
        """收集所有 judge（含 llm_judge + llm_judges）的判定 + 按 voting strategy 投票。

        llm_judge_concurrency=1 → 顺序（默认，旧行为）
        llm_judge_concurrency>1 → ThreadPoolExecutor 并发（每个 judge 独立线程）

        per-judge 配置（llm_judge_per_concurrency）：某些 judge 强制走 sequential 路径
        （即使全局开了并发）。典型场景：同步阻塞型 judge（Redis 监控、本地脚本）。

        没有 judge → 返回 SafetyVerdict(safe=True)（即不审查）
        """
        judges: list[Any] = []
        if self.config.llm_judge is not None and callable(self.config.llm_judge):
            judges.append(self.config.llm_judge)
        for j in self.config.llm_judges:
            if callable(j):
                judges.append(j)
        if not judges:
            return SafetyVerdict(safe=True)
        # ── 优先级排序：值大的在前，ties 用原顺序（stable sort） ──
        sorted_judges = sorted(
            enumerate(judges),
            key=lambda x: -self._judge_priority_for(x[1]),
        )
        # ── per-judge 分组：参与并发 vs 不参与 ──
        concurrent_judges: list[tuple[int, Any]] = []  # (orig_idx, judge)
        sequential_judges: list[tuple[int, Any]] = []
        for idx, j in sorted_judges:
            if self._judge_concurrency_for(j):
                concurrent_judges.append((idx, j))
            else:
                sequential_judges.append((idx, j))
        concurrency = max(1, self.config.llm_judge_concurrency)
        verdicts_by_idx: dict[int, SafetyVerdict] = {}
        # 并发组
        if concurrent_judges:
            if concurrency == 1 and not self.config.llm_judge_per_concurrency:
                # 全局开顺序 → 并发组也走顺序（合并到下面的顺序组）
                sequential_judges = concurrent_judges + sequential_judges
            else:
                import concurrent.futures as _cf
                with _cf.ThreadPoolExecutor(
                    max_workers=min(concurrency, len(concurrent_judges)),
                ) as pool:
                    futures = {
                        pool.submit(self._call_judge, j, text): idx
                        for idx, j in concurrent_judges
                    }
                    for fut in _cf.as_completed(futures):
                        idx = futures[fut]
                        try:
                            verdicts_by_idx[idx] = fut.result()
                        except Exception as e:  # noqa: BLE001
                            logger.warning("[hook/output_safety] judge %d error: %s", idx, e)
                            verdicts_by_idx[idx] = SafetyVerdict(
                                safe=not self.config.llm_judge_fail_closed,
                                reason=f"judge_error:{e}",
                                categories=["judge_error"],
                            )
        # 顺序组
        for idx, j in sequential_judges:
            try:
                verdicts_by_idx[idx] = self._call_judge(j, text)
            except Exception as e:  # noqa: BLE001
                logger.warning("[hook/output_safety] judge %d error: %s", idx, e)
                verdicts_by_idx[idx] = SafetyVerdict(
                    safe=not self.config.llm_judge_fail_closed,
                    reason=f"judge_error:{e}",
                    categories=["judge_error"],
                )
        # 保持原 judge 顺序（聚合按顺序）
        verdicts = [verdicts_by_idx[i] for i in range(len(judges)) if i in verdicts_by_idx]
        return self._aggregate_verdicts(verdicts)

    def _aggregate_verdicts(self, verdicts: list[SafetyVerdict]) -> SafetyVerdict:
        """按 llm_voting_strategy 聚合多个 verdict。"""
        if not verdicts:
            return SafetyVerdict(safe=True)
        strat = self.config.llm_voting_strategy
        n = len(verdicts)
        unsafe_count = sum(1 for v in verdicts if not v.safe)
        # 收集所有 categories + reason
        all_cats: list[str] = []
        all_reasons: list[str] = []
        max_score = max((v.score or 0.0) for v in verdicts) if verdicts else None
        avg_score = (
            sum(v.score or 0.0 for v in verdicts) / n
            if verdicts and any(v.score is not None for v in verdicts)
            else None
        )
        avg_confidence = (
            sum(v.confidence or 0.0 for v in verdicts) / n
            if verdicts and any(v.confidence is not None for v in verdicts)
            else None
        )
        # ── multi_categories_severity：同 category 多次投票 ──
        multi_sev: dict[str, list[str]] = {}
        merged_cat_sev: dict[str, str] = {}  # 合并的 category_severity（多数决定）
        # multi_categories_confidence：同 category 多次 confidence（取平均）
        multi_cat_conf: dict[str, list[float]] = {}
        merged_cat_conf: dict[str, float] = {}
        # weighted_severity: 每 category 的 score × confidence 加权（v0.4.13）
        # 收集每个 verdict 的 score 和 confidence_per_category
        multi_score_conf: dict[str, list[tuple[float, float]]] = {}
        merged_weighted_sev: dict[str, float] = {}
        # v0.4.14: explanation 合并——每 category 取最长
        merged_explanation: dict[str, str] = {}
        for v in verdicts:
            if v.categories:
                all_cats.extend(v.categories)
            if v.reason:
                all_reasons.append(v.reason)
            # 收集每个 verdict 的 category_severity 到 multi_sev
            for cat, sev in v.category_severity.items():
                multi_sev.setdefault(cat, []).append(sev)
            # 收集每个 verdict 的 confidence_per_category 到 multi_cat_conf
            for cat, conf in v.confidence_per_category.items():
                multi_cat_conf.setdefault(cat, []).append(float(conf))
            # 收集 explanation（最长胜出）
            for cat, exp in (v.explanation or {}).items():
                if len(exp) > len(merged_explanation.get(cat, "")):
                    merged_explanation[cat] = exp
            # 收集 score × confidence 对：score 来自 v.score，confidence 来自 v.confidence
            # 注：score 是 verdict-level；与 confidence_per_category[cat] 配对
            if v.score is not None and not v.safe:
                for cat in v.categories:
                    conf = v.confidence_per_category.get(cat, v.confidence or 0.0)
                    multi_score_conf.setdefault(cat, []).append(
                        (float(v.score), float(conf)),
                    )
        # 对每个 category 计算多数 severity（最高票数 → 当选）
        sev_rank = _SEVERITY_ORDER
        for cat, sevs in multi_sev.items():
            # 排序：先按 count 降序，再按 severity rank 降序
            counter: dict[str, int] = {}
            for s in sevs:
                counter[s] = counter.get(s, 0) + 1
            best = sorted(
                counter.items(),
                key=lambda x: (x[1], sev_rank.get(x[0], 0)),
                reverse=True,
            )[0][0]
            merged_cat_sev[cat] = best
        # 对每个 category 计算平均 confidence（fallback 到 verdict.confidence）
        for cat, confs in multi_cat_conf.items():
            merged_cat_conf[cat] = sum(confs) / len(confs)
        # 对每个 category 计算 weighted_severity = mean(score × confidence)
        for cat, pairs in multi_score_conf.items():
            merged_weighted_sev[cat] = sum(s * c for s, c in pairs) / len(pairs)

        # 计算最终 safe
        if strat == "unanimous":
            final_safe = unsafe_count == 0
        elif strat == "majority":
            final_safe = unsafe_count < (n / 2)  # 多数 safe
        elif strat == "any":
            final_safe = unsafe_count == 0
        elif strat == "weighted_majority":
            total_score = sum(v.score or 0.0 for v in verdicts if not v.safe)
            final_safe = total_score <= self.config.llm_voting_score_threshold
        elif strat == "weighted_severity":
            # 任一 category 的 weighted_severity 超阈值 → unsafe
            threshold = self.config.llm_voting_weighted_severity_threshold
            any_over = any(
                ws >= threshold for ws in merged_weighted_sev.values()
            )
            final_safe = not any_over
        else:
            final_safe = unsafe_count == 0  # fallback to unanimous

        return SafetyVerdict(
            safe=final_safe,
            reason="; ".join(all_reasons[:3]) if all_reasons else f"voting:{strat}",
            categories=list(dict.fromkeys(all_cats))[:5],  # 去重保序
            score=max_score,
            confidence=avg_confidence,
            category_severity=merged_cat_sev,
            multi_categories_severity=multi_sev,
            confidence_per_category=merged_cat_conf,
            multi_categories_confidence=multi_cat_conf,
            weighted_severity=merged_weighted_sev,
            explanation=merged_explanation,
        )

    def _apply_severity_filter(self, verdict: SafetyVerdict) -> SafetyVerdict:
        """按 category_severity 过滤：低于 safety_min_severity 的 category 视为 safe。"""
        if not self.config.safety_min_severity or not verdict.categories:
            return verdict
        sev_map = {**self.config.category_severity_map, **verdict.category_severity}
        min_sev = self.config.safety_min_severity
        kept_cats = []
        dropped_cats = []
        for cat in verdict.categories:
            sev = sev_map.get(cat, "medium")  # 默认 medium（未配置按 medium 算）
            if _meets_severity(sev, min_sev):
                kept_cats.append(cat)
            else:
                dropped_cats.append((cat, sev))
        if dropped_cats:
            logger.warning(
                "[hook/output_safety] severity filter: dropped %s (below %s)",
                dropped_cats, min_sev,
            )
        # 如果所有 category 都被过滤掉 → safe
        if not kept_cats:
            return SafetyVerdict(
                safe=True,
                reason=f"severity_filtered:{min_sev}",
                categories=[],
                score=verdict.score,
                confidence=verdict.confidence,
            )
        # 保留 verdict 但只留 kept_cats
        return SafetyVerdict(
            safe=verdict.safe,
            reason=verdict.reason,
            categories=kept_cats,
            score=verdict.score,
            confidence=verdict.confidence,
            category_severity=verdict.category_severity,
        )


def build_default_middleware(
    pii_config: PIIScrubConfig | None = None,
    rate_limit_config: RateLimitConfig | None = None,
    token_usage_config: TokenUsageConfig | None = None,
    safety_config: OutputSafetyConfig | None = None,
    audit_path: str | None = None,
) -> list[Any]:
    """构造一组默认 middleware，供 AgentCore.init_agent 注入 create_agent。

    所有参数都是可选的 —— 不传则用各自 ``*Config`` 类的默认值。

    典型用法::

        # 全部默认
        mw_list = build_default_middleware()

        # 部分定制：禁用 PII 之外还加内部身份证号
        mw_list = build_default_middleware(
            pii_config=PIIScrubConfig(extra_patterns=(r"\\d{17}[\\dXx]",)),
        )

        # 切换限流到 Redis 集群
        mw_list = build_default_middleware(
            rate_limit_config=RateLimitConfig(
                max_calls=100, window_seconds=60,
                backend="redis", redis_url="redis://10.0.0.1:6379/0",
            ),
        )
    """

    if not _HAS_OFFICIAL_MW:
        logger.warning("langchain.agents.middleware 不可用，跳过 hooks 注入")
        return []
    base = [
        LoggingMiddleware(),
        ToolCallCounterMiddleware(),
        ContextTrimMiddleware(max_messages=20),
        PIIScrubMiddleware(config=pii_config),
        RateLimitMiddleware(config=rate_limit_config or RateLimitConfig()),
        AuditLogMiddleware(audit_path=audit_path),
        TokenUsageMiddleware(config=token_usage_config or TokenUsageConfig()),
        OutputSafetyMiddleware(config=safety_config or OutputSafetyConfig()),
    ]
    # 追加 plugin 注入的 middleware
    try:
        base.extend(MiddlewareRegistry.build_all())
    except Exception as e:  # noqa: BLE001
        logger.warning("MiddlewareRegistry.build_all failed: %s", e)
    return base


__all__ = [
    # ── Hooks ──
    "LoggingMiddleware",
    "ToolCallCounterMiddleware",
    "ContextTrimMiddleware",
    "PIIScrubMiddleware",
    "RateLimitMiddleware",
    "AuditLogMiddleware",
    "TokenUsageMiddleware",
    "OutputSafetyMiddleware",
    # ── 配置（可注入）──
    "PIIScrubConfig",
    "OutputSafetyConfig",
    "RateLimitConfig",
    "TokenUsageConfig",
    # ── 工厂 / 工具 ──
    "build_default_middleware",
    "MiddlewareRegistry",
    "_HAS_OFFICIAL_MW",
    # ── Dashboard 模块级 API（v0.5 新增） ──
    "get_token_usage_registry",
    "get_token_usage_snapshot",
    "update_token_budget",
    "update_token_prometheus",
    "push_token_prometheus_now",
]


# ============================================================
# MiddlewareRegistry —— 让外部 plugin 注册额外的 LangChain middleware
# ============================================================

class MiddlewareRegistry:
    """外部 middleware 注册中心。

    用法（plugin 内）：
        from agent_middleware import MiddlewareRegistry
        class MyMW(AgentMiddleware):
            ...
        MiddlewareRegistry.register("my_plugin_mw", MyMW)
    AgentCore.init_agent 在调用 build_default_middleware() 之后追加
    MiddlewareRegistry.build_all() 的返回值。
    """

    _REGISTRY: Dict[str, Any] = {}
    _CONFIG: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def register(cls, name: str, mw_cls: Any, config: Optional[Dict[str, Any]] = None) -> None:
        cls._REGISTRY[name] = mw_cls
        cls._CONFIG[name] = config or {}

    @classmethod
    def unregister(cls, name: str) -> None:
        cls._REGISTRY.pop(name, None)
        cls._CONFIG.pop(name, None)

    @classmethod
    def list(cls) -> List[str]:
        return sorted(cls._REGISTRY.keys())

    @classmethod
    def build_all(cls) -> List[Any]:
        """实例化所有已注册 middleware。失败时跳过单条并打 warning。"""
        out: List[Any] = []
        for name, mw_cls in cls._REGISTRY.items():
            try:
                cfg = cls._CONFIG.get(name) or {}
                instance = mw_cls(**cfg) if isinstance(cfg, dict) else mw_cls(cfg)
                out.append(instance)
            except Exception as e:  # noqa: BLE001
                logger.warning("MiddlewareRegistry: skip %s: %s", name, e)
        return out


# 兼容类型提示
from typing import List, Optional  # noqa: E402  (放在末尾仅为不破坏原 import 顺序)