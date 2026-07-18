"""
SQLite MCP 工具集

提供 SQLite 数据库操作能力
"""
import os
import sqlite3
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

# 默认数据库路径
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "agent_data.db")


def get_db_connection(db_path: str = "") -> sqlite3.Connection:
    """获取数据库连接"""
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


# ==================== 数据库操作 ====================

def handle_sqlite_list_tables(args: Dict[str, Any]) -> str:
    """列出所有表"""
    db_path = args.get("db_path", DEFAULT_DB_PATH)
    
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()
        conn.close()
        
        if not tables:
            return "No tables found in database"
        
        result = f"Tables in {db_path}:\n"
        result += "=" * 50 + "\n"
        for table in tables:
            result += f"  - {table[0]}\n"
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"


def handle_sqlite_table_info(args: Dict[str, Any]) -> str:
    """获取表结构信息"""
    db_path = args.get("db_path", DEFAULT_DB_PATH)
    table = args.get("table", "")
    
    if not table:
        return "Error: table name is required"
    
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table})")
        columns = cursor.fetchall()
        conn.close()
        
        if not columns:
            return f"Table '{table}' not found"
        
        result = f"Table: {table}\n"
        result += "=" * 50 + "\n"
        result += f"{'Column':<20} {'Type':<15} {'Nullable':<10} {'Default'}\n"
        result += "-" * 60 + "\n"
        
        for col in columns:
            result += f"{col[1]:<20} {col[2]:<15} {'No' if col[3] else 'Yes':<10} {col[4]}\n"
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"


def handle_sqlite_query(args: Dict[str, Any]) -> str:
    """执行 SELECT 查询"""
    db_path = args.get("db_path", DEFAULT_DB_PATH)
    sql = args.get("sql", "")
    limit = args.get("limit", 10)
    
    if not sql:
        return "Error: SQL query is required"
    
    if not sql.strip().upper().startswith("SELECT"):
        return "Error: Only SELECT queries are allowed for security"
    
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute(f"{sql} LIMIT {limit}")
        rows = cursor.fetchall()
        
        if not rows:
            return "No results found"
        
        # 获取列名
        columns = [desc[0] for desc in cursor.description]
        
        # 格式化输出
        result = f"Query Result ({len(rows)} rows):\n"
        result += "=" * 60 + "\n"
        result += " | ".join(f"{col:<20}" for col in columns) + "\n"
        result += "-" * 60 + "\n"
        
        for row in rows:
            result += " | ".join(f"{str(val):<20}" for val in row) + "\n"
        
        conn.close()
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"


def handle_sqlite_execute(args: Dict[str, Any]) -> str:
    """执行 INSERT/UPDATE/DELETE"""
    db_path = args.get("db_path", DEFAULT_DB_PATH)
    sql = args.get("sql", "")
    
    if not sql:
        return "Error: SQL statement is required"
    
    sql_upper = sql.strip().upper()
    if not any(sql_upper.startswith(op) for op in ["INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"]):
        return "Error: Only INSERT/UPDATE/DELETE/CREATE/DROP/ALTER allowed"
    
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute(sql)
        conn.commit()
        rows_affected = cursor.rowcount
        conn.close()
        
        return f"Success! Rows affected: {rows_affected}"
        
    except Exception as e:
        return f"Error: {str(e)}"


def handle_sqlite_create_table(args: Dict[str, Any]) -> str:
    """创建表"""
    db_path = args.get("db_path", DEFAULT_DB_PATH)
    table_name = args.get("table_name", "")
    columns = args.get("columns", [])  # [{"name": "id", "type": "INTEGER PRIMARY KEY"}, ...]
    
    if not table_name or not columns:
        return "Error: table_name and columns are required"
    
    try:
        # 构建 SQL
        col_defs = []
        for col in columns:
            col_defs.append(f"{col['name']} {col.get('type', 'TEXT')}")
        
        sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(col_defs)})"
        
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute(sql)
        conn.commit()
        conn.close()
        
        return f"Success! Table '{table_name}' created/updated"
        
    except Exception as e:
        return f"Error: {str(e)}"


# ==================== 注册所有 SQLite MCP 工具 ====================

def register_all_sqlite_tools():
    """注册所有 SQLite MCP 工具"""
    from mcp_tools import MCPToolRegistry
    
    MCPToolRegistry.register(
        name="sqlite_list_tables",
        description="列出数据库中所有表",
        input_schema={
            "type": "object",
            "properties": {
                "db_path": {"type": "string", "description": "数据库文件路径"}
            }
        },
        handler=handle_sqlite_list_tables,
        category="database"
    )
    
    MCPToolRegistry.register(
        name="sqlite_table_info",
        description="获取表结构信息",
        input_schema={
            "type": "object",
            "properties": {
                "db_path": {"type": "string"},
                "table": {"type": "string", "description": "表名"}
            },
            "required": ["table"]
        },
        handler=handle_sqlite_table_info,
        category="database"
    )
    
    MCPToolRegistry.register(
        name="sqlite_query",
        description="执行 SELECT 查询",
        input_schema={
            "type": "object",
            "properties": {
                "db_path": {"type": "string"},
                "sql": {"type": "string", "description": "SELECT SQL 语句"},
                "limit": {"type": "integer", "default": 10}
            },
            "required": ["sql"]
        },
        handler=handle_sqlite_query,
        category="database"
    )
    
    MCPToolRegistry.register(
        name="sqlite_execute",
        description="执行 INSERT/UPDATE/DELETE",
        input_schema={
            "type": "object",
            "properties": {
                "db_path": {"type": "string"},
                "sql": {"type": "string", "description": "SQL 语句"}
            },
            "required": ["sql"]
        },
        handler=handle_sqlite_execute,
        category="database"
    )
    
    MCPToolRegistry.register(
        name="sqlite_create_table",
        description="创建新表",
        input_schema={
            "type": "object",
            "properties": {
                "db_path": {"type": "string"},
                "table_name": {"type": "string"},
                "columns": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string"}
                        }
                    }
                }
            },
            "required": ["table_name", "columns"]
        },
        handler=handle_sqlite_create_table,
        category="database"
    )
    
    print("[SQLite MCP] Registered 5 SQLite tools")
