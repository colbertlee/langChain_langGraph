"""
v2.0 slim — v1 → v2 记忆迁移脚本测试

构造一个 v1 风格 memory_store.db（memories + semantic_memory 表），
验证迁移路径：

1. dry-run 不写盘（subprocess，避免依赖 RAGModule）
2. ShortTermContext 表正确填充（直接调 migrate_short_term 函数，绕开 RAGModule）
3. v2 slim MemoryStore 可读迁移结果

注意：long_term 迁移依赖 RAGModule（触发真实 embedding API 调用，
测试环境无 API key）。long_term 测试放到 staging / acceptance。
"""
from __future__ import annotations

import sys
import sqlite3
import subprocess
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


def _make_v1_db(path: Path, n_working=3, n_episodic=2) -> None:
    """构造一个 v1 风格的 memory_store.db（只放 short_term 类型）。"""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_type TEXT NOT NULL,
            content TEXT NOT NULL,
            importance INTEGER DEFAULT 2,
            session_id TEXT NOT NULL,
            intent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS semantic_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id INTEGER,
            content_hash TEXT,
            summary TEXT,
            session_id TEXT
        );
    """)
    for i in range(n_working):
        conn.execute(
            "INSERT INTO memories(memory_type, content, session_id, intent) "
            "VALUES (?, ?, ?, ?)",
            ("working", f"working message {i}", f"sess-{i % 2}", "question"),
        )
    for i in range(n_episodic):
        conn.execute(
            "INSERT INTO memories(memory_type, content, session_id, intent) "
            "VALUES (?, ?, ?, ?)",
            ("episodic", f"episodic event {i}", f"sess-{i % 2}", "narrative"),
        )
    conn.commit()
    conn.close()


def _run_dry_run(src: Path) -> subprocess.CompletedProcess:
    args = [
        sys.executable, str(SCRIPTS_DIR / "migrate_memory_v1_to_v2.py"),
        "--src", str(src),
        "--dry-run",
    ]
    return subprocess.run(args, capture_output=True, text=True, cwd=str(ROOT), timeout=30)


def _run_short_term_direct(src: Path, ctx_out: Path) -> int:
    sys.path.insert(0, str(SCRIPTS_DIR))
    from migrate_memory_v1_to_v2 import _init_ctx, migrate_short_term
    src_conn = sqlite3.connect(str(src))
    dst_conn = _init_ctx(ctx_out)
    try:
        return migrate_short_term(src_conn, dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()


# ============================================================
# 1. dry-run 只统计不写盘
# ============================================================

def test_dry_run_no_write(tmp_path):
    """dry-run 必须只统计，不写盘。"""
    src = tmp_path / "v1.db"
    _make_v1_db(src, n_working=3, n_episodic=2)
    r = _run_dry_run(src)
    assert r.returncode == 0, f"stderr={r.stderr}"
    out = r.stdout + r.stderr
    assert "[DRY-RUN]" in out
    assert "short=5" in out


# ============================================================
# 2. 短记忆迁移到 ShortTermContext
# ============================================================

def test_migrate_short_term(tmp_path):
    """working + episodic 行必须迁入 ShortTermContext 表。"""
    src = tmp_path / "v1.db"
    _make_v1_db(src, n_working=3, n_episodic=2)
    ctx_out = tmp_path / "context_v2.db"

    n = _run_short_term_direct(src, ctx_out)
    assert n == 5, f"应迁移 5 行，实际 {n}"

    conn = sqlite3.connect(str(ctx_out))
    rows = conn.execute(
        "SELECT thread_id, role, content, meta FROM short_term_context ORDER BY id"
    ).fetchall()
    assert len(rows) == 5

    metas = [json.loads(r[3]) for r in rows]
    src_types = {m["src_type"] for m in metas}
    assert "working" in src_types
    assert "episodic" in src_types

    # 索引存在
    idx = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_stc_thread'"
    ).fetchone()
    assert idx is not None, "idx_stc_thread 索引必须创建"
    conn.close()


# ============================================================
# 3. v2 slim MemoryStore 可读迁移结果
# ============================================================

def test_v2_memory_store_can_load_migrated_db(tmp_path):
    """迁移后 v2 slim MemoryStore.short.load() 必须能读出来。"""
    src = tmp_path / "v1.db"
    _make_v1_db(src, n_working=2, n_episodic=1)
    ctx_out = tmp_path / "context_v2.db"

    _run_short_term_direct(src, ctx_out)

    sys.path.insert(0, str(ROOT))
    from v2_slim.memory_store_v2 import MemoryStore

    ms = MemoryStore(thread_id="sess-0", user_id="u1", short_db_path=str(ctx_out))
    rows = ms.short.load()
    assert len(rows) >= 1, f"sess-0 应至少 1 条记忆，实际 {len(rows)}"
    for r in rows:
        assert "content" in r
        assert "meta" in r


# ============================================================
# 4. 迁移函数接口稳定（import + 签名）
# ============================================================

def test_migration_module_importable():
    """迁移脚本必须可作为模块 import（不能只是 __main__）。"""
    sys.path.insert(0, str(SCRIPTS_DIR))
    import migrate_memory_v1_to_v2 as m
    assert callable(m._init_ctx)
    assert callable(m.migrate_short_term)
    assert callable(m.migrate_long_term)
    assert callable(m.main)


# ============================================================
# 5. _init_ctx 创建正确的表结构
# ============================================================

def test_init_ctx_creates_table_and_index(tmp_path):
    """_init_ctx 必须创建 short_term_context 表 + idx_stc_thread 索引。"""
    sys.path.insert(0, str(SCRIPTS_DIR))
    from migrate_memory_v1_to_v2 import _init_ctx

    db = tmp_path / "ctx.db"
    conn = _init_ctx(db)
    conn.close()

    c = sqlite3.connect(str(db))
    tables = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert "short_term_context" in tables, f"缺 short_term_context 表：{tables}"

    idx = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()]
    assert "idx_stc_thread" in idx, f"缺 idx_stc_thread 索引：{idx}"
    c.close()
