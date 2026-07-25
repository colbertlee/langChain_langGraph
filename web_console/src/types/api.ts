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
