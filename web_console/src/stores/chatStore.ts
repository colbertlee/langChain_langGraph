import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { ChatMessage, Session, PersistedAttachment } from '@/types/api';
import { uid } from '@/lib/utils';

interface ChatState {
  sessions: Record<string, Session>;
  messages: Record<string, ChatMessage[]>;
  attachments: Record<string, PersistedAttachment[]>; // sessionId → 上传过的附件
  activeSessionId: string;
  streaming: boolean;

  // actions
  setActive: (id: string) => void;
  newSession: () => string;
  deleteSession: (id: string) => void;
  renameSession: (id: string, title: string) => void;
  appendMessage: (sessionId: string, msg: ChatMessage) => void;
  updateMessage: (sessionId: string, id: string, patch: Partial<ChatMessage>) => void;
  addAttachment: (sessionId: string, att: PersistedAttachment) => void;
  removeAttachment: (sessionId: string, attId: string) => void;
  setStreaming: (s: boolean) => void;
  clearAll: () => void;
}

const initialId = uid();
const now = Date.now();
const initialSession: Session = { id: initialId, title: '新会话', createdAt: now, updatedAt: now };

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      sessions: { [initialId]: initialSession },
      messages: { [initialId]: [] },
      attachments: { [initialId]: [] },
      activeSessionId: initialId,
      streaming: false,

      setActive: (id) => set({ activeSessionId: id }),
      newSession: () => {
        const id = uid();
        const t = Date.now();
        const s: Session = { id, title: '新会话', createdAt: t, updatedAt: t };
        set((st) => ({
          sessions: { ...st.sessions, [id]: s },
          messages: { ...st.messages, [id]: [] },
          attachments: { ...st.attachments, [id]: [] },
          activeSessionId: id,
        }));
        return id;
      },
      deleteSession: (id) =>
        set((st) => {
          const { [id]: _, ...rest } = st.sessions;
          const { [id]: _m, ...restM } = st.messages;
          const { [id]: _a, ...restA } = st.attachments;
          const remaining = Object.keys(rest);
          const nextActive = remaining[0] ?? '';
          if (remaining.length === 0) {
            const nid = uid();
            const t = Date.now();
            return {
              sessions: { [nid]: { id: nid, title: '新会话', createdAt: t, updatedAt: t } },
              messages: { [nid]: [] },
              attachments: { [nid]: [] },
              activeSessionId: nid,
            };
          }
          return {
            sessions: rest,
            messages: restM,
            attachments: restA,
            activeSessionId: nextActive,
          };
        }),
      renameSession: (id, title) =>
        set((st) => ({
          sessions: { ...st.sessions, [id]: { ...st.sessions[id], title, updatedAt: Date.now() } },
        })),
      appendMessage: (sessionId, msg) =>
        set((st) => {
          const cur = st.messages[sessionId] ?? [];
          const sess = st.sessions[sessionId];
          let nextTitle = sess?.title;
          if (
            msg.role === 'user' &&
            cur.length === 0 &&
            sess &&
            (sess.title === '新会话' || !sess.title)
          ) {
            const t = msg.content.trim().replace(/\s+/g, ' ').slice(0, 32);
            if (t) nextTitle = t;
          }
          return {
            messages: {
              ...st.messages,
              [sessionId]: [...cur, msg],
            },
            sessions: {
              ...st.sessions,
              [sessionId]: {
                ...sess,
                title: nextTitle ?? sess?.title ?? '新会话',
                updatedAt: Date.now(),
              },
            },
          };
        }),
      updateMessage: (sessionId, id, patch) =>
        set((st) => ({
          messages: {
            ...st.messages,
            [sessionId]: (st.messages[sessionId] ?? []).map((m) =>
              m.id === id ? { ...m, ...patch } : m,
            ),
          },
        })),
      addAttachment: (sessionId, att) =>
        set((st) => {
          const cur = st.attachments[sessionId] ?? [];
          // 去重：相同 id 覆盖
          const next = cur.filter((a) => a.id !== att.id).concat(att);
          // 上限：每个 session 100 个，防止 localStorage 爆炸
          const trimmed = next.slice(-100);
          return {
            attachments: { ...st.attachments, [sessionId]: trimmed },
          };
        }),
      removeAttachment: (sessionId, attId) =>
        set((st) => ({
          attachments: {
            ...st.attachments,
            [sessionId]: (st.attachments[sessionId] ?? []).filter((a) => a.id !== attId),
          },
        })),
      setStreaming: (s) => set({ streaming: s }),
      clearAll: () => {
        const id = uid();
        const t = Date.now();
        set({
          sessions: { [id]: { id, title: '新会话', createdAt: t, updatedAt: t } },
          messages: { [id]: [] },
          attachments: { [id]: [] },
          activeSessionId: id,
        });
      },
    }),
    {
      name: 'agent-console-chat',
      storage: createJSONStorage(() => localStorage),
      version: 2,
      migrate: (persisted, fromVersion) => {
        if (fromVersion < 2) {
          // v1 没有 attachments，补上空对象
          const p = persisted as Partial<ChatState> | undefined;
          if (p && !p.attachments) p.attachments = {};
        }
        return persisted as ChatState;
      },
    },
  ),
);