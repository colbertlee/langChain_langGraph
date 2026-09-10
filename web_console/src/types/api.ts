export type Role = 'user' | 'assistant' | 'system' | 'tool';

export type ToolCallStatus = 'pending' | 'running' | 'success' | 'error';

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result?: string;
  status: ToolCallStatus;
  startedAt: number;
  endedAt?: number;
  error?: string;
}

export interface ChatMessage {
  id: string;
  sessionId: string;
  role: Role;
  content: string;
  toolCalls?: ToolCall[];
  createdAt: number;
}

export interface Session {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
}

export interface Agent {
  id: string;
  name: string;
  status: 'idle' | 'running' | 'error';
  capabilities: string[];
  load: number;
  profile?: Record<string, unknown>;
  currentTask?: string;
}

export interface PendingApproval {
  id: string;
  sessionId: string;
  toolName: string;
  reason: string;
  args?: Record<string, unknown>;
  createdAt: number;
}

/**
 * v2.2.1 — HITL 拦截事件
 *
 * 后端 SSE 事件 `event: approval_required` 解析后的前端类型。
 * - toolName: 触发拦截的工具名（如 python_interpreter）
 * - toolArgs: 工具参数快照（用户可二次编辑后批准）
 * - reason: 给用户的中文解释
 */
export interface ApprovalRequiredEvent {
  request_id: string;
  session_id: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  tool_call_id?: string;
  reason: string;
  /** v2.2.1 — 超时秒数（默认 300s）；前端用于倒计时显示 */
  timeout_seconds?: number;
}

/** v2.2.1 — HITL 超时自动拒绝事件 */
export interface ApprovalTimeoutEvent {
  request_id: string;
  session_id: string;
  tool_name: string;
  reason: string;
}

/** v2.2.1 — checkpoint 历史 API 单条记录的最小形状（Time-Travel 基础） */
export interface CheckpointSummary {
  thread_id: string;
  checkpoint_id: string;
  step: number;
  ts?: number;
  next_node?: string;
  metadata?: Record<string, unknown>;
}

/** v2.2.1 — 单个 checkpoint 的完整 state 快照 */
export interface CheckpointState {
  thread_id: string;
  checkpoint_id: string;
  step: number;
  values?: Record<string, unknown>;
  next?: string[];
  config?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface ObsEvent {
  id: string;
  level: 'info' | 'warn' | 'error' | 'debug';
  source: string;
  message: string;
  ts: number;
}

export interface TraceSpan {
  id: string;
  parentId?: string;
  name: string;
  startedAt: number;
  endedAt?: number;
  attrs?: Record<string, unknown>;
  status?: 'ok' | 'error';
}

export interface Capability {
  name: string;
  taskType: string;
  description?: string;
  agentId?: string;
}

/** 持久化的附件：仅存 url / name / type（不存 data URL 节省 localStorage 体积） */
export interface PersistedAttachment {
  id: string;
  name: string;
  url: string;       // 服务端 url 或 data URL
  contentType: string;
  size: number;
  uploadedAt: number;
}

/**
 * Agent 预设（v2.1）：系统提示 / 温度 / 工具白名单。
 * 后端 /api/agents/presets 返回结构；前端 AgentConfigModal 用来双向编辑。
 */
export interface AgentPreset {
  id: string;
  name: string;
  description?: string;
  avatar?: string;
  system_prompt: string;
  temperature: number;
  tools: string[];
  builtin?: boolean;
  created_at?: number;
  updated_at?: number;
}
