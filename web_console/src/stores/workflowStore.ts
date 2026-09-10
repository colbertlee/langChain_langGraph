/**
 * workflowStore — Chat 页面左上角「应用模式 / 工作流 (Workflow Mode)」状态机
 *
 * 设计动机：
 *  - 用户诉求把「当前 AGENT」改名为「应用模式 / 工作流 (Workflow Mode)」，
 *    选项收敛为三种业务编排：
 *      1. 通用对话（Single Agent） —— 单 Agent 直接对话
 *      2. 复杂研发与重构（Multi-Agent Swarm: Supervisor/Coder/Reviewer）
 *      3. 深度数据分析（Data Analyst）
 *  - 三种模式有不同的拓扑 / 监控节点集合；选择模式时同步刷新 Chat 右侧的
 *    "执行日志 / 节点状态" 面板与 Agents 监控页的高亮节点，保持两侧 UI
 *    与后端 Agent 拓扑一致。
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export type WorkflowModeId =
  | 'single'
  | 'multi_swarm'
  | 'data_analyst';

export interface WorkflowModeMeta {
  id: WorkflowModeId;
  /** 左上角下拉显示的中文标题 */
  label: string;
  /** 鼠标悬停 / 描述区的副标题 */
  description: string;
  /** 节点 id 列表 —— 与 Agents.tsx 的 MOCK_AGENTS / /api/agents 返回对齐 */
  nodes: string[];
  /** 拓扑连线：用于在监控面板画箭头（Supervisor → Coder/Reviewer） */
  edges: Array<{ from: string; to: string }>;
}

export const WORKFLOW_MODES: Record<WorkflowModeId, WorkflowModeMeta> = {
  single: {
    id: 'single',
    label: '通用对话 (Single Agent)',
    description: '单 Agent 直接对话，无调度开销。',
    nodes: ['general'],
    edges: [],
  },
  multi_swarm: {
    id: 'multi_swarm',
    label: '复杂研发与重构 (Multi-Agent Swarm)',
    description: 'Supervisor 调度 Coder / Reviewer，适合多步研发与重构。',
    nodes: ['supervisor-01', 'coder-02', 'reviewer-01'],
    edges: [
      { from: 'supervisor-01', to: 'coder-02' },
      { from: 'supervisor-01', to: 'reviewer-01' },
      { from: 'coder-02', to: 'reviewer-01' },
    ],
  },
  data_analyst: {
    id: 'data_analyst',
    label: '深度数据分析 (Data Analyst)',
    description: '数据分析师模式：清洗 → 建模 → 可视化 → 结论。',
    nodes: ['analyst-01', 'coder-02'],
    edges: [
      { from: 'analyst-01', to: 'coder-02' },
    ],
  },
};

export const WORKFLOW_MODE_ORDER: WorkflowModeId[] = [
  'single',
  'multi_swarm',
  'data_analyst',
];

/**
 * 单条执行日志（节点 → 节点 / 状态变更 / 工具调用）。
 * 后端目前没有专门的 supervisor dispatch event，这里由前端 Chat 流式事件
 * 派生（tool_call / tool_result / token）成可观察的"节点日志"。
 */
export interface WorkflowExecLog {
  id: string;
  ts: number;
  /** 触发本次事件的节点 id（消息来源）；与 WORKFLOW_MODES[].nodes 对齐 */
  nodeId: string;
  /** 派发目标（Supervisor → Coder 这种边）；无则为空 */
  toNodeId?: string;
  /** 事件类型 */
  kind: 'dispatch' | 'tool_call' | 'tool_result' | 'token' | 'status' | 'complete' | 'error';
  /** 描述（人类可读） */
  message: string;
  /** 关联的工具名（tool_call / tool_result 时） */
  toolName?: string;
  /** 关联状态：running / success / error（用于高亮） */
  status?: 'running' | 'success' | 'error';
}

interface WorkflowState {
  mode: WorkflowModeId;
  setMode: (m: WorkflowModeId) => void;

  /**
   * 当前 session 的执行日志（环形缓冲，上限 200 条）。
   * 切换 mode 时清空，避免显示"上一个工作流的尾巴"。
   */
  logs: WorkflowExecLog[];
  pushLog: (entry: Omit<WorkflowExecLog, 'id' | 'ts'>) => void;
  clearLogs: () => void;

  /** 由 useAgentLocalRuntime 在 streaming 期间置 true，供 Chat header 渲染 */
  active: boolean;
  setActive: (v: boolean) => void;
}

const initialMode: WorkflowModeId = 'single';

export const useWorkflowStore = create<WorkflowState>()(
  persist(
    (set) => ({
      mode: initialMode,
      setMode: (m) => set({ mode: m, logs: [] }),

      logs: [],
      pushLog: (entry) =>
        set((st) => {
          const id = `wf-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
          const next: WorkflowExecLog = { id, ts: Date.now(), ...entry };
          // 环形缓冲 200 条
          const merged = [...st.logs, next];
          if (merged.length > 200) merged.splice(0, merged.length - 200);
          return { logs: merged };
        }),
      clearLogs: () => set({ logs: [] }),

      active: false,
      setActive: (v) => set({ active: v }),
    }),
    {
      name: 'agent-console-workflow',
      storage: createJSONStorage(() => localStorage),
      version: 1,
      // 只持久化 mode，不持久化瞬时的 logs / active
      partialize: (s) => ({ mode: s.mode }),
    },
  ),
);