import { describe, it, expect, beforeEach } from 'vitest';
import { useChatStore } from '@/stores/chatStore';

describe('chatStore', () => {
  beforeEach(() => {
    // 每次清空 store
    useChatStore.getState().clearAll();
  });

  it('初始有一个 session', () => {
    const s = useChatStore.getState();
    expect(Object.keys(s.sessions).length).toBe(1);
    expect(s.activeSessionId).toBeTruthy();
  });

  it('newSession 创建一个新会话并切换为 active', () => {
    const before = useChatStore.getState().activeSessionId;
    const newId = useChatStore.getState().newSession();
    const after = useChatStore.getState();
    expect(newId).not.toBe(before);
    expect(after.activeSessionId).toBe(newId);
    expect(after.sessions[newId]).toBeTruthy();
    expect(after.messages[newId]).toEqual([]);
  });

  it('appendMessage 在首条 user 消息时自动用首句作标题', () => {
    const id = useChatStore.getState().activeSessionId;
    useChatStore.getState().appendMessage(id, {
      id: 'm1',
      sessionId: id,
      role: 'user',
      content: '你好   世界\nhello',
      createdAt: Date.now(),
    });
    const sess = useChatStore.getState().sessions[id];
    expect(sess?.title).toBe('你好 世界 hello');
  });

  it('appendMessage 非首条不重置标题', () => {
    const id = useChatStore.getState().activeSessionId;
    useChatStore.getState().appendMessage(id, {
      id: 'm1',
      sessionId: id,
      role: 'user',
      content: '首条',
      createdAt: Date.now(),
    });
    useChatStore.getState().renameSession(id, '已设标题');
    useChatStore.getState().appendMessage(id, {
      id: 'm2',
      sessionId: id,
      role: 'assistant',
      content: '回复',
      createdAt: Date.now(),
    });
    expect(useChatStore.getState().sessions[id]?.title).toBe('已设标题');
  });

  it('updateMessage 修改内容', () => {
    const id = useChatStore.getState().activeSessionId;
    useChatStore.getState().appendMessage(id, {
      id: 'm1',
      sessionId: id,
      role: 'assistant',
      content: 'a',
      createdAt: Date.now(),
    });
    useChatStore.getState().updateMessage(id, 'm1', { content: 'b' });
    expect(useChatStore.getState().messages[id][0].content).toBe('b');
  });

  it('deleteSession 后若删的是 active，自动创建新会话', () => {
    const id = useChatStore.getState().activeSessionId;
    useChatStore.getState().deleteSession(id);
    const after = useChatStore.getState();
    expect(after.sessions[id]).toBeUndefined();
    expect(Object.keys(after.sessions).length).toBe(1);
    expect(after.activeSessionId).not.toBe(id);
  });

  it('renameSession 改标题', () => {
    const id = useChatStore.getState().activeSessionId;
    useChatStore.getState().renameSession(id, '新名字');
    expect(useChatStore.getState().sessions[id]?.title).toBe('新名字');
  });
});
