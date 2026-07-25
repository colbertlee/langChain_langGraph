"""
状态同步管理器

提供多 Agent 之间的状态同步、分布式锁、
一致性保证、状态变更通知等功能。
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set
from enum import Enum
from dataclasses import dataclass, field
from collections import defaultdict

from message_protocol import MessageType, AgentInfo

logger = logging.getLogger(__name__)


class ConsistencyLevel(Enum):
    """一致性级别"""
    NONE = "none"              # 无一致性保证
    EVENTUAL = "eventual"      # 最终一致性
    SEQUENTIAL = "sequential"  # 顺序一致性
    STRONG = "strong"          # 强一致性


@dataclass
class StateSnapshot:
    """状态快照"""
    snapshot_id: str = ""
    agent_id: str = ""
    state: Dict = field(default_factory=dict)
    version: int = 0
    timestamp: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "snapshot_id": self.snapshot_id,
            "agent_id": self.agent_id,
            "state": self.state,
            "version": self.version,
            "timestamp": self.timestamp
        }


@dataclass
class LockInfo:
    """锁信息"""
    lock_id: str
    owner_id: str
    resource: str
    acquired_at: str
    expires_at: str
    is_shared: bool = False
    holders: List[str] = field(default_factory=list)  # 共享锁持有者列表


class StateManager:
    """
    状态同步管理器
    
    功能：
    - 分布式状态存储
    - 状态版本控制
    - 状态变更监听
    - 分布式锁
    - 一致性保证
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        # 状态存储
        self._states: Dict[str, Dict[str, Any]] = defaultdict(dict)  # agent_id -> state
        self._versions: Dict[str, int] = defaultdict(int)  # agent_id -> version
        
        # 全局状态（跨 Agent 共享）
        self._global_state: Dict[str, Any] = {}
        self._global_version: int = 0
        
        # 状态历史
        self._history: Dict[str, List[StateSnapshot]] = defaultdict(list)
        self._max_history_size = 100
        
        # 监听器
        self._watchers: Dict[str, List[Callable]] = defaultdict(list)
        self._global_watchers: List[Callable] = []
        
        # 分布式锁
        self._locks: Dict[str, LockInfo] = {}
        self._lock_waiters: Dict[str, List[asyncio.Future]] = defaultdict(list)
        
        # 消息总线
        try:
            from message_bus import get_message_bus
            self._bus = get_message_bus()
            self._bus.on_agent_update(self._handle_agent_update)
        except:
            self._bus = None
        
        # 事件队列
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._event_history: List[Dict] = []
        self._max_event_history = 500
        
        # 一致性配置
        self._consistency_level = ConsistencyLevel.EVENTUAL
        
        logger.info("StateManager initialized")
    
    @classmethod
    def get_instance(cls) -> 'StateManager':
        return cls()
    
    # ==========================================
    # 状态管理
    # ==========================================
    
    def set_state(
        self,
        agent_id: str,
        key: str,
        value: Any,
        notify: bool = True
    ):
        """设置 Agent 状态"""
        self._states[agent_id][key] = value
        self._versions[agent_id] += 1
        
        # 记录历史
        self._record_snapshot(agent_id)
        
        if notify:
            self._notify_change(agent_id, key, value)
    
    def get_state(
        self,
        agent_id: str,
        key: str = None,
        default: Any = None
    ) -> Any:
        """获取 Agent 状态"""
        if key is None:
            return self._states.get(agent_id, {}).copy()
        
        return self._states.get(agent_id, {}).get(key, default)
    
    def delete_state(self, agent_id: str, key: str = None):
        """删除状态"""
        if key is None:
            if agent_id in self._states:
                del self._states[agent_id]
            if agent_id in self._versions:
                del self._versions[agent_id]
        else:
            if agent_id in self._states and key in self._states[agent_id]:
                del self._states[agent_id][key]
                self._versions[agent_id] += 1
                self._record_snapshot(agent_id)
    
    def update_state(
        self,
        agent_id: str,
        updates: Dict[str, Any],
        merge: bool = True
    ):
        """批量更新状态"""
        if merge:
            self._states[agent_id].update(updates)
        else:
            self._states[agent_id] = updates
        
        self._versions[agent_id] += 1
        self._record_snapshot(agent_id)
        
        # 通知变更
        for key, value in updates.items():
            self._notify_change(agent_id, key, value)
    
    def get_version(self, agent_id: str) -> int:
        """获取状态版本"""
        return self._versions.get(agent_id, 0)
    
    def _record_snapshot(self, agent_id: str):
        """记录状态快照"""
        from message_protocol import Message
        
        snapshot = StateSnapshot(
            snapshot_id=f"{agent_id}_{self._versions[agent_id]}",
            agent_id=agent_id,
            state=self._states[agent_id].copy(),
            version=self._versions[agent_id],
            timestamp=datetime.now().isoformat()
        )
        
        self._history[agent_id].append(snapshot)
        
        # 限制历史大小
        if len(self._history[agent_id]) > self._max_history_size:
            self._history[agent_id] = self._history[agent_id][-self._max_history_size:]
    
    def _notify_change(self, agent_id: str, key: str, value: Any):
        """通知状态变更"""
        event = {
            "type": "state_change",
            "agent_id": agent_id,
            "key": key,
            "value": value,
            "version": self._versions[agent_id],
            "timestamp": datetime.now().isoformat()
        }
        
        self._event_queue.put_nowait(event)
        self._event_history.append(event)
        
        if len(self._event_history) > self._max_event_history:
            self._event_history = self._event_history[-self._max_event_history:]
        
        # 调用监听器
        watchers = self._watchers.get(f"{agent_id}:{key}", []) + \
                  self._watchers.get(f"{agent_id}:*", []) + \
                  self._watchers.get("*:{key}", []) + \
                  self._watchers.get("*:*", [])
        
        for watcher in watchers:
            try:
                if asyncio.iscoroutinefunction(watcher):
                    asyncio.create_task(watcher(agent_id, key, value))
                else:
                    watcher(agent_id, key, value)
            except Exception as e:
                logger.error(f"Watcher error: {e}")
    
    # ==========================================
    # 全局状态
    # ==========================================
    
    def set_global_state(self, key: str, value: Any):
        """设置全局状态"""
        self._global_state[key] = value
        self._global_version += 1
        
        event = {
            "type": "global_state_change",
            "key": key,
            "value": value,
            "version": self._global_version,
            "timestamp": datetime.now().isoformat()
        }
        
        self._event_history.append(event)
        
        # 通知全局监听器
        for watcher in self._global_watchers:
            try:
                if asyncio.iscoroutinefunction(watcher):
                    asyncio.create_task(watcher(key, value))
                else:
                    watcher(key, value)
            except Exception as e:
                logger.error(f"Global watcher error: {e}")
    
    def get_global_state(self, key: str = None, default: Any = None) -> Any:
        """获取全局状态"""
        if key is None:
            return self._global_state.copy()
        return self._global_state.get(key, default)
    
    def delete_global_state(self, key: str):
        """删除全局状态"""
        if key in self._global_state:
            del self._global_state[key]
            self._global_version += 1
    
    # ==========================================
    # 状态监听
    # ==========================================
    
    def watch(
        self,
        agent_id: str,
        key: str,
        callback: Callable
    ):
        """监听特定状态变更"""
        pattern = f"{agent_id}:{key}"
        self._watchers[pattern].append(callback)
    
    def watch_all(self, callback: Callable):
        """监听所有状态变更"""
        self._global_watchers.append(callback)
    
    def unwatch(self, agent_id: str, key: str, callback: Callable):
        """取消监听"""
        pattern = f"{agent_id}:{key}"
        if callback in self._watchers.get(pattern, []):
            self._watchers[pattern].remove(callback)
    
    # ==========================================
    # 分布式锁
    # ==========================================
    
    async def acquire_lock(
        self,
        lock_id: str,
        owner_id: str,
        resource: str,
        timeout: float = 10.0,
        is_shared: bool = False
    ) -> bool:
        """
        获取分布式锁
        
        Args:
            lock_id: 锁 ID
            owner_id: 锁持有者 ID
            resource: 资源名称
            timeout: 超时时间
            is_shared: 是否为共享锁
        
        Returns:
            是否成功获取锁
        """
        start_time = asyncio.get_event_loop().time()
        
        while True:
            lock = self._locks.get(lock_id)
            
            if lock is None:
                # 没有锁，直接获取
                lock_info = LockInfo(
                    lock_id=lock_id,
                    owner_id=owner_id,
                    resource=resource,
                    acquired_at=datetime.now().isoformat(),
                    expires_at=(
                        datetime.now().timestamp() + timeout
                    ),
                    is_shared=is_shared,
                    holders=[owner_id]
                )
                self._locks[lock_id] = lock_info
                logger.debug(f"Lock acquired: {lock_id} by {owner_id}")
                return True
            
            # 检查锁是否过期
            if datetime.now().timestamp() > lock.expires_at:
                # 锁已过期，删除并重新获取
                del self._locks[lock_id]
                continue
            
            # 检查是否可以获取共享锁
            if is_shared and lock.is_shared:
                if owner_id not in lock.holders:
                    lock.holders.append(owner_id)
                logger.debug(f"Shared lock acquired: {lock_id} by {owner_id}")
                return True
            
            # 检查是否是锁的持有者
            if lock.owner_id == owner_id:
                logger.debug(f"Lock already held: {lock_id} by {owner_id}")
                return True
            
            # 等待锁释放
            if asyncio.get_event_loop().time() - start_time >= timeout:
                logger.warning(f"Lock acquisition timeout: {lock_id}")
                return False
            
            # 创建等待者
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            self._lock_waiters[lock_id].append(future)
            
            try:
                await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                pass
    
    def release_lock(self, lock_id: str, owner_id: str):
        """释放锁"""
        lock = self._locks.get(lock_id)
        
        if lock is None:
            return
        
        if lock.is_shared:
            # 共享锁：从持有者列表中移除
            if owner_id in lock.holders:
                lock.holders.remove(owner_id)
            
            if not lock.holders:
                del self._locks[lock_id]
                self._wake_waiters(lock_id)
        else:
            # 独占锁：只有持有者可以释放
            if lock.owner_id == owner_id:
                del self._locks[lock_id]
                self._wake_waiters(lock_id)
    
    def _wake_waiters(self, lock_id: str):
        """唤醒等待者"""
        for future in self._lock_waiters.get(lock_id, []):
            if not future.done():
                future.set_result(True)
        
        if lock_id in self._lock_waiters:
            del self._lock_waiters[lock_id]
    
    def is_locked(self, lock_id: str) -> bool:
        """检查是否被锁定"""
        lock = self._locks.get(lock_id)
        if lock is None:
            return False
        return datetime.now().timestamp() < lock.expires_at
    
    def get_lock_info(self, lock_id: str) -> Optional[LockInfo]:
        """获取锁信息"""
        return self._locks.get(lock_id)
    
    # ==========================================
    # 状态同步
    # ==========================================
    
    async def sync_with_peer(
        self,
        peer_agent_id: str,
        consistency: ConsistencyLevel = ConsistencyLevel.EVENTUAL
    ) -> Dict[str, Any]:
        """与对等 Agent 同步状态"""
        if self._bus is None:
            return {"error": "Message bus not available"}
        
        peer = self._bus.get_agent(peer_agent_id)
        if peer is None:
            return {"error": "Peer agent not found"}
        
        # 获取本地状态快照
        local_state = self._states.get(self._bus._agents.get("self") if hasattr(self._bus, '_agents') else "self", {})
        local_version = self._versions.get(peer_agent_id, 0)
        
        # 请求对等状态
        from message_protocol import create_message, MessageType
        
        request = create_message(
            msg_type=MessageType.STATE_SYNC,
            sender_id=self._bus.supervisor_id if hasattr(self._bus, 'supervisor_id') else "self",
            receiver_id=peer_agent_id,
            content={"type": "state_sync_request"},
            payload={
                "local_version": local_version,
                "local_state": local_state
            }
        )
        
        try:
            response = await self._bus.request(
                sender_id=request.sender_id,
                receiver_id=peer_agent_id,
                content=request,
                timeout=5.0
            )
            
            if response:
                peer_state = response.payload.get("state", {})
                peer_version = response.payload.get("version", 0)
                
                # 根据一致性级别合并状态
                merged_state = self._merge_states(local_state, peer_state, consistency)
                
                return {
                    "status": "synced",
                    "local_state": local_state,
                    "peer_state": peer_state,
                    "merged_state": merged_state,
                    "local_version": local_version,
                    "peer_version": peer_version
                }
        
        except Exception as e:
            logger.error(f"State sync error: {e}")
            return {"error": str(e)}
        
        return {"status": "sync_failed"}
    
    def _merge_states(
        self,
        local: Dict,
        peer: Dict,
        consistency: ConsistencyLevel
    ) -> Dict:
        """合并状态"""
        if consistency == ConsistencyLevel.NONE:
            return local if local else peer
        
        if consistency == ConsistencyLevel.STRONG:
            # 强一致性：使用时间戳决定
            # 这里简化处理，返回本地状态
            return local
        
        # 最终一致性和顺序一致性：合并
        merged = local.copy()
        merged.update(peer)
        return merged
    
    async def _handle_agent_update(self, event: str, agent_id: str, data: Dict = None):
        """处理 Agent 状态更新"""
        if event == "status_changed":
            self.set_global_state(f"agent_status:{agent_id}", data.get("status"))
    
    # ==========================================
    # 状态历史
    # ==========================================
    
    def get_history(
        self,
        agent_id: str,
        limit: int = 50
    ) -> List[StateSnapshot]:
        """获取状态历史"""
        return self._history.get(agent_id, [])[-limit:]
    
    def get_snapshot(
        self,
        agent_id: str,
        version: int = None
    ) -> Optional[StateSnapshot]:
        """获取特定版本的状态快照"""
        history = self._history.get(agent_id, [])
        
        if version is None:
            return history[-1] if history else None
        
        for snapshot in reversed(history):
            if snapshot.version == version:
                return snapshot
        
        return None
    
    def rollback(self, agent_id: str, version: int) -> bool:
        """回滚到指定版本"""
        snapshot = self.get_snapshot(agent_id, version)
        
        if snapshot is None:
            return False
        
        self._states[agent_id] = snapshot.state.copy()
        self._versions[agent_id] = snapshot.version
        return True
    
    # ==========================================
    # 事件
    # ==========================================
    
    def get_events(
        self,
        event_type: str = None,
        agent_id: str = None,
        limit: int = 100
    ) -> List[Dict]:
        """获取事件历史"""
        events = self._event_history
        
        if event_type:
            events = [e for e in events if e.get("type") == event_type]
        
        if agent_id:
            events = [e for e in events if e.get("agent_id") == agent_id]
        
        return events[-limit:]
    
    async def wait_for_event(
        self,
        event_type: str = None,
        agent_id: str = None,
        timeout: float = 30.0
    ) -> Optional[Dict]:
        """等待特定事件"""
        start_time = asyncio.get_event_loop().time()
        
        while True:
            # 检查历史事件
            for event in reversed(self._event_history):
                if self._match_event(event, event_type, agent_id):
                    return event
            
            # 等待新事件
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=1.0
                )
                
                if self._match_event(event, event_type, agent_id):
                    return event
                else:
                    # 不匹配，重新放回队列
                    self._event_queue.put_nowait(event)
            except asyncio.TimeoutError:
                pass
            
            if asyncio.get_event_loop().time() - start_time >= timeout:
                return None
    
    def _match_event(
        self,
        event: Dict,
        event_type: str,
        agent_id: str
    ) -> bool:
        """匹配事件"""
        if event_type and event.get("type") != event_type:
            return False
        
        if agent_id and event.get("agent_id") != agent_id:
            return False
        
        return True
    
    # ==========================================
    # 工具方法
    # ==========================================
    
    def get_all_states(self) -> Dict[str, Dict]:
        """获取所有 Agent 状态"""
        return {k: v.copy() for k, v in self._states.items()}
    
    def get_all_versions(self) -> Dict[str, int]:
        """获取所有版本"""
        return dict(self._versions)
    
    def reset(self):
        """重置状态管理器"""
        self._states.clear()
        self._versions.clear()
        self._global_state.clear()
        self._global_version = 0
        self._history.clear()
        self._locks.clear()
        self._event_history.clear()
        
        logger.info("StateManager reset")
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "total_agents": len(self._states),
            "total_locks": len(self._locks),
            "global_version": self._global_version,
            "event_history_size": len(self._event_history),
            "consistency_level": self._consistency_level.value
        }


def get_state_manager() -> StateManager:
    """获取状态管理器实例"""
    return StateManager.get_instance()


# ==========================================
# 上下文管理器
# ==========================================

class StateContext:
    """状态访问上下文"""
    
    def __init__(self, agent_id: str):
        self._agent_id = agent_id
        self._manager = StateManager.get_instance()
        self._previous_state: Dict = {}
        self._changes: Dict = {}
    
    def __enter__(self):
        self._previous_state = self._manager.get_state(self._agent_id).copy()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if not exc_type:  # 没有异常
            self._manager.update_state(self._agent_id, self._changes)
        else:
            # 发生异常，回滚
            self._manager.update_state(self._agent_id, self._previous_state, merge=False)
        return False
    
    def set(self, key: str, value: Any):
        """设置值"""
        self._changes[key] = value
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取值"""
        return self._changes.get(key, self._manager.get_state(self._agent_id, key, default))


# ==========================================
# 锁上下文管理器
# ==========================================

class LockContext:
    """锁访问上下文"""
    
    def __init__(
        self,
        lock_id: str,
        owner_id: str,
        resource: str = "",
        timeout: float = 10.0,
        is_shared: bool = False
    ):
        self._lock_id = lock_id
        self._owner_id = owner_id
        self._resource = resource
        self._timeout = timeout
        self._is_shared = is_shared
        self._manager = StateManager.get_instance()
        self._acquired = False
    
    async def __aenter__(self):
        self._acquired = await self._manager.acquire_lock(
            self._lock_id,
            self._owner_id,
            self._resource,
            self._timeout,
            self._is_shared
        )
        
        if not self._acquired:
            raise TimeoutError(f"Failed to acquire lock: {self._lock_id}")
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._acquired:
            self._manager.release_lock(self._lock_id, self._owner_id)
        return False
