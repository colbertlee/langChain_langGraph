"""
长期记忆（Long-term Memory）

提供：
- MemoryItem    记忆条目（key / value / type / 来源 / 时间）
- MemoryStore   存储 + 检索（按 type / session / 全局 / 关键词）
- MemoryType    类型枚举（PREFERENCE / FACT / TASK_HISTORY / EPISODE / SKILL）
- 持久化        可选内存 / 文件 / 跨 session

使用：
    store = get_memory_store()

    # 记录用户偏好
    store.put(MemoryItem(
        key="user_name",
        value="Alice",
        memory_type=MemoryType.FACT,
        scope="global",
    ))

    # 记录任务历史
    store.put(MemoryItem(
        key="last_search_topic",
        value="AI 论文",
        memory_type=MemoryType.TASK_HISTORY,
        scope="user:alice",
    ))

    # 检索
    items = store.query(scope="user:alice", memory_type=MemoryType.PREFERENCE)

    # 跨 session 持久化
    store.save_to_file("memory.json")
    store.load_from_file("memory.json")
"""

import json
import time
import uuid
import logging
import os
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field, asdict
from threading import Lock
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============================================================
# MemoryItem
# ============================================================

class MemoryType(str, Enum):
    PREFERENCE = "preference"   # 用户偏好（用户偏好什么语言/风格）
    FACT = "fact"               # 事实（用户叫什么、住在哪）
    TASK_HISTORY = "task_history"   # 任务历史
    EPISODE = "episode"         # 情节（某个完整交互记录）
    SKILL = "skill"             # 习得的技能
    CONTEXT = "context"         # 上下文片段
    INSTRUCTION = "instruction" # 用户给出的指令


@dataclass
class MemoryItem:
    """一个记忆条目"""
    item_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    key: str = ""
    value: Any = None
    memory_type: MemoryType = MemoryType.FACT
    scope: str = "global"   # global / user:<id> / session:<id>
    source: str = "system"  # 谁创建的（user / agent / system）
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None  # 过期时间
    tags: List[str] = field(default_factory=list)
    importance: float = 0.5  # 0-1, 用于排序
    access_count: int = 0
    last_accessed: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def touch(self) -> None:
        """访问时调用"""
        self.access_count += 1
        self.last_accessed = time.time()

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["memory_type"] = self.memory_type.value
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "MemoryItem":
        d = dict(d)
        if "memory_type" in d and isinstance(d["memory_type"], str):
            d["memory_type"] = MemoryType(d["memory_type"])
        return cls(**d)


# ============================================================
# MemoryStore
# ============================================================

class MemoryStore:
    """
    记忆存储 + 检索

    角色：
    - put(item): 添加记忆
    - get(key, scope): 获取记忆
    - query(): 多条件检索
    - 持久化（save_to_file / load_from_file）
    """

    def __init__(self, max_items: int = 10000):
        self._items: Dict[str, MemoryItem] = {}
        self._index_by_scope: Dict[str, Set[str]] = defaultdict(set)
        self._index_by_key: Dict[Tuple[str, str], str] = {}  # (scope, key) -> item_id
        self._index_by_type: Dict[MemoryType, Set[str]] = defaultdict(set)
        self._lock = Lock()
        self._max_items = max_items
        # 订阅：添加时回调
        self._on_put: List[Callable[[MemoryItem], None]] = []

    # ----------------- 添加 / 更新 -----------------

    def put(
        self,
        key: str,
        value: Any,
        memory_type: MemoryType = MemoryType.FACT,
        scope: str = "global",
        source: str = "system",
        tags: Optional[List[str]] = None,
        importance: float = 0.5,
        expires_in_seconds: Optional[float] = None,
        metadata: Optional[Dict] = None,
    ) -> MemoryItem:
        """
        添加或更新一条记忆（按 (scope, key) 唯一）。

        Returns:
            MemoryItem
        """
        with self._lock:
            index_key = (scope, key)
            if index_key in self._index_by_key:
                existing_id = self._index_by_key[index_key]
                existing = self._items[existing_id]
                existing.value = value
                existing.memory_type = memory_type
                existing.source = source
                existing.tags = tags or existing.tags
                existing.importance = importance
                existing.updated_at = time.time()
                if expires_in_seconds is not None:
                    existing.expires_at = time.time() + expires_in_seconds
                if metadata:
                    existing.metadata.update(metadata)
                item = existing
            else:
                expires_at = (
                    time.time() + expires_in_seconds
                    if expires_in_seconds is not None else None
                )
                item = MemoryItem(
                    key=key,
                    value=value,
                    memory_type=memory_type,
                    scope=scope,
                    source=source,
                    tags=tags or [],
                    importance=importance,
                    expires_at=expires_at,
                    metadata=metadata or {},
                )
                # 容量检查：淘汰最不重要的
                if len(self._items) >= self._max_items:
                    self._evict_least_important()
                self._items[item.item_id] = item
                self._index_by_key[index_key] = item.item_id
                self._index_by_scope[scope].add(item.item_id)
                self._index_by_type[memory_type].add(item.item_id)

        # 回调（异步安全）
        for cb in self._on_put:
            try:
                cb(item)
            except Exception as e:
                logger.warning(f"memory put callback error: {e}")

        return item

    def add(self, item: MemoryItem) -> MemoryItem:
        """直接 put MemoryItem"""
        return self.put(
            key=item.key,
            value=item.value,
            memory_type=item.memory_type,
            scope=item.scope,
            source=item.source,
            tags=item.tags,
            importance=item.importance,
            metadata=item.metadata,
        )

    # ----------------- 检索 -----------------

    def get(self, key: str, scope: str = "global", touch: bool = True) -> Optional[MemoryItem]:
        with self._lock:
            index_key = (scope, key)
            item_id = self._index_by_key.get(index_key)
            if not item_id:
                return None
            item = self._items.get(item_id)
            if item and item.is_expired():
                self._delete(item_id)
                return None
            if item and touch:
                item.touch()
            return item

    def query(
        self,
        scope: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        tags: Optional[List[str]] = None,
        keyword: Optional[str] = None,
        limit: int = 50,
        min_importance: float = 0.0,
    ) -> List[MemoryItem]:
        """
        多条件检索。

        Args:
            scope: 限定 scope（None = 不限）
            memory_type: 限定类型
            tags: 至少匹配一个 tag
            keyword: 在 key/value/metadata 中搜索
            limit: 返回数量上限
            min_importance: 重要性阈值
        """
        with self._lock:
            items = list(self._items.values())

        # 过滤
        results = []
        for item in items:
            if item.is_expired():
                continue
            if scope and item.scope != scope:
                continue
            if memory_type and item.memory_type != memory_type:
                continue
            if tags and not any(t in item.tags for t in tags):
                continue
            if min_importance > 0 and item.importance < min_importance:
                continue
            if keyword:
                kw = keyword.lower()
                haystack = (
                    item.key.lower() + " "
                    + str(item.value).lower() + " "
                    + " ".join(item.tags).lower() + " "
                    + json.dumps(item.metadata, default=str).lower()
                )
                if kw not in haystack:
                    continue
            results.append(item)

        # 排序：importance desc + last_accessed desc
        results.sort(
            key=lambda i: (i.importance, i.last_accessed or i.updated_at),
            reverse=True,
        )
        return results[:limit]

    def delete(self, key: str, scope: str = "global") -> bool:
        with self._lock:
            index_key = (scope, key)
            item_id = self._index_by_key.get(index_key)
            if not item_id:
                return False
            self._delete(item_id)
            return True

    def clear_scope(self, scope: str) -> int:
        with self._lock:
            ids = list(self._index_by_scope.get(scope, set()))
            for item_id in ids:
                self._delete(item_id)
        return len(ids)

    # ----------------- 订阅 -----------------

    def on_put(self, callback: Callable[[MemoryItem], None]) -> None:
        self._on_put.append(callback)

    # ----------------- 持久化 -----------------

    def save_to_file(self, path: str) -> None:
        with self._lock:
            items = [item.to_dict() for item in self._items.values()]
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save memory to {path}: {e}")

    def load_from_file(self, path: str) -> int:
        """从文件加载记忆，返回成功加载数量"""
        if not os.path.exists(path):
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            n = 0
            for d in raw:
                try:
                    item = MemoryItem.from_dict(d)
                    if item.is_expired():
                        continue
                    self.add(item)
                    n += 1
                except Exception as e:
                    logger.warning(f"Failed to load memory item: {e}")
            return n
        except Exception as e:
            logger.warning(f"Failed to load memory from {path}: {e}")
            return 0

    # ----------------- 状态 -----------------

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            n = len(self._items)
            scopes = {s: len(ids) for s, ids in self._index_by_scope.items()}
            types = {t.value: len(ids) for t, ids in self._index_by_type.items()}
        return {
            "total_items": n,
            "max_items": self._max_items,
            "by_scope": scopes,
            "by_type": types,
        }

    # ----------------- 内部 -----------------

    def _delete(self, item_id: str) -> None:
        item = self._items.pop(item_id, None)
        if not item:
            return
        self._index_by_scope[item.scope].discard(item_id)
        if not self._index_by_scope[item.scope]:
            del self._index_by_scope[item.scope]
        self._index_by_type[item.memory_type].discard(item_id)
        if not self._index_by_type[item.memory_type]:
            del self._index_by_type[item.memory_type]
        index_key = (item.scope, item.key)
        self._index_by_key.pop(index_key, None)

    def _evict_least_important(self) -> None:
        """淘汰最不重要的一个"""
        if not self._items:
            return
        victim = min(
            self._items.values(),
            key=lambda i: (i.importance, i.last_accessed or i.updated_at),
        )
        self._delete(victim.item_id)


# ============================================================
# 全局单例
# ============================================================

_memory_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
    return _memory_store


def reset_memory_store() -> None:
    """重置（测试用）"""
    global _memory_store
    _memory_store = None