"""sqlite_tools.py 单元测试。

用 in-memory SQLite（tmp_path）避免真实数据库。
覆盖：list_tables / table_info / query / execute / create_table + register_all_sqlite_tools。
"""
import os
import sqlite3
import pytest
from unittest.mock import MagicMock, patch

import sqlite_tools
from sqlite_tools import (
    get_db_connection,
    handle_sqlite_list_tables,
    handle_sqlite_table_info,
    handle_sqlite_query,
    handle_sqlite_execute,
    handle_sqlite_create_table,
    register_all_sqlite_tools,
)


@pytest.fixture
def sample_db(tmp_path):
    """创建一个带测试数据的临时 SQLite 数据库。"""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER
        )
    """)
    cur.execute("INSERT INTO users (name, age) VALUES ('alice', 30)")
    cur.execute("INSERT INTO users (name, age) VALUES ('bob', 25)")
    cur.execute("INSERT INTO users (name, age) VALUES ('charlie', 35)")
    conn.commit()
    conn.close()
    return db_path


# ==================== get_db_connection ====================


class TestConnection:

    def test_get_connection_default(self):
        conn = get_db_connection()
        assert conn is not None
        conn.close()

    def test_get_connection_custom_path(self, tmp_path):
        db_path = str(tmp_path / "custom.db")
        conn = get_db_connection(db_path)
        assert conn is not None
        conn.close()


# ==================== list_tables ====================


class TestListTables:

    def test_list_tables_empty(self, tmp_path):
        """空数据库应返回 'No tables found'。"""
        db_path = str(tmp_path / "empty.db")
        sqlite3.connect(db_path).close()  # 创建空 db

        result = handle_sqlite_list_tables({"db_path": db_path})
        assert "No tables" in result

    def test_list_tables_success(self, sample_db):
        result = handle_sqlite_list_tables({"db_path": sample_db})
        assert "users" in result
        assert "Tables in" in result

    def test_list_tables_multiple(self, tmp_path):
        db_path = str(tmp_path / "multi.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t1 (x INTEGER)")
        conn.execute("CREATE TABLE t2 (y TEXT)")
        conn.commit()
        conn.close()

        result = handle_sqlite_list_tables({"db_path": db_path})
        assert "t1" in result
        assert "t2" in result

    def test_list_tables_invalid_path(self):
        result = handle_sqlite_list_tables({"db_path": "/nonexistent/dir/db.db"})
        assert "Error" in result


# ==================== table_info ====================


class TestTableInfo:

    def test_table_info_success(self, sample_db):
        result = handle_sqlite_table_info({"db_path": sample_db, "table": "users"})
        assert "users" in result
        assert "id" in result
        assert "name" in result
        assert "age" in result

    def test_table_info_no_table_arg(self, sample_db):
        result = handle_sqlite_table_info({"db_path": sample_db})
        assert "table name is required" in result

    def test_table_info_nonexistent_table(self, sample_db):
        result = handle_sqlite_table_info({"db_path": sample_db, "table": "no_such_table"})
        assert "not found" in result.lower() or "no columns" in result.lower()


# ==================== query ====================


class TestQuery:

    def test_select_all(self, sample_db):
        result = handle_sqlite_query({
            "db_path": sample_db,
            "sql": "SELECT * FROM users",
        })
        assert "alice" in result
        assert "bob" in result
        assert "charlie" in result

    def test_select_with_where(self, sample_db):
        result = handle_sqlite_query({
            "db_path": sample_db,
            "sql": "SELECT name FROM users WHERE age > 28",
        })
        assert "alice" in result
        assert "charlie" in result
        assert "bob" not in result

    def test_select_with_limit(self, sample_db):
        result = handle_sqlite_query({
            "db_path": sample_db,
            "sql": "SELECT * FROM users",
            "limit": 1,
        })
        # 只应返回 1 行
        assert "Query Result (1 rows)" in result

    def test_select_no_results(self, sample_db):
        result = handle_sqlite_query({
            "db_path": sample_db,
            "sql": "SELECT * FROM users WHERE age > 100",
        })
        assert "No results" in result

    def test_query_no_sql(self, sample_db):
        result = handle_sqlite_query({"db_path": sample_db})
        assert "SQL query is required" in result

    def test_query_blocks_insert(self, sample_db):
        """非 SELECT 应被阻止。"""
        result = handle_sqlite_query({
            "db_path": sample_db,
            "sql": "INSERT INTO users (name) VALUES ('evil')",
        })
        assert "Only SELECT" in result or "Error" in result

    def test_query_blocks_delete(self, sample_db):
        result = handle_sqlite_query({
            "db_path": sample_db,
            "sql": "DELETE FROM users",
        })
        assert "Only SELECT" in result or "Error" in result

    def test_query_syntax_error(self, sample_db):
        result = handle_sqlite_query({
            "db_path": sample_db,
            "sql": "SELECT FROMM users",
        })
        assert "Error" in result


# ==================== execute ====================


class TestExecute:

    def test_insert(self, sample_db):
        result = handle_sqlite_execute({
            "db_path": sample_db,
            "sql": "INSERT INTO users (name, age) VALUES ('diana', 28)",
        })
        assert "Success" in result
        assert "1" in result   # rows affected

        # 验证插入成功
        conn = sqlite3.connect(sample_db)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE name='diana'")
        assert cur.fetchone()[0] == 1
        conn.close()

    def test_update(self, sample_db):
        result = handle_sqlite_execute({
            "db_path": sample_db,
            "sql": "UPDATE users SET age = 31 WHERE name = 'alice'",
        })
        assert "Success" in result

        conn = sqlite3.connect(sample_db)
        cur = conn.cursor()
        cur.execute("SELECT age FROM users WHERE name='alice'")
        assert cur.fetchone()[0] == 31
        conn.close()

    def test_delete(self, sample_db):
        result = handle_sqlite_execute({
            "db_path": sample_db,
            "sql": "DELETE FROM users WHERE name = 'bob'",
        })
        assert "Success" in result

        conn = sqlite3.connect(sample_db)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE name='bob'")
        assert cur.fetchone()[0] == 0
        conn.close()

    def test_execute_blocks_select(self, sample_db):
        """SELECT 不应在 execute 工具中允许。"""
        result = handle_sqlite_execute({
            "db_path": sample_db,
            "sql": "SELECT * FROM users",
        })
        assert "Only INSERT" in result or "Error" in result

    def test_execute_no_sql(self, sample_db):
        result = handle_sqlite_execute({"db_path": sample_db})
        assert "SQL statement is required" in result


# ==================== create_table ====================


class TestCreateTable:

    def test_create_table_success(self, tmp_path):
        db_path = str(tmp_path / "new.db")
        result = handle_sqlite_create_table({
            "db_path": db_path,
            "table_name": "products",
            "columns": [
                {"name": "id", "type": "INTEGER PRIMARY KEY"},
                {"name": "name", "type": "TEXT"},
            ],
        })
        assert "Success" in result

        # 验证表创建
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
        assert cur.fetchone() is not None
        conn.close()

    def test_create_table_no_name(self, sample_db):
        result = handle_sqlite_create_table({
            "db_path": sample_db,
            "columns": [{"name": "id", "type": "INTEGER"}],
        })
        assert "required" in result.lower()

    def test_create_table_no_columns(self, sample_db):
        result = handle_sqlite_create_table({
            "db_path": sample_db,
            "table_name": "x",
        })
        assert "required" in result.lower()

    def test_create_table_default_type(self, tmp_path):
        """columns 不指定 type 应默认 TEXT。"""
        db_path = str(tmp_path / "default_type.db")
        result = handle_sqlite_create_table({
            "db_path": db_path,
            "table_name": "t",
            "columns": [{"name": "x"}],  # no type → default TEXT
        })
        assert "Success" in result


# ==================== register_all_sqlite_tools ====================


class TestRegistration:

    def test_register_all(self):
        # 清空注册表
        from mcp_server import get_mcp_tool_registry
        get_mcp_tool_registry()["tools"].clear()

        register_all_sqlite_tools()

        all_tools = get_mcp_tool_registry()["tools"]
        # 应有 database 分类
        assert "database" in all_tools

        db_tools = all_tools["database"]
        assert "sqlite_list_tables" in db_tools
        assert "sqlite_table_info" in db_tools
        assert "sqlite_query" in db_tools
        assert "sqlite_execute" in db_tools
        assert "sqlite_create_table" in db_tools


# ==================== Edge cases ====================


class TestEdgeCases:

    def test_query_with_special_chars_in_data(self, tmp_path):
        db_path = str(tmp_path / "special.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (msg TEXT)")
        conn.execute("INSERT INTO t VALUES ('hello | world')")
        conn.commit()
        conn.close()

        result = handle_sqlite_query({
            "db_path": db_path,
            "sql": "SELECT * FROM t",
        })
        assert "hello | world" in result

    def test_concurrent_connections(self, sample_db):
        """多次调用应不冲突。"""
        for _ in range(5):
            r = handle_sqlite_query({
                "db_path": sample_db,
                "sql": "SELECT COUNT(*) FROM users",
            })
            assert "3" in r

    def test_large_query(self, tmp_path):
        """1000 行的查询应正常返回。"""
        db_path = str(tmp_path / "large.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE big (id INTEGER, val TEXT)")
        for i in range(1000):
            conn.execute("INSERT INTO big VALUES (?, ?)", (i, f"value_{i}"))
        conn.commit()
        conn.close()

        result = handle_sqlite_query({
            "db_path": db_path,
            "sql": "SELECT * FROM big",
            "limit": 100,
        })
        assert "100 rows" in result
