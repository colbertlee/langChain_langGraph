import { create } from 'zustand';

interface UIState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  // 全局后端连接状态
  backendOnline: boolean;
  setBackendOnline: (v: boolean) => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidebarCollapsed: false,
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  backendOnline: false,
  setBackendOnline: (v) => set({ backendOnline: v }),
}));
