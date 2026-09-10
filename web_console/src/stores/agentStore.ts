/**
 * agentStore — v2.1 Agent Preset 管理
 *
 * 设计：
 *  - 独立 store，不污染 chatStore，便于按需懒加载
 *  - 与后端 /api/agents/presets 双向同步
 *  - activeAgentId 既支持全局（默认），也支持按 sessionId 覆盖（用 Map）
 *    —— 切换 Session 时自动恢复该 session 绑定的 agent
 */
import { create } from 'zustand';
import { api } from '@/lib/api';
import type { AgentPreset } from '@/types/api';

interface AgentState {
  presets: AgentPreset[];
  loading: boolean;
  loaded: boolean;
  /** 全局默认 agent_id（用于新 Session 初始化） */
  defaultAgentId: string;
  /** per-session 覆盖：sessionId → agent_id */
  sessionAgentMap: Record<string, string>;
  /** 当前 active session 解析出来的 agent_id（derived） */
  resolveActiveAgentId: (sessionId: string) => string;

  // actions
  loadPresets: () => Promise<void>;
  setDefaultAgent: (id: string) => void;
  bindAgentToSession: (sessionId: string, agentId: string) => void;
  unbindAgentFromSession: (sessionId: string) => void;
  createPreset: (payload: Partial<AgentPreset>) => Promise<AgentPreset>;
  updatePreset: (id: string, patch: Partial<AgentPreset>) => Promise<AgentPreset>;
  deletePreset: (id: string) => Promise<void>;
  resetForTests: () => void;
}

export const useAgentStore = create<AgentState>((set, get) => ({
  presets: [],
  loading: false,
  loaded: false,
  defaultAgentId: 'builtin-general',
  sessionAgentMap: {},

  resolveActiveAgentId: (sessionId: string) => {
    const { sessionAgentMap, defaultAgentId } = get();
    return sessionAgentMap[sessionId] ?? defaultAgentId;
  },

  loadPresets: async () => {
    if (get().loading) return;
    set({ loading: true });
    try {
      const data = await api.listAgentPresets();
      const presets = (data?.presets ?? []) as AgentPreset[];
      set({ presets, loaded: true });
      // 若 defaultAgentId 失效，回退到第一个 builtin
      const ids = new Set(presets.map((p) => p.id));
      if (!ids.has(get().defaultAgentId)) {
        const fallback =
          presets.find((p) => p.id === 'builtin-general') ??
          presets.find((p) => p.builtin) ??
          presets[0];
        if (fallback) {
          set({ defaultAgentId: fallback.id });
        }
      }
    } catch (e) {
      // 静默失败 —— UI 用空列表兜底
      // eslint-disable-next-line no-console
      console.warn('[agentStore] loadPresets failed', e);
    } finally {
      set({ loading: false });
    }
  },

  setDefaultAgent: (id) => set({ defaultAgentId: id }),

  bindAgentToSession: (sessionId, agentId) =>
    set((st) => ({
      sessionAgentMap: { ...st.sessionAgentMap, [sessionId]: agentId },
    })),

  unbindAgentFromSession: (sessionId) =>
    set((st) => {
      const next = { ...st.sessionAgentMap };
      delete next[sessionId];
      return { sessionAgentMap: next };
    }),

  createPreset: async (payload) => {
    const created = await api.createAgentPreset(payload);
    set((st) => ({ presets: [created, ...st.presets] }));
    return created;
  },

  updatePreset: async (id, patch) => {
    const updated = await api.updateAgentPreset(id, patch);
    set((st) => ({
      presets: st.presets.map((p) => (p.id === id ? updated : p)),
    }));
    return updated;
  },

  deletePreset: async (id) => {
    await api.deleteAgentPreset(id);
    set((st) => ({
      presets: st.presets.filter((p) => p.id !== id),
      // 若删的是默认 agent，回退到 builtin-general
      defaultAgentId:
        st.defaultAgentId === id ? 'builtin-general' : st.defaultAgentId,
      sessionAgentMap: Object.fromEntries(
        Object.entries(st.sessionAgentMap).filter(([, v]) => v !== id),
      ),
    }));
  },

  resetForTests: () =>
    set({
      presets: [],
      loading: false,
      loaded: false,
      defaultAgentId: 'builtin-general',
      sessionAgentMap: {},
    }),
}));

// 测试辅助
export const _agentStoreTestHelpers = {
  getInitial: () => ({
    presets: [],
    loading: false,
    loaded: false,
    defaultAgentId: 'builtin-general',
    sessionAgentMap: {},
  }),
};
