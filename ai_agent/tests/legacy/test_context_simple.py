"""
结构化上下文持久化 - 快速测试脚本
"""
import os
# 添加当前目录到路径

from context_db import (
    DatabaseManager, SessionRepository, MessageRepository,
    EntityRepository, SummaryRepository,
    SessionStatus, MessageRole, EntityType, SummaryType
)


def test_all():
    """综合测试"""
    print("=" * 60)
    print("Context Persistence - Integration Test")
    print("=" * 60)
    
    # 使用测试专用数据库
    test_db_path = "test_context.db"
    
    # 清理可能存在的旧测试数据库
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
    
    print(f"\n1. Creating database at: {test_db_path}")
    db = DatabaseManager(test_db_path)
    print(f"   Database path: {db._db_path}")
    
    # =========================================
    # 测试会话
    # =========================================
    print("\n2. Testing Session Repository")
    session_repo = SessionRepository(db)
    
    session1 = session_repo.create(user_id="user1")
    print(f"   Created session1: {session1.id}")
    
    session2 = session_repo.create(user_id="user2")
    print(f"   Created session2: {session2.id}")
    
    # 查询会话
    retrieved = session_repo.get_by_id(session1.id)
    print(f"   Retrieved session: {retrieved.id if retrieved else 'None'}")
    
    # 列表会话
    sessions = session_repo.list_sessions(limit=10)
    print(f"   Listed sessions: {len(sessions)}")
    
    # =========================================
    # 测试消息
    # =========================================
    print("\n3. Testing Message Repository")
    msg_repo = MessageRepository(db)
    
    msg1 = msg_repo.create(session1.id, MessageRole.USER.value, "Hello world")
    msg2 = msg_repo.create(session1.id, MessageRole.ASSISTANT.value, "Hi there")
    print(f"   Created messages: {msg1.id}, {msg2.id}")
    
    # 列表消息
    messages = msg_repo.list_by_session(session1.id)
    print(f"   Listed messages: {len(messages)}")
    
    # =========================================
    # 测试实体
    # =========================================
    print("\n4. Testing Entity Repository")
    entity_repo = EntityRepository(db)
    
    entity1 = entity_repo.create(
        session1.id,
        EntityType.ETF.value,
        "510300",
        entity_value={"code": "510300", "name": "CSI300 ETF"}
    )
    print(f"   Created entity: {entity1.entity_name}")
    
    # 查找或创建
    entity2, created = entity_repo.find_or_create(
        session1.id,
        EntityType.ETF.value,
        "510300"
    )
    print(f"   find_or_create - mention count: {entity2.mention_count}")
    
    # 创建另一个实体
    entity_repo.create(session1.id, EntityType.CITY.value, "Beijing")
    
    # 列表实体
    entities = entity_repo.list_by_session(session1.id)
    print(f"   Listed entities: {len(entities)}")
    
    etf_entities = entity_repo.list_by_session(session1.id, entity_type=EntityType.ETF.value)
    print(f"   ETF entities: {len(etf_entities)}")
    
    # =========================================
    # 测试摘要
    # =========================================
    print("\n5. Testing Summary Repository")
    summary_repo = SummaryRepository(db)
    
    summary = summary_repo.create(
        session_id=session1.id,
        summary_content="User queried ETF information",
        summary_type=SummaryType.AUTO.value,
        topic="ETF Query",
        keywords=["ETF", "query"],
        key_entities=["510300"]
    )
    print(f"   Created summary: {summary.id}")
    print(f"   Topic: {summary.topic}")
    print(f"   Keywords: {summary.keywords}")
    
    # 获取最新摘要
    latest = summary_repo.get_latest(session1.id)
    print(f"   Latest summary topic: {latest.topic if latest else 'None'}")
    
    # =========================================
    # 测试更新
    # =========================================
    print("\n6. Testing Updates")
    
    # 更新会话
    session_repo.increment_message_count(session1.id, tokens=100)
    updated_session = session_repo.get_by_id(session1.id)
    print(f"   Session message_count: {updated_session.message_count}")
    
    # 更新实体
    entity_repo.update(entity1.id, is_active=False)
    entities = entity_repo.list_by_session(session1.id, active_only=True)
    print(f"   Active entities: {len(entities)}")
    
    # =========================================
    # 统计
    # =========================================
    print("\n7. Statistics")
    stats = {
        "sessions": len(session_repo.list_sessions(limit=100)),
        "messages": len(msg_repo.list_by_session(session1.id)),
        "entities": len(entity_repo.list_by_session(session1.id)),
        "summaries": len(summary_repo.list_by_session(session1.id))
    }
    print(f"   Total sessions: {stats['sessions']}")
    print(f"   Total messages: {stats['messages']}")
    print(f"   Total entities: {stats['entities']}")
    print(f"   Total summaries: {stats['summaries']}")
    
    # =========================================
    # 清理
    # =========================================
    print("\n8. Cleanup")
    deleted = session_repo.delete(session1.id)
    print(f"   Deleted session1: {deleted}")
    
    remaining = session_repo.list_sessions(limit=10)
    print(f"   Remaining sessions: {len(remaining)}")
    
    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)
    
    # 清理测试文件
    try:
        os.remove(test_db_path)
        print("\nTest database cleaned up")
    except:
        pass
    
    return True


if __name__ == "__main__":
    try:
        success = test_all()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
