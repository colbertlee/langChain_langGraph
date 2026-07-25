# 结构化上下文持久化 - 设计文档

## 概述

本文档定义 AI Agent 的结构化上下文持久化系统，采用 **SQLite + JSON** 混合方案，支持复杂查询和分析。

> **状态**: ✅ 已实现所有阶段 (Phase 1-5)

---

## 一、系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      AI Agent                               │
├─────────────────────────────────────────────────────────────┤
│  ┌───────────┐    ┌───────────┐    ┌───────────┐           │
│  │   Input   │───>│ Processor │───>│  Output   │           │
│  │ Processor │    │           │    │ Generator │           │
│  └───────────┘    └───────────┘    └───────────┘           │
│       │                │                │                    │
│       ▼                ▼                ▼                    │
│  ┌─────────────────────────────────────────────┐           │
│  │         Context Manager (上下文管理器)        │           │
│  ├─────────────────────────────────────────────┤           │
│  │  • Entity Extraction (实体提取)              │           │
│  │  • Intent Classification (意图识别)          │           │
│  │  • Context Building (上下文构建)             │           │
│  │  • Summary Generation (摘要生成)             │           │
│  └─────────────────────────────────────────────┘           │
│                         │                                   │
└─────────────────────────┼───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   SQLite Database                            │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐       │
│  │sessions │  │messages │  │entities │  │  tools  │       │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘       │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐                    │
│  │summaries│  │relations│  │ analytics│                    │
│  └─────────┘  └─────────┘  └─────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、数据库 Schema

### 2.1 建表 SQL

```sql
-- =====================================================
-- 会话管理表
-- =====================================================
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'paused', 'completed', 'archived')),
    message_count INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    
    -- 核心元数据 (JSON)
    metadata TEXT DEFAULT '{}',
    
    -- 用户偏好
    preferences TEXT DEFAULT '{}',
    
    -- 用户画像
    profile TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at DESC);


-- =====================================================
-- 消息记录表
-- =====================================================
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    
    -- 内容
    content TEXT NOT NULL,
    content_type TEXT DEFAULT 'text' CHECK(content_type IN ('text', 'code', 'error', 'json', 'html')),
    
    -- 时间与性能
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    token_count INTEGER DEFAULT 0,
    latency_ms INTEGER,
    
    -- 消息元数据 (JSON)
    metadata TEXT DEFAULT '{}',
    
    -- 意图与情感
    intent TEXT,
    sentiment TEXT,
    
    -- 关联的消息（用于回复链）
    parent_id INTEGER REFERENCES messages(id),
    
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_intent ON messages(intent);


-- =====================================================
-- 实体提取表
-- =====================================================
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    
    -- 实体基本信息
    entity_type TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    entity_value TEXT DEFAULT '{}',  -- JSON 存储完整值
    
    -- 统计信息
    confidence REAL DEFAULT 1.0,
    mention_count INTEGER DEFAULT 1,
    first_mentioned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_mentioned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 状态
    is_active BOOLEAN DEFAULT TRUE,
    is_verified BOOLEAN DEFAULT FALSE,
    
    -- 扩展属性 (JSON)
    attributes TEXT DEFAULT '{}',
    
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_entities_session_type ON entities(session_id, entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_type_name ON entities(entity_type, entity_name);
CREATE INDEX IF NOT EXISTS idx_entities_active ON entities(is_active);
CREATE INDEX IF NOT EXISTS idx_entities_mentioned ON entities(last_mentioned_at DESC);


-- =====================================================
-- 工具调用记录表
-- =====================================================
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    message_id INTEGER,
    
    -- 调用信息
    tool_name TEXT NOT NULL,
    tool_input TEXT DEFAULT '{}',    -- JSON
    tool_output TEXT DEFAULT '{}',   -- JSON (摘要)
    
    -- 执行状态
    status TEXT DEFAULT 'success' CHECK(status IN ('success', 'error', 'timeout', 'cancelled')),
    error_message TEXT,
    execution_time_ms INTEGER,
    
    -- 统计
    call_count INTEGER DEFAULT 1,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_toolcalls_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_toolcalls_tool ON tool_calls(tool_name);
CREATE INDEX IF NOT EXISTS idx_toolcalls_status ON tool_calls(status);
CREATE INDEX IF NOT EXISTS idx_toolcalls_created ON tool_calls(created_at DESC);


-- =====================================================
-- 会话摘要表
-- =====================================================
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    
    -- 摘要类型
    summary_type TEXT DEFAULT 'auto' CHECK(summary_type IN ('auto', 'manual', 'milestone', 'final')),
    
    -- 摘要内容
    summary_content TEXT NOT NULL,
    
    -- 结构化摘要 (JSON)
    topic TEXT,                      -- 会话主题
    keywords TEXT DEFAULT '[]',      -- JSON array
    key_entities TEXT DEFAULT '[]',  -- JSON array
    
    -- 任务与操作
    action_items TEXT DEFAULT '[]',  -- JSON array: [{"task": "xxx", "status": "pending"}]
    completed_goals TEXT DEFAULT '[]',
    pending_questions TEXT DEFAULT '[]',
    
    -- 情感分析
    sentiment TEXT,
    sentiment_score REAL,
    
    -- 质量评估
    user_satisfaction REAL,
    resolution_status TEXT CHECK(resolution_status IN ('resolved', 'partial', 'unresolved', 'escalated')),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_summaries_session ON summaries(session_id);
CREATE INDEX IF NOT EXISTS idx_summaries_type ON summaries(summary_type);
CREATE INDEX IF NOT EXISTS idx_summaries_topic ON summaries(topic);


-- =====================================================
-- 实体关系表
-- =====================================================
CREATE TABLE IF NOT EXISTS entity_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    
    -- 关联的实体
    from_entity_id INTEGER NOT NULL,
    to_entity_id INTEGER NOT NULL,
    
    -- 关系类型
    relation_type TEXT NOT NULL,
    -- 关系类型选项:
    -- - similar_to: 相似
    -- - compared_with: 对比
    -- - part_of: 包含
    -- - caused_by: 导致
    -- - related_to: 相关
    -- - followed_by: 后续
    
    -- 关系强度 (0-1)
    strength REAL DEFAULT 0.5,
    
    -- 上下文（什么情况下产生这个关系）
    context TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (from_entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (to_entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_relations_session ON entity_relations(session_id);
CREATE INDEX IF NOT EXISTS idx_relations_from ON entity_relations(from_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_type ON entity_relations(relation_type);


-- =====================================================
-- 用户画像表（跨会话）
-- =====================================================
CREATE TABLE IF NOT EXISTS user_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT UNIQUE NOT NULL,
    
    -- 基本信息
    display_name TEXT,
    language TEXT DEFAULT 'zh-CN',
    
    -- 偏好设置
    preferences TEXT DEFAULT '{}',   -- JSON
    -- {"theme": "dark", "default_range": "30天", "risk_level": "中等"}
    
    -- 行为统计
    total_sessions INTEGER DEFAULT 0,
    total_messages INTEGER DEFAULT 0,
    favorite_tools TEXT DEFAULT '[]',
    
    -- 知识偏好
    interests TEXT DEFAULT '[]',     -- ["股票", "ETF", "基金"]
    expertise_areas TEXT DEFAULT '[]',
    
    -- 学习到的偏好 (从对话中提取)
    learned_preferences TEXT DEFAULT '{}',
    
    -- 统计指标
    avg_session_length INTEGER,     -- 平均会话长度
    most_active_hour INTEGER,       -- 最活跃时段
    common_intents TEXT DEFAULT '[]',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_profiles_user ON user_profiles(user_id);
```

---

## 三、Python 数据模型

### 3.1 基础模型

```python
# models/context_models.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


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


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    PARTIAL = "partial"
    UNRESOLVED = "unresolved"
    ESCALATED = "escalated"


# =====================================================
# 会话模型
# =====================================================
class SessionMetadata(BaseModel):
    """会话元数据"""
    source: Optional[str] = None           # 来源: web, api, cli
    channel: Optional[str] = None          # 渠道
    tags: List[str] = []


class UserPreferences(BaseModel):
    """用户偏好"""
    theme: str = "light"
    language: str = "zh-CN"
    default_etf_range: str = "30天"
    risk_level: Optional[str] = None
    notification_enabled: bool = True


class UserProfile(BaseModel):
    """用户画像"""
    risk_level: Optional[str] = None
    investment_exp: str = "未知"  # 有经验/初学者/专业
    investment_goal: Optional[str] = None
    preferred_etf_types: List[str] = []


class Session(BaseModel):
    """会话"""
    id: str
    user_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    status: SessionStatus = SessionStatus.ACTIVE
    message_count: int = 0
    total_tokens: int = 0
    metadata: SessionMetadata = Field(default_factory=SessionMetadata)
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    profile: UserProfile = Field(default_factory=UserProfile)
    
    class Config:
        use_enum_values = True


# =====================================================
# 消息模型
# =====================================================
class MessageMetadata(BaseModel):
    """消息元数据"""
    intent: Optional[str] = None
    intent_confidence: float = 1.0
    entities_found: List[str] = []
    language: str = "zh-CN"
    urgency: str = "normal"
    tags: List[str] = []


class Message(BaseModel):
    """消息"""
    id: Optional[int] = None
    session_id: str
    role: MessageRole
    content: str
    content_type: ContentType = ContentType.TEXT
    created_at: datetime = Field(default_factory=datetime.now)
    token_count: int = 0
    latency_ms: Optional[int] = None
    metadata: MessageMetadata = Field(default_factory=MessageMetadata)
    intent: Optional[str] = None
    sentiment: Optional[str] = None
    parent_id: Optional[int] = None
    
    class Config:
        use_enum_values = True


# =====================================================
# 实体模型
-- =====================================================
class EtfEntity(BaseModel):
    """ETF 实体"""
    code: str
    name: str
    type: Optional[str] = None


class StockEntity(BaseModel):
    """股票实体"""
    code: str
    name: str
    market: str  # A股, 港股, 美股


class CityEntity(BaseModel):
    """城市实体"""
    name: str
    country: Optional[str] = None
    weather: Optional[str] = None


class Entity(BaseModel):
    """实体"""
    id: Optional[int] = None
    session_id: str
    entity_type: EntityType
    entity_name: str
    entity_value: Dict[str, Any] = {}
    confidence: float = 1.0
    mention_count: int = 1
    first_mentioned_at: datetime = Field(default_factory=datetime.now)
    last_mentioned_at: datetime = Field(default_factory=datetime.now)
    is_active: bool = True
    is_verified: bool = False
    attributes: Dict[str, Any] = {}
    
    class Config:
        use_enum_values = True


# =====================================================
# 工具调用模型
# =====================================================
class ToolInput(BaseModel):
    """工具输入"""
    params: Dict[str, Any] = {}


class ToolOutput(BaseModel):
    """工具输出（摘要）"""
    success: bool = True
    result_type: Optional[str] = None
    record_count: Optional[int] = None
    summary: Optional[str] = None
    error: Optional[str] = None


class ToolCall(BaseModel):
    """工具调用"""
    id: Optional[int] = None
    session_id: str
    message_id: Optional[int] = None
    tool_name: str
    tool_input: ToolInput = Field(default_factory=ToolInput)
    tool_output: ToolOutput = Field(default_factory=ToolOutput)
    status: ToolStatus = ToolStatus.SUCCESS
    error_message: Optional[str] = None
    execution_time_ms: Optional[int] = None
    call_count: int = 1
    created_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        use_enum_values = True


# =====================================================
# 摘要模型
# =====================================================
class ActionItem(BaseModel):
    """待办事项"""
    task: str
    status: str = "pending"  # pending, completed, cancelled
    due_date: Optional[str] = None


class Summary(BaseModel):
    """会话摘要"""
    id: Optional[int] = None
    session_id: str
    summary_type: SummaryType = SummaryType.AUTO
    summary_content: str
    topic: Optional[str] = None
    keywords: List[str] = []
    key_entities: List[str] = []
    action_items: List[ActionItem] = []
    completed_goals: List[str] = []
    pending_questions: List[str] = []
    sentiment: Optional[str] = None
    sentiment_score: Optional[float] = None
    user_satisfaction: Optional[float] = None
    resolution_status: Optional[ResolutionStatus] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        use_enum_values = True


# =====================================================
# 实体关系模型
# =====================================================
class EntityRelation(BaseModel):
    """实体关系"""
    id: Optional[int] = None
    session_id: str
    from_entity_id: int
    to_entity_id: int
    relation_type: str  # similar_to, compared_with, part_of, etc.
    strength: float = 0.5
    context: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


# =====================================================
# 用户画像模型
# =====================================================
class LearnedPreference(BaseModel):
    """学习到的偏好"""
    key: str
    value: Any
    source: str  # explicit, implicit
    confidence: float = 1.0


class UserProfileFull(BaseModel):
    """完整用户画像"""
    id: Optional[int] = None
    user_id: str
    display_name: Optional[str] = None
    language: str = "zh-CN"
    preferences: Dict[str, Any] = {}
    total_sessions: int = 0
    total_messages: int = 0
    favorite_tools: List[str] = []
    interests: List[str] = []
    expertise_areas: List[str] = []
    learned_preferences: Dict[str, Any] = {}
    avg_session_length: Optional[int] = None
    most_active_hour: Optional[int] = None
    common_intents: List[str] = []
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
```

---

## 四、上下文注入策略

### 4.1 上下文构建流程

```python
class ContextBuilder:
    """上下文构建器"""
    
    def build_context(self, session_id: str, max_tokens: int = 4000) -> str:
        """
        构建结构化上下文用于注入 LLM
        """
        context_parts = []
        
        # 1. 会话摘要 (最重要，优先添加)
        summary = self.get_latest_summary(session_id)
        if summary:
            context_parts.append(self._build_summary_section(summary))
        
        # 2. 活跃实体 (次重要)
        entities = self.get_active_entities(session_id)
        if entities:
            context_parts.append(self._build_entities_section(entities))
        
        # 3. 最近工具调用 (了解用户行为)
        recent_tools = self.get_recent_tool_calls(session_id, limit=5)
        if recent_tools:
            context_parts.append(self._build_tools_section(recent_tools))
        
        # 4. 用户偏好 (如果可用)
        preferences = self.get_user_preferences(session_id)
        if preferences:
            context_parts.append(self._build_preferences_section(preferences))
        
        # 5. 截断确保不超 token 限制
        final_context = self._join_and_truncate(context_parts, max_tokens)
        
        return final_context
    
    def _build_summary_section(self, summary: Summary) -> str:
        """构建摘要部分"""
        parts = []
        if summary.topic:
            parts.append(f"会话主题: {summary.topic}")
        if summary.keywords:
            parts.append(f"关键词: {', '.join(summary.keywords)}")
        if summary.key_entities:
            parts.append(f"关键实体: {', '.join(summary.key_entities)}")
        if summary.completed_goals:
            parts.append(f"已完成目标: {', '.join(summary.completed_goals)}")
        if summary.pending_questions:
            parts.append(f"待解决问题: {', '.join(summary.pending_questions)}")
        return "【会话摘要】\n" + "\n".join(parts)
    
    def _build_entities_section(self, entities: List[Entity]) -> str:
        """构建实体部分"""
        # 按类型分组
        by_type = defaultdict(list)
        for e in entities:
            by_type[e.entity_type].append(e.entity_name)
        
        parts = []
        for etype, names in by_type.items():
            parts.append(f"{etype}: {', '.join(set(names))}")
        
        return "【当前上下文中的实体】\n" + "\n".join(parts)
    
    def _build_tools_section(self, tools: List[ToolCall]) -> str:
        """构建工具部分"""
        tool_names = [t.tool_name for t in tools]
        return f"【最近使用的工具】\n{', '.join(tool_names)}"
    
    def _build_preferences_section(self, preferences: dict) -> str:
        """构建偏好部分"""
        parts = []
        for key, value in preferences.items():
            parts.append(f"{key}: {value}")
        return "【用户偏好】\n" + "\n".join(parts)
```

### 4.2 自动摘要策略

```python
class AutoSummarizer:
    """自动摘要生成器"""
    
    def should_generate_summary(self, session: Session) -> bool:
        """
        判断是否需要生成摘要
        """
        # 每 10 条消息生成一次
        if session.message_count % 10 == 0:
            return True
        
        # 会话超过 30 分钟
        elapsed = datetime.now() - session.updated_at
        if elapsed > timedelta(minutes=30):
            return True
        
        # 会话结束
        if session.status == SessionStatus.COMPLETED:
            return True
        
        return False
    
    def generate_summary(self, session_id: str, messages: List[Message]) -> Summary:
        """
        生成会话摘要
        """
        # 1. 提取关键词
        keywords = self._extract_keywords(messages)
        
        # 2. 提取关键实体
        key_entities = self._extract_key_entities(messages)
        
        # 3. 识别会话主题
        topic = self._identify_topic(messages)
        
        # 4. 识别已完成的目标
        completed_goals = self._extract_completed_goals(messages)
        
        # 5. 识别待解决问题
        pending_questions = self._extract_pending_questions(messages)
        
        # 6. 生成摘要文本
        summary_content = self._generate_summary_text(
            topic, keywords, completed_goals, pending_questions
        )
        
        return Summary(
            session_id=session_id,
            summary_type=SummaryType.AUTO,
            summary_content=summary_content,
            topic=topic,
            keywords=keywords,
            key_entities=key_entities,
            completed_goals=completed_goals,
            pending_questions=pending_questions
        )
```

---

## 五、API 接口设计

### 5.1 会话管理 API

```python
# API 路径: /api/context/

class SessionAPI:
    """会话管理 API"""
    
    # 创建会话
    @app.post("/api/context/sessions")
    async def create_session(user_id: Optional[str] = None) -> Session:
        """
        创建新会话
        POST /api/context/sessions
        Body: {"user_id": "xxx"} (optional)
        """
        pass
    
    # 获取会话
    @app.get("/api/context/sessions/{session_id}")
    async def get_session(session_id: str) -> Session:
        """
        获取会话详情
        GET /api/context/sessions/{session_id}
        """
        pass
    
    # 更新会话
    @app.patch("/api/context/sessions/{session_id}")
    async def update_session(
        session_id: str,
        status: Optional[str] = None,
        preferences: Optional[dict] = None
    ) -> Session:
        """
        更新会话状态/偏好
        PATCH /api/context/sessions/{session_id}
        """
        pass
    
    # 列表会话
    @app.get("/api/context/sessions")
    async def list_sessions(
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[Session]:
        """
        列出用户会话
        GET /api/context/sessions?user_id=xxx&status=active
        """
        pass
    
    # 删除会话
    @app.delete("/api/context/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict:
        """
        删除会话及关联数据
        DELETE /api/context/sessions/{session_id}
        """
        pass
```

### 5.2 消息 API

```python
class MessageAPI:
    """消息 API"""
    
    # 发送消息（核心接口）
    @app.post("/api/context/sessions/{session_id}/messages")
    async def send_message(
        session_id: str,
        content: str,
        role: str = "user",
        metadata: Optional[dict] = None
    ) -> Message:
        """
        发送消息并自动处理：
        1. 实体提取
        2. 意图识别
        3. 工具调用
        4. 上下文更新
        5. 摘要生成（触发时）
        
        POST /api/context/sessions/{session_id}/messages
        """
        pass
    
    # 获取消息历史
    @app.get("/api/context/sessions/{session_id}/messages")
    async def get_messages(
        session_id: str,
        role: Optional[str] = None,
        limit: int = 50,
        before: Optional[datetime] = None
    ) -> List[Message]:
        """
        获取会话消息
        GET /api/context/sessions/{session_id}/messages
        """
        pass
```

### 5.3 实体 API

```python
class EntityAPI:
    """实体 API"""
    
    # 获取活跃实体
    @app.get("/api/context/sessions/{session_id}/entities")
    async def get_entities(
        session_id: str,
        entity_type: Optional[str] = None,
        active_only: bool = True
    ) -> List[Entity]:
        """
        获取会话中的实体
        GET /api/context/sessions/{session_id}/entities?entity_type=etf
        """
        pass
    
    # 更新实体状态
    @app.patch("/api/context/entities/{entity_id}")
    async def update_entity(
        entity_id: int,
        is_active: Optional[bool] = None,
        entity_value: Optional[dict] = None
    ) -> Entity:
        """
        更新实体（如确认 ETF 代码）
        PATCH /api/context/entities/{entity_id}
        """
        pass
```

### 5.4 摘要 API

```python
class SummaryAPI:
    """摘要 API"""
    
    # 获取最新摘要
    @app.get("/api/context/sessions/{session_id}/summary")
    async def get_latest_summary(session_id: str) -> Summary:
        """
        获取会话最新摘要
        GET /api/context/sessions/{session_id}/summary
        """
        pass
    
    # 生成/更新摘要
    @app.post("/api/context/sessions/{session_id}/summary")
    async def generate_summary(
        session_id: str,
        summary_type: str = "auto"
    ) -> Summary:
        """
        手动触发摘要生成
        POST /api/context/sessions/{session_id}/summary
        """
        pass
    
    # 获取摘要历史
    @app.get("/api/context/sessions/{session_id}/summaries")
    async def get_summaries(session_id: str) -> List[Summary]:
        """
        获取会话的所有摘要
        GET /api/context/sessions/{session_id}/summaries
        """
        pass
```

### 5.5 分析 API

```python
class AnalyticsAPI:
    """分析 API"""
    
    # 获取会话统计
    @app.get("/api/context/sessions/{session_id}/analytics")
    async def get_session_analytics(session_id: str) -> dict:
        """
        获取会话统计
        GET /api/context/sessions/{session_id}/analytics
        返回：
        {
            "total_messages": 50,
            "total_tools_calls": 15,
            "entity_count": 8,
            "avg_response_time_ms": 1200,
            "tool_usage": {"get_etf_info": 5, "compare_etfs": 3}
        }
        """
        pass
    
    # 获取用户画像
    @app.get("/api/context/users/{user_id}/profile")
    async def get_user_profile(user_id: str) -> UserProfileFull:
        """
        获取用户画像
        GET /api/context/users/{user_id}/profile
        """
        pass
    
    # 搜索历史会话
    @app.get("/api/context/search")
    async def search_sessions(
        query: str,
        user_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 20
    ) -> List[Session]:
        """
        搜索历史会话
        GET /api/context/search?query=ETF&entity_type=etf
        """
        pass
```

---

## 六、实现计划

### Phase 1: 基础框架 (预计 1-2 天)

| 任务 | 描述 | 优先级 |
|------|------|--------|
| 创建数据库 Schema | 实现所有建表 SQL | P0 |
| 实现基础 Repository | CRUD 操作封装 | P0 |
| 实现 Session 管理 | 创建/更新/删除会话 | P0 |
| 实现 Message 记录 | 消息存储和查询 | P0 |
| 单元测试 | 基础功能测试 | P1 |

### Phase 2: 实体与工具 (预计 1 天)

| 任务 | 描述 | 优先级 |
|------|------|--------|
| 实现 Entity Repository | 实体 CRUD | P0 |
| 实现 Entity 提取器 | 从消息中提取实体 | P0 |
| 实现 ToolCall 记录 | 工具调用记录 | P0 |
| 实现 Entity 关系管理 | 实体关联 | P1 |

### Phase 3: 摘要与上下文 (预计 1-2 天)

| 任务 | 描述 | 优先级 |
|------|------|--------|
| 实现 Summary Repository | 摘要 CRUD | P0 |
| 实现自动摘要生成 | 定时/触发生成 | P0 |
| 实现 ContextBuilder | 上下文构建器 | P0 |
| 集成到 Agent | 替换现有 memory | P0 |

### Phase 4: 高级功能 (预计 2-3 天)

| 任务 | 描述 | 优先级 |
|------|------|--------|
| 实现用户画像 | UserProfile | P1 |
| 实现分析 API | 统计报表 | P1 |
| 实现搜索功能 | 历史检索 | P1 |
| 性能优化 | 索引优化、缓存 | P2 |

### Phase 5: 生产就绪 (预计 1-2 天)

| 任务 | 描述 | 优先级 |
|------|------|--------|
| 错误处理 | 异常情况处理 | P0 |
| 日志记录 | 完整日志 | P1 |
| 监控指标 | 关键指标埋点 | P2 |
| 文档完善 | API 文档 | P1 |

---

## 七、向后兼容

### 保留现有接口

```python
# 现有接口保持不变，内部改为调用新系统

class AIAgent:
    def run(self, user_input: str) -> str:
        # 获取或创建会话
        session = self.context_manager.get_or_create_session()
        
        # 记录消息
        message = self.context_manager.add_message(
            session_id=session.id,
            role="user",
            content=user_input
        )
        
        # 构建上下文
        context = self.context_manager.build_context(session.id)
        
        # 调用 LLM
        response = self.llm.invoke(context)
        
        # 记录响应
        self.context_manager.add_message(
            session_id=session.id,
            role="assistant",
            content=response
        )
        
        return response
```

---

## 八、数据迁移

```sql
-- 从现有 memory.db 迁移数据

-- 1. 导出现有消息
SELECT * FROM messages;

-- 2. 插入到新表
INSERT INTO messages (session_id, role, content, created_at)
SELECT 'default_session', role, content, created_at
FROM old_messages;

-- 3. 清理
DROP TABLE IF EXISTS old_messages;
```

---

## 九、验收标准

### 功能验收

- [ ] 会话创建、查询、更新、删除正常
- [ ] 消息记录和历史查询正常
- [ ] 实体提取和关联正常
- [ ] 工具调用记录正常
- [ ] 自动摘要生成正常
- [ ] 上下文注入到 LLM 正常

### 性能验收

- [ ] 单次消息响应时间 < 100ms
- [ ] 上下文构建时间 < 200ms
- [ ] 支持 10000+ 条消息的会话

### 兼容性验收

- [ ] 现有 Agent 代码无需修改即可运行
- [ ] 历史数据可以迁移

---

*文档版本: 1.0*
*创建日期: 2026-07-19*
*作者: AI Assistant*
