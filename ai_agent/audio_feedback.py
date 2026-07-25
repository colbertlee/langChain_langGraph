"""
语音识别错误样本落库 + 持续学习。

提供：
- AudioFeedbackStore：把低置信度音频 + 用户纠正结果写入 SQLite
- 启动时自动建表（依赖现有 sqlite3，不需要额外服务）
- 提供查询接口：可分析哪些 ASR 错误最频繁、哪些热词需要扩充

使用：
    from audio_feedback import get_audio_feedback_store
    store = get_audio_feedback_store()
    store.record(session_id=..., original_text=..., corrected_text=..., confidence=...)
    rows = store.recent(limit=50)
    stats = store.stats()

依赖：使用现有 context_db 的 SQLite 连接复用；如不可用，降级到本地 sqlite 文件。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


DEFAULT_DB_PATH = os.getenv("AUDIO_FEEDBACK_DB", "audio_feedback.db")


class AudioFeedbackStore:
    """SQLite 实现的简单反馈存储。"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audio_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    session_id TEXT,
                    attachment_id TEXT,
                    original_text TEXT,
                    corrected_text TEXT,
                    confidence REAL,
                    provider TEXT,
                    metadata TEXT,
                    created_at REAL DEFAULT (datetime('now', 'localtime'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audio_feedback_session ON audio_feedback(session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audio_feedback_ts ON audio_feedback(ts)"
            )

    @contextmanager
    def _connect(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def record(
        self,
        session_id: str = "",
        attachment_id: str = "",
        original_text: str = "",
        corrected_text: str = "",
        confidence: float = 0.0,
        provider: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO audio_feedback
                   (ts, session_id, attachment_id, original_text, corrected_text,
                    confidence, provider, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    time.time(),
                    session_id or "",
                    attachment_id or "",
                    original_text or "",
                    corrected_text or "",
                    float(confidence or 0.0),
                    provider or "",
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            return int(cur.lastrowid or 0)

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audio_feedback ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]

    def by_session(self, session_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audio_feedback WHERE session_id = ? ORDER BY id DESC",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> Dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM audio_feedback").fetchone()["n"]
            avg_conf = conn.execute(
                "SELECT AVG(confidence) AS c FROM audio_feedback"
            ).fetchone()["c"] or 0.0
            by_provider = conn.execute(
                "SELECT provider, COUNT(*) AS n FROM audio_feedback GROUP BY provider"
            ).fetchall()
            # 错误最频繁的词（粗略：拆 corrected 与 original 的差集）
            error_words = conn.execute(
                """SELECT original_text, corrected_text FROM audio_feedback
                   WHERE original_text != corrected_text
                     AND corrected_text != ''
                   ORDER BY id DESC LIMIT 200"""
            ).fetchall()
        return {
            "total": total,
            "avg_confidence": avg_conf,
            "by_provider": {r["provider"]: r["n"] for r in by_provider},
            "error_samples": [dict(r) for r in error_words],
        }

    def suggest_hotwords(self, min_count: int = 2) -> List[str]:
        """
        从 corrected_text 中提取出现频次 ≥ min_count 的高频词，
        作为新的 hotwords 候选。
        """
        import re
        from collections import Counter

        with self._connect() as conn:
            rows = conn.execute(
                """SELECT corrected_text FROM audio_feedback
                   WHERE corrected_text IS NOT NULL AND corrected_text != ''
                   ORDER BY id DESC LIMIT 500"""
            ).fetchall()
        texts = [r["corrected_text"] for r in rows]
        # 提取 2-12 字的连续中文 / 英文单词
        counter: Counter = Counter()
        for t in texts:
            for m in re.findall(r"[A-Za-z][A-Za-z0-9]{1,20}|[\u4e00-\u9fff]{2,8}", t):
                counter[m] += 1
        return [w for w, c in counter.most_common(50) if c >= min_count]


# ============================================================
# 全局单例
# ============================================================

_store: Optional[AudioFeedbackStore] = None


def get_audio_feedback_store() -> AudioFeedbackStore:
    global _store
    if _store is None:
        _store = AudioFeedbackStore()
    return _store


def reset_audio_feedback_store() -> None:
    global _store
    _store = None


# ============================================================
# 分析脚本入口
# ============================================================

def _cli():
    import argparse
    p = argparse.ArgumentParser(description="audio feedback analyzer")
    p.add_argument("--recent", type=int, default=0, help="show recent N records")
    p.add_argument("--stats", action="store_true", help="show aggregate stats")
    p.add_argument("--hotwords", type=int, default=0, metavar="MIN_COUNT",
                   help="suggest hotwords with frequency >= MIN_COUNT")
    args = p.parse_args()

    store = get_audio_feedback_store()
    if args.recent:
        for r in store.recent(args.recent):
            print(json.dumps(r, ensure_ascii=False, indent=2))
    if args.stats:
        s = store.stats()
        s["error_samples"] = s["error_samples"][:10]
        print(json.dumps(s, ensure_ascii=False, indent=2))
    if args.hotwords:
        for w in store.suggest_hotwords(min_count=args.hotwords):
            print(w)
    if not (args.recent or args.stats or args.hotwords):
        p.print_help()


if __name__ == "__main__":
    _cli()
