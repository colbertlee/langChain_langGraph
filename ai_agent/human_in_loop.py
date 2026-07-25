"""
Human-in-the-Loop（HITL）模块

设计目标：
- 在关键拦截点请求人类审批（同步阻塞等待决策）
- 支持策略：auto / ask / block
- 支持超时自动决策
- 与 StreamingBus / Observability 集成（发出 HITL_REQUESTED / HITL_RESOLVED 事件）

拦截点（HookPoint）：
- BEFORE_TOOL_CALL    工具调用前
- BEFORE_DELEGATE     Worker 任务分派前
- BEFORE_BID          Worker 出价前
- BEFORE_NEGOTIATE    协商回合前
- BEFORE_SEND         关键消息发送前
- FINAL_ANSWER        最终回答输出前

使用：
    guard = get_hitl_guard()
    guard.set_default_policy(HITLPolicy.AUTO)

    decision = await guard.request_approval(
        HookPoint.BEFORE_DELEGATE,
        payload={"task_type": "code", "worker": "codeworker"},
        timeout=10.0,
    )
    # decision = ApprovalDecision(approved=True, ...)
"""

import asyncio
import time
import uuid
import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger(__name__)


# ============================================================
# 拦截点 / 策略
# ============================================================

class HookPoint(str, Enum):
    """HITL 拦截点"""
    BEFORE_TOOL_CALL = "before_tool_call"
    BEFORE_DELEGATE = "before_delegate"
    BEFORE_BID = "before_bid"
    BEFORE_NEGOTIATE = "before_negotiate"
    BEFORE_SEND = "before_send"
    FINAL_ANSWER = "final_answer"


class HITLPolicy(str, Enum):
    """默认 HITL 策略"""
    AUTO = "auto"          # 全部自动放行（开发用）
    ASK = "ask"            # 关键点询问
    BLOCK = "block"        # 关键点必须人工审批（生产用）
    DISABLED = "disabled"  # 不启用 HITL


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"        # 人类改了 payload
    TIMEOUT = "timeout"
    SKIPPED = "skipped"          # 自动放行


@dataclass
class ApprovalRequest:
    """一次审批请求"""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    hook_point: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    status: ApprovalDecision = ApprovalDecision.SKIPPED
    decision_payload: Optional[Dict[str, Any]] = None
    requested_by: str = ""
    decided_by: str = ""
    created_at: float = field(default_factory=time.time)
    decided_at: Optional[float] = None
    timeout_seconds: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> Dict:
        return {
            "request_id": self.request_id,
            "hook_point": self.hook_point,
            "payload": self.payload,
            "description": self.description,
            "status": self.status.value if isinstance(self.status, ApprovalDecision) else str(self.status),
            "decision_payload": self.decision_payload,
            "requested_by": self.requested_by,
            "decided_by": self.decided_by,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "timeout_seconds": self.timeout_seconds,
            "notes": self.notes,
        }


# ============================================================
# HumanInLoopGuard
# ============================================================

class HumanInLoopGuard:
    """
    HITL 守卫

    角色：
    - request_approval()：阻塞等待人类决策
    - decide()：人类通过 UI/API 提交决策
    - 策略 / 拦截点 hook
    """

    def __init__(self, default_policy: HITLPolicy = HITLPolicy.AUTO):
        self._default_policy = default_policy
        # 每个 hook_point 的策略（覆盖默认）
        self._hook_policies: Dict[str, HITLPolicy] = {}
        # 等待中的请求（request_id -> request）
        self._pending: Dict[str, ApprovalRequest] = {}
        # 等待中的 Future
        self._futures: Dict[str, asyncio.Future] = {}
        # 已完成的请求（环形缓冲）
        self._history: List[ApprovalRequest] = []
        self._max_history = 200
        # 回调：每次决策后调用
        self._on_decided: List[Callable[[ApprovalRequest], None]] = []
        # 锁
        self._lock = Lock()

        # 可观测性接入（可选）
        self._observability = None
        try:
            from observability import get_observability
            self._observability = get_observability()
        except Exception:
            pass

    # ----------------- 策略 -----------------

    def set_default_policy(self, policy: HITLPolicy) -> None:
        self._default_policy = policy

    def get_default_policy(self) -> HITLPolicy:
        return self._default_policy

    def set_hook_policy(self, hook_point: str, policy: HITLPolicy) -> None:
        self._hook_policies[hook_point] = policy

    def get_hook_policy(self, hook_point: str) -> HITLPolicy:
        return self._hook_policies.get(hook_point, self._default_policy)

    # ----------------- 决策接口 -----------------

    async def request_approval(
        self,
        hook_point: str,
        payload: Dict[str, Any],
        description: str = "",
        requested_by: str = "",
        timeout: Optional[float] = None,
    ) -> ApprovalRequest:
        """
        请求人类审批（异步阻塞）。

        策略决定行为：
        - DISABLED / AUTO：直接返回 SKIPPED
        - ASK：发出事件，但不阻塞（返回 SKIPPED + notes="auto_skipped"）
        - BLOCK：阻塞等待人类决策（通过 decide()）

        Args:
            hook_point: HookPoint
            payload: 给人类看的内容（task_type, worker, content 等）
            description: 简短说明
            requested_by: 谁发起的请求（agent_id）
            timeout: 阻塞等待超时（None = 永远等）

        Returns:
            ApprovalRequest
        """
        policy = self.get_hook_policy(hook_point)

        req = ApprovalRequest(
            hook_point=hook_point,
            payload=payload,
            description=description,
            requested_by=requested_by,
            timeout_seconds=timeout,
        )

        if policy == HITLPolicy.DISABLED or policy == HITLPolicy.AUTO:
            req.status = ApprovalDecision.SKIPPED
            req.notes = f"auto_skipped_by_{policy.value}"
            req.decided_at = time.time()
            self._record_history(req)
            self._publish_event("hitl_requested", req)
            self._publish_event("hitl_resolved", req)
            return req

        if policy == HITLPolicy.ASK:
            # 发出事件但不阻塞
            with self._lock:
                self._pending[req.request_id] = req
            self._publish_event("hitl_requested", req)
            # 给人类 N 秒响应，超时则按 SKIPPED 处理
            if timeout:
                try:
                    req = await self._await_decision(req, timeout=timeout)
                    if req.status == ApprovalDecision.SKIPPED:
                        req.status = ApprovalDecision.SKIPPED
                        req.notes = "ask_timeout_skipped"
                except asyncio.TimeoutError:
                    req.status = ApprovalDecision.TIMEOUT
                    req.notes = "ask_timeout"
                    req.decided_at = time.time()
            else:
                # 不超时：直接 SKIPPED
                req.status = ApprovalDecision.SKIPPED
                req.notes = "ask_no_timeout_auto_skip"
                req.decided_at = time.time()
            with self._lock:
                self._pending.pop(req.request_id, None)
            self._record_history(req)
            self._publish_event("hitl_resolved", req)
            return req

        # BLOCK：阻塞等人类决策
        fut = asyncio.get_event_loop().create_future()
        with self._lock:
            self._pending[req.request_id] = req
            self._futures[req.request_id] = fut
        self._publish_event("hitl_requested", req)
        logger.info(
            f"[HITL] BLOCK at {hook_point} from {requested_by}: "
            f"req_id={req.request_id}"
        )

        try:
            req = await self._await_decision(req, timeout=timeout, future=fut)
        finally:
            with self._lock:
                self._pending.pop(req.request_id, None)
                self._futures.pop(req.request_id, None)
            self._record_history(req)
            self._publish_event("hitl_resolved", req)

        return req

    async def _await_decision(
        self,
        req: ApprovalRequest,
        timeout: Optional[float] = None,
        future: Optional[asyncio.Future] = None,
    ) -> ApprovalRequest:
        """等待决策（带超时）"""
        target_future = future
        if target_future is None:
            # ASK 模式：暂时创建一个
            target_future = asyncio.get_event_loop().create_future()
            self._futures[req.request_id] = target_future

        try:
            if timeout:
                await asyncio.wait_for(target_future, timeout=timeout)
            else:
                await target_future
            # 人类已决策
            decided = target_future.result()
            if isinstance(decided, ApprovalRequest):
                return decided
            elif isinstance(decided, dict):
                req.status = ApprovalDecision(decided.get("status", "approved"))
                req.decision_payload = decided.get("decision_payload")
                req.decided_by = decided.get("decided_by", "human")
                req.notes = decided.get("notes", "")
            elif isinstance(decided, ApprovalDecision):
                req.status = decided
            else:
                req.status = ApprovalDecision.APPROVED
            req.decided_at = time.time()
        except asyncio.TimeoutError:
            req.status = ApprovalDecision.TIMEOUT
            req.notes = "block_timeout"
            req.decided_at = time.time()
        return req

    def decide(
        self,
        request_id: str,
        status: str,
        decided_by: str = "human",
        decision_payload: Optional[Dict[str, Any]] = None,
        notes: str = "",
    ) -> bool:
        """
        人类提交决策（外部 API/Web UI 调用）

        Args:
            request_id: ApprovalRequest.request_id
            status: "approved" | "rejected" | "modified"
            decided_by: 操作人标识
            decision_payload: 如果 modified，给出修改后的 payload
            notes: 备注

        Returns:
            True if 决策成功
        """
        with self._lock:
            req = self._pending.get(request_id)
            fut = self._futures.get(request_id)

        if req is None:
            logger.warning(f"[HITL] decide: request {request_id} not found")
            return False

        try:
            req.status = ApprovalDecision(status)
        except ValueError:
            req.status = ApprovalDecision.APPROVED

        req.decision_payload = decision_payload
        req.decided_by = decided_by
        req.notes = notes
        req.decided_at = time.time()

        if fut is not None and not fut.done():
            try:
                # 直接 set_result（因为 decide 通常在主 loop 中被调）
                if not fut.done():
                    fut.set_result(req)
            except RuntimeError as e:
                logger.warning(f"HITL decide failed to set future: {e}")

        # 回调
        for cb in self._on_decided:
            try:
                cb(req)
            except Exception as e:
                logger.warning(f"HITL callback error: {e}")

        return True

    def decide_by_payload_match(
        self,
        hook_point: str,
        payload_match: Dict[str, Any],
        status: str = "approved",
        decided_by: str = "human",
        notes: str = "",
    ) -> int:
        """根据 payload 匹配自动决定（一次性决定所有匹配项）"""
        n = 0
        with self._lock:
            for req_id, req in list(self._pending.items()):
                if req.hook_point != hook_point:
                    continue
                if all(req.payload.get(k) == v for k, v in payload_match.items()):
                    if self.decide(req_id, status, decided_by, None, notes):
                        n += 1
        return n

    # ----------------- 查询 -----------------

    def get_pending(self, hook_point: Optional[str] = None) -> List[ApprovalRequest]:
        with self._lock:
            pending = list(self._pending.values())
        if hook_point:
            pending = [r for r in pending if r.hook_point == hook_point]
        return pending

    def get_history(
        self,
        hook_point: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[ApprovalRequest]:
        out = list(self._history)
        if hook_point:
            out = [r for r in out if r.hook_point == hook_point]
        if status:
            out = [r for r in out if r.status.value == status]
        return out[-limit:]

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        with self._lock:
            req = self._pending.get(request_id)
        if req is not None:
            return req
        return next((r for r in self._history if r.request_id == request_id), None)

    # ----------------- 订阅 -----------------

    def on_decided(self, callback: Callable[[ApprovalRequest], None]) -> None:
        self._on_decided.append(callback)

    # ----------------- 内部 -----------------

    def _record_history(self, req: ApprovalRequest) -> None:
        with self._lock:
            self._history.append(req)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

    def _publish_event(self, event_type: str, req: ApprovalRequest) -> None:
        if not self._observability:
            return
        try:
            self._observability.publish_event(
                event_type,
                source="hitl",
                payload={
                    "request_id": req.request_id,
                    "hook_point": req.hook_point,
                    "status": req.status.value,
                    "requested_by": req.requested_by,
                    "decided_by": req.decided_by,
                    "description": req.description,
                },
            )
        except Exception as e:
            logger.warning(f"HITL publish event error: {e}")

    # ----------------- 状态 -----------------

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            n_pending = len(self._pending)
            n_history = len(self._history)
        return {
            "default_policy": self._default_policy.value,
            "hook_policies": {k: v.value for k, v in self._hook_policies.items()},
            "pending_count": n_pending,
            "history_count": n_history,
            "total_decided": n_history,
        }


# ============================================================
# 全局单例
# ============================================================

_hitl_guard: Optional[HumanInLoopGuard] = None


def get_hitl_guard() -> HumanInLoopGuard:
    """获取全局 HITL Guard 单例"""
    global _hitl_guard
    if _hitl_guard is None:
        _hitl_guard = HumanInLoopGuard(default_policy=HITLPolicy.AUTO)
    return _hitl_guard


def reset_hitl_guard() -> None:
    """重置（测试用）"""
    global _hitl_guard
    _hitl_guard = None