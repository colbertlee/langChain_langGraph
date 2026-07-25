import { useChatStore } from '@/stores/chatStore';
import type { ChatMessage } from '@/types/api';

export interface RemoteThreadMetadata {
  remoteId: string;
  title?: string;
  status?: 'regular' | 'archived';
}

export interface ThreadListAdapter {
  list(): Promise<{ threads: RemoteThreadMetadata[] }>;
  initialize?(threadId: string): Promise<void>;
  rename?(threadId: string, title: string): Promise<void>;
  archive?(threadId: string): Promise<void>;
  unarchive?(threadId: string): Promise<void>;
  delete?(threadId: string): Promise<void>;
  generateTitle?(threadId: string, message: ChatMessage): Promise<void>;
  history?(threadId: string): Promise<{ messages: ChatMessage[] }>;
}

function toThreadMeta(threadId: string, title: string): RemoteThreadMetadata {
  return { remoteId: threadId, title: title || '新会话', status: 'regular' };
}

/**
 * 把本地 chatStore 包装成 assistant-ui 的 ThreadListAdapter。
 * 所有数据落到 localStorage（zustand persist），离线可用。
 */
export const localThreadListAdapter: ThreadListAdapter = {
  async list() {
    const s = useChatStore.getState();
    const list = Object.values(s.sessions)
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .map((x) => toThreadMeta(x.id, x.title));
    return { threads: list };
  },

  async initialize(threadId) {
    // 确保该 thread 在 store 中存在
    const s = useChatStore.getState();
    if (!s.sessions[threadId]) {
      s.newSession();
    }
  },

  async rename(threadId, title) {
    useChatStore.getState().renameSession(threadId, title);
  },

  async archive(threadId) {
    // 归档：暂时等价于删除（保持 store 干净）
    const s = useChatStore.getState();
    if (s.activeSessionId === threadId) return;
    s.deleteSession(threadId);
  },

  async unarchive(threadId) {
    // 简化：恢复为普通会话（这里我们直接跳过，因为 archive 已删除）
    void threadId;
  },

  async delete(threadId) {
    useChatStore.getState().deleteSession(threadId);
  },

  async generateTitle(_threadId, _message) {
    // 由 chatStore 在收到首条 user 消息时自动用首句做标题
  },

  async history(threadId) {
    const s = useChatStore.getState();
    return { messages: s.messages[threadId] ?? [] };
  },
};
