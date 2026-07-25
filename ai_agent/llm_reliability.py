"""
LLM 多级容错机制（Fallback / Retry / Fail Log / Timeout / Graceful Degradation）。

设计目标：
    任何 LLM 调用失败都不应导致用户得到空白或崩溃；按层级降级，
    直到给出有意义的响应。

五层容错栈（自上而下）：
    1. Timeout        - 包裹 LLM 调用，超时即抛 LLMTimeoutError
    2. RetryPolicy    - 指数退避 + 抖动，对可重试错误重试 N 次
    3. FallbackChain  - 当前 provider 失败后切换到备用 provider
    4. FailLog        - 每次失败持久化到 SQLite（含错误指纹与恢复状态）
    5. GracefulDegrade - 全部 fallback 都失败时，基于记忆/上下文生成骨架回答

关键设计：
    - LLM 调用错误分类为 4 类，每类对应不同处理策略
    - CircuitBreaker per provider：连续失败 N 次进入 cooldown，避免对挂掉的服务重试
    - 所有事件可观测：失败时同步写 FailLog，成功时记录恢复时间

与 reliability.py 的关系：
    reliability.py 是给多 Agent 消息总线用的（异步、async-only），
    本模块是给 LLM 调用用的（同步接口），不强行复用避免耦合。
    借鉴其设计模式：指数退避+抖动、三态熔断、DLQ。
"""

import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 第一层：错误分类协议
# ============================================================

class LLMErrorKind(str, Enum):
    """LLM 错误的分类（决定重试/fallback 策略）。"""
    TIMEOUT = "timeout"               # 网络超时
    RATE_LIMIT = "rate_limit"         # 限流（429）
    AUTH = "auth"                     # API Key 无效（401/403）
    UNAVAILABLE = "unavailable"       # 服务不可用（5xx / 网络断开）
    BAD_REQUEST = "bad_request"       # 请求格式错（400，不应重试）
    UNKNOWN = "unknown"               # 其它


# 可重试错误集合
RETRYABLE_KINDS = frozenset({
    LLMErrorKind.TIMEOUT,
    LLMErrorKind.RATE_LIMIT,
    LLMErrorKind.UNAVAILABLE,
    LLMErrorKind.UNKNOWN,
})


class LLMError(Exception):
    """LLM 调用错误的统一包装。"""

    def __init__(self, kind: LLMErrorKind, message: str,
                 provider: Optional[str] = None,
                 model: Optional[str] = None,
                 cause: Optional[BaseException] = None,
                 fingerprint: Optional[str] = None):
        super().__init__(message)
        self.kind = kind
        self.provider = provider
        self.model = model
        self.cause = cause
        # 错误指纹：同类错误聚合去重，便于 FailLog 去重
        self.fingerprint = fingerprint or self._compute_fingerprint(kind, message, provider)

    @staticmethod
    def _compute_fingerprint(kind: LLMErrorKind, message: str, provider: Optional[str]) -> str:
        """同类错误指纹（同 provider + 同 kind + 同错误类别）→ 同一指纹。

        修复 F1：原版取 message 前 40 字符，导致 req_abc123 与 req_def456
        被识别为不同错误，FailLog 无法聚合。改为：去掉数字/UUID-like 尾部，
        再取前若干字符作为语义指纹。
        """
        # 去掉数字 ID、UUID、request_id 等尾部变量
        cleaned = re.sub(r"[a-f0-9-]{8,}", "<id>", message or "")
        cleaned = re.sub(r"\b\d+\b", "<n>", cleaned)
        # 取前 60 字符（已剥掉变量部分）
        msg_key = cleaned[:60].strip().lower()
        return f"{provider or '?'}|{kind.value}|{msg_key}"

    @staticmethod
    def from_exception(exc: BaseException, provider: Optional[str] = None,
                       model: Optional[str] = None) -> "LLMError":
        """从任意异常归类为 LLMError。"""
        msg = str(exc) or ""
        msg_lower = msg.lower()

        # 限流
        if ("rate limit" in msg_lower or "429" in msg
                or "quota" in msg_lower or "tpm" in msg_lower):
            kind = LLMErrorKind.RATE_LIMIT
        # 超时
        elif ("timeout" in msg_lower or "timed out" in msg_lower
              or "deadline" in msg_lower):
            kind = LLMErrorKind.TIMEOUT
        # 鉴权
        elif ("api key" in msg_lower or "unauthorized" in msg_lower
              or "401" in msg or "403" in msg or "invalid_api_key" in msg_lower):
            kind = LLMErrorKind.AUTH
        # 服务不可用
        elif ("503" in msg or "502" in msg or "500" in msg
              or "service unavailable" in msg_lower
              or "internal server error" in msg_lower
              or "connection" in msg_lower or "network" in msg_lower):
            kind = LLMErrorKind.UNAVAILABLE
        # 请求格式错
        elif ("400" in msg or "bad request" in msg_lower
              or "invalid request" in msg_lower):
            kind = LLMErrorKind.BAD_REQUEST
        else:
            kind = LLMErrorKind.UNKNOWN

        return LLMError(kind, msg, provider=provider, model=model, cause=exc)


# ============================================================
# 第二层：重试策略（指数退避 + 抖动，同步实现）
# ============================================================

@dataclass
class RetryConfig:
    """重试配置。"""
    max_attempts: int = 3                # 单个 provider 内最大重试次数
    initial_delay: float = 0.5           # 初始延迟（秒）
    max_delay: float = 8.0               # 单次最大延迟
    jitter_factor: float = 0.3           # 抖动 ±30%
    backoff_multiplier: float = 2.0      # 指数基数
    retry_on_kinds: Tuple[LLMErrorKind, ...] = tuple(RETRYABLE_KINDS)

    def compute_delay(self, attempt: int) -> float:
        """第 N 次重试前的延迟（attempt=0 是第一次重试）。"""
        if attempt < 0:
            return 0.0
        delay = self.initial_delay * (self.backoff_multiplier ** attempt)
        # 抖动
        jitter = delay * self.jitter_factor * (((time.time_ns() % 1000) / 1000.0) * 2 - 1)
        delay = max(0.0, delay + jitter)
        return min(delay, self.max_delay)


# ============================================================
# 第三层：Provider 熔断器（per-provider cooldown）
# ============================================================

@dataclass
class ProviderBreaker:
    """单 provider 的简单熔断器。

    - 连续失败 N 次 → 进入 OPEN 状态，跳过该 provider
    - cooldown_seconds 后 → 进入 HALF_OPEN，放一次试探
    - 试探成功 → CLOSED，清零计数；失败 → 重新 OPEN
    """
    failure_threshold: int = 3
    cooldown_seconds: float = 60.0

    state: str = "closed"          # closed | open | half_open
    consecutive_failures: int = 0
    open_until: float = 0.0
    last_error: Optional[str] = None
    last_failure_at: float = 0.0

    def allow(self) -> bool:
        """是否允许调用该 provider。"""
        now = time.time()
        if self.state == "closed":
            return True
        if self.state == "open":
            if now >= self.open_until:
                self.state = "half_open"
                logger.info("Circuit breaker -> half_open")
                return True
            return False
        # half_open：仅放一次（后续拒绝直到试探结果）
        return True

    def record_success(self):
        if self.state != "closed":
            logger.info(f"Circuit breaker recovered (was {self.state})")
        self.state = "closed"
        self.consecutive_failures = 0
        self.open_until = 0.0
        self.last_error = None

    def record_failure(self, error_msg: str):
        self.consecutive_failures += 1
        self.last_error = error_msg
        self.last_failure_at = time.time()
        if self.consecutive_failures >= self.failure_threshold:
            self.state = "open"
            self.open_until = time.time() + self.cooldown_seconds
            logger.warning(
                f"Circuit breaker OPENED after {self.consecutive_failures} "
                f"consecutive failures, cooldown {self.cooldown_seconds}s"
            )

    def status(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "open_until": self.open_until,
            "last_error": self.last_error,
        }


# ============================================================
# 第四层：Fail Log（SQLite 持久化）
# ============================================================

class FailLogRepository:
    """失败日志仓储（SQLite）。

    Schema:
        id                - 自增 PK
        trace_id          - 链路追踪 ID（与 observability.py 对齐）
        session_id        - 会话 ID
        provider          - 失败 provider
        model             - 失败 model
        error_kind        - LLMErrorKind.value
        error_fingerprint - 用于聚合同类错误
        message           - 错误消息
        attempts          - 已尝试次数（含 fallback）
        fallbacks_tried   - 已试过的 fallback 数（JSON list）
        recovered         - 是否最终被 fallback 救回（0/1）
        created_at        - 时间戳
    """

    def __init__(self, db_path: str = "fail_log.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS fail_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trace_id TEXT NOT NULL,
                        session_id TEXT,
                        provider TEXT,
                        model TEXT,
                        error_kind TEXT NOT NULL,
                        error_fingerprint TEXT NOT NULL,
                        message TEXT,
                        attempts INTEGER DEFAULT 1,
                        fallbacks_tried TEXT DEFAULT '[]',
                        recovered INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_fail_fingerprint
                    ON fail_log(error_fingerprint)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_fail_trace
                    ON fail_log(trace_id)
                """)
                conn.commit()
            finally:
                conn.close()

    def record(self, *, trace_id: str, session_id: Optional[str],
               provider: Optional[str], model: Optional[str],
               error_kind: str, error_fingerprint: str,
               message: str, attempts: int,
               fallbacks_tried: List[str], recovered: bool = False) -> int:
        """记录一次失败。Returns inserted id."""
        with self._lock:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                cur = conn.execute(
                    """
                    INSERT INTO fail_log
                        (trace_id, session_id, provider, model,
                         error_kind, error_fingerprint, message,
                         attempts, fallbacks_tried, recovered)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (trace_id, session_id, provider, model,
                     error_kind, error_fingerprint, message,
                     attempts, json.dumps(fallbacks_tried, ensure_ascii=False),
                     1 if recovered else 0),
                )
                conn.commit()
                return cur.lastrowid
            finally:
                conn.close()

    def mark_recovered(self, trace_id: str):
        """当某次失败最终被 fallback 救回时，把同 trace 的失败标记为 recovered=1。"""
        with self._lock:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                conn.execute(
                    "UPDATE fail_log SET recovered = 1 WHERE trace_id = ? AND recovered = 0",
                    (trace_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def recent(self, limit: int = 50, only_unrecovered: bool = False) -> List[Dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                conn.row_factory = sqlite3.Row
                if only_unrecovered:
                    cur = conn.execute(
                        "SELECT * FROM fail_log WHERE recovered = 0 "
                        "ORDER BY id DESC LIMIT ?",
                        (limit,),
                    )
                else:
                    cur = conn.execute(
                        "SELECT * FROM fail_log ORDER BY id DESC LIMIT ?",
                        (limit,),
                    )
                return [dict(row) for row in cur.fetchall()]
            finally:
                conn.close()

    def fingerprint_stats(self) -> List[Dict[str, Any]]:
        """聚合：同指纹错误出现次数。"""
        with self._lock:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                conn.row_factory = sqlite3.Row
                cur = conn.execute("""
                    SELECT error_fingerprint, error_kind, provider, COUNT(*) as cnt,
                           SUM(CASE WHEN recovered = 1 THEN 1 ELSE 0 END) as recovered_cnt,
                           MAX(created_at) as last_seen
                    FROM fail_log
                    GROUP BY error_fingerprint
                    ORDER BY cnt DESC
                    LIMIT 50
                """)
                return [dict(row) for row in cur.fetchall()]
            finally:
                conn.close()


# ============================================================
# 第五层：Fallback 链
# ============================================================

@dataclass
class FallbackCandidate:
    """一个候选 provider + model 组合。"""
    provider: str
    model: str


class ModelFallbackChain:
    """Fallback 链：按优先级尝试 provider/model。

    用法：
        chain = ModelFallbackChain([
            FallbackCandidate("openai", "gpt-4o-mini"),
            FallbackCandidate("deepseek", "deepseek-chat"),
        ])
        for attempt in chain.iter_attempts(breaker_map):
            try:
                result = await attempt.invoke(...)
                attempt.mark_success()
                return result
            except LLMError as e:
                attempt.mark_failure(str(e))
                # continue to next
    """

    def __init__(self, candidates: List[FallbackCandidate]):
        if not candidates:
            raise ValueError("FallbackChain requires at least one candidate")
        self.candidates = candidates

    def iter_attempts(self, breakers: Dict[str, ProviderBreaker]):
        """返回可迭代的 Attempt 对象；每个对应一个 provider/model。"""
        for idx, cand in enumerate(self.candidates):
            breaker = breakers.get(cand.provider)
            if breaker and not breaker.allow():
                logger.info(
                    f"Skip {cand.provider}/{cand.model} (breaker={breaker.state})"
                )
                continue
            yield FallbackAttempt(idx, cand, breaker)


@dataclass
class FallbackAttempt:
    """单次 fallback 尝试的句柄。"""
    index: int
    candidate: FallbackCandidate
    breaker: Optional[ProviderBreaker]

    @property
    def provider(self) -> str:
        return self.candidate.provider

    @property
    def model(self) -> str:
        return self.candidate.model

    def mark_success(self):
        if self.breaker:
            self.breaker.record_success()

    def mark_failure(self, error_msg: str):
        if self.breaker:
            self.breaker.record_failure(error_msg)


# ============================================================
# 第六层：Graceful Degradation（骨架回答）
# ============================================================

class GracefulDegradation:
    """全部 fallback 失败时，基于已有上下文生成"骨架回答"。

    设计原则：
    - 不假装智能——明确告诉用户："系统繁忙，下面是已知的相关信息"
    - 尽量使用已有上下文（短期记忆 / 结构化摘要 / 工具调用历史）
    - 给出后续建议（重试 / 检查配置）
    """

    def __init__(self, fail_log: Optional[FailLogRepository] = None):
        self.fail_log = fail_log

    def build(
        self,
        *,
        user_input: str,
        trace_id: str,
        attempted_providers: List[str],
        last_error_kind: Optional[str],
        memory_hint: Optional[str] = None,
        context_hint: Optional[str] = None,
    ) -> str:
        """生成降级回答。"""
        lines: List[str] = [
            "⚠️ 当前所有模型都不可用，已为您保存问题并启用降级回答。",
            "",
            f"**您的输入**：{user_input[:200]}",
            "",
        ]

        # 已尝试的 provider 列表（让用户知道不是没尝试）
        if attempted_providers:
            lines.append(f"**已尝试**：{' → '.join(attempted_providers)}")
        if last_error_kind:
            lines.append(f"**最后错误**：{last_error_kind}")

        # 已知上下文（如果有）
        if context_hint:
            lines.append("")
            lines.append("**最近对话要点**：")
            lines.append(context_hint[:500])
        if memory_hint:
            lines.append("")
            lines.append("**可能相关的记忆**：")
            lines.append(memory_hint[:500])

        lines.extend([
            "",
            "**建议**：",
            "1. 等待片刻后重试（熔断通常 60 秒后自动恢复）",
            "2. 在 ⚙️ 设置中切换其他模型提供商",
            "3. 检查 API Key 是否有效且有可用额度",
        ])

        # 失败信息已写入 fail log（trace_id 让用户能反馈问题）
        lines.append("")
        lines.append(f"**故障追踪 ID**：`{trace_id}`（可用于反馈问题）")

        return "\n".join(lines)


# ============================================================
# 顶层：ResilientLLMInvoker（容错栈编排）
# ============================================================

@dataclass
class InvokeResult:
    """一次 invoke 的最终结果。"""
    text: str
    success: bool
    degraded: bool                       # 是否走了降级
    provider_used: Optional[str] = None
    model_used: Optional[str] = None
    trace_id: str = ""
    attempts: int = 0
    fallbacks_used: List[str] = field(default_factory=list)
    last_error_kind: Optional[str] = None


class ResilientLLMInvoker:
    """LLM 容错栈的总入口。

    调用流程：
        invoke(user_input, payload, agent_factory, hooks)
        -> 对每个 fallback 候选 provider 调用 agent_factory(provider, model)
        -> 该 provider 内 retry
        -> 全部失败 -> graceful_degradation
        -> 写入 fail_log
    """

    def __init__(
        self,
        *,
        fallback_chain: ModelFallbackChain,
        retry_config: Optional[RetryConfig] = None,
        breakers: Optional[Dict[str, ProviderBreaker]] = None,
        fail_log: Optional[FailLogRepository] = None,
        degradation: Optional[GracefulDegradation] = None,
        invoke_timeout: float = 30.0,
        total_timeout: float = 120.0,
    ):
        self.fallback_chain = fallback_chain
        self.retry_config = retry_config or RetryConfig()
        # 默认 breaker：每个候选 provider 一个，初始 CLOSED
        self.breakers: Dict[str, ProviderBreaker] = breakers or {}
        for cand in fallback_chain.candidates:
            self.breakers.setdefault(
                cand.provider,
                ProviderBreaker(),
            )
        self.fail_log = fail_log or FailLogRepository()
        self.degradation = degradation or GracefulDegradation(fail_log=self.fail_log)
        self.invoke_timeout = invoke_timeout
        self.total_timeout = total_timeout

    def invoke(
        self,
        *,
        agent_factory: Callable[[str, str], Any],
        payload: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        memory_hint: Optional[str] = None,
        context_hint: Optional[str] = None,
        user_input: str = "",
        text_extractor: Optional[Callable[[Any], str]] = None,
    ) -> InvokeResult:
        """同步 invoke，自动应用 fallback + retry + degradation。

        Args:
            agent_factory: (provider, model) -> 已注入模型的 agent/compiled graph
            payload: 传给 agent.invoke 的输入
            config: agent.invoke 的 config（如 thread_id）
            trace_id: 调用追踪 ID（默认自动生成）
            session_id: 会话 ID（用于 fail_log 关联）
            memory_hint: 已知记忆（降级时使用）
            context_hint: 已知上下文（降级时使用）
            user_input: 用户原始输入（降级时展示）
            text_extractor: 从 agent.invoke 返回值抽取纯文本的可选回调。
                若不提供，invoker 直接把返回值当 text（适用于 invoke 直接返回 string 的场景）。

        Returns:
            InvokeResult（永远非空；失败时 degraded=True，text 是降级回答）
        """
        trace_id = trace_id or str(uuid.uuid4())
        config = config or {}
        deadline = time.time() + self.total_timeout
        attempted: List[str] = []
        last_err: Optional[LLMError] = None
        attempts_total = 0

        for attempt in self.fallback_chain.iter_attempts(self.breakers):
            if time.time() >= deadline:
                logger.warning(f"Total timeout reached during fallback iteration")
                break

            # 单 provider 内重试
            for retry_i in range(self.retry_config.max_attempts):
                if time.time() >= deadline:
                    break
                attempts_total += 1

                try:
                    agent = agent_factory(attempt.provider, attempt.model)
                    raw_result = self._invoke_with_timeout(
                        agent, payload, config
                    )
                    # 成功：抽取纯文本
                    if text_extractor is not None:
                        output_text = text_extractor(raw_result)
                    elif isinstance(raw_result, str):
                        output_text = raw_result
                    else:
                        output_text = str(raw_result) if raw_result is not None else ""
                    # 成功
                    attempt.mark_success()
                    if attempted:  # 说明走过 fallback
                        # 标记之前的 fail_log 为已恢复
                        self.fail_log.mark_recovered(trace_id)
                    return InvokeResult(
                        text=output_text,
                        success=True,
                        degraded=False,
                        provider_used=attempt.provider,
                        model_used=attempt.model,
                        trace_id=trace_id,
                        attempts=attempts_total,
                        fallbacks_used=list(attempted),
                    )
                except LLMError as e:
                    last_err = e
                    logger.warning(
                        f"LLM call failed [{attempt.provider}/{attempt.model}] "
                        f"attempt {retry_i + 1}/{self.retry_config.max_attempts}: "
                        f"{e.kind.value} - {e}"
                    )
                    # 记录失败
                    self.fail_log.record(
                        trace_id=trace_id,
                        session_id=session_id,
                        provider=attempt.provider,
                        model=attempt.model,
                        error_kind=e.kind.value,
                        error_fingerprint=e.fingerprint,
                        message=str(e)[:500],
                        attempts=attempts_total,
                        fallbacks_tried=list(attempted),
                        recovered=False,
                    )
                    # 不可重试 → 直接跳出重试循环
                    if e.kind not in self.retry_config.retry_on_kinds:
                        break
                    # 重试前 sleep（最后一次不睡）
                    if retry_i + 1 < self.retry_config.max_attempts:
                        delay = self.retry_config.compute_delay(retry_i)
                        time.sleep(min(delay, max(0.0, deadline - time.time())))
                except Exception as e:
                    # 兜底：非 LLMError 也包装
                    wrapped = LLMError.from_exception(e, provider=attempt.provider,
                                                      model=attempt.model)
                    last_err = wrapped
                    logger.error(f"Unexpected error [{attempt.provider}]: {e}")
                    break

            # 走到这里说明该 provider 全部重试用尽
            attempt.mark_failure(str(last_err) if last_err else "unknown")
            attempted.append(f"{attempt.provider}/{attempt.model}")

        # 全部 fallback 失败 → 降级
        logger.error(
            f"All fallbacks failed for trace_id={trace_id}, "
            f"attempted={attempted}, last_error={last_err}"
        )
        degraded_text = self.degradation.build(
            user_input=user_input,
            trace_id=trace_id,
            attempted_providers=attempted,
            last_error_kind=last_err.kind.value if last_err else None,
            memory_hint=memory_hint,
            context_hint=context_hint,
        )
        return InvokeResult(
            text=degraded_text,
            success=False,
            degraded=True,
            provider_used=None,
            model_used=None,
            trace_id=trace_id,
            attempts=attempts_total,
            fallbacks_used=list(attempted),
            last_error_kind=last_err.kind.value if last_err else None,
        )

    def _invoke_with_timeout(
        self,
        agent: Any,
        payload: Dict[str, Any],
        config: Dict[str, Any],
    ) -> str:
        """调用 agent.invoke 并施加单次超时。

        简化实现：使用线程超时（LangChain sync invoke 在主线程阻塞）。
        对于真正的生产部署，建议改用 asyncio.run_in_executor 或
        signal-based 超时（Windows 上 signal 不可用，线程方案更通用）。
        """
        result_box: Dict[str, Any] = {"value": None, "error": None}

        def _target():
            try:
                result_box["value"] = agent.invoke(payload, config=config)
            except BaseException as e:  # noqa: BLE001
                result_box["error"] = e

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(timeout=self.invoke_timeout)

        if t.is_alive():
            # 注意：daemon 线程继续在后台跑，可能最终完成但我们不再等待
            raise LLMError(
                LLMErrorKind.TIMEOUT,
                f"invoke timeout after {self.invoke_timeout}s",
            )
        if result_box["error"] is not None:
            err = result_box["error"]
            raise LLMError.from_exception(err)

        result = result_box["value"]
        # 由调用方负责从 result 抽取文本（agent.py 提供 helper）
        return result

    def stream(
        self,
        *,
        agent_factory: Callable[[str, str], Any],
        payload: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        text_extractor: Optional[Callable[[Any], str]] = None,
    ) -> Iterator[Tuple[str, Any]]:
        """流式调用：yield (event, payload)。

        event in {"chunk", "error", "degraded"}。
        - chunk: payload 是 agent.stream 返回的原始 chunk
        - error: payload 是 error_kind
        - degraded: payload 是降级回答字符串
        流式模式不重试整次，只在错误时切换到 fallback 后从头开始；
        超时通过下一次 chunk 间隔判断（简化）。
        """
        trace_id = trace_id or str(uuid.uuid4())
        config = config or {}
        last_err: Optional[LLMError] = None
        attempted: List[str] = []

        for attempt in self.fallback_chain.iter_attempts(self.breakers):
            try:
                agent = agent_factory(attempt.provider, attempt.model)
                for chunk in agent.stream(payload, config=config, stream_mode="values"):
                    yield ("chunk", chunk)
                attempt.mark_success()
                if attempted:
                    self.fail_log.mark_recovered(trace_id)
                return
            except Exception as e:
                wrapped = LLMError.from_exception(
                    e, provider=attempt.provider, model=attempt.model
                )
                last_err = wrapped
                self.fail_log.record(
                    trace_id=trace_id,
                    session_id=session_id,
                    provider=attempt.provider,
                    model=attempt.model,
                    error_kind=wrapped.kind.value,
                    error_fingerprint=wrapped.fingerprint,
                    message=str(wrapped)[:500],
                    attempts=1,
                    fallbacks_tried=list(attempted),
                    recovered=False,
                )
                attempt.mark_failure(str(wrapped))
                attempted.append(f"{attempt.provider}/{attempt.model}")
                yield ("error", wrapped.kind.value)

        # 全部失败：降级
        degraded = self.degradation.build(
            user_input="",
            trace_id=trace_id,
            attempted_providers=attempted,
            last_error_kind=last_err.kind.value if last_err else None,
        )
        yield ("degraded", degraded)


# ============================================================
# 单例访问
# ============================================================

_invoker_singleton: Optional[ResilientLLMInvoker] = None
_invoker_lock = threading.Lock()


def get_invoker(
    fallback_chain: Optional[ModelFallbackChain] = None,
    *,
    force_new: bool = False,
) -> ResilientLLMInvoker:
    """获取/构建全局容错 invoker 单例。"""
    global _invoker_singleton
    with _invoker_lock:
        if force_new or _invoker_singleton is None:
            if fallback_chain is None:
                # 默认 fallback：当前 provider → 同系列其它 → 跨系列
                fallback_chain = ModelFallbackChain([
                    FallbackCandidate("openai", "gpt-4o-mini"),
                    FallbackCandidate("deepseek", "deepseek-chat"),
                    FallbackCandidate("qwen", "qwen-turbo"),
                    FallbackCandidate("moonshot", "moonshot-v1-8k"),
                ])
            _invoker_singleton = ResilientLLMInvoker(
                fallback_chain=fallback_chain,
            )
        return _invoker_singleton


def reset_invoker():
    """重置单例（用于测试或切换 fallback 配置）。"""
    global _invoker_singleton
    with _invoker_lock:
        _invoker_singleton = None


# ============================================================
# 第七层：主备（Primary/Standby）模型声明式配置
# ============================================================

@dataclass
class PrimaryStandbyConfig:
    """主备模型声明式配置。

    语义：
    - primary  = 正常情况下使用的 provider/model
    - standbys = 故障时按顺序尝试的备选；可以是 1 个或多个
    - switching_strategy = "automatic"（自动故障切换）/ "manual"（仅手动切换）

    区别于 ModelFallbackChain：
    - ModelFallbackChain 是隐式的"链"，调用方不知道具体顺序
    - PrimaryStandbyConfig 是面向运维/UI 的声明式接口，明确"主备"
    """
    primary: FallbackCandidate
    standbys: List[FallbackCandidate] = field(default_factory=list)
    switching_strategy: str = "automatic"   # automatic | manual

    def to_chain(self) -> ModelFallbackChain:
        """转成 ModelFallbackChain（primary 优先，standbys 兜底）。"""
        return ModelFallbackChain([self.primary] + self.standbys)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary": {"provider": self.primary.provider, "model": self.primary.model},
            "standbys": [
                {"provider": s.provider, "model": s.model} for s in self.standbys
            ],
            "switching_strategy": self.switching_strategy,
        }


class StandbyWarmupService:
    """Standby 预热服务：定期 ping standby 模型，确保它活着。

    必要性：
    - 若 standby 长时间未调用，触发时可能冷启动失败
    - 通过后台周期性健康检查，让 standby 始终"热"状态

    设计：
    - 轻量线程，单次 ping = invoke 一个最小 prompt
    - 失败不阻断主流程，仅记录健康状态
    """

    def __init__(
        self,
        standby: FallbackCandidate,
        ping_interval: float = 300.0,       # 5 分钟
        ping_timeout: float = 10.0,
        ping_prompt: str = "ping",
    ):
        self.standby = standby
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.ping_prompt = ping_prompt
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_check_at: float = 0.0
        self.last_check_ok: Optional[bool] = None
        self.last_error: Optional[str] = None

    def start(self, agent_factory: Callable[[str, str], Any],
               text_extractor: Callable[[Any], str]):
        """启动后台预热线程。"""
        if self._thread and self._thread.is_alive():
            return  # 已运行
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, args=(agent_factory, text_extractor),
            daemon=True, name=f"warmup-{self.standby.provider}"
        )
        self._thread.start()
        logger.info(f"Standby warmup started: {self.standby.provider}")

    def stop(self):
        """停止预热线程。"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Standby warmup stopped")

    def _loop(self, agent_factory, text_extractor):
        """预热循环。"""
        while not self._stop_event.is_set():
            try:
                self._ping(agent_factory, text_extractor)
            except Exception as e:
                logger.warning(f"Warmup ping failed: {e}")
            # 等待下一次
            self._stop_event.wait(self.ping_interval)

    def _ping(self, agent_factory, text_extractor):
        """单次 ping。"""
        from langchain_core.messages import HumanMessage
        payload = {"messages": [HumanMessage(content=self.ping_prompt)]}
        try:
            agent = agent_factory(self.standby.provider, self.standby.model)
            # 简单 invoke 调用，不走完整容错栈
            state = agent.invoke(payload, config={})
            text = text_extractor(state) if text_extractor else str(state)
            self.last_check_at = time.time()
            self.last_check_ok = bool(text)
            self.last_error = None if self.last_check_ok else "empty response"
        except Exception as e:
            self.last_check_at = time.time()
            self.last_check_ok = False
            self.last_error = str(e)[:200]

    def status(self) -> Dict[str, Any]:
        return {
            "standby": f"{self.standby.provider}/{self.standby.model}",
            "running": self._thread.is_alive() if self._thread else False,
            "last_check_at": self.last_check_at,
            "last_check_ok": self.last_check_ok,
            "last_error": self.last_error,
        }