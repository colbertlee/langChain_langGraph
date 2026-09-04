"""
v2.0 slim 记忆存储（双类：ShortTermContext + LongTermKnowledge）

设计：
- ShortTermContext  → 复用 context_db.ContextManager + LangGraph SqliteSaver checkpoint
- LongTermKnowledge → 复用 rag.RAGIndex（Chroma）
- 旧 4 类型（WORKING / EPISODIC / SEMANTIC / PROCEDURAL）的 EPISODIC/PROCEDURAL 存储
  通过迁移脚本合入 ShortTerm/LongTerm（见 scripts/migrate_memory_v1_to_v2.py）
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ShortTermContext:
    """短期上下文：当前会话消息 + tool_calls + checkpoint。

    后端：context_db.ContextManager + LangGraph SqliteSaver
    """

    thread_id: str
    db_path: str = "memory.db"

    _conn: Optional[sqlite3.Connection] = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def _ensure(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS short_term_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    meta TEXT DEFAULT '{}',
                    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_stc_thread ON short_term_context(thread_id, ts)"
            )
            self._conn.commit()
        return self._conn

    def append(self, role: str, content: str, **meta) -> None:
        with self._lock:
            conn = self._ensure()
            conn.execute(
                "INSERT INTO short_term_context(thread_id, role, content, meta) VALUES (?, ?, ?, ?)",
                (self.thread_id, role, content, _to_json(meta)),
            )
            conn.commit()

    def load(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._ensure()
            cur = conn.execute(
                "SELECT role, content, meta, ts FROM short_term_context "
                "WHERE thread_id=? ORDER BY ts DESC LIMIT ?",
                (self.thread_id, limit),
            )
            return [
                {"role": r, "content": c, "meta": _from_json(m), "ts": ts}
                for r, c, m, ts in cur.fetchall()
            ][::-1]

    def truncate(self, keep_last: int = 20) -> int:
        with self._lock:
            conn = self._ensure()
            cur = conn.execute(
                "SELECT id FROM short_term_context WHERE thread_id=? ORDER BY ts DESC LIMIT -1 OFFSET ?",
                (self.thread_id, keep_last),
            )
            ids = [r[0] for r in cur.fetchall()]
            if ids:
                conn.execute(
                    f"DELETE FROM short_term_context WHERE id IN ({','.join('?'*len(ids))})",
                    ids,
                )
                conn.commit()
            return len(ids)


@dataclass(slots=True)
class LongTermKnowledge:
    """长期知识：跨会话 RAG（事实 / 用户偏好 / skill 文档）。

    后端：rag.RAGIndex（Chroma 向量库）
    """

    user_id: str
    rag: Any = None  # rag.RAGIndex 实例（由外部注入）

    def upsert(self, doc_id: str, text: str, *, kind: str = "fact") -> None:
        if self.rag is None:
            logger.warning("LongTermKnowledge.rag 未注入，upsert 跳过: doc_id=%s", doc_id)
            return
        # 复用 rag.RAGIndex 的接口（load_documents 接受文件路径时是写库；
        # 单条文本插入走 add_texts 或自定义接口，下面用通用 fallback）
        if hasattr(self.rag, "add_text"):
            self.rag.add_text(doc_id=doc_id, text=text, metadata={"kind": kind, "user_id": self.user_id})
        elif hasattr(self.rag, "add_texts"):
            self.rag.add_texts([text], ids=[doc_id], metadatas=[{"kind": kind, "user_id": self.user_id}])
        else:
            # 兼容性兜底：写入临时文件再 load_documents
            import tempfile, os
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
                f.write(text)
                tmp = f.name
            try:
                self.rag.load_documents([tmp])
            finally:
                os.unlink(tmp)

    def query(self, q: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if self.rag is None:
            return []
        if hasattr(self.rag, "query"):
            result = self.rag.query(q, top_k=top_k)
            if isinstance(result, list):
                return result
            if isinstance(result, str):
                return [{"text": result}]
        return []

    def forget(self, doc_id: str) -> bool:
        if self.rag is None:
            return False
        if hasattr(self.rag, "delete"):
            try:
                self.rag.delete(doc_id)
                return True
            except Exception:
                return False
        return False


class MemoryStore:
    """v2.0 唯一对外记忆入口。

    使用：
        ms = MemoryStore(thread_id="abc", user_id="u1", rag=rag_index)
        ms.short.append("user", "你好")
        ms.long.query("...")
    """

    def __init__(
        self,
        *,
        thread_id: str,
        user_id: str,
        rag: Any = None,
        short_db_path: str = "memory.db",
    ):
        self.short = ShortTermContext(thread_id=thread_id, db_path=short_db_path)
        self.long = LongTermKnowledge(user_id=user_id, rag=rag)

    def get(self, kind: str):
        """兼容旧 API：仅允许 'short' / 'long'；其它类型抛 NotImplementedError。"""
        if kind in ("short", "long"):
            return getattr(self, kind)
        raise NotImplementedError(f"memory.{kind}: Frozen in v2.0 slim")

    def as_node(self):
        """注册为 LangGraph 节点（最小实现）。"""
        from langgraph.graph import StateGraph

        def _memory_node(state: dict) -> dict:
            # 仅做心跳回写，不修改 messages
            return state

        return _memory_node


# ============================================================
# helpers
# ============================================================

def _to_json(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


def _from_json(s: str) -> Any:
    import json
    try:
        return json.loads(s)
    except Exception:
        return {}


# 模块级单例
_DEFAULT_MS: Optional[MemoryStore] = None


def get_memory_store_v2(
    *,
    thread_id: Optional[str] = None,
    user_id: str = "default",
    rag: Any = None,
) -> MemoryStore:
    global _DEFAULT_MS
    if _DEFAULT_MS is None:
        import uuid
        _DEFAULT_MS = MemoryStore(
            thread_id=thread_id or str(uuid.uuid4()),
            user_id=user_id,
            rag=rag,
        )
    return _DEFAULT_MS


def reset_memory_store_v2() -> None:
    global _DEFAULT_MS
    _DEFAULT_MS = None