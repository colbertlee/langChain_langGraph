"""
结构化上下文持久化 - 调试测试
"""
import os
import sqlite3

test_db_path = "test_simple.db"

# 清理旧数据库
if os.path.exists(test_db_path):
    os.remove(test_db_path)

# 直接使用 sqlite3 测试
conn = sqlite3.connect(test_db_path)
cursor = conn.cursor()

print("1. Creating tables...")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'active',
        message_count INTEGER DEFAULT 0,
        total_tokens INTEGER DEFAULT 0,
        metadata TEXT DEFAULT '{}',
        preferences TEXT DEFAULT '{}',
        profile TEXT DEFAULT '{}'
    )
""")
conn.commit()

print("2. Inserting session...")
import uuid
session_id = str(uuid.uuid4())
now = "2024-01-01 12:00:00"
cursor.execute("""
    INSERT INTO sessions (id, user_id, created_at, updated_at, status, message_count, total_tokens)
    VALUES (?, ?, ?, ?, ?, ?, ?)
""", (session_id, "test_user", now, now, "active", 0, 0))
conn.commit()

print(f"3. Inserted session: {session_id}")

print("4. Querying session...")
cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
row = cursor.fetchone()
print(f"Row: {row}")

if row:
    print(f"5. Session found! ID: {row[0]}")
else:
    print("5. Session NOT found!")

conn.close()

# 清理
os.remove(test_db_path)
print("\nTest completed!")
