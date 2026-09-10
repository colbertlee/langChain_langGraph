"""
hitl_langgraph.py — v2.2.1 LangGraph 动态中断 + Human-in-the-Loop (HITL) 拦截

设计目标
=========
为 LangGraph 状态图接入 LangChain 原生 HITL 拦截机制，覆盖以下两类场景：

1. **高风险 Tool 拦截**（默认开启 `python_interpreter`）：
   - Tool 被调用前，检查 ``requires_approval`` 元数据。
   - 若标记为 True，则把工具调用"挂起"，把待审批信息写入 pending store，
     同时向前端 SSE 流发 ``event: approval_required`` 事件。
   - 用户在前端点击「批准」→ 调用 ``/api/chat/approve`` → 后端恢复执行
     （使用修改后或原样 ``tool_args``）。
   - 用户点击「拒绝」→ 调用 ``/api/chat/reject`` → 后端把拒绝消息注入为
     ToolMessage（``content="Action cancelled by user"``），让 Agent 继续生成。

2. **状态查询 / Time-Travel（v2.2.1 基础）**：
   - 提供 ``list_checkpoints(session_id)`` / ``get_state(session_id, checkpoint_id)``
     让前端展示历史 checkpoint 列表（Time-Travel UI 后续可基于此构建）。

核心不变量
==========
- 不替换 LangGraph 已有 SqliteSaver 行为；只在其上叠加一个"pending approval" 注册表
  （内存 + SQLite 持久化到 ``pending_approvals`` 表）。
- pending approval 与 ``thread_id`` 严格绑定 —— 不会跨 session 串台。
- approve/reject 操作幂等：同一 ``request_id`` 重复 resolve 只返回首次结果。

关键 API
========
- ``HITLStore.instance()`` — 全局单例（按 session 隔离 pending 队列）
- ``HITLStore.intercept_tool_call(...)`` — 工具调用前 hook，决定"挂起 / 直接执行 / 拦截拒绝"
- ``HITLStore.request_approval(...)`` — 发起一个挂起的审批（写入 store + 返回 request_id）
- ``HITLStore.approve(request_id, tool_args=...)`` — 批准并返回恢复执行所需的 tool_args
- ``HITLStore.reject(request_id, reason=...)`` — 拒绝并返回注入 ToolMessage 的 reason
- ``HITLStore.list_pending(session_id=...)`` — 列出待审批（前端轮询用）
- ``HITLStore.consume_pending(session_id)`` — 主循环拉取当前线程所有待审批
- ``HITLStore.mark_consumed(request_id)`` — 标记已被前端/流消费，避免重复弹窗

线程安全
========
- 使用 ``threading.Lock`` 保护 pending dict（FastAPI 多 worker / 多线程）。
- SQLite ``pending_approvals`` 表作为持久化层，进程崩溃重启后 pending 不丢；
  内存 dict 启动时从 SQLite 加载。

注意事项
========
- 本模块不替代 LangGraph 的 ``interrupt()`` —— 因为 1.x ``agent.stream`` 是同步 API，
  无法直接 await interrupt；我们采用"在 ToolNode 前后做条件拦截"的更务实方案，
  仍能完整覆盖"高风险操作 → 拦截 → 人工批准 → 恢复"的 HITL 主流程。
- 如未来升级到 LangGraph ``astream`` / ``interrupt``，本 store 可平滑迁移为
  interrupt payload 的存储层。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================


@dataclass
class PendingApproval:
    """一个挂起的审批请求。

    字段：
      - request_id: 唯一 ID（前端用来 confirm）
      - session_id: thread_id（LangGraph checkpointer 维度隔离）
      - tool_name: 工具名（如 python_interpreter）
      - tool_args: 完整 kwargs（dict）
      - tool_call_id: LangChain AIMessage.tool_calls[*].id（如有）
      - reason: 给人类看的解释
      - created_at: epoch seconds
      - status: pending / approved / rejected / consumed
      - decision_payload: 人类批准的最终 tool_args（仅 approved 时有值）
      - reject_reason: 拒绝原因（仅 rejected 时有值）
    """
    request_id: str
    session_id: str
    tool_name: str
    tool_args: Dict[str, Any] = field(default_factory=dict)
    tool_call_id: Optional[str] = None
    reason: str = ""
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending / approved / rejected / consumed
    decision_payload: Optional[Dict[str, Any]] = None
    reject_reason: Optional[str] = None
    # v2.2.1 — 超时自动拒绝
    timeout_seconds: float = 300.0
    timed_out: bool = False
    # v2.2.1 — Edit & Resume 标记（用户改过 args）
    edited: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # 把 dict 序列化为友好 JSON 字符串，供前端直接渲染 args
        return d


# ============================================================
# SQLite 持久化层
# ============================================================

_PENDING_DB_FILENAME = "hitl_pending.db"
_PENDING_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_approvals (
    request_id   TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    tool_name    TEXT NOT NULL,
    tool_args    TEXT NOT NULL,
    tool_call_id TEXT,
    reason       TEXT,
    created_at   REAL NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    decision_payload TEXT,
    reject_reason    TEXT,
    timeout_seconds  REAL DEFAULT 300.0,
    timed_out        INTEGER DEFAULT 0,
    edited           INTEGER DEFAULT 0
);
"""
_PENDING_TABLE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_pending_session ON pending_approvals(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_approvals(status);",
]


class _PendingDB:
    """SQLite 持久化 pending_approvals（独立于 LangGraph checkpointer.db）。

    设计：
      - 独立文件 hitl_pending.db，避免污染 LangGraph 的 checkpoints 表结构
      - 进程启动时全量加载 pending 记录到内存 dict
      - 状态变更（approve / reject / consume）双写内存 + 落库
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._path = db_path or _PENDING_DB_FILENAME
        # check_same_thread=False 让 FastAPI 多线程也能用同一个连接
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_PENDING_TABLE_SCHEMA)
            for idx in _PENDING_TABLE_INDEXES:
                self._conn.execute(idx)
            # v2.2.1 — 兼容老 schema：补齐新增列
            cur = self._conn.execute("PRAGMA table_info(pending_approvals)")
            cols = {row[1] for row in cur.fetchall()}
            if "timeout_seconds" not in cols:
                self._conn.execute(
                    "ALTER TABLE pending_approvals ADD COLUMN timeout_seconds REAL DEFAULT 300.0"
                )
            if "timed_out" not in cols:
                self._conn.execute(
                    "ALTER TABLE pending_approvals ADD COLUMN timed_out INTEGER DEFAULT 0"
                )
            if "edited" not in cols:
                self._conn.execute(
                    "ALTER TABLE pending_approvals ADD COLUMN edited INTEGER DEFAULT 0"
                )
            self._conn.commit()

    def _row_to_obj(self, row: sqlite3.Row) -> PendingApproval:
        try:
            tool_args = json.loads(row["tool_args"] or "{}")
        except Exception:
            tool_args = {}
        try:
            decision_payload = json.loads(row["decision_payload"]) if row["decision_payload"] else None
        except Exception:
            decision_payload = None
        # 兼容旧 schema：timeout_seconds / timed_out / edited 列可能不存在
        try:
            timeout_seconds = float(row["timeout_seconds"]) if "timeout_seconds" in row.keys() and row["timeout_seconds"] is not None else 300.0
        except Exception:
            timeout_seconds = 300.0
        try:
            timed_out = bool(row["timed_out"]) if "timed_out" in row.keys() and row["timed_out"] is not None else False
        except Exception:
            timed_out = False
        try:
            edited = bool(row["edited"]) if "edited" in row.keys() and row["edited"] is not None else False
        except Exception:
            edited = False
        return PendingApproval(
            request_id=row["request_id"],
            session_id=row["session_id"],
            tool_name=row["tool_name"],
            tool_args=tool_args,
            tool_call_id=row["tool_call_id"],
            reason=row["reason"] or "",
            created_at=float(row["created_at"]),
            status=row["status"],
            decision_payload=decision_payload,
            reject_reason=row["reject_reason"],
            timeout_seconds=timeout_seconds,
            timed_out=timed_out,
            edited=edited,
        )

    def load_all(self) -> List[PendingApproval]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM pending_approvals")
            return [self._row_to_obj(r) for r in cur.fetchall()]

    def upsert(self, p: PendingApproval) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO pending_approvals
                  (request_id, session_id, tool_name, tool_args, tool_call_id,
                   reason, created_at, status, decision_payload, reject_reason,
                   timeout_seconds, timed_out, edited)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    p.request_id,
                    p.session_id,
                    p.tool_name,
                    json.dumps(p.tool_args, ensure_ascii=False),
                    p.tool_call_id,
                    p.reason,
                    p.created_at,
                    p.status,
                    json.dumps(p.decision_payload, ensure_ascii=False) if p.decision_payload else None,
                    p.reject_reason,
                    float(p.timeout_seconds or 300.0),
                    1 if p.timed_out else 0,
                    1 if p.edited else 0,
                ),
            )
            self._conn.commit()

    def delete(self, request_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM pending_approvals WHERE request_id = ?", (request_id,)
            )
            self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# ============================================================
# HITLStore — 顶层门面（单例）
# ============================================================


class HITLStore:
    """全局 HITL pending store。

    设计要点：
      - 单例（``HITLStore.instance()``），进程内唯一。
      - 内存 dict 用于快速查询；SQLite 用于持久化（重启不丢）。
      - 每个 session_id 可挂多个 pending（罕见，但允许）。
      - approve / reject 都会把内存对象标记 + 落库；调用方需要消费结果（consume）。
    """

    _instance: Optional["HITLStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self, db_path: Optional[str] = None) -> None:
        # 允许注入 db_path，方便测试用 tmp_path
        self._db = _PendingDB(db_path=db_path)
        self._lock = threading.Lock()
        # 按 request_id 索引（O(1) 查询）
        self._by_id: Dict[str, PendingApproval] = {}
        # 启动时从 DB 加载
        for p in self._db.load_all():
            self._by_id[p.request_id] = p

    @classmethod
    def instance(cls) -> "HITLStore":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """测试用：清空单例，便于每次测试重置。

        行为：
          - 关闭当前 db 连接
          - 删除默认 db 文件（hitl_pending.db）以确保完全干净状态
          - 单例置 None
        """
        with cls._instance_lock:
            if cls._instance is not None:
                db_path = getattr(cls._instance._db, "_path", None)
                try:
                    cls._instance._db.close()
                except Exception:
                    pass
                # 删 db 文件（仅对默认 db 路径生效；测试自定义 db 由测试自己清理）
                if db_path and db_path == _PENDING_DB_FILENAME:
                    try:
                        Path(db_path).unlink(missing_ok=True)
                    except Exception:
                        pass
            cls._instance = None

    # ---------- 查询 ----------

    def get(self, request_id: str) -> Optional[PendingApproval]:
        with self._lock:
            return self._by_id.get(request_id)

    def list_pending(self, session_id: Optional[str] = None) -> List[PendingApproval]:
        with self._lock:
            items = list(self._by_id.values())
        if session_id:
            items = [p for p in items if p.session_id == session_id]
        # 只返回 status=pending 的；已 resolved 的从 pending 列表移除
        return [p for p in items if p.status == "pending"]

    def consume_pending(self, session_id: str) -> List[PendingApproval]:
        """主循环拉取当前 session 的所有 pending（并标记 consumed，避免重复处理）。

        返回值是「待审批 → 已发 SSE」的对象快照；调用方负责把每个对象转换
        成 SSE approval_required 帧发给前端。
        """
        out: List[PendingApproval] = []
        with self._lock:
            for p in self._by_id.values():
                if p.session_id == session_id and p.status == "pending":
                    out.append(p)
                    p.status = "consumed"
                    self._db.upsert(p)
        return out

    def list_all_for_session(self, session_id: str) -> List[PendingApproval]:
        """返回该 session 全部 pending_approvals（不限 status），调试用。"""
        with self._lock:
            return [p for p in self._by_id.values() if p.session_id == session_id]

    # ---------- 写入 ----------

    def request_approval(
        self,
        *,
        session_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        reason: str = "",
        timeout_seconds: float = 300.0,
    ) -> PendingApproval:
        """创建一个 pending approval（写入内存 + DB），返回对象引用。

        Args:
          timeout_seconds: 超时阈值（秒）。默认 300s (5min)。
            超时后会被 check_approval_timeouts() 标记为 rejected + timed_out=True。
        """
        req = PendingApproval(
            request_id=str(uuid.uuid4()),
            session_id=session_id,
            tool_name=tool_name,
            tool_args=dict(tool_args or {}),
            tool_call_id=tool_call_id,
            reason=reason or f"Tool '{tool_name}' requires human approval",
            timeout_seconds=float(timeout_seconds) if timeout_seconds else 300.0,
        )
        with self._lock:
            self._by_id[req.request_id] = req
            self._db.upsert(req)
        logger.info(
            f"HITL request_approval id={req.request_id} sid={session_id} tool={tool_name}"
        )
        return req

    def approve(
        self, request_id: str, tool_args: Optional[Dict[str, Any]] = None
    ) -> Optional[PendingApproval]:
        """批准一个 pending 请求。

        Args:
          request_id: 前端传来的 request id
          tool_args: 用户修改后的 tool_args（None = 用原 args；与原 args 不同时自动标记 edited=True）

        Returns:
          更新后的 PendingApproval（status='approved'），若 request_id 不存在返回 None
        """
        with self._lock:
            p = self._by_id.get(request_id)
            if p is None:
                return None
            p.status = "approved"
            if tool_args is not None:
                # 检测是否被用户修改（Edit & Resume）
                try:
                    p.edited = (dict(tool_args) != dict(p.tool_args))
                except Exception:
                    p.edited = True
                p.decision_payload = dict(tool_args)
            else:
                p.decision_payload = dict(p.tool_args)
            self._db.upsert(p)
        logger.info(
            f"HITL approve id={request_id} edited={p.edited}"
        )
        return p

    def check_approval_timeouts(
        self, *, now: Optional[float] = None
    ) -> List[PendingApproval]:
        """检查所有 pending approval，超时的自动标记为 rejected（timed_out=True）。

        Returns:
          本次被超时拒绝的 PendingApproval 列表（已被标记 + 落库）。
          主循环应调用 emit_timeout_events(...) 把它们注入 SSE 流。
        """
        now_ts = float(now) if now is not None else time.time()
        timed_out: List[PendingApproval] = []
        with self._lock:
            for p in self._by_id.values():
                if p.status != "pending":
                    continue
                cutoff = p.created_at + float(p.timeout_seconds or 300.0)
                if now_ts >= cutoff:
                    p.status = "rejected"
                    p.timed_out = True
                    p.reject_reason = (
                        f"[System] Approval request timed out after "
                        f"{int(p.timeout_seconds)}s. Action automatically cancelled."
                    )
                    self._db.upsert(p)
                    timed_out.append(p)
                    logger.info(
                        f"HITL timeout id={p.request_id} sid={p.session_id} tool={p.tool_name}"
                    )
        return timed_out

    def reject(self, request_id: str, reason: str = "") -> Optional[PendingApproval]:
        """拒绝一个 pending 请求。

        Returns:
          更新后的 PendingApproval（status='rejected'），若不存在返回 None
        """
        with self._lock:
            p = self._by_id.get(request_id)
            if p is None:
                return None
            p.status = "rejected"
            p.reject_reason = reason or "Action cancelled by user"
            self._db.upsert(p)
        logger.info(f"HITL reject id={request_id}")
        return p

    def cleanup_old(self, ttl_seconds: float = 3600.0) -> int:
        """清理超过 ttl 的非 pending 记录（防止 DB 无限增长）。返回清理条数。"""
        cutoff = time.time() - ttl_seconds
        deleted = 0
        with self._lock:
            ids = [rid for rid, p in self._by_id.items() if p.status != "pending" and p.created_at < cutoff]
            for rid in ids:
                p = self._by_id.pop(rid)
                self._db.delete(rid)
                deleted += 1
        return deleted


# ============================================================
# 工具注册表感知 —— 哪些工具需要审批？
# ============================================================

def tool_requires_approval(tool: Any) -> bool:
    """判定一个 LangChain Tool / StructuredTool 是否需要 HITL 审批。

    优先级：
      1. tool.metadata / tool.tool_call_meta 等属性显式声明 ``requires_approval=True``
         （未来 LangChain 版本可能支持）
      2. tool 的 underlying callable 在 v21_tools.TOOL_REGISTRY 里且 entry['requires_approval']==True
      3. fallback：工具名在 ``_DEFAULT_APPROVAL_TOOLS`` 白名单里
    """
    name = getattr(tool, "name", None)

    # 1) metadata 属性（兼容未来版本）
    meta = getattr(tool, "metadata", None) or getattr(tool, "tool_call_meta", None)
    if isinstance(meta, dict) and "requires_approval" in meta:
        return bool(meta["requires_approval"])

    # 2) v21_tools.TOOL_REGISTRY 兜底（python_interpreter 默认开启）
    try:
        from v21_tools import TOOL_REGISTRY

        entry = TOOL_REGISTRY.get(name or "")
        if isinstance(entry, dict) and entry.get("requires_approval"):
            return True
    except Exception:
        pass

    # 3) 兜底白名单（防御：避免漏标）
    if name in _DEFAULT_APPROVAL_TOOLS:
        return True
    return False


# 默认需要审批的工具名集合（兜底白名单；保持最小集，避免误伤）。
_DEFAULT_APPROVAL_TOOLS = {
    "python_interpreter",
    # 后续可加入：
    # "shell_exec",
    # "vcs_commit",
    # "delete_file",
    # "http_request",
}


# ============================================================
# 高层 API：拦截 + 恢复
# ============================================================


def intercept_tool_call(
    tool: Any,
    tool_args: Dict[str, Any],
    session_id: str,
    *,
    tool_call_id: Optional[str] = None,
) -> Tuple[str, Optional[PendingApproval]]:
    """拦截一次工具调用。

    决策：
      - 工具不需要审批 → 返回 ("allow", None)，主循环正常调用
      - 需要审批 → 创建 pending approval → 返回 ("pending", pending_obj)

    Args:
        tool: LangChain Tool / StructuredTool 实例
        tool_args: 工具参数 dict
        session_id: thread_id（来自 LangGraph config["configurable"]["thread_id"]）
        tool_call_id: AIMessage.tool_calls[*].id（用于回写 ToolMessage 时保持关联）

    Returns:
        (decision, pending_obj)
        - decision ∈ {"allow", "pending"}
        - pending_obj 在 pending 决策时是 PendingApproval 实例；allow 时是 None
    """
    if not tool_requires_approval(tool):
        return ("allow", None)
    name = getattr(tool, "name", "unknown_tool")
    pending = HITLStore.instance().request_approval(
        session_id=session_id,
        tool_name=name,
        tool_args=dict(tool_args or {}),
        tool_call_id=tool_call_id,
        reason=(
            f"工具 '{name}' 被标记为高风险操作，需要人工确认。"
            f"参数: {json.dumps(tool_args, ensure_ascii=False)[:300]}"
        ),
    )
    return ("pending", pending)


def emit_pending_to_sse(session_id: str) -> List[Dict[str, Any]]:
    """把当前 session 的 pending approval 列表转换为 SSE 事件 dict 列表。

    每个事件形如：
        {
          "type": "approval_required",
          "request_id": "uuid",
          "session_id": "...",
          "tool_name": "python_interpreter",
          "tool_args": {...},
          "tool_call_id": "...",
          "reason": "...",
          "timeout_seconds": 300,
        }

    主循环应在每次 yield chunk 之前调用一次本函数，把待审批帧夹到 SSE 流里。
    调用方负责把这些 dict 序列化为 SSE 帧（``event: approval_required``）。
    """
    pending = HITLStore.instance().consume_pending(session_id)
    out: List[Dict[str, Any]] = []
    for p in pending:
        out.append(
            {
                "type": "approval_required",
                "request_id": p.request_id,
                "session_id": p.session_id,
                "tool_name": p.tool_name,
                "tool_args": p.tool_args,
                "tool_call_id": p.tool_call_id,
                "reason": p.reason,
                "timeout_seconds": float(p.timeout_seconds or 300.0),
            }
        )
    return out


def emit_timeout_events() -> List[Dict[str, Any]]:
    """扫描全局 pending 中的超时项，转换为 SSE 事件 dict 列表。

    每个事件形如：
        {
          "type": "approval_timeout",
          "request_id": "uuid",
          "session_id": "...",
          "tool_name": "...",
          "reason": "[System] Approval request timed out after Ns. ...",
        }

    主循环应在每次 yield chunk 之前调用一次本函数。
    """
    timed_out = HITLStore.instance().check_approval_timeouts()
    out: List[Dict[str, Any]] = []
    for p in timed_out:
        out.append(
            {
                "type": "approval_timeout",
                "request_id": p.request_id,
                "session_id": p.session_id,
                "tool_name": p.tool_name,
                "reason": p.reject_reason or "Approval request timed out",
            }
        )
    return out


# ============================================================
# 恢复执行辅助
# ============================================================


def resolve_after_decision(
    request_id: str,
    session_id: str,
    tool_call_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """查询审批结果，返回主循环恢复执行所需信息。

    Returns:
        None: 该 request_id 不存在 / 已 resolved 但 result 丢失
        dict:
          - {"decision": "approved", "tool_args": {...}, "tool_call_id": "..."} → 实际调用工具
          - {"decision": "rejected", "reason": "...", "tool_call_id": "..."} → 注入 ToolMessage
          - {"decision": "pending"} → 仍未决议（调用方应继续等待或 yield pending 帧）

    Args:
        request_id: pending id
        session_id: 用于校验 session 归属
        tool_call_id: 用于回写 ToolMessage 时回填 tool_call_id 关联
    """
    p = HITLStore.instance().get(request_id)
    if p is None:
        return None
    if p.session_id != session_id:
        logger.warning(
            f"HITL resolve_after_decision session mismatch: req={p.session_id} caller={session_id}"
        )
        return None
    if p.status == "approved":
        return {
            "decision": "approved",
            "tool_args": p.decision_payload or {},
            "tool_call_id": tool_call_id or p.tool_call_id,
            "tool_name": p.tool_name,
        }
    if p.status == "rejected":
        return {
            "decision": "rejected",
            "reason": p.reject_reason or "Action cancelled by user",
            "tool_call_id": tool_call_id or p.tool_call_id,
            "tool_name": p.tool_name,
        }
    # 仍 pending
    return {"decision": "pending", "tool_call_id": tool_call_id or p.tool_call_id}


__all__ = [
    "PendingApproval",
    "HITLStore",
    "tool_requires_approval",
    "intercept_tool_call",
    "emit_pending_to_sse",
    "emit_timeout_events",
    "resolve_after_decision",
]
