"""
记忆系统测试
"""

from memory_store import (
    get_memory_store,
    MemoryType,
    MemoryImportance,
    UnifiedMemoryStore
)

def test_memory_store():
    """测试记忆存储"""
    # 重置单例以确保测试隔离
    UnifiedMemoryStore._instance = None
    
    store = get_memory_store()
    session_id = "test_session_001"
    
    print("=== 添加记忆 ===")
    
    # 添加不同重要性的记忆
    store.add(
        "用户查询了510300ETF的基本信息",
        session_id=session_id,
        importance=MemoryImportance.HIGH.value,
        keywords=["ETF", "510300"]
    )
    
    store.add(
        "用户说'你好'",
        session_id=session_id,
        importance=MemoryImportance.LOW.value
    )
    
    store.add(
        "用户想要了解定投策略",
        session_id=session_id,
        importance=MemoryImportance.MEDIUM.value,
        keywords=["定投", "策略"]
    )
    
    store.add(
        "用户说'谢谢'",
        session_id=session_id,
        importance=MemoryImportance.LOW.value
    )
    
    store.add(
        "用户查询了510050ETF的历史数据",
        session_id=session_id,
        importance=MemoryImportance.HIGH.value,
        keywords=["ETF", "510050", "历史"]
    )
    
    # 添加固定记忆
    store.add(
        "用户偏好：低风险投资者，关注稳健收益",
        session_id=session_id,
        importance=MemoryImportance.CRITICAL.value,
        is_pinned=True
    )
    
    print(f"已添加 6 条记忆")
    
    print("\n=== 获取注意力聚焦记忆 ===")
    attention_memories = store.short_term.get_attention_focused(session_id, "ETF")
    for mem in attention_memories:
        print(f"[重要性:{mem.importance}, 衰减:{mem.decay_factor:.2f}] {mem.content}")
    
    print("\n=== 获取上下文 ===")
    context = store.get_context("ETF定投", session_id)
    print(context if context else "(无相关记忆)")
    
    print("\n=== 记忆整合 ===")
    consolidated = store.consolidate(session_id)
    print(f"整合了 {consolidated} 条记忆到长期记忆")
    
    print("\n=== 检索长期记忆 ===")
    results = store.long_term.retrieve("ETF定投", session_id, limit=3)
    if results:
        for item, score in results:
            print(f"[{score:.2f}] {item.content[:80]}...")
    else:
        print("(无匹配结果)")
    
    print("\n=== 测试摘要 ===")
    store.archive_episode(
        session_id,
        "本次会话用户查询了沪深300ETF和上证50ETF，了解了定投策略，用户为低风险偏好投资者",
        MemoryImportance.HIGH.value
    )
    print("已归档会话摘要")
    
    episodic = store.long_term.get_episodic(session_id)
    print(f"情景记忆数量: {len(episodic)}")
    for ep in episodic:
        print(f"  - {ep.content[:50]}...")

    print("\n[OK] All tests passed!")

if __name__ == "__main__":
    test_memory_store()
