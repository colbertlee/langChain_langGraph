"""
结构化上下文持久化 - 单元测试
Phase 1: 基础框架
"""
import unittest
import os
import tempfile
from datetime import datetime

# 设置测试数据库路径
os.environ["TEST_MODE"] = "true"

from context_db import (
    DatabaseManager, SessionRepository, MessageRepository, 
    EntityRepository, ToolCallRepository, SummaryRepository,
    Session, Message, Entity, ToolCall, Summary,
    SessionStatus, MessageRole, EntityType, ToolStatus, SummaryType
)


class TestDatabaseManager(unittest.TestCase):
    """数据库管理器测试"""
    
    def setUp(self):
        """设置测试环境"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.db = DatabaseManager(self.temp_db.name)
    
    def tearDown(self):
        """清理测试环境"""
        try:
            os.unlink(self.temp_db.name)
        except:
            pass
    
    def test_database_initialization(self):
        """测试数据库初始化"""
        # 验证表已创建
        with self.db.get_cursor() as cursor:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            expected_tables = ['sessions', 'messages', 'entities', 'tool_calls', 'summaries', 'entity_relations']
            for table in expected_tables:
                self.assertIn(table, tables, f"Table {table} should exist")


class TestSessionRepository(unittest.TestCase):
    """会话仓储测试"""
    
    def setUp(self):
        """设置测试环境"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.db = DatabaseManager(self.temp_db.name)
        self.repo = SessionRepository(self.db)
    
    def tearDown(self):
        """清理测试环境"""
        try:
            os.unlink(self.temp_db.name)
        except:
            pass
    
    def test_create_session(self):
        """测试创建会话"""
        session = self.repo.create(user_id="test_user")
        
        self.assertIsNotNone(session.id)
        self.assertEqual(session.user_id, "test_user")
        self.assertEqual(session.status, SessionStatus.ACTIVE.value)
        self.assertEqual(session.message_count, 0)
    
    def test_get_session(self):
        """测试获取会话"""
        created = self.repo.create(user_id="test_user")
        retrieved = self.repo.get_by_id(created.id)
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, created.id)
        self.assertEqual(retrieved.user_id, "test_user")
    
    def test_update_session(self):
        """测试更新会话"""
        session = self.repo.create(user_id="test_user")
        
        updated = self.repo.update(
            session.id,
            status=SessionStatus.COMPLETED.value,
            message_count=10
        )
        
        self.assertEqual(updated.status, SessionStatus.COMPLETED.value)
        self.assertEqual(updated.message_count, 10)
    
    def test_increment_message_count(self):
        """测试增加消息计数"""
        session = self.repo.create(user_id="test_user")
        
        self.repo.increment_message_count(session.id, tokens=100)
        
        updated = self.repo.get_by_id(session.id)
        self.assertEqual(updated.message_count, 1)
        self.assertEqual(updated.total_tokens, 100)
    
    def test_list_sessions(self):
        """测试列出会话"""
        self.repo.create(user_id="user1")
        self.repo.create(user_id="user2")
        
        sessions = self.repo.list_sessions(limit=10)
        self.assertEqual(len(sessions), 2)
    
    def test_delete_session(self):
        """测试删除会话"""
        session = self.repo.create(user_id="test_user")
        
        result = self.repo.delete(session.id)
        self.assertTrue(result)
        
        deleted = self.repo.get_by_id(session.id)
        self.assertIsNone(deleted)


class TestMessageRepository(unittest.TestCase):
    """消息仓储测试"""
    
    def setUp(self):
        """设置测试环境"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.db = DatabaseManager(self.temp_db.name)
        self.repo = MessageRepository(self.db)
        self.session_repo = SessionRepository(self.db)
        
        # 创建测试会话
        self.session = self.session_repo.create(user_id="test_user")
    
    def tearDown(self):
        """清理测试环境"""
        try:
            os.unlink(self.temp_db.name)
        except:
            pass
    
    def test_create_message(self):
        """测试创建消息"""
        message = self.repo.create(
            session_id=self.session.id,
            role=MessageRole.USER.value,
            content="Hello, world!"
        )
        
        self.assertIsNotNone(message.id)
        self.assertEqual(message.content, "Hello, world!")
        self.assertEqual(message.role, MessageRole.USER.value)
    
    def test_list_messages(self):
        """测试列出消息"""
        self.repo.create(self.session.id, MessageRole.USER.value, "Message 1")
        self.repo.create(self.session.id, MessageRole.ASSISTANT.value, "Response 1")
        
        messages = self.repo.list_by_session(self.session.id)
        self.assertEqual(len(messages), 2)
    
    def test_get_recent_messages(self):
        """测试获取最近消息"""
        for i in range(5):
            self.repo.create(self.session.id, MessageRole.USER.value, f"Message {i}")
        
        recent = self.repo.get_recent_messages(self.session.id, limit=3)
        self.assertEqual(len(recent), 3)


class TestEntityRepository(unittest.TestCase):
    """实体仓储测试"""
    
    def setUp(self):
        """设置测试环境"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.db = DatabaseManager(self.temp_db.name)
        self.repo = EntityRepository(self.db)
        self.session_repo = SessionRepository(self.db)
        
        # 创建测试会话
        self.session = self.session_repo.create(user_id="test_user")
    
    def tearDown(self):
        """清理测试环境"""
        try:
            os.unlink(self.temp_db.name)
        except:
            pass
    
    def test_create_entity(self):
        """测试创建实体"""
        entity = self.repo.create(
            session_id=self.session.id,
            entity_type=EntityType.ETF.value,
            entity_name="510300",
            entity_value={"code": "510300", "name": "沪深300ETF"}
        )
        
        self.assertIsNotNone(entity.id)
        self.assertEqual(entity.entity_type, EntityType.ETF.value)
        self.assertEqual(entity.entity_name, "510300")
    
    def test_find_or_create(self):
        """测试查找或创建实体"""
        entity1, created = self.repo.find_or_create(
            session_id=self.session.id,
            entity_type=EntityType.ETF.value,
            entity_name="510300"
        )
        self.assertTrue(created)
        
        entity2, created = self.repo.find_or_create(
            session_id=self.session.id,
            entity_type=EntityType.ETF.value,
            entity_name="510300"
        )
        self.assertFalse(created)
        self.assertEqual(entity2.mention_count, 2)
    
    def test_list_entities(self):
        """测试列出会话实体"""
        self.repo.create(self.session.id, EntityType.ETF.value, "510300")
        self.repo.create(self.session.id, EntityType.ETF.value, "510500")
        self.repo.create(self.session.id, EntityType.CITY.value, "北京")
        
        etf_entities = self.repo.list_by_session(self.session.id, entity_type=EntityType.ETF.value)
        self.assertEqual(len(etf_entities), 2)
        
        all_entities = self.repo.list_by_session(self.session.id)
        self.assertEqual(len(all_entities), 3)


class TestToolCallRepository(unittest.TestCase):
    """工具调用仓储测试"""
    
    def setUp(self):
        """设置测试环境"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.db = DatabaseManager(self.temp_db.name)
        self.repo = ToolCallRepository(self.db)
        self.session_repo = SessionRepository(self.db)
        
        # 创建测试会话
        self.session = self.session_repo.create(user_id="test_user")
    
    def tearDown(self):
        """清理测试环境"""
        try:
            os.unlink(self.temp_db.name)
        except:
            pass
    
    def test_create_tool_call(self):
        """测试创建工具调用"""
        tool_call = self.repo.create(
            session_id=self.session.id,
            tool_name="get_etf_info",
            tool_input={"etf_code": "510300"},
            tool_output={"name": "沪深300ETF", "price": 3.85},
            status=ToolStatus.SUCCESS.value,
            execution_time_ms=150
        )
        
        self.assertIsNotNone(tool_call.id)
        self.assertEqual(tool_call.tool_name, "get_etf_info")
        self.assertEqual(tool_call.status, ToolStatus.SUCCESS.value)
    
    def test_get_tool_usage_stats(self):
        """测试获取工具使用统计"""
        self.repo.create(self.session.id, "get_etf_info")
        self.repo.create(self.session.id, "get_etf_info")
        self.repo.create(self.session.id, "get_weather")
        
        stats = self.repo.get_tool_usage_stats(self.session.id)
        
        self.assertEqual(stats.get("get_etf_info"), 2)
        self.assertEqual(stats.get("get_weather"), 1)


class TestSummaryRepository(unittest.TestCase):
    """摘要仓储测试"""
    
    def setUp(self):
        """设置测试环境"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.db = DatabaseManager(self.temp_db.name)
        self.repo = SummaryRepository(self.db)
        self.session_repo = SessionRepository(self.db)
        
        # 创建测试会话
        self.session = self.session_repo.create(user_id="test_user")
    
    def tearDown(self):
        """清理测试环境"""
        try:
            os.unlink(self.temp_db.name)
        except:
            pass
    
    def test_create_summary(self):
        """测试创建摘要"""
        summary = self.repo.create(
            session_id=self.session.id,
            summary_content="用户查询了ETF信息",
            summary_type=SummaryType.AUTO.value,
            topic="ETF查询",
            keywords=["ETF", "基金", "查询"],
            key_entities=["510300", "510500"]
        )
        
        self.assertIsNotNone(summary.id)
        self.assertEqual(summary.topic, "ETF查询")
        self.assertEqual(len(summary.keywords), 3)
    
    def test_get_latest(self):
        """测试获取最新摘要"""
        self.repo.create(self.session.id, "Summary 1", topic="Topic 1")
        self.repo.create(self.session.id, "Summary 2", topic="Topic 2")
        
        latest = self.repo.get_latest(self.session.id)
        self.assertEqual(latest.topic, "Topic 2")


if __name__ == '__main__':
    unittest.main(verbosity=2)
