import type {
  Agent,
  Capability,
  ObsEvent,
  PendingApproval,
  TraceSpan,
} from '@/types/api';

// API 基础路径：开发期通过 vite proxy 转发到 8000
const BASE = '/api';

/**
 * 把后端 worker dict 规整成前端 Agent 形状。
 * 后端 WorkerProfile.to_dict() 的字段：worker_id / name / capabilities(dict) / tags / online / metrics(dict)
 * 前端 Agent：id / name / status / capabilities(string[]) / load / profile
 */
function normalizeAgent(raw: unknown): Agent {
  const r = (raw ?? {}) as Record<string, any>;
  const metrics = (r.metrics ?? {}) as Record<string, any>;
  const capDict = (r.capabilities ?? {}) as Record<string, unknown>;
  const capList = Array.isArray(r.capabilities)
    ? (r.capabilities as string[])
    : Object.keys(capDict);
  const online = r.online !== false;
  const lastStatus = String(metrics.last_status ?? '').toLowerCase();
  const status: Agent['status'] = !online
    ? 'idle'
    : lastStatus === 'busy' || (metrics.active_tasks ?? 0) > 0
      ? 'running'
      : lastStatus === 'error'
        ? 'error'
        : 'idle';
  const load = Math.max(0, Math.min(100, Number(r.load ?? metrics.load ?? 0) * 100 || 0));
  return {
    id: String(r.worker_id ?? r.id ?? ''),
    name: String(r.name ?? r.worker_id ?? 'agent'),
    status,
    capabilities: capList,
    load,
    profile: {
      ...(r.tags ? { tags: r.tags } : {}),
      ...(metrics.active_tasks !== undefined ? { active_tasks: metrics.active_tasks } : {}),
      ...(metrics.error_rate !== undefined ? { error_rate: metrics.error_rate } : {}),
      ...(metrics.recent_avg_latency_ms !== undefined
        ? { recent_avg_latency_ms: metrics.recent_avg_latency_ms }
        : {}),
    },
    currentTask:
      metrics.last_status === 'busy'
        ? `active_tasks=${metrics.active_tasks ?? 0}`
        : undefined,
  };
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    let detail = '';
    try {
      const body = await res.text();
      try {
        const parsed = JSON.parse(body);
        detail = parsed?.detail ?? parsed?.message ?? body;
      } catch {
        detail = body;
      }
    } catch {
      /* ignore */
    }
    const msg = `${res.status} ${res.statusText}${detail ? `: ${detail}` : ''}`;
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => json<{ status: string; agent_ready: boolean }>('/health'),
  agents: () =>
    json<Agent[] | { agents?: Agent[]; count?: number }>('/agents')
      .then((r) => {
        const list: unknown[] = Array.isArray(r) ? r : (r.agents ?? []);
        return list.map(normalizeAgent);
      }) as Promise<Agent[]>,
  loadStats: () => json<Record<string, unknown>>('/load_stats'),
  capabilities: () =>
    json<Capability[] | { capabilities?: Capability[]; task_types?: unknown[] }>(
      '/capabilities',
    ).then((r) => (Array.isArray(r) ? r : (r.capabilities ?? []))) as Promise<Capability[]>,
  policies: () => json<unknown[] | { policies: unknown[] }>('/policies')
    .then((r) => (Array.isArray(r) ? r : (r.policies ?? []))) as Promise<unknown[]>,

  // ----- Models / Providers -----
  models: () => json<ModelsBundle>('/models'),
  /**
   * 切换主 provider/model（写到后端 in-memory 配置，立即生效）。
   * 后端路由：POST /api/model/switch，body {provider, model_name}
   */
  switchModel: (provider: string, model: string) =>
    json<{ success: boolean; message: string; provider: string; model: string }>(
      '/model/switch',
      { method: 'POST', body: JSON.stringify({ provider, model_name: model }) },
    ) as Promise<{ success: boolean; message: string; provider: string; model: string }>,
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
    json<{ success: boolean; request_id: string }>('/hitl/decide', {
      method: 'POST',
      // 后端 HITLDecision 期望 request_id / status / notes；前端用 id / decision / note，做兼容映射
      body: JSON.stringify({
        request_id: id,
        status: decision === 'approve' ? 'approved' : 'rejected',
        notes: note ?? '',
        id,
        decision,
        note,
      }),
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

  // ----- 扩展接口（v2 widgets 使用；后端未实现时优雅降级） -----
  /**
   * 上传附件。后端未提供 /api/upload 时返回 ok=false，由调用方决定降级策略。
   */
  uploadAttachment: async (_fd: FormData): Promise<{ ok: boolean; url?: string; error?: string }> => {
    return { ok: false, error: 'uploadAttachment backend endpoint not implemented' };
  },
  /**
   * 拉取 telemetry snapshot。后端未提供 /api/telemetry/snapshot 时返回空结构。
   */
  telemetry: async (): Promise<{
    counters?: { errors_total?: number; requests_total?: number };
    gauges?: { tokens_total?: number };
    recent_spans?: Array<{ name: string; duration_ms?: number; status?: string }>;
  }> => {
    return { counters: {}, gauges: {}, recent_spans: [] };
  },
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
