import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export type ThemeMode = 'dark' | 'light';

interface UIState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  // v2.1 — SessionSidebar 显隐（小屏默认收起）
  sessionsCollapsed: boolean;
  toggleSessions: () => void;
  setSessionsCollapsed: (v: boolean) => void;
  // 全局后端连接状态
  backendOnline: boolean;
  setBackendOnline: (v: boolean) => void;
  // 主题：dark（默认）/ light
  theme: ThemeMode;
  setTheme: (m: ThemeMode) => void;
  toggleTheme: () => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set, get) => ({
      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      // v2.1
      sessionsCollapsed: false,
      toggleSessions: () => set((s) => ({ sessionsCollapsed: !s.sessionsCollapsed })),
      setSessionsCollapsed: (v) => set({ sessionsCollapsed: v }),
      backendOnline: false,
      setBackendOnline: (v) => set({ backendOnline: v }),
      theme: 'dark',
      setTheme: (m) => set({ theme: m }),
      toggleTheme: () => set({ theme: get().theme === 'dark' ? 'light' : 'dark' }),
    }),
    {
      name: 'agent-console-ui',
      storage: createJSONStorage(() => localStorage),
      version: 2,
      // 只持久化主题相关字段，避免与其它 store 冲突
      partialize: (s) => ({ theme: s.theme, sidebarCollapsed: s.sidebarCollapsed, sessionsCollapsed: s.sessionsCollapsed }),
      migrate: (persisted, fromVersion) => {
        // v1 → v2: 补 sessionsCollapsed 字段（持久化数据无该字段时默认 false）
        const p = (persisted ?? {}) as Partial<UIState>;
        if (fromVersion < 2 && typeof p.sessionsCollapsed !== 'boolean') {
          p.sessionsCollapsed = false;
        }
        return p as UIState;
      },
    },
  ),
);
