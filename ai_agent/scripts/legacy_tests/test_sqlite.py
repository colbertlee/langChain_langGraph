"""测试 SQLite MCP 工具"""
from sqlite_tools import (
    handle_sqlite_create_table,
    handle_sqlite_execute,
    handle_sqlite_list_tables,
    handle_sqlite_query,
    handle_sqlite_table_info
)

print("=" * 50)
print("Testing SQLite MCP Tools")
print("=" * 50)

# 1. 创建测试表
print("\n1. Create table:")
result = handle_sqlite_create_table({
    'table_name': 'test_table',
    'columns': [
        {'name': 'id', 'type': 'INTEGER PRIMARY KEY'},
        {'name': 'name', 'type': 'TEXT'},
        {'name': 'created_at', 'type': 'DATETIME DEFAULT CURRENT_TIMESTAMP'}
    ]
})
print(result)

# 2. 插入数据
print("\n2. Insert data:")
result = handle_sqlite_execute({
    'sql': "INSERT INTO test_table (name) VALUES ('test1')"
})
print(result)

result = handle_sqlite_execute({
    'sql': "INSERT INTO test_table (name) VALUES ('test2')"
})
print(result)

# 3. 查询数据
print("\n3. Query data:")
result = handle_sqlite_query({'sql': 'SELECT * FROM test_table'})
print(result)

# 4. 表信息
print("\n4. Table info:")
result = handle_sqlite_table_info({'table': 'test_table'})
print(result)

# 5. 列出所有表
print("\n5. List tables:")
result = handle_sqlite_list_tables({})
print(result)

print("\n" + "=" * 50)
print("All tests completed!")
print("=" * 50)
