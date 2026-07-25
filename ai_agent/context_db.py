"""
结构化上下文持久化 - 数据库层
Phase 1: 基础框架
"""
import sqlite3
import json
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from enum import Enum
from functools import wraps

logger = logging.getLogger(__name__)

# =====================================================
# 枚举定义
# =====================================================

class SessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ContentType(str, Enum):
    TEXT = "text"
    CODE = "code"
    ERROR = "error"
    JSON = "json"
    HTML = "html"


class EntityType(str, Enum):
    ETF = "etf"
    STOCK = "stock"
    FUND = "fund"
    PERSON = "person"
    CITY = "city"
    DATE = "date"
    ACTION = "action"
    QUERY = "query"
    CONCEPT = "concept"
    OTHER = "other"


class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class SummaryType(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"
    MILESTONE = "milestone"
    FINAL = "final"


# =====================================================
# 数据类定义
# =====================================================

@dataclass
class Session:
    """会话"""
    id: str
    user_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    status: str = SessionStatus.ACTIVE.value
    message_count: int = 0
    total_tokens: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    preferences: Dict[str, Any] = field(default_factory=dict)
    profile: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    """消息"""
    id: Optional[int] = None
    session_id: str = ""
    role: str = MessageRole.USER.value
    content: str = ""
    content_type: str = ContentType.TEXT.value
    created_at: datetime = field(default_factory=datetime.now)
    token_count: int = 0
    latency_ms: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    intent: Optional[str] = None
    sentiment: Optional[str] = None
    parent_id: Optional[int] = None


@dataclass
class Entity:
    """实体"""
    id: Optional[int] = None
    session_id: str = ""
    entity_type: str = EntityType.OTHER.value
    entity_name: str = ""
    entity_value: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    mention_count: int = 1
    first_mentioned_at: datetime = field(default_factory=datetime.now)
    last_mentioned_at: datetime = field(default_factory=datetime.now)
    is_active: bool = True
    is_verified: bool = False
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    """工具调用"""
    id: Optional[int] = None
    session_id: str = ""
    message_id: Optional[int] = None
    tool_name: str = ""
    tool_input: Dict[str, Any] = field(default_factory=dict)
    tool_output: Dict[str, Any] = field(default_factory=dict)
    status: str = ToolStatus.SUCCESS.value
    error_message: Optional[str] = None
    execution_time_ms: Optional[int] = None
    call_count: int = 1
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Summary:
    """会话摘要"""
    id: Optional[int] = None
    session_id: str = ""
    summary_type: str = SummaryType.AUTO.value
    summary_content: str = ""
    topic: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    key_entities: List[str] = field(default_factory=list)
    action_items: List[Dict[str, Any]] = field(default_factory=list)
    completed_goals: List[str] = field(default_factory=list)
    pending_questions: List[str] = field(default_factory=list)
    sentiment: Optional[str] = None
    sentiment_score: Optional[float] = None
    user_satisfaction: Optional[float] = None
    resolution_status: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class EntityRelation:
    """实体关系"""
    id: Optional[int] = None
    session_id: str = ""
    from_entity_id: int = 0
    to_entity_id: int = 0
    relation_type: str = "related_to"
    strength: float = 0.5
    context: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class UserProfile:
    """用户画像"""
    id: Optional[int] = None
    user_id: str = ""
    display_name: Optional[str] = None
    language: str = "zh-CN"
    preferences: Dict[str, Any] = field(default_factory=dict)
    total_sessions: int = 0
    total_messages: int = 0
    favorite_tools: List[str] = field(default_factory=list)
    interests: List[str] = field(default_factory=list)
    expertise_areas: List[str] = field(default_factory=list)
    learned_preferences: Dict[str, Any] = field(default_factory=dict)
    avg_session_length: Optional[int] = None
    most_active_hour: Optional[int] = None
    common_intents: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


# =====================================================
# 数据库连接管理
# =====================================================

class DatabaseManager:
    """数据库管理器"""

    _instance = None
    _db_path: str = "context_memory.db"
    _conn: Optional[sqlite3.Connection] = None
    
    def __new__(cls, db_path: str = None):
        # 如果指定了 db_path，创建一个新实例（用于测试）
        if db_path:
            instance = super().__new__(cls)
            instance._initialized = False
            instance._db_path = db_path
            instance._init_db()
            instance._initialized = True
            return instance
        
        # 默认单例模式
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_path: str = None):
        # 如果已初始化，跳过
        if self._initialized:
            return
        
        if db_path:
            self._db_path = db_path
        else:
            self._db_path = "context_memory.db"
        
        self._init_db()
        self._initialized = True
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接

        用 check_same_thread=False + 共享单连接 + WAL 模式，
        让多个 cursor 上下文能看到彼此的提交。
        """
        if self._conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode=WAL")
            self._conn = conn
        return self._conn
    
    @contextmanager
    def get_cursor(self) -> sqlite3.Cursor:
        """上下文管理器：自动管理 cursor 和提交"""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            cursor.close()
            # 不关闭 conn：让它持久化以便后续 cursor 复用
    
    def _init_db(self):
        """初始化数据库"""
        with self.get_cursor() as cursor:
            # 会话表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'paused', 'completed', 'archived')),
                    message_count INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    metadata TEXT DEFAULT '{}',
                    preferences TEXT DEFAULT '{}',
                    profile TEXT DEFAULT '{}'
                )
            """)
            
            # 消息表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
                    content TEXT NOT NULL,
                    content_type TEXT DEFAULT 'text' CHECK(content_type IN ('text', 'code', 'error', 'json', 'html')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    token_count INTEGER DEFAULT 0,
                    latency_ms INTEGER,
                    metadata TEXT DEFAULT '{}',
                    intent TEXT,
                    sentiment TEXT,
                    parent_id INTEGER REFERENCES messages(id),
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)
            
            # 实体表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_name TEXT NOT NULL,
                    entity_value TEXT DEFAULT '{}',
                    confidence REAL DEFAULT 1.0,
                    mention_count INTEGER DEFAULT 1,
                    first_mentioned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_mentioned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1,
                    is_verified INTEGER DEFAULT 0,
                    attributes TEXT DEFAULT '{}',
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)
            
            # 工具调用表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    message_id INTEGER,
                    tool_name TEXT NOT NULL,
                    tool_input TEXT DEFAULT '{}',
                    tool_output TEXT DEFAULT '{}',
                    status TEXT DEFAULT 'success' CHECK(status IN ('success', 'error', 'timeout', 'cancelled')),
                    error_message TEXT,
                    execution_time_ms INTEGER,
                    call_count INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL
                )
            """)
            
            # 摘要表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    summary_type TEXT DEFAULT 'auto' CHECK(summary_type IN ('auto', 'manual', 'milestone', 'final')),
                    summary_content TEXT NOT NULL,
                    topic TEXT,
                    keywords TEXT DEFAULT '[]',
                    key_entities TEXT DEFAULT '[]',
                    action_items TEXT DEFAULT '[]',
                    completed_goals TEXT DEFAULT '[]',
                    pending_questions TEXT DEFAULT '[]',
                    sentiment TEXT,
                    sentiment_score REAL,
                    user_satisfaction REAL,
                    resolution_status TEXT CHECK(resolution_status IN ('resolved', 'partial', 'unresolved', 'escalated')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)
            
            # 实体关系表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entity_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    from_entity_id INTEGER NOT NULL,
                    to_entity_id INTEGER NOT NULL,
                    relation_type TEXT NOT NULL,
                    strength REAL DEFAULT 0.5,
                    context TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                    FOREIGN KEY (from_entity_id) REFERENCES entities(id) ON DELETE CASCADE,
                    FOREIGN KEY (to_entity_id) REFERENCES entities(id) ON DELETE CASCADE
                )
            """)
            
            # 用户画像表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT UNIQUE NOT NULL,
                    display_name TEXT,
                    language TEXT DEFAULT 'zh-CN',
                    preferences TEXT DEFAULT '{}',
                    total_sessions INTEGER DEFAULT 0,
                    total_messages INTEGER DEFAULT 0,
                    favorite_tools TEXT DEFAULT '[]',
                    interests TEXT DEFAULT '[]',
                    expertise_areas TEXT DEFAULT '[]',
                    learned_preferences TEXT DEFAULT '{}',
                    avg_session_length INTEGER,
                    most_active_hour INTEGER,
                    common_intents TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_intent ON messages(intent)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_session ON entities(session_id, entity_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_toolcalls_session ON tool_calls(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_summaries_session ON summaries(session_id)")
            
            # 性能优化索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_type_name ON entities(entity_type, entity_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_active ON entities(is_active)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_toolcalls_tool ON tool_calls(tool_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_relations_from ON entity_relations(from_entity_id)")
            
            logger.info("Database initialized successfully")
    
    def reset_database(self):
        """重置数据库（测试用）"""
        with self.get_cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS entity_relations")
            cursor.execute("DROP TABLE IF EXISTS summaries")
            cursor.execute("DROP TABLE IF EXISTS tool_calls")
            cursor.execute("DROP TABLE IF EXISTS entities")
            cursor.execute("DROP TABLE IF EXISTS messages")
            cursor.execute("DROP TABLE IF EXISTS sessions")
        self._init_db()


# =====================================================
# JSON 辅助函数
# =====================================================

def to_json(data: Any) -> str:
    """将数据转换为 JSON 字符串"""
    if data is None:
        return "{}"
    if isinstance(data, str):
        return data
    return json.dumps(data, ensure_ascii=False, default=str)


def from_json(data: str) -> Any:
    """从 JSON 字符串解析数据"""
    if not data:
        return {} if isinstance(data, str) and data == '{}' else []
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return {} if data == '{}' else []


# =====================================================
# Repository 基类
# =====================================================

class BaseRepository:
    """Repository 基类"""
    
    def __init__(self, db_manager: DatabaseManager = None):
        self.db = db_manager or DatabaseManager()
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将 Row 转换为字典"""
        if row is None:
            return {}
        return dict(row)
    
    def _parse_json_fields(self, data: Dict[str, Any], json_fields: List[str]) -> Dict[str, Any]:
        """解析 JSON 字段"""
        result = data.copy()
        for field in json_fields:
            if field in result:
                result[field] = from_json(result[field])
        return result


# =====================================================
# Session Repository
# =====================================================

class SessionRepository(BaseRepository):
    """会话仓储"""
    
    JSON_FIELDS = ['metadata', 'preferences', 'profile']
    
    def create(self, user_id: str = None, session_id: str = None, **kwargs) -> Session:
        """创建会话"""
        session_id = session_id or str(uuid.uuid4())
        now = datetime.now()
        now_str = str(now)
        metadata_dict = kwargs.get('metadata', {})
        preferences_dict = kwargs.get('preferences', {})
        profile_dict = kwargs.get('profile', {})
        
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO sessions (id, user_id, created_at, updated_at, status, message_count, 
                                    total_tokens, metadata, preferences, profile)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                user_id,
                now_str,
                now_str,
                kwargs.get('status', SessionStatus.ACTIVE.value),
                0,
                0,
                to_json(metadata_dict),
                to_json(preferences_dict),
                to_json(profile_dict)
            ))
        
        # 直接返回新创建的 Session 对象，避免事务隔离问题
        return Session(
            id=session_id,
            user_id=user_id,
            created_at=now,
            updated_at=now,
            status=kwargs.get('status', SessionStatus.ACTIVE.value),
            message_count=0,
            total_tokens=0,
            metadata=metadata_dict,
            preferences=preferences_dict,
            profile=profile_dict
        )
    
    def get_by_id(self, session_id: str) -> Optional[Session]:
        """根据 ID 获取会话"""
        with self.db.get_cursor() as cursor:
            cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            data = self._row_to_dict(row)
            data = self._parse_json_fields(data, self.JSON_FIELDS)
            
            # 安全解析 datetime
            def parse_datetime(val):
                if not val:
                    return datetime.now()
                try:
                    # 处理空格分隔的格式
                    if ' ' in str(val):
                        return datetime.strptime(str(val), '%Y-%m-%d %H:%M:%S.%f')
                    return datetime.fromisoformat(str(val))
                except:
                    return datetime.now()
            
            return Session(
                id=data['id'],
                user_id=data.get('user_id'),
                created_at=parse_datetime(data.get('created_at')),
                updated_at=parse_datetime(data.get('updated_at')),
                status=data.get('status', 'active'),
                message_count=data.get('message_count', 0),
                total_tokens=data.get('total_tokens', 0),
                metadata=data.get('metadata', {}),
                preferences=data.get('preferences', {}),
                profile=data.get('profile', {})
            )
    
    def update(self, session_id: str, **kwargs) -> Optional[Session]:
        """更新会话"""
        updates = []
        values = []
        
        for key in ['status', 'message_count', 'total_tokens', 'metadata', 'preferences', 'profile']:
            if key in kwargs:
                if key in self.JSON_FIELDS:
                    updates.append(f"{key} = ?")
                    values.append(to_json(kwargs[key]))
                else:
                    updates.append(f"{key} = ?")
                    values.append(kwargs[key])
        
        if not updates:
            return self.get_by_id(session_id)
        
        updates.append("updated_at = ?")
        values.append(str(datetime.now()))
        values.append(session_id)
        
        with self.db.get_cursor() as cursor:
            cursor.execute(f"""
                UPDATE sessions SET {', '.join(updates)} WHERE id = ?
            """, values)
            
            return self.get_by_id(session_id)
    
    def increment_message_count(self, session_id: str, tokens: int = 0):
        """增加消息计数"""
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                UPDATE sessions 
                SET message_count = message_count + 1,
                    total_tokens = total_tokens + ?,
                    updated_at = ?
                WHERE id = ?
            """, (tokens, str(datetime.now()), session_id))
    
    def list_sessions(
        self, 
        user_id: str = None, 
        status: str = None, 
        limit: int = 20, 
        offset: int = 0
    ) -> List[Session]:
        """列出会话"""
        conditions = []
        values = []
        
        if user_id:
            conditions.append("user_id = ?")
            values.append(user_id)
        
        if status:
            conditions.append("status = ?")
            values.append(status)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        with self.db.get_cursor() as cursor:
            cursor.execute(f"""
                SELECT * FROM sessions 
                WHERE {where_clause}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
            """, values + [limit, offset])
            
            sessions = []
            for row in cursor.fetchall():
                data = self._row_to_dict(row)
                data = self._parse_json_fields(data, self.JSON_FIELDS)
                sessions.append(Session(
                    id=data['id'],
                    user_id=data.get('user_id'),
                    created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now(),
                    updated_at=datetime.fromisoformat(data['updated_at']) if data.get('updated_at') else datetime.now(),
                    status=data.get('status', 'active'),
                    message_count=data.get('message_count', 0),
                    total_tokens=data.get('total_tokens', 0),
                    metadata=data.get('metadata', {}),
                    preferences=data.get('preferences', {}),
                    profile=data.get('profile', {})
                ))
            
            return sessions
    
    def delete(self, session_id: str) -> bool:
        """删除会话"""
        with self.db.get_cursor() as cursor:
            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return cursor.rowcount > 0


# =====================================================
# Message Repository
# =====================================================

class MessageRepository(BaseRepository):
    """消息仓储"""
    
    JSON_FIELDS = ['metadata']
    
    def create(self, session_id: str, role: str, content: str, **kwargs) -> Message:
        """创建消息"""
        now = datetime.now()
        now_str = str(now)
        metadata_dict = kwargs.get('metadata', {})
        
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO messages (session_id, role, content, content_type, created_at,
                                    token_count, latency_ms, metadata, intent, sentiment, parent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                role,
                content,
                kwargs.get('content_type', ContentType.TEXT.value),
                now_str,
                kwargs.get('token_count', 0),
                kwargs.get('latency_ms'),
                to_json(metadata_dict),
                kwargs.get('intent'),
                kwargs.get('sentiment'),
                kwargs.get('parent_id')
            ))
            
            message_id = cursor.lastrowid
        
        # 直接返回新创建的消息对象
        return Message(
            id=message_id,
            session_id=session_id,
            role=role,
            content=content,
            content_type=kwargs.get('content_type', ContentType.TEXT.value),
            created_at=now,
            token_count=kwargs.get('token_count', 0),
            latency_ms=kwargs.get('latency_ms'),
            metadata=metadata_dict,
            intent=kwargs.get('intent'),
            sentiment=kwargs.get('sentiment'),
            parent_id=kwargs.get('parent_id')
        )
    
    def get_by_id(self, message_id: int) -> Optional[Message]:
        """根据 ID 获取消息"""
        with self.db.get_cursor() as cursor:
            cursor.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return self._row_to_message(row)
    
    def _row_to_message(self, row: sqlite3.Row) -> Message:
        """将 Row 转换为 Message"""
        data = self._row_to_dict(row)
        data = self._parse_json_fields(data, self.JSON_FIELDS)
        
        return Message(
            id=data.get('id'),
            session_id=data.get('session_id', ''),
            role=data.get('role', 'user'),
            content=data.get('content', ''),
            content_type=data.get('content_type', 'text'),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now(),
            token_count=data.get('token_count', 0),
            latency_ms=data.get('latency_ms'),
            metadata=data.get('metadata', {}),
            intent=data.get('intent'),
            sentiment=data.get('sentiment'),
            parent_id=data.get('parent_id')
        )
    
    def list_by_session(
        self, 
        session_id: str, 
        role: str = None, 
        limit: int = 50,
        before: datetime = None
    ) -> List[Message]:
        """列出会话的消息"""
        conditions = ["session_id = ?"]
        values = [session_id]
        
        if role:
            conditions.append("role = ?")
            values.append(role)
        
        if before:
            conditions.append("created_at < ?")
            values.append(before)
        
        where_clause = " AND ".join(conditions)
        
        with self.db.get_cursor() as cursor:
            cursor.execute(f"""
                SELECT * FROM messages 
                WHERE {where_clause}
                ORDER BY created_at ASC
                LIMIT ?
            """, values + [limit])
            
            return [self._row_to_message(row) for row in cursor.fetchall()]
    
    def get_recent_messages(self, session_id: str, limit: int = 10) -> List[Message]:
        """获取最近的消息"""
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM messages 
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (session_id, limit))
            
            messages = [self._row_to_message(row) for row in cursor.fetchall()]
            return list(reversed(messages))


# =====================================================
# Entity Repository
# =====================================================

class EntityRepository(BaseRepository):
    """实体仓储"""
    
    JSON_FIELDS = ['entity_value', 'attributes']
    
    def create(self, session_id: str, entity_type: str, entity_name: str, **kwargs) -> Entity:
        """创建实体"""
        now = datetime.now()
        now_str = str(now)
        entity_value_dict = kwargs.get('entity_value', {})
        attributes_dict = kwargs.get('attributes', {})
        
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO entities (session_id, entity_type, entity_name, entity_value,
                                    confidence, mention_count, first_mentioned_at, 
                                    last_mentioned_at, is_active, is_verified, attributes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                entity_type,
                entity_name,
                to_json(entity_value_dict),
                kwargs.get('confidence', 1.0),
                1,
                now_str,
                now_str,
                1 if kwargs.get('is_active', True) else 0,
                1 if kwargs.get('is_verified', False) else 0,
                to_json(attributes_dict)
            ))
            
            entity_id = cursor.lastrowid
        
        # 直接返回新创建的实体对象
        return Entity(
            id=entity_id,
            session_id=session_id,
            entity_type=entity_type,
            entity_name=entity_name,
            entity_value=entity_value_dict,
            confidence=kwargs.get('confidence', 1.0),
            mention_count=1,
            first_mentioned_at=now,
            last_mentioned_at=now,
            is_active=kwargs.get('is_active', True),
            is_verified=kwargs.get('is_verified', False),
            attributes=attributes_dict
        )
    
    def get_by_id(self, entity_id: int) -> Optional[Entity]:
        """根据 ID 获取实体"""
        with self.db.get_cursor() as cursor:
            cursor.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return self._row_to_entity(row)
    
    def _row_to_entity(self, row: sqlite3.Row) -> Entity:
        """将 Row 转换为 Entity"""
        data = self._row_to_dict(row)
        data = self._parse_json_fields(data, self.JSON_FIELDS)
        
        return Entity(
            id=data.get('id'),
            session_id=data.get('session_id', ''),
            entity_type=data.get('entity_type', 'other'),
            entity_name=data.get('entity_name', ''),
            entity_value=data.get('entity_value', {}),
            confidence=data.get('confidence', 1.0),
            mention_count=data.get('mention_count', 1),
            first_mentioned_at=datetime.fromisoformat(data['first_mentioned_at']) if data.get('first_mentioned_at') else datetime.now(),
            last_mentioned_at=datetime.fromisoformat(data['last_mentioned_at']) if data.get('last_mentioned_at') else datetime.now(),
            is_active=bool(data.get('is_active', True)),
            is_verified=bool(data.get('is_verified', False)),
            attributes=data.get('attributes', {})
        )
    
    def find_or_create(
        self, 
        session_id: str, 
        entity_type: str, 
        entity_name: str, 
        **kwargs
    ) -> tuple[Entity, bool]:
        """查找或创建实体（如果存在则更新计数）"""
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM entities 
                WHERE session_id = ? AND entity_type = ? AND entity_name = ?
            """, (session_id, entity_type, entity_name))
            
            row = cursor.fetchone()
            
            if row:
                # 更新提及次数
                cursor.execute("""
                    UPDATE entities
                    SET mention_count = mention_count + 1,
                        last_mentioned_at = ?
                    WHERE id = ?
                """, (str(datetime.now()), row['id']))

                # 重新查询获取最新值（含新 mention_count）
                cursor.execute("""
                    SELECT * FROM entities WHERE id = ?
                """, (row['id'],))
                updated_row = cursor.fetchone()
                return self._row_to_entity(updated_row), False

            # 创建新实体
            return self.create(session_id, entity_type, entity_name, **kwargs), True
    
    def list_by_session(
        self, 
        session_id: str, 
        entity_type: str = None,
        active_only: bool = True
    ) -> List[Entity]:
        """列出会话的实体"""
        conditions = ["session_id = ?"]
        values = [session_id]
        
        if entity_type:
            conditions.append("entity_type = ?")
            values.append(entity_type)
        
        if active_only:
            conditions.append("is_active = 1")
        
        where_clause = " AND ".join(conditions)
        
        with self.db.get_cursor() as cursor:
            cursor.execute(f"""
                SELECT * FROM entities 
                WHERE {where_clause}
                ORDER BY last_mentioned_at DESC
            """, values)
            
            return [self._row_to_entity(row) for row in cursor.fetchall()]
    
    def update(self, entity_id: int, **kwargs) -> Optional[Entity]:
        """更新实体"""
        updates = []
        values = []
        
        for key in ['entity_value', 'attributes']:
            if key in kwargs:
                updates.append(f"{key} = ?")
                values.append(to_json(kwargs[key]))
        
        for key in ['is_active', 'is_verified', 'confidence']:
            if key in kwargs:
                if key in ['is_active', 'is_verified']:
                    updates.append(f"{key} = ?")
                    values.append(1 if kwargs[key] else 0)
                else:
                    updates.append(f"{key} = ?")
                    values.append(kwargs[key])
        
        if not updates:
            return self.get_by_id(entity_id)
        
        values.append(entity_id)
        
        with self.db.get_cursor() as cursor:
            cursor.execute(f"""
                UPDATE entities SET {', '.join(updates)} WHERE id = ?
            """, values)
            
            return self.get_by_id(entity_id)


# =====================================================
# ToolCall Repository
# =====================================================

class ToolCallRepository(BaseRepository):
    """工具调用仓储"""
    
    JSON_FIELDS = ['tool_input', 'tool_output']
    
    def create(self, session_id: str, tool_name: str, **kwargs) -> ToolCall:
        """创建工具调用记录"""
        now = datetime.now()
        now_str = str(now)
        tool_input_dict = kwargs.get('tool_input', {})
        tool_output_dict = kwargs.get('tool_output', {})
        
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO tool_calls (session_id, message_id, tool_name, tool_input, 
                                       tool_output, status, error_message, 
                                       execution_time_ms, call_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                kwargs.get('message_id'),
                tool_name,
                to_json(tool_input_dict),
                to_json(tool_output_dict),
                kwargs.get('status', ToolStatus.SUCCESS.value),
                kwargs.get('error_message'),
                kwargs.get('execution_time_ms'),
                kwargs.get('call_count', 1),
                now_str
            ))
            
            toolcall_id = cursor.lastrowid
        
        # 直接返回新创建的 ToolCall 对象
        return ToolCall(
            id=toolcall_id,
            session_id=session_id,
            message_id=kwargs.get('message_id'),
            tool_name=tool_name,
            tool_input=tool_input_dict,
            tool_output=tool_output_dict,
            status=kwargs.get('status', ToolStatus.SUCCESS.value),
            error_message=kwargs.get('error_message'),
            execution_time_ms=kwargs.get('execution_time_ms'),
            call_count=kwargs.get('call_count', 1),
            created_at=now
        )
    
    def get_by_id(self, toolcall_id: int) -> Optional[ToolCall]:
        """根据 ID 获取工具调用"""
        with self.db.get_cursor() as cursor:
            cursor.execute("SELECT * FROM tool_calls WHERE id = ?", (toolcall_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return self._row_to_toolcall(row)
    
    def _row_to_toolcall(self, row: sqlite3.Row) -> ToolCall:
        """将 Row 转换为 ToolCall"""
        data = self._row_to_dict(row)
        data = self._parse_json_fields(data, self.JSON_FIELDS)
        
        return ToolCall(
            id=data.get('id'),
            session_id=data.get('session_id', ''),
            message_id=data.get('message_id'),
            tool_name=data.get('tool_name', ''),
            tool_input=data.get('tool_input', {}),
            tool_output=data.get('tool_output', {}),
            status=data.get('status', 'success'),
            error_message=data.get('error_message'),
            execution_time_ms=data.get('execution_time_ms'),
            call_count=data.get('call_count', 1),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now()
        )
    
    def list_by_session(self, session_id: str, tool_name: str = None, limit: int = 50) -> List[ToolCall]:
        """列出工具调用"""
        conditions = ["session_id = ?"]
        values = [session_id]
        
        if tool_name:
            conditions.append("tool_name = ?")
            values.append(tool_name)
        
        where_clause = " AND ".join(conditions)
        
        with self.db.get_cursor() as cursor:
            cursor.execute(f"""
                SELECT * FROM tool_calls 
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
            """, values + [limit])
            
            return [self._row_to_toolcall(row) for row in cursor.fetchall()]
    
    def get_recent(self, session_id: str, limit: int = 5) -> List[ToolCall]:
        """获取最近的工具调用"""
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM tool_calls 
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (session_id, limit))
            
            return [self._row_to_toolcall(row) for row in cursor.fetchall()]
    
    def get_tool_usage_stats(self, session_id: str) -> Dict[str, int]:
        """获取工具使用统计"""
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                SELECT tool_name, COUNT(*) as call_count
                FROM tool_calls
                WHERE session_id = ?
                GROUP BY tool_name
                ORDER BY call_count DESC
            """, (session_id,))
            
            return {row['tool_name']: row['call_count'] for row in cursor.fetchall()}


# =====================================================
# Summary Repository
# =====================================================

class SummaryRepository(BaseRepository):
    """摘要仓储"""
    
    JSON_FIELDS = ['keywords', 'key_entities', 'action_items', 'completed_goals', 'pending_questions']
    
    def create(self, session_id: str, summary_content: str, **kwargs) -> Summary:
        """创建摘要"""
        now = datetime.now()
        now_str = str(now)
        
        # 预先获取所有 kwargs
        keywords_list = kwargs.get('keywords', [])
        key_entities_list = kwargs.get('key_entities', [])
        action_items_list = kwargs.get('action_items', [])
        completed_goals_list = kwargs.get('completed_goals', [])
        pending_questions_list = kwargs.get('pending_questions', [])
        
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO summaries (session_id, summary_type, summary_content, topic,
                                      keywords, key_entities, action_items, completed_goals,
                                      pending_questions, sentiment, sentiment_score,
                                      user_satisfaction, resolution_status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                kwargs.get('summary_type', SummaryType.AUTO.value),
                summary_content,
                kwargs.get('topic'),
                to_json(keywords_list),
                to_json(key_entities_list),
                to_json(action_items_list),
                to_json(completed_goals_list),
                to_json(pending_questions_list),
                kwargs.get('sentiment'),
                kwargs.get('sentiment_score'),
                kwargs.get('user_satisfaction'),
                kwargs.get('resolution_status'),
                now_str,
                now_str
            ))
            
            summary_id = cursor.lastrowid
        
        # 直接返回新创建的摘要对象
        return Summary(
            id=summary_id,
            session_id=session_id,
            summary_type=kwargs.get('summary_type', SummaryType.AUTO.value),
            summary_content=summary_content,
            topic=kwargs.get('topic'),
            keywords=keywords_list,
            key_entities=key_entities_list,
            action_items=action_items_list,
            completed_goals=completed_goals_list,
            pending_questions=pending_questions_list,
            sentiment=kwargs.get('sentiment'),
            sentiment_score=kwargs.get('sentiment_score'),
            user_satisfaction=kwargs.get('user_satisfaction'),
            resolution_status=kwargs.get('resolution_status'),
            created_at=now,
            updated_at=now
        )
    
    def get_by_id(self, summary_id: int) -> Optional[Summary]:
        """根据 ID 获取摘要"""
        with self.db.get_cursor() as cursor:
            cursor.execute("SELECT * FROM summaries WHERE id = ?", (summary_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return self._row_to_summary(row)
    
    def _row_to_summary(self, row: sqlite3.Row) -> Summary:
        """将 Row 转换为 Summary"""
        data = self._row_to_dict(row)
        data = self._parse_json_fields(data, self.JSON_FIELDS)
        
        return Summary(
            id=data.get('id'),
            session_id=data.get('session_id', ''),
            summary_type=data.get('summary_type', 'auto'),
            summary_content=data.get('summary_content', ''),
            topic=data.get('topic'),
            keywords=data.get('keywords', []),
            key_entities=data.get('key_entities', []),
            action_items=data.get('action_items', []),
            completed_goals=data.get('completed_goals', []),
            pending_questions=data.get('pending_questions', []),
            sentiment=data.get('sentiment'),
            sentiment_score=data.get('sentiment_score'),
            user_satisfaction=data.get('user_satisfaction'),
            resolution_status=data.get('resolution_status'),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now(),
            updated_at=datetime.fromisoformat(data['updated_at']) if data.get('updated_at') else datetime.now()
        )
    
    def get_latest(self, session_id: str) -> Optional[Summary]:
        """获取最新摘要"""
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM summaries 
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (session_id,))
            
            row = cursor.fetchone()
            return self._row_to_summary(row) if row else None
    
    def list_by_session(self, session_id: str, summary_type: str = None) -> List[Summary]:
        """列出会话的所有摘要"""
        conditions = ["session_id = ?"]
        values = [session_id]
        
        if summary_type:
            conditions.append("summary_type = ?")
            values.append(summary_type)
        
        where_clause = " AND ".join(conditions)
        
        with self.db.get_cursor() as cursor:
            cursor.execute(f"""
                SELECT * FROM summaries 
                WHERE {where_clause}
                ORDER BY created_at DESC
            """, values)
            
            return [self._row_to_summary(row) for row in cursor.fetchall()]
    
    def update(self, summary_id: int, **kwargs) -> Optional[Summary]:
        """更新摘要"""
        updates = []
        values = []
        
        for key in ['summary_content', 'topic', 'keywords', 'key_entities', 
                   'action_items', 'completed_goals', 'pending_questions']:
            if key in kwargs:
                updates.append(f"{key} = ?")
                values.append(to_json(kwargs[key]) if key in self.JSON_FIELDS else kwargs[key])
        
        for key in ['sentiment', 'sentiment_score', 'user_satisfaction', 'resolution_status']:
            if key in kwargs:
                updates.append(f"{key} = ?")
                values.append(kwargs[key])
        
        if not updates:
            return self.get_by_id(summary_id)
        
        updates.append("updated_at = ?")
        values.append(str(datetime.now()))
        values.append(summary_id)
        
        with self.db.get_cursor() as cursor:
            cursor.execute(f"""
                UPDATE summaries SET {', '.join(updates)} WHERE id = ?
            """, values)
            
            return self.get_by_id(summary_id)


# =====================================================
# 数据库单例访问
# =====================================================

_db_instance = None
_session_repo = None
_message_repo = None
_entity_repo = None
_toolcall_repo = None
_summary_repo = None


def get_db() -> DatabaseManager:
    """获取数据库实例"""
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseManager()
    return _db_instance


def get_session_repo() -> SessionRepository:
    """获取会话仓储"""
    global _session_repo
    if _session_repo is None:
        _session_repo = SessionRepository(get_db())
    return _session_repo


def get_message_repo() -> MessageRepository:
    """获取消息仓储"""
    global _message_repo
    if _message_repo is None:
        _message_repo = MessageRepository(get_db())
    return _message_repo


def get_entity_repo() -> EntityRepository:
    """获取实体仓储"""
    global _entity_repo
    if _entity_repo is None:
        _entity_repo = EntityRepository(get_db())
    return _entity_repo


def get_toolcall_repo() -> ToolCallRepository:
    """获取工具调用仓储"""
    global _toolcall_repo
    if _toolcall_repo is None:
        _toolcall_repo = ToolCallRepository(get_db())
    return _toolcall_repo


def get_summary_repo() -> SummaryRepository:
    """获取摘要仓储"""
    global _summary_repo
    if _summary_repo is None:
        _summary_repo = SummaryRepository(get_db())
    return _summary_repo


# =====================================================
# EntityRelation Repository (实体关系)
# =====================================================

class EntityRelationRepository(BaseRepository):
    """实体关系仓储"""
    
    def create(self, session_id: str, from_entity_id: int, to_entity_id: int, 
               relation_type: str, **kwargs) -> EntityRelation:
        """创建实体关系"""
        now = datetime.now()
        
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO entity_relations (session_id, from_entity_id, to_entity_id, 
                                          relation_type, strength, context, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                from_entity_id,
                to_entity_id,
                relation_type,
                kwargs.get('strength', 0.5),
                kwargs.get('context'),
                str(now)
            ))
            
            relation_id = cursor.lastrowid
        
        return EntityRelation(
            id=relation_id,
            session_id=session_id,
            from_entity_id=from_entity_id,
            to_entity_id=to_entity_id,
            relation_type=relation_type,
            strength=kwargs.get('strength', 0.5),
            context=kwargs.get('context'),
            created_at=now
        )
    
    def get_by_id(self, relation_id: int) -> Optional[EntityRelation]:
        """根据 ID 获取关系"""
        with self.db.get_cursor() as cursor:
            cursor.execute("SELECT * FROM entity_relations WHERE id = ?", (relation_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return self._row_to_relation(row)
    
    def _row_to_relation(self, row: sqlite3.Row) -> EntityRelation:
        """将 Row 转换为 EntityRelation"""
        data = self._row_to_dict(row)
        
        return EntityRelation(
            id=data.get('id'),
            session_id=data.get('session_id', ''),
            from_entity_id=data.get('from_entity_id', 0),
            to_entity_id=data.get('to_entity_id', 0),
            relation_type=data.get('relation_type', ''),
            strength=data.get('strength', 0.5),
            context=data.get('context'),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now()
        )
    
    def list_by_session(self, session_id: str, relation_type: str = None) -> List[EntityRelation]:
        """列出会话的关系"""
        conditions = ["session_id = ?"]
        values = [session_id]
        
        if relation_type:
            conditions.append("relation_type = ?")
            values.append(relation_type)
        
        where_clause = " AND ".join(conditions)
        
        with self.db.get_cursor() as cursor:
            cursor.execute(f"""
                SELECT * FROM entity_relations 
                WHERE {where_clause}
                ORDER BY strength DESC
            """, values)
            
            return [self._row_to_relation(row) for row in cursor.fetchall()]
    
    def list_by_entity(self, entity_id: int) -> List[EntityRelation]:
        """列出与某实体相关的所有关系"""
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM entity_relations 
                WHERE from_entity_id = ? OR to_entity_id = ?
                ORDER BY strength DESC
            """, (entity_id, entity_id))
            
            return [self._row_to_relation(row) for row in cursor.fetchall()]
    
    def find_relation(self, from_entity_id: int, to_entity_id: int, 
                    relation_type: str = None) -> Optional[EntityRelation]:
        """查找两个实体之间的关系"""
        conditions = ["from_entity_id = ? AND to_entity_id = ?"]
        values = [from_entity_id, to_entity_id]
        
        if relation_type:
            conditions.append("relation_type = ?")
            values.append(relation_type)
        
        where_clause = " AND ".join(conditions)
        
        with self.db.get_cursor() as cursor:
            cursor.execute(f"""
                SELECT * FROM entity_relations 
                WHERE {where_clause}
                LIMIT 1
            """, values)
            
            row = cursor.fetchone()
            return self._row_to_relation(row) if row else None
    
    def update_strength(self, relation_id: int, strength: float):
        """更新关系强度"""
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                UPDATE entity_relations SET strength = ? WHERE id = ?
            """, (strength, relation_id))
    
    def delete(self, relation_id: int) -> bool:
        """删除关系"""
        with self.db.get_cursor() as cursor:
            cursor.execute("DELETE FROM entity_relations WHERE id = ?", (relation_id,))
            return cursor.rowcount > 0


def get_relation_repo() -> EntityRelationRepository:
    """获取实体关系仓储"""
    global _relation_repo
    if _relation_repo is None:
        _relation_repo = EntityRelationRepository(get_db())
    return _relation_repo


_relation_repo = None


# =====================================================
# UserProfile Repository (用户画像)
# =====================================================

class UserProfileRepository(BaseRepository):
    """用户画像仓储"""
    
    JSON_FIELDS = ['preferences', 'favorite_tools', 'interests', 'expertise_areas', 'learned_preferences', 'common_intents']
    
    def create(self, user_id: str, **kwargs) -> UserProfile:
        """创建用户画像"""
        now = datetime.now()
        now_str = str(now)
        
        preferences_dict = kwargs.get('preferences', {})
        favorite_tools_list = kwargs.get('favorite_tools', [])
        interests_list = kwargs.get('interests', [])
        expertise_areas_list = kwargs.get('expertise_areas', [])
        learned_preferences_dict = kwargs.get('learned_preferences', {})
        common_intents_list = kwargs.get('common_intents', [])
        
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO user_profiles (user_id, display_name, language, preferences,
                                        total_sessions, total_messages, favorite_tools,
                                        interests, expertise_areas, learned_preferences,
                                        avg_session_length, most_active_hour, common_intents,
                                        created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                kwargs.get('display_name'),
                kwargs.get('language', 'zh-CN'),
                to_json(preferences_dict),
                0, 0,
                to_json(favorite_tools_list),
                to_json(interests_list),
                to_json(expertise_areas_list),
                to_json(learned_preferences_dict),
                None, None,
                to_json(common_intents_list),
                now_str,
                now_str
            ))
            
            profile_id = cursor.lastrowid
        
        return UserProfile(
            id=profile_id,
            user_id=user_id,
            display_name=kwargs.get('display_name'),
            language=kwargs.get('language', 'zh-CN'),
            preferences=preferences_dict,
            total_sessions=0,
            total_messages=0,
            favorite_tools=favorite_tools_list,
            interests=interests_list,
            expertise_areas=expertise_areas_list,
            learned_preferences=learned_preferences_dict,
            avg_session_length=None,
            most_active_hour=None,
            common_intents=common_intents_list,
            created_at=now,
            updated_at=now
        )
    
    def get_by_user_id(self, user_id: str) -> Optional[UserProfile]:
        """根据 user_id 获取用户画像"""
        with self.db.get_cursor() as cursor:
            cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return self._row_to_profile(row)
    
    def _row_to_profile(self, row: sqlite3.Row) -> UserProfile:
        """将 Row 转换为 UserProfile"""
        data = self._row_to_dict(row)
        data = self._parse_json_fields(data, self.JSON_FIELDS)
        
        def parse_datetime(val):
            if not val:
                return datetime.now()
            try:
                return datetime.fromisoformat(str(val))
            except:
                return datetime.now()
        
        return UserProfile(
            id=data.get('id'),
            user_id=data.get('user_id', ''),
            display_name=data.get('display_name'),
            language=data.get('language', 'zh-CN'),
            preferences=data.get('preferences', {}),
            total_sessions=data.get('total_sessions', 0),
            total_messages=data.get('total_messages', 0),
            favorite_tools=data.get('favorite_tools', []),
            interests=data.get('interests', []),
            expertise_areas=data.get('expertise_areas', []),
            learned_preferences=data.get('learned_preferences', {}),
            avg_session_length=data.get('avg_session_length'),
            most_active_hour=data.get('most_active_hour'),
            common_intents=data.get('common_intents', []),
            created_at=parse_datetime(data.get('created_at')),
            updated_at=parse_datetime(data.get('updated_at'))
        )
    
    def get_or_create(self, user_id: str) -> UserProfile:
        """获取或创建用户画像"""
        profile = self.get_by_user_id(user_id)
        if profile:
            return profile
        return self.create(user_id)
    
    def update(self, user_id: str, **kwargs) -> Optional[UserProfile]:
        """更新用户画像"""
        updates = []
        values = []
        
        for key in self.JSON_FIELDS:
            if key in kwargs:
                updates.append(f"{key} = ?")
                values.append(to_json(kwargs[key]))
        
        for key in ['display_name', 'language', 'avg_session_length', 'most_active_hour']:
            if key in kwargs:
                updates.append(f"{key} = ?")
                values.append(kwargs[key])
        
        if not updates:
            return self.get_by_user_id(user_id)
        
        updates.append("updated_at = ?")
        values.append(str(datetime.now()))
        values.append(user_id)
        
        with self.db.get_cursor() as cursor:
            cursor.execute(f"""
                UPDATE user_profiles SET {', '.join(updates)} WHERE user_id = ?
            """, values)
            
            return self.get_by_user_id(user_id)
    
    def increment_stats(self, user_id: str, sessions: int = 0, messages: int = 0):
        """增加统计计数"""
        with self.db.get_cursor() as cursor:
            cursor.execute("""
                UPDATE user_profiles 
                SET total_sessions = total_sessions + ?,
                    total_messages = total_messages + ?,
                    updated_at = ?
                WHERE user_id = ?
            """, (sessions, messages, str(datetime.now()), user_id))
    
    def add_learned_preference(self, user_id: str, key: str, value: Any):
        """添加学习到的偏好"""
        profile = self.get_by_user_id(user_id)
        if not profile:
            profile = self.create(user_id)
        
        prefs = profile.learned_preferences.copy()
        prefs[key] = value
        
        self.update(user_id, learned_preferences=prefs)
    
    def add_interest(self, user_id: str, interest: str):
        """添加兴趣"""
        profile = self.get_by_user_id(user_id)
        if not profile:
            profile = self.create(user_id)
        
        interests = list(profile.interests)
        if interest not in interests:
            interests.append(interest)
            self.update(user_id, interests=interests)
    
    def add_tool_usage(self, user_id: str, tool_name: str):
        """记录工具使用"""
        profile = self.get_by_user_id(user_id)
        if not profile:
            profile = self.create(user_id)
        
        tools = list(profile.favorite_tools)
        if tool_name not in tools:
            tools.append(tool_name)
            self.update(user_id, favorite_tools=tools[:10])  # 最多保留10个


def get_profile_repo() -> UserProfileRepository:
    """获取用户画像仓储"""
    global _profile_repo
    if _profile_repo is None:
        _profile_repo = UserProfileRepository(get_db())
    return _profile_repo


_profile_repo = None
