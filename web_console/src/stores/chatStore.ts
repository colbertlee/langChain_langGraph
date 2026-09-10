import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { ChatMessage, Session, PersistedAttachment } from '@/types/api';
import { uid } from '@/lib/utils';

/**
 * v2.2.1 — HITL 待审批卡片
 * 一条 ApprovalRequiredEvent 进入前端后，会被 chatStore 落成本结构。
 * 状态：pending → approved / rejected
 */
export type ApprovalStatus = 'pending' | 'approved' | 'rejected';

export interface ChatApprovalCard {
  id: string; // request_id
  sessionId: string;
  toolName: string;
  toolArgs: Record<string, unknown>;
  reason: string;
  status: ApprovalStatus;
  createdAt: number;
  rejectReason?: string;
}

/**
 * v2.2.3 — Multi-Agent Supervisor 协作轨迹中的单个事件节点。
 *
 *  - type === 'switch'   → Supervisor 切到新 Worker（来自 SSE `event: agent_switch`）
 *  - type === 'done'     → 当前 Worker / 整轮流程结束（来自 SSE `event: agent_done`）
 *
 * 设计要点：
 *  - 一条 switch 事件携带 agent / reason；store 会自动计算 durationMs（与上一节点的时间差）。
 *  - 数据持久化到 localStorage，F5 / 切 Session 后 AgentExecutionGraph 仍能恢复整棵树。
 *  - requestId 可选：code_worker 触发 HITL 时，approvalCards 与这里通过 requestId 关联，
 *    UI 可在对应节点下方渲染嵌套的 ApprovalCard。
 */
export type ChatAgentEventType = 'switch' | 'done';

export interface ChatAgentEvent {
  id: string;
  sessionId: string;
  type: ChatAgentEventType;
  /** 目标 Worker 名（research_worker / code_worker / rag_worker / supervisor / FINISH） */
  agent: string;
  /** Supervisor 思考过程（仅 switch 事件） */
  reason?: string;
  ts: number;
  /** 与上一节点的耗时（ms），由 store 自动计算（可选） */
  durationMs?: number;
  /** 若该 Worker 触发 HITL，关联的审批 request_id（仅可选） */
  requestId?: string;
}

interface ChatState {
  sessions: Record<string, Session>;
  messages: Record<string, ChatMessage[]>;
  attachments: Record<string, PersistedAttachment[]>; // sessionId → 上传过的附件
  approvalCards: Record<string, ChatApprovalCard[]>; // v2.2.1 — sessionId → HITL 待审批卡片
  resumeBySession: Record<string, string>; // P1-5 — HITL resume 累积文本（独立于 messages）
  // v2.2.3 — sessionId → 该会话触发的 Agent 协作轨迹（agent_switch / agent_done 等）
  // 由后端 SSE `event: agent_switch` 与 `event: agent_done` 累加；持久化到 localStorage，
  // F5 刷新或切换 Session 时可在 UI 上恢复历史轨迹。
  agentEvents: Record<string, ChatAgentEvent[]>;
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
  removeMessage: (sessionId: string, id: string) => void;

  // v2.2.1 — HITL 审批动作
  recordApproval: (card: Omit<ChatApprovalCard, 'createdAt' | 'status'>) => void;
  resolveApproval: (
    sessionId: string,
    cardId: string,
    status: 'approved' | 'rejected',
    rejectReason?: string,
  ) => void;
  getApprovalCards: (sessionId: string) => ChatApprovalCard[];

  // v2.2.3 — Multi-Agent Supervisor 轨迹
  appendAgentEvent: (sessionId: string, ev: Omit<ChatAgentEvent, 'id' | 'ts'>) => void;
  clearAgentEvents: (sessionId: string) => void;
  getAgentEvents: (sessionId: string) => ChatAgentEvent[];

  // P1-5 — HITL 拒绝/批准后 resume 流的累积文本（独立于主 messages）
  appendResumeText: (sessionId: string, text: string) => void;
  clearResumeText: (sessionId: string) => void;

  clearAll: () => void;
}

const initialId = uid();
const now = Date.now();
const initialSession: Session = { id: initialId, title: '新会话', createdAt: now, updatedAt: now };

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      sessions: { [initialId]: initialSession },
      messages: { [initialId]: [] },
      attachments: { [initialId]: [] },
      approvalCards: { [initialId]: [] }, // v2.2.1
      agentEvents: { [initialId]: [] }, // v2.2.3
      resumeBySession: { [initialId]: '' }, // P1-5
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
          approvalCards: { ...st.approvalCards, [id]: [] }, // v2.2.1
          agentEvents: { ...st.agentEvents, [id]: [] }, // v2.2.3
          resumeBySession: { ...st.resumeBySession, [id]: '' }, // P1-5
          activeSessionId: id,
        }));
        return id;
      },
      deleteSession: (id) =>
        set((st) => {
          const { [id]: _, ...rest } = st.sessions;
          const { [id]: _m, ...restM } = st.messages;
          const { [id]: _a, ...restA } = st.attachments;
          const { [id]: _p, ...restP } = st.approvalCards; // v2.2.1
          const { [id]: _e, ...restE } = st.agentEvents; // v2.2.3
          const { [id]: _r, ...restR } = st.resumeBySession; // P1-5
          const remaining = Object.keys(rest);
          const nextActive = remaining[0] ?? '';
          if (remaining.length === 0) {
            const nid = uid();
            const t = Date.now();
            return {
              sessions: { [nid]: { id: nid, title: '新会话', createdAt: t, updatedAt: t } },
              messages: { [nid]: [] },
              attachments: { [nid]: [] },
              approvalCards: { [nid]: [] }, // v2.2.1
              agentEvents: { [nid]: [] }, // v2.2.3
              resumeBySession: { [nid]: '' }, // P1-5
              activeSessionId: nid,
            };
          }
          return {
            sessions: rest,
            messages: restM,
            attachments: restA,
            approvalCards: restP, // v2.2.1
            agentEvents: restE, // v2.2.3
            resumeBySession: restR, // P1-5
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
      updateMessage: (sessionId: string, id: string, patch: Partial<ChatMessage>) =>
        set((st) => ({
          messages: {
            ...st.messages,
            [sessionId]: (st.messages[sessionId] ?? []).map((m) =>
              m.id === id ? { ...m, ...patch } : m,
            ),
          },
        })),
      removeMessage: (sessionId: string, id: string) =>
        set((st) => ({
          messages: {
            ...st.messages,
            [sessionId]: (st.messages[sessionId] ?? []).filter((m) => m.id !== id),
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

      // v2.2.1 — HITL 卡片动作
      recordApproval: (card) =>
        set((st) => {
          const cur = st.approvalCards[card.sessionId] ?? [];
          // 去重：同 request_id 覆盖（避免前端 SSE 重复发送造成多张卡片）
          const next = cur
            .filter((c) => c.id !== card.id)
            .concat({ ...card, status: 'pending', createdAt: Date.now() });
          // 每 session 最多保留 50 张历史卡片
          const trimmed = next.slice(-50);
          return {
            approvalCards: { ...st.approvalCards, [card.sessionId]: trimmed },
          };
        }),
      resolveApproval: (sessionId, cardId, status, rejectReason) =>
        set((st) => {
          const cur = st.approvalCards[sessionId] ?? [];
          return {
            approvalCards: {
              ...st.approvalCards,
              [sessionId]: cur.map((c) =>
                c.id === cardId
                  ? {
                      ...c,
                      status,
                      ...(rejectReason ? { rejectReason } : {}),
                    }
                  : c,
              ),
            },
          };
        }),
      getApprovalCards: (sessionId) => get().approvalCards[sessionId] ?? [],

      // v2.2.3 — Agent 协作轨迹
      appendAgentEvent: (sessionId, ev) =>
        set((st) => {
          const cur = st.agentEvents[sessionId] ?? [];
          const ts = Date.now();
          // 自动计算与上一节点耗时（首节点为 0）
          const prev = cur.length > 0 ? cur[cur.length - 1] : null;
          const durationMs = prev ? Math.max(0, ts - prev.ts) : 0;
          const next = cur
            .concat({
              ...ev,
              id: uid(),
              ts,
              durationMs,
            })
            // 每 session 最多保留 100 条节点（防止 localStorage 爆炸）
            .slice(-100);
          return {
            agentEvents: { ...st.agentEvents, [sessionId]: next },
          };
        }),
      clearAgentEvents: (sessionId) =>
        set((st) => ({
          agentEvents: { ...st.agentEvents, [sessionId]: [] },
        })),
      getAgentEvents: (sessionId) => get().agentEvents[sessionId] ?? [],

      clearAll: () => {
        const id = uid();
        const t = Date.now();
        set({
          sessions: { [id]: { id, title: '新会话', createdAt: t, updatedAt: t } },
          messages: { [id]: [] },
          attachments: { [id]: [] },
          approvalCards: { [id]: [] }, // v2.2.1
          agentEvents: { [id]: [] }, // v2.2.3
          resumeBySession: { [id]: '' }, // P1-5
          activeSessionId: id,
        });
      },

      // P1-5 — HITL resume 累积文本
      appendResumeText: (sessionId, text) =>
        set((st) => {
          const cur = st.resumeBySession[sessionId] ?? '';
          return {
            resumeBySession: {
              ...st.resumeBySession,
              [sessionId]: cur + text,
            },
          };
        }),
      clearResumeText: (sessionId) =>
        set((st) => ({
          resumeBySession: { ...st.resumeBySession, [sessionId]: '' },
        })),
    }),
    {
      name: 'agent-console-chat',
      storage: createJSONStorage(() => localStorage),
      version: 4,
      migrate: (persisted, fromVersion) => {
        const p = (persisted ?? {}) as Partial<ChatState>;
        if (fromVersion < 2) {
          // v1 没有 attachments，补上空对象
          if (!p.attachments) p.attachments = {};
        }
        if (fromVersion < 3) {
          // v2 没有 approvalCards，补上空对象
          if (!p.approvalCards) p.approvalCards = {};
        }
        if (fromVersion < 4) {
          // v3 没有 agentEvents，补上空对象（F5 后旧会话也能优雅降级）
          if (!p.agentEvents) p.agentEvents = {};
        }
        return persisted as ChatState;
      },
    },
  ),
);