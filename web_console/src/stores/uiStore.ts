import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export type ThemeMode = 'dark' | 'light';

interface UIState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
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
      backendOnline: false,
      setBackendOnline: (v) => set({ backendOnline: v }),
      theme: 'dark',
      setTheme: (m) => set({ theme: m }),
      toggleTheme: () => set({ theme: get().theme === 'dark' ? 'light' : 'dark' }),
    }),
    {
      name: 'agent-console-ui',
      storage: createJSONStorage(() => localStorage),
      version: 1,
      // 只持久化主题相关字段，避免与其它 store 冲突
      partialize: (s) => ({ theme: s.theme, sidebarCollapsed: s.sidebarCollapsed }),
    },
  ),
);
