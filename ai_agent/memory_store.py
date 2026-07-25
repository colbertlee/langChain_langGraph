"""
结构化记忆存储 - 短期记忆与长期记忆统一管理
支持工作记忆窗口、注意力机制、记忆衰减、语义检索
"""
import sqlite3
import json
import hashlib
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
import threading

logger = logging.getLogger(__name__)


class MemoryType(str, Enum):
    """记忆类型"""
    WORKING = "working"      # 工作记忆（当前交互）
    EPISODIC = "episodic"    # 情景记忆（会话片段）
    SEMANTIC = "semantic"    # 语义记忆（知识沉淀）
    PROCEDURAL = "procedural" # 程序记忆（操作流程）


class MemoryImportance(int, Enum):
    """记忆重要性等级"""
    LOW = 1      # 普通信息
    MEDIUM = 2   # 中等重要
    HIGH = 3     # 高重要
    CRITICAL = 4 # 关键信息（保留更久）


@dataclass
class MemoryItem:
    """记忆项"""
    id: Optional[int] = None
    memory_type: str = MemoryType.WORKING.value
    content: str = ""
    content_embedding: Optional[List[float]] = None  # 向量表示
    importance: int = MemoryImportance.MEDIUM.value
    session_id: str = ""
    message_id: Optional[int] = None
    
    # 元信息
    keywords: List[str] = field(default_factory=list)
    entities: List[Dict[str, str]] = field(default_factory=list)
    intent: Optional[str] = None
    
    # 时间与衰减
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    access_count: int = 1
    
    # 衰减参数
    decay_base: float = 0.95  # 基础衰减率
    decay_factor: float = 1.0  # 当前衰减因子
    
    # 状态
    is_pinned: bool = False  # 固定记忆（不淘汰）
    is_archived: bool = False  # 已归档到长期记忆
    metadata: Dict[str, Any] = field(default_factory=dict)


class MemoryDatabase:
    """记忆数据库管理器"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, db_path: str = None):
        with cls._lock:
            if db_path:
                instance = super().__new__(cls)
                instance._db_path = db_path
                instance._initialized = False
                instance._init_db()
                instance._initialized = True
                return instance
            
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._db_path = "memory_store.db"
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self, db_path: str = None):
        if getattr(self, '_initialized', False):
            return
        if db_path:
            self._db_path = db_path
        self._init_db()
        self._initialized = True
    
    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    
    def _init_db(self):
        """初始化数据库"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 记忆主表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_embedding TEXT,
                    importance INTEGER DEFAULT 2,
                    session_id TEXT NOT NULL,
                    message_id INTEGER,
                    
                    keywords TEXT DEFAULT '[]',
                    entities TEXT DEFAULT '[]',
                    intent TEXT,
                    
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    access_count INTEGER DEFAULT 1,
                    
                    decay_base REAL DEFAULT 0.95,
                    decay_factor REAL DEFAULT 1.0,
                    
                    is_pinned INTEGER DEFAULT 0,
                    is_archived INTEGER DEFAULT 0,
                    metadata TEXT DEFAULT '{}'
                )
            """)
            
            # 记忆索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_decay ON memories(decay_factor)")
            
            # 长期记忆向量表（用于语义检索）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS semantic_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id INTEGER NOT NULL,
                    session_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    content_embedding BLOB NOT NULL,
                    summary TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    use_count INTEGER DEFAULT 0,
                    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
                )
            """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_semantic_hash ON semantic_memory(content_hash)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_semantic_session ON semantic_memory(session_id)")
            
            # 记忆关系表（记忆之间的关联）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_memory_id INTEGER NOT NULL,
                    to_memory_id INTEGER NOT NULL,
                    relation_type TEXT NOT NULL,
                    strength REAL DEFAULT 0.5,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (from_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                    FOREIGN KEY (to_memory_id) REFERENCES memories(id) ON DELETE CASCADE
                )
            """)
            
            conn.commit()
            logger.info("Memory database initialized")


class ShortTermMemory:
    """短期记忆 - 工作记忆窗口"""
    
    def __init__(
        self,
        db: MemoryDatabase,
        max_size: int = 50,
        decay_threshold: float = 0.1,
        consolidation_interval: int = 10
    ):
        self.db = db
        self.max_size = max_size
        self.decay_threshold = decay_threshold
        self.consolidation_interval = consolidation_interval
        
        # 内存中的工作记忆缓存
        self._working_cache: deque = deque(maxlen=max_size)
        self._importance_weights = {
            MemoryImportance.CRITICAL.value: 1.0,
            MemoryImportance.HIGH.value: 0.8,
            MemoryImportance.MEDIUM.value: 0.5,
            MemoryImportance.LOW.value: 0.3
        }
    
    def add(
        self,
        content: str,
        session_id: str,
        importance: int = MemoryImportance.MEDIUM.value,
        memory_type: str = MemoryType.WORKING.value,
        **kwargs
    ) -> MemoryItem:
        """添加工作记忆"""
        now = datetime.now()
        
        item = MemoryItem(
            memory_type=memory_type,
            content=content,
            importance=importance,
            session_id=session_id,
            created_at=now,
            last_accessed=now,
            decay_factor=self._calculate_initial_decay(importance),
            **kwargs
        )
        
        # 保存到数据库
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO memories 
                (memory_type, content, importance, session_id, message_id, keywords, 
                 entities, intent, decay_base, decay_factor, is_pinned, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.memory_type,
                item.content,
                item.importance,
                item.session_id,
                item.message_id,
                json.dumps(item.keywords, ensure_ascii=False),
                json.dumps(item.entities, ensure_ascii=False),
                item.intent,
                item.decay_base,
                item.decay_factor,
                1 if item.is_pinned else 0,
                json.dumps(item.metadata, ensure_ascii=False)
            ))
            item.id = cursor.lastrowid
        
        # 添加到内存缓存
        self._working_cache.append(item)

        # 检查是否需要触发整合（仅查询候选，真正迁移由 MemoryConsolidator.consolidate 完成）
        if len(self._working_cache) >= self.consolidation_interval:
            self._select_consolidation_candidates(session_id)

        return item
    
    def _calculate_initial_decay(self, importance: int) -> float:
        """计算初始衰减因子"""
        weight = self._importance_weights.get(importance, 0.5)
        return 1.0 - (1.0 - weight) * 0.5
    
    def get_recent(self, session_id: str, limit: int = 10) -> List[MemoryItem]:
        """获取最近的记忆（按衰减调整）"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM memories
                WHERE session_id = ? AND is_archived = 0
                ORDER BY decay_factor DESC, created_at DESC
                LIMIT ?
            """, (session_id, limit))
            
            return [self._row_to_memory(row) for row in cursor.fetchall()]
    
    def get_attention_focused(self, session_id: str, query: str = None) -> List[MemoryItem]:
        """获取注意力聚焦的记忆"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            
            if query:
                # 基于相关性和重要性加权
                cursor.execute("""
                    SELECT * FROM memories
                    WHERE session_id = ? AND is_archived = 0
                    AND (
                        content LIKE ? 
                        OR keywords LIKE ?
                        OR intent = ?
                    )
                    ORDER BY importance DESC, decay_factor DESC, created_at DESC
                    LIMIT 15
                """, (session_id, f"%{query[:20]}%", f"%{query[:20]}%", query[:50] if query else ""))
            else:
                cursor.execute("""
                    SELECT * FROM memories
                    WHERE session_id = ? AND is_archived = 0
                    ORDER BY (decay_factor * importance / 4.0) DESC
                    LIMIT 15
                """, (session_id,))
            
            return [self._row_to_memory(row) for row in cursor.fetchall()]
    
    def apply_decay(self, session_id: str):
        """对记忆应用时间衰减"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE memories
                SET decay_factor = decay_factor * decay_base * 0.99,
                    last_accessed = ?
                WHERE session_id = ? AND is_pinned = 0 AND is_archived = 0
            """, (datetime.now(), session_id))
    
    def _select_consolidation_candidates(self, session_id: str):
        """筛选可整合的候选记忆。

        修复 C7：本方法仅负责选取候选，**不会**执行迁移。
        真正迁移由 MemoryConsolidator.consolidate(session_id) 完成。
        调用方（agent.py）应周期性地主动调用 consolidate。
        """
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM memories
                WHERE session_id = ?
                AND is_archived = 0
                AND importance >= ?
                AND decay_factor >= ?
                ORDER BY importance DESC, created_at ASC
            """, (session_id, MemoryImportance.HIGH.value, 0.3))

            candidates = [self._row_to_memory(row) for row in cursor.fetchall()]

        logger.info(
            f"Consolidation candidates selected for session {session_id}: {len(candidates)}"
        )
        return candidates
    
    def _row_to_memory(self, row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=row['id'],
            memory_type=row['memory_type'],
            content=row['content'],
            importance=row['importance'],
            session_id=row['session_id'],
            message_id=row['message_id'],
            keywords=json.loads(row['keywords'] or '[]'),
            entities=json.loads(row['entities'] or '[]'),
            intent=row['intent'],
            created_at=datetime.fromisoformat(row['created_at']),
            last_accessed=datetime.fromisoformat(row['last_accessed']),
            access_count=row['access_count'],
            decay_base=row['decay_base'],
            decay_factor=row['decay_factor'],
            is_pinned=bool(row['is_pinned']),
            is_archived=bool(row['is_archived']),
            metadata=json.loads(row['metadata'] or '{}')
        )


class LongTermMemory:
    """长期记忆 - 语义记忆与情景记忆"""

    # 修复 C4：声明 fallback embedding 维度，便于 retrieve 校验一致性
    FALLBACK_EMBEDDING_DIM = 128

    def __init__(self, db: MemoryDatabase, embedding_model=None):
        self.db = db
        self.embedding_model = embedding_model
        self._semantic_cache: Dict[str, List[float]] = {}
        self._embedding_dim: Optional[int] = None  # 运行时探测实际维度
    
    def store(
        self,
        content: str,
        session_id: str,
        memory_type: str = MemoryType.SEMANTIC.value,
        importance: int = MemoryImportance.MEDIUM.value,
        **kwargs
    ) -> MemoryItem:
        """存储长期记忆"""
        now = datetime.now()
        
        # 生成向量表示
        embedding = self._generate_embedding(content)
        
        item = MemoryItem(
            memory_type=memory_type,
            content=content,
            content_embedding=embedding,
            importance=importance,
            session_id=session_id,
            created_at=now,
            is_archived=True,
            **kwargs
        )
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO memories 
                (memory_type, content, content_embedding, importance, session_id,
                 keywords, entities, intent, is_archived, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.memory_type,
                item.content,
                json.dumps(embedding) if embedding else None,
                item.importance,
                item.session_id,
                json.dumps(item.keywords, ensure_ascii=False),
                json.dumps(item.entities, ensure_ascii=False),
                item.intent,
                1,
                json.dumps(item.metadata, ensure_ascii=False)
            ))
            item.id = cursor.lastrowid
            
            # 同时存储到语义记忆表
            if embedding:
                try:
                    import numpy as np
                    cursor.execute("""
                        INSERT INTO semantic_memory 
                        (memory_id, session_id, content_hash, content_embedding, summary)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        item.id,
                        session_id,
                        str(hash(content)),
                        np.array(embedding).tobytes(),
                        content[:200]
                    ))
                except ImportError:
                    logger.warning("numpy not available, skipping vector storage")
        
        return item
    
    def retrieve(
        self,
        query: str,
        session_id: str = None,
        limit: int = 5,
        memory_type: str = None
    ) -> List[Tuple[MemoryItem, float]]:
        """语义检索长期记忆"""
        query_embedding = self._generate_embedding(query)
        if not query_embedding:
            return []
        
        try:
            import numpy as np
            query_vec = np.array(query_embedding)
        except ImportError:
            query_vec = None
        
        conditions = ["m.is_archived = 1"]
        params = []
        
        if session_id:
            conditions.append("m.session_id = ?")
            params.append(session_id)
        
        if memory_type:
            conditions.append("m.memory_type = ?")
            params.append(memory_type)
        
        where_clause = " AND ".join(conditions)
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT 
                    m.id, m.memory_type, m.content, m.importance, m.session_id,
                    m.message_id, m.keywords, m.entities, m.intent, m.created_at,
                    m.last_accessed, m.access_count, m.decay_base, m.decay_factor,
                    m.is_pinned, m.is_archived, m.metadata,
                    sm.content_embedding
                FROM memories m
                LEFT JOIN semantic_memory sm ON m.id = sm.memory_id
                WHERE {where_clause}
                ORDER BY m.importance DESC, m.created_at DESC
            """, params)
            
            results = []
            for row in cursor.fetchall():
                item = MemoryItem(
                    id=row['id'],
                    memory_type=row['memory_type'],
                    content=row['content'],
                    importance=row['importance'],
                    session_id=row['session_id'],
                    keywords=json.loads(row['keywords'] or '[]'),
                    intent=row['intent'],
                    created_at=datetime.fromisoformat(row['created_at']),
                    is_archived=True
                )
                
                # 计算相似度
                if query_vec is not None and row['content_embedding']:
                    try:
                        stored_vec = np.frombuffer(row['content_embedding'], dtype=np.float32)
                        # 修复 C4：维度不一致时跳过向量相似度，降级到关键词相似度
                        if query_vec.shape[0] != stored_vec.shape[0]:
                            similarity = self._keyword_similarity(query, item.content)
                        else:
                            similarity = float(np.dot(query_vec, stored_vec) /
                                             (np.linalg.norm(query_vec) * np.linalg.norm(stored_vec) + 1e-8))
                        results.append((item, similarity))
                    except Exception:
                        similarity = self._keyword_similarity(query, item.content)
                        results.append((item, similarity))
                else:
                    similarity = self._keyword_similarity(query, item.content)
                    results.append((item, similarity))
            
            # 按相似度排序
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:limit]
    
    def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """生成文本向量，并记录实际维度（修复 C4：维度一致性）。"""
        if self.embedding_model:
            try:
                vec = self.embedding_model.embed_query(text)
                if vec:
                    self._embedding_dim = len(vec)
                return vec
            except Exception as e:
                logger.warning(f"Embedding generation failed: {e}")

        vec = self._simple_embedding(text)
        self._embedding_dim = len(vec)
        return vec
    
    def _simple_embedding(self, text: str, dim: int = 128) -> List[float]:
        """简单词袋向量（无嵌入模型时使用）"""
        words = set(text.lower().split())
        vec = [0.0] * dim
        
        for i, word in enumerate(words):
            hash_val = int(hashlib.md5(word.encode()).hexdigest(), 16)
            for j in range(dim):
                vec[j] += (hash_val >> ((i * 4 + j) % 32)) & 0xFF
        
        # 归一化
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm if norm > 0 else 0 for v in vec]
    
    def _keyword_similarity(self, query: str, content: str) -> float:
        """关键词相似度"""
        query_words = set(query.lower().split())
        content_words = set(content.lower().split())
        
        if not query_words:
            return 0.0
        
        intersection = query_words & content_words
        return len(intersection) / len(query_words)
    
    def get_episodic(self, session_id: str, limit: int = 10) -> List[MemoryItem]:
        """获取情景记忆（会话片段）"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM memories
                WHERE session_id = ? AND memory_type = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (session_id, MemoryType.EPISODIC.value, limit))
            
            results = []
            for row in cursor.fetchall():
                results.append(MemoryItem(
                    id=row['id'],
                    memory_type=row['memory_type'],
                    content=row['content'],
                    importance=row['importance'],
                    session_id=row['session_id'],
                    keywords=json.loads(row['keywords'] or '[]'),
                    created_at=datetime.fromisoformat(row['created_at']),
                    is_archived=True
                ))
            return results


class MemoryConsolidator:
    """记忆整合器 - 管理短期记忆向长期记忆的迁移"""
    
    def __init__(self, short_term: ShortTermMemory, long_term: LongTermMemory):
        self.short_term = short_term
        self.long_term = long_term
        
        # 整合阈值
        self.min_importance_threshold = MemoryImportance.HIGH.value
        self.min_decay_threshold = 0.3
    
    def consolidate(self, session_id: str) -> int:
        """执行记忆整合，返回迁移的记忆数量。

        修复 C5：原实现对每条候选都调用 long_term.retrieve()，等于
        N × 全表扫描。现改为：先一次性拉取 session 范围内所有长期记忆，
        在内存中用关键词相似度做去重判断，避免 N 次 SQL。
        """
        consolidated_count = 0

        # 获取需要迁移的候选
        with self.short_term.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM memories
                WHERE session_id = ?
                AND is_archived = 0
                AND (importance >= ? OR is_pinned = 1)
                AND decay_factor >= ?
            """, (session_id, self.min_importance_threshold, self.min_decay_threshold))

            candidates = [self.short_term._row_to_memory(row) for row in cursor.fetchall()]

        # 一次性预加载长期记忆库到内存（修复 C5：避免 N 次 SQL）
        existing_corpus = self._load_long_term_corpus(session_id)
        if existing_corpus is None:
            # numpy 不可用时退化为逐条 retrieve（旧路径）
            existing_corpus = []
            use_bulk = False
        else:
            use_bulk = True

        for item in candidates:
            # 检查是否已存在相似记忆
            if use_bulk and existing_corpus:
                if self._is_similar_in_corpus(item.content, existing_corpus, threshold=0.85):
                    logger.debug(f"Memory {item.id} similar to existing, skipping")
                    continue
            else:
                existing = self.long_term.retrieve(
                    item.content[:100], session_id=session_id, limit=1
                )
                if existing and existing[0][1] > 0.85:
                    logger.debug(f"Memory {item.id} similar to existing, skipping")
                    continue

            # 迁移到长期记忆
            self.long_term.store(
                content=item.content,
                session_id=item.session_id,
                memory_type=MemoryType.SEMANTIC.value,
                importance=item.importance,
                keywords=item.keywords,
                entities=item.entities,
                intent=item.intent,
                metadata=item.metadata,
            )

            # 标记为已归档
            with self.short_term.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE memories SET is_archived = 1 WHERE id = ?",
                    (item.id,),
                )

            consolidated_count += 1

        logger.info(f"Consolidated {consolidated_count} memories for session {session_id}")
        return consolidated_count

    def _load_long_term_corpus(self, session_id: str) -> Optional[List[Tuple[int, set]]]:
        """一次性加载 session 范围内的长期记忆，返回 [(memory_id, word_set), ...]。

        numpy 不可用时返回 None，调用方降级到旧路径。
        """
        try:
            with self.short_term.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, content FROM memories
                    WHERE session_id = ? AND is_archived = 1
                """, (session_id,))
                return [(row["id"], set(row["content"].lower().split())) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"_load_long_term_corpus failed: {e}")
            return None

    @staticmethod
    def _is_similar_in_corpus(content: str, corpus: List[Tuple[int, set]], threshold: float = 0.85) -> bool:
        """基于词袋的 Jaccard 相似度去重。"""
        if not corpus:
            return False
        words = set(content.lower().split())
        if not words:
            return False
        for _, stored_words in corpus:
            if not stored_words:
                continue
            inter = len(words & stored_words)
            union = len(words | stored_words)
            if union and (inter / union) >= threshold:
                return True
        return False
    
    def retrieve_context(self, query: str, session_id: str) -> str:
        """检索相关上下文"""
        results = self.long_term.retrieve(query, session_id, limit=5)
        
        if not results:
            return ""
        
        context_parts = ["【相关记忆】"]
        for item, similarity in results:
            if similarity > 0.3:
                context_parts.append(f"- [{similarity:.2f}] {item.content[:150]}...")
        
        return "\n".join(context_parts)


class UnifiedMemoryStore:
    """统一记忆存储 - 整合短期与长期记忆"""
    
    _instance = None
    
    def __new__(cls, embedding_model=None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, embedding_model=None):
        if self._initialized:
            return
        
        self.db = MemoryDatabase()
        self.short_term = ShortTermMemory(self.db)
        self.long_term = LongTermMemory(self.db, embedding_model)
        self.consolidator = MemoryConsolidator(self.short_term, self.long_term)
        
        self._initialized = True
    
    def add(
        self,
        content: str,
        session_id: str,
        importance: int = MemoryImportance.MEDIUM.value,
        memory_type: str = MemoryType.WORKING.value,
        is_pinned: bool = False,
        **kwargs
    ) -> MemoryItem:
        """添加记忆"""
        return self.short_term.add(
            content=content,
            session_id=session_id,
            importance=importance,
            memory_type=memory_type,
            is_pinned=is_pinned,
            **kwargs
        )
    
    def get_context(self, query: str, session_id: str) -> str:
        """获取增强上下文"""
        # 1. 获取注意力聚焦的短期记忆
        attention_memories = self.short_term.get_attention_focused(session_id, query)
        
        # 2. 检索相关的长期记忆
        long_term_context = self.consolidator.retrieve_context(query, session_id)
        
        # 3. 构建增强上下文
        context_parts = []
        
        if long_term_context:
            context_parts.append(long_term_context)
        
        if attention_memories:
            context_parts.append("【当前会话关键信息】")
            for mem in attention_memories[:5]:
                context_parts.append(f"- {mem.content[:100]}...")
        
        return "\n".join(context_parts) if context_parts else ""
    
    def consolidate(self, session_id: str) -> int:
        """执行记忆整合（含衰减 + 短期→长期迁移）。

        修复 C3/C8：apply_decay 之前没有任何调用方；此处一并调度，
        确保每次 consolidate 同时推进衰减与迁移。
        """
        # 先衰减，再迁移——避免迁移候选里的"已衰减"项被错误归入长期
        try:
            self.short_term.apply_decay(session_id)
        except Exception as e:
            logger.warning(f"apply_decay failed: {e}")

        return self.consolidator.consolidate(session_id)
    
    def archive_episode(self, session_id: str, summary: str, importance: int = MemoryImportance.HIGH.value):
        """归档会话片段为情景记忆"""
        return self.long_term.store(
            content=summary,
            session_id=session_id,
            memory_type=MemoryType.EPISODIC.value,
            importance=importance
        )
    
    def reset(self):
        """重置记忆存储（测试用）"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memory_relations")
            cursor.execute("DELETE FROM semantic_memory")
            cursor.execute("DELETE FROM memories")
        # 修复 C2：_working_cache 属于 ShortTermMemory，
        # 在此重置而非在 UnifiedMemoryStore 上凭空赋值。
        self.short_term._working_cache.clear()


# 全局单例
_memory_store: Optional[UnifiedMemoryStore] = None


def get_memory_store(embedding_model=None) -> UnifiedMemoryStore:
    """获取统一记忆存储单例"""
    global _memory_store
    if _memory_store is None:
        _memory_store = UnifiedMemoryStore(embedding_model)
    return _memory_store
