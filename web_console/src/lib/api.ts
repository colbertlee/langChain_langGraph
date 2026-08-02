import type {
  Agent,
  Capability,
  ObsEvent,
  PendingApproval,
  TraceSpan,
} from '@/types/api';

// API 基础路径：开发期通过 vite proxy 转发到 8000
const BASE = '/api';

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export const api = {
  health: () => json<{ status: string; agent_ready: boolean }>('/health'),
  agents: () => json<Agent[]>('/agents'),
  loadStats: () => json<Record<string, unknown>>('/load_stats'),
  capabilities: () =>
    json<Capability[] | { capabilities?: Capability[]; task_types?: unknown[] }>(
      '/capabilities',
    ).then((r) => (Array.isArray(r) ? r : (r.capabilities ?? []))) as Promise<Capability[]>,
  policies: () => json<unknown[] | { policies: unknown[] }>('/policies')
    .then((r) => (Array.isArray(r) ? r : (r.policies ?? []))) as Promise<unknown[]>,

  // ----- Models / Providers -----
  models: () => json<ModelsBundle>('/models'),
  events: (limit = 100) =>
    json<ObsEvent[] | { events?: ObsEvent[]; count?: number }>(`/events?limit=${limit}`)
      .then((r) => (Array.isArray(r) ? r : (r.events ?? []))) as Promise<ObsEvent[]>,
  traces: (limit = 100) =>
    json<TraceSpan[] | { traces?: TraceSpan[]; count?: number }>(`/traces?limit=${limit}`)
      .then((r) => (Array.isArray(r) ? r : (r.traces ?? []))) as Promise<TraceSpan[]>,
  metrics: () => fetch(BASE + '/metrics/prometheus').then((r) => r.text()),
  hitlPending: () =>
    json<PendingApproval[] | { pending: PendingApproval[]; count: number }>(
      '/hitl/pending',
    ).then((r) => (Array.isArray(r) ? r : (r.pending ?? []))) as Promise<PendingApproval[]>,
  hitlDecide: (id: string, decision: 'approve' | 'reject', note?: string) =>
    json<{ ok: boolean }>('/hitl/decide', {
      method: 'POST',
      body: JSON.stringify({ id, decision, note }),
    }),
  hitlStats: () => json<unknown>('/hitl/stats'),

  // ----- Prompt 模板（System + User） -----
  promptsList: () => json<{ templates: PromptTemplateSummary[] }>('/prompts'),
  promptsRollback: (name: string, version: string) =>
    json<{ ok: boolean; name: string; version: string }>('/prompts/rollback', {
      method: 'POST',
      body: JSON.stringify({ name, version }),
    }),
  userPromptsList: () =>
    json<{ templates: PromptTemplateSummary[] }>('/user-prompts'),
  userPromptsRollback: (name: string, version: string) =>
    json<{ ok: boolean; name: string; version: string }>(
      '/user-prompts/rollback',
      { method: 'POST', body: JSON.stringify({ name, version }) },
    ),
  userPromptsRegister: (
    template: PromptTemplateDetail,
    baseName = 'default',
  ) =>
    json<{ ok: boolean; template: PromptTemplateDetail }>(
      '/user-prompts/register',
      {
        method: 'POST',
        body: JSON.stringify({ ...template, name: baseName }),
      },
    ),
  userPromptsRender: (payload: {
    name?: string;
    user_input: string;
    context?: string;
    variables?: Record<string, unknown>;
  }) =>
    json<{ ok: boolean; rendered: string; active_version?: string }>(
      '/user-prompts/render',
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  userPromptsExport: () => json<unknown>('/user-prompts/export'),
  userPromptsImport: (payload: unknown) =>
    json<{ ok: boolean; imported: number }>('/user-prompts/import', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // ----- Memory（对话式记忆） -----
  // 极简接口：用户输入一行文本 → 后端自动 key/value/scope，默认 scope=global
  memoryAdd: (content: string) =>
    json<{ id: number; stored: boolean; content: string; created_at?: number }>(
      '/memory/add',
      { method: 'POST', body: JSON.stringify({ content }) },
    ),
  memoryList: (limit = 100) =>
    json<{ items: MemoryItem[]; total: number }>(
      `/memory/list?limit=${limit}`,
    ),
  memoryDelete: (id: number) =>
    json<{ ok: boolean }>(`/memory/${id}`, { method: 'DELETE' }),
  memoryStats: () =>
    json<{ total: number; by_type?: Record<string, number> }>(
      '/memory/stats',
    ),

  // ----- External MCP Servers -----
  mcpServers: () => json<{ servers: MCPServerInfo[] }>('/mcp/servers'),
  mcpTools: () => json<{ tools: MCPToolInfo[] }>('/mcp/tools'),
  mcpToggle: (id: string, enabled: boolean) =>
    json<{
      ok: boolean;
      server_id?: string;
      enabled?: boolean;
      server?: MCPServerInfo;
      error?: string;
      missing_env?: string[];
    }>(`/mcp/servers/${id}/toggle`, {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    }),
  mcpSetHost: (id: string, host: string) =>
    json<{ ok: boolean; server_id: string; host: string }>(
      `/mcp/servers/${id}/host`,
      { method: 'POST', body: JSON.stringify({ host }) },
    ),
  mcpReload: () =>
    json<{ ok: boolean; results?: Record<string, string> }>('/mcp/reload', {
      method: 'POST',
    }),
};

// ----- Prompt 相关类型 -----

// ----- Models / Providers 类型 -----
export type ProviderGroup = 'global' | 'china' | 'other';

export interface ProviderInfo {
  id: string;
  label: string;
  group: ProviderGroup;
  desc: string;
  configured: boolean;
  base_url?: string | null;
  models: string[];
  is_openai_compatible?: boolean;
}

export interface ModelsBundle {
  providers: ProviderInfo[];
  models_by_provider: Record<string, string[]>;
  current_provider: string;
  current_model: string;
  provider_meta?: Record<string, { label: string; group: ProviderGroup; desc: string }>;
}

export interface FewShotEntry {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

// ----- Memory 类型 -----
export interface MemoryItem {
  id: number;
  content: string;
  memory_type?: string;
  importance?: number;
  session_id?: string;
  created_at?: number;
  tags?: string[];
}

// ----- MCP Servers 类型 -----
export interface MCPEnvKey {
  name: string;
  configured: boolean;
  required: boolean;
}

export interface MCPServerInfo {
  id: string;
  name: string;
  description: string;
  command: string;
  args: string[];
  enabled: boolean;
  running: boolean;
  tools_count: number;
  env_keys: MCPEnvKey[];
  env_defaults?: Record<string, string>;
  host_region_note?: string;
  pid?: number | null;
  last_error?: string | null;
}

export interface MCPToolInfo {
  server_id: string;
  name: string;
  description: string;
  inputSchema?: Record<string, unknown>;
}

export interface SecurityRewritePolicy {
  enabled: boolean;
  redact_patterns: string[];
  strip_injection_markers: boolean;
  max_length: number;
}

export interface PromptTemplateDetail {
  name: string;
  version: string;
  author: string;
  changelog: string;
  // system prompt 字段（可选）
  system_block?: string;
  role_block?: string;
  tool_block_template?: string;
  cot_instructions?: string;
  // user prompt 字段（可选）
  structure?: string;
  intro_template?: string;
  few_shots?: FewShotEntry[];
  context_injection?: string;
  security_rewrite?: SecurityRewritePolicy;
  variables: string[];
  created_at: number;
}

export interface PromptTemplateSummary {
  name: string;
  active_version: string;
  versions: PromptTemplateDetail[];
}

/**
 * POST SSE 流式接口封装：使用 fetch + ReadableStream
 * 后端约定事件格式：`data: {"type":"token","content":"..."}\n\n`
 */
export interface StreamEvent {
  type:
    | 'token'
    | 'tool_call'
    | 'tool_result'
    | 'message'
    | 'done'
    | 'error'
    | 'message_start'
    | 'message_end'
    | string;
  content?: string;
  tool_call_id?: string;
  name?: string;
  args?: Record<string, unknown>;
  result?: string;
  error?: string;
}

export async function* streamChat(
  message: string,
  sessionId: string,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await fetch(BASE + '/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  });
  if (!res.ok || !res.body) {
    yield { type: 'error', error: `HTTP ${res.status}` };
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE 以 \n\n 分隔
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? '';
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith('data:')) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      try {
        yield JSON.parse(payload) as StreamEvent;
      } catch {
        // 忽略非 JSON 帧
      }
    }
  }
}
