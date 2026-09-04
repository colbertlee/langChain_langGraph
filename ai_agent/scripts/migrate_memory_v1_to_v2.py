"""
v1.0 记忆数据 → v2.0 slim 迁移脚本

输入：v1.0 memory_store.db（表：memories / semantic_memory / memory_relations）
输出：
  - context_v2.db（ShortTermContext 表：thread_id, role, content, meta, ts）
  - chroma_v2/ 目录（LongTermKnowledge 向量，存于 knowledge_base collection）

设计原则：
- 不破坏现有 RAGModule.load_documents 接口（它只接受 file_paths，每次覆盖 vectorstore）
- 兼容 v1 表结构：memories.memory_type ∈ {working, episodic, semantic, procedural}
  + semantic_memory.content_hash（事实指纹）
- 备份：迁移前自动备份 src → src.bak-<timestamp>
- dry-run：不写盘，只统计

执行：
  python scripts/migrate_memory_v1_to_v2.py --src data/memory_store.db --dry-run
  python scripts/migrate_memory_v1_to_v2.py --src data/memory_store.db \\
      --ctx-out data/context_v2.db --chroma-out data/chroma_v2
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate_memory")


def _ensure_src(src: Path) -> sqlite3.Connection:
    if not src.exists():
        raise FileNotFoundError(f"v1 db 不存在: {src}")
    return sqlite3.connect(str(src))


def _init_ctx(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS short_term_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            meta TEXT DEFAULT '{}',
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_stc_thread ON short_term_context(thread_id, ts)"
    )
    conn.commit()
    return conn


def migrate_short_term(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    """v1 working/episodic 行 → v2 ShortTermContext 表。"""
    rows = src.execute("""
        SELECT memory_type, session_id, content, importance, intent, created_at
        FROM memories
        WHERE memory_type IN ('working', 'episodic')
        ORDER BY created_at ASC
    """).fetchall()

    inserted = 0
    for mtype, session_id, content, importance, intent, created_at in rows:
        meta = json.dumps({
            "src_type": mtype,
            "importance": importance,
            "intent": intent,
        })
        dst.execute(
            "INSERT INTO short_term_context(thread_id, role, content, meta, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, "message", content, meta, created_at),
        )
        inserted += 1
    dst.commit()
    return inserted


def migrate_long_term(src: sqlite3.Connection, chroma_out: Path,
                      rag_module: str = "rag") -> int:
    """v1 semantic/procedural 行 → Chroma。"""
    import os as _os
    _ai_agent_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    if _ai_agent_dir not in sys.path:
        sys.path.insert(0, _ai_agent_dir)
    try:
        rag_pkg = __import__(rag_module, fromlist=["RAGModule"])
    except ImportError as e:
        logger.warning("无法导入 %s 模块：%s（跳过 long_term 迁移）", rag_module, e)
        return 0
    RAGModule = getattr(rag_pkg, "RAGModule", None)
    if RAGModule is None:
        logger.error("rag.RAGModule 不存在，跳过 long_term 迁移")
        return 0

    chroma_out.mkdir(parents=True, exist_ok=True)
    try:
        rag = RAGModule(model=None, api_key=None, embedding_model_type="openai")
    except Exception as e:
        logger.warning("RAGModule 初始化失败：%s（跳过 long_term 迁移）", e)
        return 0

    tmpdir = Path(tempfile.mkdtemp(prefix="v1_migrate_"))
    try:
        file_paths: list[str] = []

        sem_rows = src.execute("""
            SELECT memory_id, content_hash, summary
            FROM semantic_memory
        """).fetchall()

        for memory_id, content_hash, summary in sem_rows:
            mem_row = src.execute(
                "SELECT content, intent, session_id FROM memories WHERE id=?",
                (memory_id,),
            ).fetchone()
            if not mem_row:
                continue
            content, intent, session_id = mem_row
            doc_text = summary or content or ""
            if not doc_text:
                continue
            doc_id = f"sem_{content_hash[:16]}"
            fp = tmpdir / f"{doc_id}.txt"
            fp.write_text(doc_text, encoding="utf-8")
            file_paths.append(str(fp))

        proc_rows = src.execute(
            "SELECT id, content, intent FROM memories WHERE memory_type='procedural'"
        ).fetchall()
        for mid, content, intent in proc_rows:
            if not content:
                continue
            doc_id = f"proc_{mid}"
            fp = tmpdir / f"{doc_id}.txt"
            fp.write_text(content, encoding="utf-8")
            file_paths.append(str(fp))

        if not file_paths:
            logger.warning("v1 db 中没有可迁移的 long-term 记忆")
            return 0

        try:
            ok = rag.load_documents(file_paths)
        except Exception as e:
            logger.warning("RAGModule.load_documents 失败（可能是 embedding API 不可用）：%s", e)
            return 0
        if not ok:
            logger.error("RAGModule.load_documents 返回 False")
            return 0
        return len(file_paths)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AIAgent v1 → v2 slim 记忆迁移")
    p.add_argument("--src", default="memory_store.db", help="v1 db 路径")
    p.add_argument("--ctx-out", default="context_v2.db", help="v2 ShortTermContext db 路径")
    p.add_argument("--chroma-out", default="chroma_v2", help="v2 Chroma 持久化目录")
    p.add_argument("--rag-module", default="rag", help="rag 模块名（默认 rag）")
    p.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = p.parse_args(list(argv) if argv is not None else None)

    src_path = Path(args.src)
    ctx_out = Path(args.ctx_out)
    chroma_out = Path(args.chroma_out)

    if not src_path.exists():
        logger.error("v1 db 不存在: %s", src_path)
        return 2

    src = _ensure_src(src_path)

    if args.dry_run:
        short_count = src.execute(
            "SELECT COUNT(*) FROM memories WHERE memory_type IN ('working','episodic')"
        ).fetchone()[0]
        long_count = src.execute(
            "SELECT COUNT(*) FROM semantic_memory"
        ).fetchone()[0] + src.execute(
            "SELECT COUNT(*) FROM memories WHERE memory_type='procedural'"
        ).fetchone()[0]
        logger.info("[DRY-RUN] 将迁移 short=%d long=%d", short_count, long_count)
        return 0

    ts = int(time.time())
    backup = src_path.with_suffix(src_path.suffix + f".bak-{ts}")
    shutil.copy2(src_path, backup)
    logger.info("已备份 v1 db → %s", backup)

    try:
        dst = _init_ctx(ctx_out)
        short_count = migrate_short_term(src, dst)
        dst.close()
        logger.info("ShortTermContext 迁移完成：%d 行", short_count)

        long_count = migrate_long_term(src, chroma_out, args.rag_module)
        logger.info("LongTermKnowledge 迁移完成：%d 个文档", long_count)

        logger.info("✅ 迁移完成。短记忆=%d / 长记忆=%d", short_count, long_count)
        logger.info("下一步：设置环境变量 AIAgent_LEGACY=false 启用 v2 slim")
        return 0
    except Exception as e:
        logger.exception("迁移失败: %s", e)
        return 1
    finally:
        src.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())