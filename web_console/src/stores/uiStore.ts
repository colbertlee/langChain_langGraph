import { create } from 'zustand';

interface UIState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  // 全局后端连接状态
  backendOnline: boolean;
  setBackendOnline: (v: boolean) => void;
  // MCP Servers 摘要:running 数 + 总工具数(给 Sidebar 角标用)
  mcpRunningCount: number;
  mcpToolCount: number;
  setMcpSummary: (running: number, tools: number) => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidebarCollapsed: false,
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  backendOnline: false,
  setBackendOnline: (v) => set({ backendOnline: v }),
  mcpRunningCount: 0,
  mcpToolCount: 0,
  setMcpSummary: (running, tools) =>
    set({ mcpRunningCount: running, mcpToolCount: tools }),
}));
