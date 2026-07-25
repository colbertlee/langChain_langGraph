"""
结构化上下文持久化 - 调试测试
"""
import os
# 修复语法错误
test_file = __file__ if '__file__' in dir() else 'test_debug.py'

from context_db import DatabaseManager, SessionRepository

test_db_path = "test_debug.db"

# 清理旧数据库
if os.path.exists(test_db_path):
    os.remove(test_db_path)

print("1. Creating database...")
db = DatabaseManager(test_db_path)
repo = SessionRepository(db)

print("\n2. Manual execution of create() logic...")

# 手动执行 create 中的操作
import uuid
from datetime import datetime
from context_db import to_json, SessionStatus

session_id = str(uuid.uuid4())
now = str(datetime.now())

print(f"   Generated session_id: {session_id}")
print(f"   Generated now: {now}")

with db.get_cursor() as cursor:
    print("   Executing INSERT...")
    cursor.execute("""
        INSERT INTO sessions (id, user_id, created_at, updated_at, status, message_count, total_tokens, metadata, preferences, profile)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id,
        "test_user",
        now,
        now,
        SessionStatus.ACTIVE.value,
        0,
        0,
        to_json({}),
        to_json({}),
        to_json({})
    ))
    print(f"   INSERT completed, session_id: {session_id}")

print("\n3. Calling get_by_id() separately...")
result = repo.get_by_id(session_id)
print(f"   Result: {result}")

# 4. 在同一个方法中测试
print("\n4. Testing create() method...")
session = repo.create(user_id="test_user2")
print(f"   create() result: {session}")

# 5. 检查数据库状态
print("\n5. Checking database state...")
with db.get_cursor() as cursor:
    cursor.execute("SELECT id, user_id FROM sessions")
    rows = cursor.fetchall()
    print(f"   Total sessions: {len(rows)}")
    for row in rows:
        print(f"   - {row[0]}: {row[1]}")

# 清理
try:
    os.remove(test_db_path)
except:
    pass
